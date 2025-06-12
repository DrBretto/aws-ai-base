import sys
import os

# Add the vendor directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vendor'))
import os
import requests
import boto3
import time
import json
from datetime import datetime, timedelta, date
import logging

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Tiingo API configuration
TIINGO_API_KEY = os.environ.get("TIINGO_API_KEY")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")

# Tickers and interval
# Replaced EEM with XAUUSD for spot gold, keeping the list size at 12
TICKERS = ["DXY", "VIX", "TLT", "GDX", "SPY", "XLF", "DBC", "XAUUSD", "TIP", "IWM", "NUGT", "JDST"]
INTERVAL = "15min" # Changed interval back to 15min

# S3 client
s3_client = boto3.client("s3")

def make_tiingo_request(url, headers, params):
    """
    Makes a single API request to Tiingo.
    """
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        status_code = e.response.status_code if hasattr(e, 'response') and e.response is not None else 'N/A'
        logger.error(f"Request failed for {url} with status code {status_code}: {e}")
        return None

def fetch_tiingo_data(ticker, start_date, end_date):
    """
    Fetches historical data for a single ticker from Tiingo API using appropriate endpoint.
    Returns raw JSON data.
    """
    if not TIINGO_API_KEY:
        logger.error("TIINGO_API_KEY environment variable not set.")
        return None

    # Use iex endpoint for all tickers as in reference_only.py
    endpoint = "iex"
    url = (
        f"https://api.tiingo.com/{endpoint}/{ticker}/prices?resampleFreq={INTERVAL}"
        f"&startDate={start_date.strftime('%Y-%m-%d')}&endDate={end_date.strftime('%Y-%m-%d')}"
        f"&token={TIINGO_API_KEY}&columns=open,high,low,close,volume"
    )
    logger.info(f"Attempting to fetch data for {ticker} from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')} using /{endpoint} endpoint")

    # Note: reference_only.py had a separate crypto endpoint, but user requested to ignore BTC.
    # All other tickers in our list are likely covered by /iex.
    # If other non-equity tickers are added later, this logic may need adjustment.

    headers = {
        'Content-Type': 'application/json'
    }

    data = make_tiingo_request(url, headers, {})

    if data:
        logger.info(f"Successfully fetched data for {ticker}.")
        return data # Return raw JSON data
    else:
        logger.warning(f"Failed to fetch data for {ticker}.")
        return None

def save_to_s3(data, ticker):
    """
    Saves data points grouped by date to S3 in JSON format with TICKER/YYYY/MM/DD structure.
    Handles different data structures from different endpoints.
    """
    if not data:
        logger.warning(f"No data to save for {ticker}.")
        return

    if not S3_BUCKET_NAME:
        logger.error("S3_BUCKET_NAME environment variable not set.")
        return

    logger.info(f"Attempting to save {len(data)} records for {ticker} to S3.")

    # Check if data is a list of data points (expected from /iex and /tiingo/daily)
    if isinstance(data, list):
        # Group data by date
        data_by_date = {}
        for entry in data:
            if 'date' not in entry:
                logger.warning(f"Skipping entry for {ticker} due to missing 'date' field: {entry}")
                continue
            try:
                # Parse the date
                ts_str_original = entry['date']
                ts_str = ts_str_original.replace('Z', '+00:00')
                if '.' in ts_str:
                     tz_part = ''
                     if '+' in ts_str: tz_part = '+' + ts_str.split('+')[-1]
                     elif '-' in ts_str[10:]: tz_part = '-' + ts_str.split('-')[-1]
                     ts_str = ts_str.split('.')[0] + tz_part
                dt = datetime.fromisoformat(ts_str)
                date_key = dt.date() # Use date object as dictionary key
                if date_key not in data_by_date:
                    data_by_date[date_key] = []
                data_by_date[date_key].append(entry)
            except ValueError as e:
                logger.error(f"Could not parse date '{ts_str_original}' for {ticker} during grouping: {e}")
                continue # Skip this entry if date parsing fails

        logger.info(f"Grouped data for {ticker} into {len(data_by_date)} dates.")

        # Save data for each date to a single file
        for date_obj, entries_for_date in data_by_date.items():
            try:
                day_str = date_obj.strftime('%Y/%m/%d') # YYYY/MM/DD folder structure
                # S3 key format: tiingo/TICKER/yyyy/mm/dd/data.json
                s3_key = f"tiingo/{ticker}/{day_str}/data.json"
                file_path = f"/tmp/{ticker}_{date_obj.strftime('%Y%m%d')}_data.json" # Save to /tmp first

                # Save all data points for this date to a single temporary file
                with open(file_path, 'w') as f:
                    json.dump(entries_for_date, f)

                # Upload the temporary file to S3
                s3_client.upload_file(file_path, S3_BUCKET_NAME, s3_key)
                logger.info(f"Successfully saved {s3_key} to S3 bucket {S3_BUCKET_NAME}.")

            except Exception as e:
                logger.error(f"Error saving data for {ticker} on {date_obj.strftime('%Y-%m-%d')} to S3: {e}")
            finally:
                # Clean up the temporary file
                if os.path.exists(file_path):
                    os.remove(file_path)

    else:
        logger.warning(f"Unexpected data format for {ticker}. Expected a list, but received: {type(data)}")


