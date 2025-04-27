# 📚 CryptoMood
Real-Time Trend Analyzer for Top Cryptocurrencies

---

## 🚀 Project Motivation

- **Problem:** Many traders lack real-time detection of major crypto trend reversals (Golden Cross, Dead Cross).
- **Importance:** Identifying trend changes early can significantly improve trading decisions.
- **Goal:** Build an automatic system to detect crypto trends and alert users without manual monitoring.

---

## 🛠️ Solution Overview

- **Kinesis Data Stream** collects real-time crypto price data.
- **Lambda Functions** process price streams, calculate SMA/EMA indicators, detect trends, and send alerts.
- **DynamoDB** stores crypto trend history and status.
- **SNS Topic** notifies users when a Golden Cross or Dead Cross event is detected.

---

## 🧰 Setup Instructions

### 1. Prerequisites

You will need AWS services:

- **AWS Kinesis (Stream)**
  - Create a Kinesis data stream named `CryptoStream`
  - Capacity mode: On-demand
  - Data retention period: 1 day

- **AWS DynamoDB (Table)**
  - Create a table named `CryptoTrends_table`
  - Partition key: `coin_id` (String)
  - Capacity mode: On-demand

- **AWS SNS (Topic)**
  - Create an SNS topic named `CryptoTrendAlerts`
  - Type: Standard
  - ARN Example:  
    `arn:aws:sns:ap-southeast-1:961341553833:CryptoTrendAlerts`

- **AWS EventBridge**
  - Used to trigger scheduled Lambda executions every minute.

Make sure you have:
- An AWS Account with sufficient permissions to create these resources.

---

### 2. Create Role and Policy for Lambda Functions

Create a **Lambda execution role** named `cryptomood_lambda_role` with the following permissions:

- Lambda can read/write to Kinesis for fetching prices
- Lambda can read Kinesis and write/read DynamoDB
- Lambda can publish to SNS

Policy Example (from `cryptomood_lambda_policy.json`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KinesisPutRecordStream1",
      "Effect": "Allow",
      "Action": "kinesis:PutRecord",
      "Resource": "arn:aws:kinesis:ap-southeast-1:961341553833:stream/CryptoStream"
    },
    {
      "Sid": "KinesisReadAccessStream1",
      "Effect": "Allow",
      "Action": [
        "kinesis:GetRecords",
        "kinesis:GetShardIterator",
        "kinesis:DescribeStream",
        "kinesis:ListStreams"
      ],
      "Resource": "arn:aws:kinesis:ap-southeast-1:961341553833:stream/CryptoStream"
    },
    {
      "Sid": "DynamoDBAccessMainTable",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:DescribeTable"
      ],
      "Resource": "arn:aws:dynamodb:ap-southeast-1:961341553833:table/CryptoTrends_table"
    },
    {
      "Sid": "SNSPublishAlertMain",
      "Effect": "Allow",
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:ap-southeast-1:961341553833:CryptoTrendAlerts"
    },
    {
      "Sid": "CloudWatchLogging",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

---

### 3. Deploy Lambda Functions

> 📢 **Note:** If your Lambda Python environment does not have the `requests` library, create and add a **Layer** from a ZIP file containing `requests-py312`.

#### 3.1 Create `fetch_prices` Lambda Function

- **Runtime:** Python 3.12
- **Code:** Upload `fetch_prices_lambda_function.py`
- **Role:** Attach `cryptomood_lambda_role`
- **Trigger:**  
  - **AWS EventBridge (CloudWatch Events)**  
  - **Schedule:** Every 1 minute
- **Environment variables:**
  - `KINESIS_STREAM=CryptoStream`

#### 3.2 Create `process_cryptostream` Lambda Function

- **Runtime:** Python 3.12
- **Code:** Upload `process_cryptostream_lambda_function.py`
- **Role:** Attach `cryptomood_lambda_role`
- **Trigger:**  
  - **AWS Kinesis (Stream):** `CryptoStream`
  - **Starting Position:** Latest
- **Environment variables:**
  - `DYNAMODB_TABLE=CryptoTrends_table`
  - `SNS_TOPIC_ARN=arn:aws:sns:ap-southeast-1:961341553833:CryptoTrendAlerts`

#### 3.3 Create `sns_to_discord_forwarder` Lambda Function

- **Runtime:** Python 3.12
- **Code:** Upload `sns_to_discord_forwarder_lambda_function.py`
- **Role:** Attach `cryptomood_lambda_role`
- **Trigger:**  
  - **AWS SNS (Topic):** `CryptoTrendAlerts`
- **Environment variables:**
  - `DISCORD_WEBHOOK_URL=https://discordapp.com/api/webhooks/(your webhook)`

> 📢 **Note:** You must first create a webhook URL in your Discord server.

---

### 4. Testing

- Send a test crypto price record into the `CryptoStream`.
- Verify that the DynamoDB table is updated with trend history.
- Verify that SNS sends an alert (Golden Cross / Dead Cross) to Discord.






