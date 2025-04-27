import json
import boto3
import os
import base64
from decimal import Decimal
from datetime import datetime, timezone, timedelta

# Boto3 clients
dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')

# Environment variables
TABLE_NAME = os.environ['DYNAMODB_TABLE']
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']
PRICE_HISTORY_LIMIT = 500

# DynamoDB table object
table = dynamodb.Table(TABLE_NAME)

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def decode_kinesis_record(record):
    try:
        base64_data = record['kinesis']['data']
        decoded_data = base64.b64decode(base64_data).decode('utf-8')
        return json.loads(decoded_data, parse_float=Decimal)
    except Exception as e:
        print(f"❌ Error decoding record: {e}")
        return None

def update_price_history(coin_id, price, timestamp):
    response = table.get_item(Key={'coin_id': coin_id})
    item = response.get('Item', {})
    history = item.get('price_history', [])

    # Avoid appending if the last record is exactly the same
    if history and history[-1]['price'] == price and history[-1]['timestamp'] == timestamp:
        return history[-PRICE_HISTORY_LIMIT:], len(history[-PRICE_HISTORY_LIMIT:])

    history.append({'price': price, 'timestamp': timestamp})
    return history[-PRICE_HISTORY_LIMIT:], len(history[-PRICE_HISTORY_LIMIT:])


EMA_SHORT = 50
EMA_LONG = 200
SMA_SHORT = 50
SMA_LONG = 200

def calculate_ema(prices, period):
    if len(prices) < period:
        return sum(prices) / len(prices)
    ema = prices[0]
    multiplier = Decimal('2') / (Decimal(period) + Decimal('1'))
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_sma(prices, period):
    if len(prices) < period:
        return sum(prices) / len(prices)
    return sum(prices[-period:]) / Decimal(period)

def calculate_moving_averages(history):
    prices = [p['price'] for p in history]
    ema_short = calculate_ema(prices[-EMA_SHORT:], EMA_SHORT)
    ema_long = calculate_ema(prices[-EMA_LONG:], EMA_LONG)
    sma_short = calculate_sma(prices, SMA_SHORT)
    sma_long = calculate_sma(prices, SMA_LONG)
    return ema_short, ema_long, sma_short, sma_long

def detect_signal(short_ma, long_ma, prev_short, prev_long):
    if prev_short < prev_long and short_ma > long_ma:
        return "Golden Cross"
    elif prev_short > prev_long and short_ma < long_ma:
        return "Dead Cross"
    return None

def store_to_dynamodb(coin_id, history, ema_short, ema_long, sma_short, sma_long, timestamp, trend_status, num_price_history):
    table.update_item(
        Key={'coin_id': coin_id},
        UpdateExpression="""
            SET price_history = :history,
                ema_short = :ema_short,
                ema_long = :ema_long,
                sma_short = :sma_short,
                sma_long = :sma_long,
                last_updated = :last_updated,
                trend_status = :trend_status,
                num_price_history = :num_ph
        """,
        ExpressionAttributeValues={
            ':history': history,
            ':ema_short': str(round(ema_short, 5)),
            ':ema_long': str(round(ema_long, 5)),
            ':sma_short': str(round(sma_short, 5)),
            ':sma_long': str(round(sma_long, 5)),
            ':last_updated': timestamp,
            ':trend_status': trend_status,
            ':num_ph': num_price_history
        }
    )
    print(f"✅ Updated {coin_id} trend data in DynamoDB")

def publish_sns_alert(signal, coin_id, price, ema_short, ema_long, sma_short, sma_long, timestamp, trend_status):
    message = {
        'coin': coin_id,
        'signal': signal,
        'trend_status': trend_status,
        'price': str(round(price, 5)),
        'ema_short': str(round(ema_short, 5)),
        'ema_long': str(round(ema_long, 5)),
        'sma_short': str(round(sma_short, 5)),
        'sma_long': str(round(sma_long, 5)),
        'timestamp': timestamp
    }
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Message=json.dumps(message),
        Subject=f'{signal} detected for {coin_id}'
    )
    print(f"📢 SNS Alert sent: {signal} for {coin_id}")

