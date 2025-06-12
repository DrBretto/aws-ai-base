import os
import boto3
import json
from datetime import datetime, timedelta
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
lambda_client = boto3.client('lambda')
s3_client = boto3.client('s3')

# Environment variables
SCRAPER_LAMBDA_NAME = os.environ.get("SCRAPER_LAMBDA_NAME")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME") # Use the existing S3 bucket
BACKFILL_STATE_KEY = "tiingo_backfill_state/progress.json" # Key for the state file in S3 - Made more descriptive

# Backfill configuration
CHUNK_DAYS = 180  # Process data in 180-day (approx 6 months) chunks
OVERLAP_DAYS = 7 # Number of days to overlap between chunks to ensure no data is missed

def get_backfill_state(bucket_name, state_key):
    """
    Retrieves the last processed end date from an S3 object.
    """
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=state_key)
        state_data = json.loads(response['Body'].read().decode('utf-8'))
        last_date_str = state_data.get('last_processed_date')
        if last_date_str:
            return datetime.strptime(last_date_str, '%Y-%m-%d')
        else:
            logger.info("Backfill state file found but 'last_processed_date' is missing. Starting from 5 years ago.")
            return datetime.now() - timedelta(days=5*365)
    except s3_client.exceptions.NoSuchKey:
        logger.info("Backfill state file not found. Starting from 5 years ago.")
        return datetime.now() - timedelta(days=5*365)
    except Exception as e:
        logger.error(f"Error getting backfill state from S3: {e}")
        return datetime.now() - timedelta(days=5*365)

def update_backfill_state(bucket_name, state_key, last_processed_date):
    """
    Updates the last processed end date in the S3 state object.
    """
    try:
        state_data = {'last_processed_date': last_processed_date.strftime('%Y-%m-%d')}
        s3_client.put_object(
            Bucket=bucket_name,
            Key=state_key,
            Body=json.dumps(state_data).encode('utf-8')
        )
        logger.info(f"Updated backfill state in S3 to {last_processed_date.strftime('%Y-%m-%d')}")
    except Exception as e:
        logger.error(f"Error updating backfill state in S3: {e}")

def lambda_handler(event, context):
    """
    Lambda function to orchestrate the backfill process.
    Triggers the scraper Lambda for chunks until up to today.
    """
    request_id = context.aws_request_id if context else 'local'
    logger.info(f"--- Starting Tiingo Backfill Orchestrator --- Request ID: {request_id}")

    if not SCRAPER_LAMBDA_NAME or not S3_BUCKET_NAME:
        logger.error("SCRAPER_LAMBDA_NAME or S3_BUCKET_NAME environment variables not set.")
        return {
            'statusCode': 500,
            'body': 'Configuration error.'
        }

    last_processed_date = get_backfill_state(S3_BUCKET_NAME, BACKFILL_STATE_KEY)
    current_date = datetime.now().date()

    # Always move forward: next chunk is after last_processed_date
    chunk_start_date = last_processed_date + timedelta(days=1)
    chunk_end_date = chunk_start_date + timedelta(days=CHUNK_DAYS - 1)
    if chunk_end_date.date() > current_date:
        chunk_end_date = current_date

    logger.info(f"Chunk start date: {chunk_start_date.strftime('%Y-%m-%d')}")
    logger.info(f"Chunk end date: {chunk_end_date.strftime('%Y-%m-%d')}")

    if chunk_start_date > chunk_end_date:
        logger.info("Backfill complete or no new data to process.")
        return {
            'statusCode': 200,
            'body': 'Backfill complete or no new data to process.'
        }

    try:
        payload = {
            'type': 'backfill',
            'start_date': chunk_start_date.strftime('%Y-%m-%d'),
            'end_date': chunk_end_date.strftime('%Y-%m-%d')
        }
        logger.info(f"Triggering scraper Lambda for backfill chunk: {chunk_start_date.strftime('%Y-%m-%d')} to {chunk_end_date.strftime('%Y-%m-%d')}")
        lambda_client.invoke(
            FunctionName=SCRAPER_LAMBDA_NAME,
            InvocationType='Event',
            Payload=json.dumps(payload)
        )
        logger.info("Scraper Lambda triggered successfully.")

        # Update the backfill state to the end date of this chunk
        update_backfill_state(S3_BUCKET_NAME, BACKFILL_STATE_KEY, chunk_end_date)

        return {
            'statusCode': 200,
            'body': f'Triggered backfill for {chunk_start_date.strftime("%Y-%m-%d")} to {chunk_end_date.strftime("%Y-%m-%d")}.'
        }

    except Exception as e:
        logger.error(f"Error triggering scraper Lambda: {e}")
        return {
            'statusCode': 500,
            'body': 'Error triggering scraper Lambda.'
        }