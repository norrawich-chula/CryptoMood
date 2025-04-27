import json
import os
import urllib3

http = urllib3.PoolManager()
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')

def lambda_handler(event, context):
    if not DISCORD_WEBHOOK_URL:
        raise ValueError("Missing DISCORD_WEBHOOK_URL in environment variables")

    for record in event['Records']:
        try:
            sns_msg = json.loads(record['Sns']['Message'])

            coin = sns_msg.get('coin', 'UNKNOWN').upper()
            price = float(sns_msg.get('price', 0))
            timestamp = sns_msg.get('timestamp', 'N/A')

            # Extract individual components
            signal = sns_msg.get('signal', '')  # e.g., "EMA: None, SMA: Dead Cross"
            trend_status = sns_msg.get('trend_status', '')  # e.g., "EMA: Hold, SMA: Sell"
            ema_short = sns_msg.get('ema_short', 'N/A')
            ema_long = sns_msg.get('ema_long', 'N/A')
            sma_short = sns_msg.get('sma_short', 'N/A')
            sma_long = sns_msg.get('sma_long', 'N/A')

            # Parse signals and statuses
            ema_signal = next((s.strip().split(": ")[1] for s in signal.split(",") if "EMA" in s), None)
            sma_signal = next((s.strip().split(": ")[1] for s in signal.split(",") if "SMA" in s), None)
            ema_status = next((s.strip().split(": ")[1] for s in trend_status.split(",") if "EMA" in s), None)
            sma_status = next((s.strip().split(": ")[1] for s in trend_status.split(",") if "SMA" in s), None)

            # --- Compose and send EMA message if available ---
            if ema_signal and ema_signal != "None":
                content_ema = (
                    f"📊 **EMA: {ema_signal}** detected for **{coin}**\n"
                    f"📍 Trend Status: EMA: {ema_status}\n"
                    f"💰 Price: ${price:,.5f}\n"
                    f"📈 EMA Short: {ema_short} | EMA Long: {ema_long}\n"
                    f"⏱ Timestamp: {timestamp}\n"
                )
                send_discord_message(content_ema)

            # --- Compose and send SMA message if available ---
            if sma_signal and sma_signal != "None":
                content_sma = (
                    f"📊 **SMA: {sma_signal}** detected for **{coin}**\n"
                    f"📍 Trend Status: SMA: {sma_status}\n"
                    f"💰 Price: ${price:,.5f}\n"
                    f"📈 SMA Short: {sma_short} | SMA Long: {sma_long}\n"
                    f"⏱ Timestamp: {timestamp}\n"
                )
                send_discord_message(content_sma)

        except Exception as e:
            print(f"❌ Error processing record: {e}")
            print(f"🔍 Raw record: {record}")

    return {
        'statusCode': 200,
        'body': 'Processed all alerts'
    }


def send_discord_message(content):
    response = http.request(
        "POST",
        DISCORD_WEBHOOK_URL,
        headers={"Content-Type": "application/json"},
        body=json.dumps({"content": content})
    )
    if response.status == 204:
        print("✅ Alert sent to Discord")
    else:
        print(f"⚠️ Discord send failed with status: {response.status}")
        print(response.data.decode('utf-8'))