def lambda_handler(event, context):
    for record in event['Records']:
        try:
            payload = decode_kinesis_record(record)
            if not payload:
                continue

            coin_id = payload['id']
            price = Decimal(str(payload['price']))
            utc_time = datetime.fromisoformat(payload['timestamp'].replace("Z", "+00:00"))
            bangkok_time = utc_time.astimezone(timezone(timedelta(hours=7)))
            timestamp = bangkok_time.isoformat()

            history, num_price_history = update_price_history(coin_id, price, timestamp)
            ema_short, ema_long, sma_short, sma_long = calculate_moving_averages(history)

            # Try to fetch previous data
            response = table.get_item(Key={'coin_id': coin_id})
            item = response.get('Item')

            # First time: no data in DynamoDB
            if not item:
                prev_ema_short = ema_short  
                prev_ema_long = ema_long
                prev_sma_short = sma_short
                prev_sma_long = sma_long
            else:
                prev_ema_short = Decimal(item['ema_short'])
                prev_ema_long = Decimal(item['ema_long'])
                prev_sma_short = Decimal(item['sma_short'])
                prev_sma_long = Decimal(item['sma_long'])

            ema_signal = detect_signal(ema_short, ema_long, prev_ema_short, prev_ema_long)
            sma_signal = detect_signal(sma_short, sma_long, prev_sma_short, prev_sma_long)

            ema_trend_status = 'Buy' if ema_signal == 'Golden Cross' else 'Sell' if ema_signal == 'Dead Cross' else 'Hold'
            sma_trend_status = 'Buy' if sma_signal == 'Golden Cross' else 'Sell' if sma_signal == 'Dead Cross' else 'Hold'
            trend_status_ema = ema_trend_status
            trend_status_sma = sma_trend_status
            trend_status = f"EMA: {trend_status_ema}, SMA: {trend_status_sma}"

            store_to_dynamodb(
                coin_id=coin_id,
                history=history,
                ema_short=ema_short,
                ema_long=ema_long,
                sma_short=sma_short,
                sma_long=sma_long,
                timestamp=timestamp,
                trend_status=trend_status,
                num_price_history=num_price_history
            )

            if ema_signal:
                response = table.get_item(Key={'coin_id': coin_id})
                item = response.get('Item', {})
                holding = bool(item.get('ema_status_holding', False))

                if ema_signal == "Golden Cross":
                    if not holding:
                        ema_golden_history = item.get('ema_golden_cross_history', [])
                        ema_golden_history.append({
                            'timestamp': timestamp,
                            'price': price
                        })
                        num_golden = Decimal(len(ema_golden_history))
                        table.update_item(
                            Key={'coin_id': coin_id},
                            UpdateExpression="""
                                SET ema_last_golden_cross_price = :p,
                                    ema_last_golden_cross_timestamp = :t,
                                    ema_status_holding = :h,
                                    ema_golden_cross_history = :gh,
                                    ema_num_golden_crosses = :ng
                            """,
                            ExpressionAttributeValues={
                                ':p': price,
                                ':t': timestamp,
                                ':h': True,
                                ':gh': ema_golden_history,
                                ':ng': num_golden
                            }
                        )
                        print(f"💰 EMA Buy signal saved at price {price} for {coin_id}")
                    else:
                        print(f"🔁 Already holding EMA for {coin_id}, skipping buy")

                elif ema_signal == "Dead Cross":
                    buy_price = Decimal(item.get('ema_last_golden_cross_price', 0))

                    if holding and buy_price:
                        profit = price - buy_price
                        profit_pct = (profit / buy_price) * Decimal('100')

                        ema_dead_history = item.get('ema_dead_cross_history', [])
                        ema_golden_history = item.get('ema_golden_cross_history', [])
                        ema_profit_history = item.get('ema_profit_history', [])

                        ema_dead_history.append({
                            'timestamp': timestamp,
                            'price': price
                        })
                        num_dead = Decimal(len(ema_dead_history))
                        num_getprofit = len(ema_profit_history) + 1

                        new_profit_entry = {
                            "num_getprofit": num_getprofit,
                            "ema_profit": str(round(profit, 6)),
                            "ema_profit_percentage": str(round(profit_pct, 4)),
                            "ema_dead_cross_history_last": {
                                "price": str(price),
                                "timestamp": timestamp
                            },
                            "ema_golden_cross_history_last": ema_golden_history[-1] if ema_golden_history else {}
                        }

                        ema_profit_history.insert(0, new_profit_entry)

                        table.update_item(
                            Key={'coin_id': coin_id},
                            UpdateExpression="""
                                SET ema_profit = :profit,
                                    ema_profit_percentage = :pct,
                                    ema_status_holding = :h,
                                    ema_last_dead_cross_price = :p,
                                    ema_last_dead_cross_timestamp = :t,
                                    ema_dead_cross_history = :dh,
                                    ema_num_dead_crosses = :nd,
                                    ema_profit_history = :ph
                            """,
                            ExpressionAttributeValues={
                                ':profit': profit,
                                ':pct': profit_pct,
                                ':h': False,
                                ':p': price,
                                ':t': timestamp,
                                ':dh': ema_dead_history,
                                ':nd': num_dead,
                                ':ph': ema_profit_history
                            }
                        )
                        print(f"📈 EMA Sold {coin_id} at {price}, Profit: {profit:.5f}, Profit%: {profit_pct:.2f}%")
                    else:
                        print(f"⚠️ Not holding EMA for {coin_id}, skipping sell")

                response = table.get_item(Key={'coin_id': coin_id})
                item = response.get('Item', {})
                ema_history = item.get('ema_cross_history', [])
                ema_history.append({
                    'timestamp': timestamp,
                    'price': price,
                    'signal': ema_signal
                })
                table.update_item(
                    Key={'coin_id': coin_id},
                    UpdateExpression="SET ema_cross_history = :hist",
                    ExpressionAttributeValues={':hist': ema_history}
                )

            if sma_signal:
                response = table.get_item(Key={'coin_id': coin_id})
                item = response.get('Item', {})
                holding = bool(item.get('sma_status_holding', False))

                if sma_signal == "Golden Cross":
                    if not holding:
                        sma_golden_history = item.get('sma_golden_cross_history', [])
                        sma_golden_history.append({
                            'timestamp': timestamp,
                            'price': price
                        })
                        num_golden = Decimal(len(sma_golden_history))
                        table.update_item(
                            Key={'coin_id': coin_id},
                            UpdateExpression="""
                                SET sma_last_golden_cross_price = :p,
                                    sma_last_golden_cross_timestamp = :t,
                                    sma_status_holding = :h,
                                    sma_golden_cross_history = :gh,
                                    sma_num_golden_crosses = :ng
                            """,
                            ExpressionAttributeValues={
                                ':p': price,
                                ':t': timestamp,
                                ':h': True,
                                ':gh': sma_golden_history,
                                ':ng': num_golden
                            }
                        )
                        print(f"💰 SMA Buy signal saved at price {price} for {coin_id}")
                    else:
                        print(f"🔁 Already holding SMA for {coin_id}, skipping buy")

                elif sma_signal == "Dead Cross":
                    buy_price = Decimal(item.get('sma_last_golden_cross_price', 0))
                    if holding and buy_price:
                        profit = price - buy_price
                        profit_pct = (profit / buy_price) * Decimal('100')

                        sma_dead_history = item.get('sma_dead_cross_history', [])
                        sma_golden_history = item.get('sma_golden_cross_history', [])
                        sma_profit_history = item.get('sma_profit_history', [])

                        sma_dead_history.append({
                            'timestamp': timestamp,
                            'price': price
                        })
                        num_dead = Decimal(len(sma_dead_history))

                        num_getprofit = len(sma_profit_history) + 1

                        new_profit_entry = {
                            "num_getprofit": num_getprofit,
                            "sma_profit": str(round(profit, 6)),
                            "sma_profit_percentage": str(round(profit_pct, 4)),
                            "sma_dead_cross_history_last": {
                                "price": str(price),
                                "timestamp": timestamp
                            },
                            "sma_golden_cross_history_last": sma_golden_history[-1] if sma_golden_history else {}
                        }

                        sma_profit_history.insert(0, new_profit_entry)

                        table.update_item(
                            Key={'coin_id': coin_id},
                            UpdateExpression="""
                                SET sma_profit = :profit,
                                    sma_profit_percentage = :pct,
                                    sma_status_holding = :h,
                                    sma_last_dead_cross_price = :p,
                                    sma_last_dead_cross_timestamp = :t,
                                    sma_dead_cross_history = :dh,
                                    sma_num_dead_crosses = :nd,
                                    sma_profit_history = :ph
                            """,
                            ExpressionAttributeValues={
                                ':profit': profit,
                                ':pct': profit_pct,
                                ':h': False,
                                ':p': price,
                                ':t': timestamp,
                                ':dh': sma_dead_history,
                                ':nd': num_dead,
                                ':ph': sma_profit_history
                            }
                        )
                        print(f"📈 SMA Sold {coin_id} at {price}, Profit: {profit:.5f}, Profit%: {profit_pct:.2f}%")
                    else:
                        print(f"⚠️ Not holding SMA for {coin_id}, skipping sell")

                sma_history = item.get('sma_cross_history', [])
                sma_history.append({
                    'timestamp': timestamp,
                    'price': price,
                    'signal': sma_signal
                })
                table.update_item(
                    Key={'coin_id': coin_id},
                    UpdateExpression="SET sma_cross_history = :hist",
                    ExpressionAttributeValues={':hist': sma_history}
                )
                

            if ema_signal or sma_signal:
                publish_sns_alert(
                    signal=f"EMA: {ema_signal}, SMA: {sma_signal}",
                    coin_id=coin_id,
                    price=price,
                    ema_short=ema_short,
                    ema_long=ema_long,
                    sma_short=sma_short,
                    sma_long=sma_long,
                    timestamp=timestamp,
                    trend_status=trend_status
                )

        except Exception as e:
            print(f"❌ Error processing record: {e}")
            print(f"🔍 Raw record: {record}")

    return {
        'statusCode': 200,
        'body': 'Processed Kinesis stream records.'
    }