def lambda_handler(event, context):
    """
    Main Lambda function handler.
    Determines the date range based on the event (hourly, backfill chunk, or daily).
    """
    try:
        import requests
        logger.info("Requests library imported successfully.")
    except ImportError:
        logger.error("Requests library not found.")

    try:
        end_date = datetime.now()
        start_date = None

        # Determine date range based on event type
        # Assuming event['type'] can be 'hourly', 'backfill', or 'daily'
        event_type = event.get('type', 'hourly')

        if event_type == 'hourly':
            # Hourly job: last 6 months (default behavior if no type specified)
            start_date = end_date - timedelta(days=6*30) # Approximate 6 months
            logger.info("Running hourly job: fetching last 6 months of data.")
        elif event_type == 'backfill':
            # Backfill job: date range provided in event
            try:
                start_date = datetime.strptime(event['start_date'], '%Y-%m-%d')
                end_date = datetime.strptime(event['end_date'], '%Y-%m-%d')
                logger.info(f"Running backfill job: fetching data from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}.")
            except KeyError:
                logger.error("Backfill event requires 'start_date' and 'end_date'.")
                return {
                    'statusCode': 400,
                    'body': 'Backfill event requires start_date and end_date.'
                }
            except ValueError:
                 logger.error("Invalid date format in event. Use YYYY-MM-DD.")
                 return {
                    'statusCode': 400,
                    'body': 'Invalid date format in event. Use YYYY-MM-DD.'
                 }
        elif event_type == 'daily':
            # Daily job: fetch data for the previous day
            today = datetime.now().date()
            yesterday = today - timedelta(days=1)
            start_date = datetime.combine(yesterday, datetime.min.time())
            end_date = datetime.combine(yesterday, datetime.max.time())
            logger.info(f"Running daily job: fetching data for {yesterday.strftime('%Y-%m-%d')}.")
        else:
            logger.error(f"Unknown event type: {event_type}")
            return {
                'statusCode': 400,
                'body': f'Unknown event type: {event_type}'
            }

        if start_date is None:
             return {
                'statusCode': 500,
                'body': 'Failed to determine date range.'
             }

        # Fetch and save data for each ticker
        for ticker in TICKERS:
            data = fetch_tiingo_data(ticker, start_date, end_date)
            if data: # Check if data is not None and not empty list/dict
                logger.info(f"Data fetched successfully for {ticker}. Attempting to save to S3.")
                # Pass the fetched data to the modified save_to_s3 function
                save_to_s3(data, ticker)
            else:
                logger.warning(f"Failed to fetch data for {ticker}. Skipping save to S3.")
            time.sleep(1) # Reverted delay to 1 second


        return {
            'statusCode': 200,
            'body': 'Tiingo data scraping complete.'
        }
    except Exception as e:
        logger.error(f"An error occurred during Lambda execution: {e}")
        return {
            'statusCode': 500,
            'body': f'An error occurred during Lambda execution: {e}'
        }