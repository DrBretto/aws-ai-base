import os
import json
import boto3
from datetime import datetime, timedelta
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
SCRAPER_LAMBDA_NAME = os.environ.get("SCRAPER_LAMBDA_NAME")
BACKFILL_STATE_KEY = os.environ.get("BACKFILL_STATE_KEY", "GDELT/backfill_state.json")

s3_client = boto3.client("s3")
lambda_client = boto3.client("lambda")

# Backfill 1 day (96 intervals) per invocation for efficiency
CHUNK_INTERVALS = 96  # 24h * 4 (15-min intervals)

def get_backfill_state(bucket_name, state_key):
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=state_key)
        state_data = json.loads(response['Body'].read().decode('utf-8'))
        last_dt_str = state_data.get('last_processed_dt')
        if last_dt_str:
            return datetime.strptime(last_dt_str, '%Y-%m-%dT%H:%M')
        else:
            logger.info("Backfill state file found but 'last_processed_dt' is missing. Starting from 5 years ago.")
            return datetime.utcnow() - timedelta(days=5*365)
    except s3_client.exceptions.NoSuchKey:
        logger.info("Backfill state file not found. Starting from 5 years ago.")
        return datetime.utcnow() - timedelta(days=5*365)
    except Exception as e:
        logger.error(f"Error getting backfill state from S3: {e}")
        return datetime.utcnow() - timedelta(days=5*365)

def update_backfill_state(bucket_name, state_key, last_processed_dt):
    try:
        state_data = {'last_processed_dt': last_processed_dt.strftime('%Y-%m-%dT%H:%M')}
        s3_client.put_object(
            Bucket=bucket_name,
            Key=state_key,
            Body=json.dumps(state_data).encode('utf-8')
        )
        logger.info(f"Updated backfill state in S3 to {last_processed_dt.strftime('%Y-%m-%dT%H:%M')}")
    except Exception as e:
        logger.error(f"Error updating backfill state in S3: {e}")

def lambda_handler(event, context):
    request_id = context.aws_request_id if context else 'local'
    logger.info(f"--- Starting GDELT Backfill Orchestrator --- Request ID: {request_id}")

    if not SCRAPER_LAMBDA_NAME or not S3_BUCKET_NAME:
        logger.error("SCRAPER_LAMBDA_NAME or S3_BUCKET_NAME environment variables not set.")
        return {
            'statusCode': 500,
            'body': 'Configuration error.'
        }

    last_processed_dt = get_backfill_state(S3_BUCKET_NAME, BACKFILL_STATE_KEY)
    now = datetime.utcnow()
    intervals = []
    dt = last_processed_dt + timedelta(minutes=15)
    for _ in range(CHUNK_INTERVALS):
        if dt > now:
            break
        intervals.append(dt)
        dt += timedelta(minutes=15)

    if not intervals:
        logger.info("Backfill complete or no new intervals to process.")
        return {
            'statusCode': 200,
            'body': 'Backfill complete or no new intervals to process.'
        }

    # Trigger the scraper Lambda for each interval (fan-out, async)
    for interval_dt in intervals:
        payload = {
            "year": interval_dt.year,
            "month": interval_dt.month,
            "day": interval_dt.day,
            "hour": interval_dt.hour,
            "minute": interval_dt.minute
        }
        logger.info(f"Triggering scraper Lambda for {interval_dt.isoformat()}")
        try:
            lambda_client.invoke(
                FunctionName=SCRAPER_LAMBDA_NAME,
                InvocationType='Event',
                Payload=json.dumps(payload)
            )
        except Exception as e:
            logger.error(f"Error triggering scraper Lambda for {interval_dt}: {e}")

    # Update the backfill state to the last interval processed
    update_backfill_state(S3_BUCKET_NAME, BACKFILL_STATE_KEY, intervals[-1])

    return {
        'statusCode': 200,
        'body': f'Triggered backfill for {len(intervals)} intervals up to {intervals[-1].isoformat()}.'
    }