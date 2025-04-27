import json
import requests
import boto3
import os

# Load environment variables
KINESIS_STREAM = os.environ.get('KINESIS_STREAM', 'CryptoStream')

# Initialize Kinesis client
kinesis = boto3.client('kinesis')

# Set of allowed CoinGecko IDs
TARGET_COINS = {'bitcoin', 'ethereum', 'ripple', 'binancecoin', 'solana', 'dogecoin', 'cardano', 'chainlink','polkadot', 'stellar', 'litecoin'}

def lambda_handler(event, context):
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        'vs_currency': 'usd',
        'order': 'market_cap_desc',
        'per_page': 50,
        'page': 1,
        'sparkline': False
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        coins = response.json()

        count = 0
        for coin in coins:
            if coin['id'] not in TARGET_COINS:
                continue  # Skip coins not in our target list

            record = {
                'id': coin['id'],
                'symbol': coin['symbol'],
                'price': coin['current_price'],
                'market_cap': coin['market_cap'],
                'timestamp': coin['last_updated']
            }

            kinesis.put_record(
                StreamName=KINESIS_STREAM,
                Data=json.dumps(record),
                PartitionKey=coin['id']
            )

            count += 1

        return {
            'statusCode': 200,
            'body': f"{count} selected coin records sent to Kinesis stream '{KINESIS_STREAM}'"
        }

    except requests.exceptions.RequestException as e:
        return {
            'statusCode': 500,
            'body': f"Request failed: {str(e)}"
        }
