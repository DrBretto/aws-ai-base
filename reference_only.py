import json
import boto3
import requests
import os
from datetime import datetime, timedelta
import logging

# Configuration
bucket_name = os.environ['S3_BUCKET_NAME']
manifest_key = f"{os.environ['S3_FOLDER_PATH']}/manifest.json"

# Initialize SSM client and logger
ssm_client = boto3.client('ssm')
logger = logging.getLogger()
logger.setLevel(logging.INFO) # Set to INFO, use DEBUG in functions if needed

# Fetch API key from SSM
try:
    parameter = ssm_client.get_parameter(Name='/tiingo/api_key', WithDecryption=True)
    api_key = parameter['Parameter']['Value']
    logger.info("Successfully retrieved Tiingo API key from SSM Parameter Store.")
except Exception as e:
    logger.error(f"Failed to retrieve Tiingo API key from SSM: {str(e)}")
    api_key = None # Ensure api_key is None if retrieval fails

logger.info(f"Using bucket: {bucket_name}")
logger.info(f"API Key retrieved: {'Yes' if api_key else 'No'}")

# Define tickers and their types
tickers = [
    {'symbol': 'SPY', 'type': 'equity'},
    {'symbol': 'GLD', 'type': 'equity'},
    {'symbol': 'SLV', 'type': 'equity'},
    {'symbol': 'VXX', 'type': 'equity'},
    {'symbol': 'USO', 'type': 'equity'},
    {'symbol': 'UUP', 'type': 'equity'},
    {'symbol': 'JDST', 'type': 'equity'},
    {'symbol': 'NUGT', 'type': 'equity'},
    {'symbol': 'BTC', 'type': 'crypto'}  # BTC handled as crypto
]

interval = '15min'
# Set earliest date reasonably far back, e.g., 5 years
earliest_possible_date = datetime.now() - timedelta(days=5*365)
chunk_days = 180  # Process data in 180-day (approx 6 months) chunks

s3_client = boto3.client('s3')

def load_manifest():
    logger.debug(f"Attempting to load manifest from {bucket_name}/{manifest_key}")
    try:
        resp = s3_client.get_object(Bucket=bucket_name, Key=manifest_key)
        manifest_data = json.loads(resp['Body'].read().decode('utf-8'))
        logger.info(f"Loaded manifest: {manifest_data}")
        return manifest_data
    except s3_client.exceptions.NoSuchKey:
        logger.info("Manifest not found. Initializing.")
        # If no manifest, initialize each ticker to today (no backfill done yet)
        now_str = datetime.now().strftime('%Y-%m-%d')
        return {t['symbol']: now_str for t in tickers}
    except Exception as e:
        logger.error(f"Error loading manifest: {e}")
        # Return an empty dict or raise error depending on desired handling
        return {}


def save_manifest(manifest):
    logger.debug(f"Attempting to save manifest to {bucket_name}/{manifest_key}")
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=manifest_key,
            Body=json.dumps(manifest),
            ContentType="application/json"
        )
        logger.info(f"Successfully saved manifest.") # Avoid logging full manifest repeatedly if large
        logger.debug(f"Saved manifest content: {manifest}")
    except Exception as e:
        logger.error(f"Failed to save manifest: {e}")
        # raise e # Optional: re-raise if save failure should stop execution


def fetch_data_from_tiingo(ticker, ticker_type, start_date, end_date):
    """Fetches data for a given ticker and date range."""
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    logger.info(f"[FETCH START] Fetching {ticker_type} data for {ticker} from {start_str} to {end_str}")

    if ticker_type == 'crypto':
        url = (
            f"https://api.tiingo.com/tiingo/crypto/prices?tickers={ticker.lower()}usd&resampleFreq={interval}"
            f"&startDate={start_str}&endDate={end_str}"
            f"&token={api_key}&columns=open,high,low,close,volume"
        )
    else: # equity
        url = (
            f"https://api.tiingo.com/iex/{ticker}/prices?resampleFreq={interval}"
            f"&startDate={start_str}&endDate={end_date.strftime('%Y-%m-%d')}"
            f"&token={api_key}&columns=open,high,low,close,volume"
        )
    logger.debug(f"Fetch URL: {url}")
    try:
        resp = requests.get(url, timeout=60) # Add a timeout
        logger.debug(f"Fetch response status code: {resp.status_code}")
        resp.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        data = resp.json()
        record_count = 0
        if ticker_type == 'crypto' and data and isinstance(data[0], dict) and 'priceData' in data[0]:
            if data[0]['priceData']:
                first_entry = data[0]['priceData'][0]
                first_date = first_entry.get('date', 'unknown')
                logger.info(f"First date in crypto data for {ticker}: {first_date}")
            else:
                logger.info(f"No priceData found in crypto response for {ticker}")
            extracted_data = data[0]['priceData']
            record_count = len(extracted_data)
            logger.info(f"[FETCH END] Successfully fetched and extracted {record_count} crypto records for {ticker}.")
            return extracted_data
        elif ticker_type == 'equity':
             record_count = len(data)
             logger.info(f"[FETCH END] Successfully fetched {record_count} equity records for {ticker}.")
             return data
        else:
             logger.warning(f"[FETCH END] Unexpected data structure or empty data for {ticker}: {data}")
             return [] # Return empty list for unexpected structure

    except requests.exceptions.RequestException as e:
        logger.error(f"[FETCH FAIL] API request failed for {ticker} ({start_str} to {end_str}): {e}")
        return None # Indicate API failure
    except json.JSONDecodeError as e:
         logger.error(f"[FETCH FAIL] Failed to decode JSON response for {ticker} ({start_str} to {end_str}): {e}")
         return None # Indicate JSON failure


def store_data_in_s3(ticker, data):
    """
    Stores fetched data points in daily JSON files on S3.
    Returns True if all writes succeed, False otherwise.
    """
    logger.info(f"[STORE START] Storing {len(data)} fetched records for {ticker}.")
    time_field = 'date'
    daily_grouped_data = {}
    parse_errors = 0

    for entry_idx, entry in enumerate(data):
        if time_field not in entry:
            logger.warning(f"[STORE PARSE SKIP] Entry {entry_idx}: Field '{time_field}' not found for {ticker}: {entry}")
            parse_errors += 1
            continue

        ts_str_original = entry[time_field]
        try:
            ts_str = ts_str_original.replace('Z', '+00:00')
            if '.' in ts_str:
                 tz_part = ''
                 if '+' in ts_str: tz_part = '+' + ts_str.split('+')[-1]
                 elif '-' in ts_str[10:]: tz_part = '-' + ts_str.split('-')[-1]
                 ts_str = ts_str.split('.')[0] + tz_part

            dt = datetime.fromisoformat(ts_str)
            day_str = dt.strftime('%Y-%m-%d')
            if day_str not in daily_grouped_data:
                daily_grouped_data[day_str] = []
            daily_grouped_data[day_str].append(entry)
        except ValueError as e:
            logger.error(f"Could not parse date '{ts_str_original}' for {ticker}: {e}")
            parse_errors += 1
            continue

    if parse_errors > 0:
         logger.warning(f"Encountered {parse_errors} date parsing errors while grouping data for {ticker}.")

    logger.info(f"Grouped data for {ticker} into {len(daily_grouped_data)} days.")
    if not daily_grouped_data:
         logger.info(f"[STORE END] No data to store for {ticker} after grouping/parsing.")
         return True # Nothing to write

    all_writes_succeeded = True
    days_processed = 0
    for day_str, entries_for_day in daily_grouped_data.items():
        days_processed += 1
        logger.debug(f"[STORE DAY START] Processing day {day_str} ({len(entries_for_day)} entries) for {ticker}")
        year, month, day = day_str.split('-')
        s3_key = f"{os.environ.get('S3_FOLDER_PATH', 'tiingo')}/{year}/{month}/{day}/{ticker}.json"
        day_data = []

        try:
            logger.debug(f"Attempting to read existing data from {s3_key}")
            existing_resp = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
            day_data = json.loads(existing_resp['Body'].read().decode('utf-8'))
            logger.debug(f"Read {len(day_data)} existing entries from {s3_key}")
        except s3_client.exceptions.NoSuchKey:
            logger.debug(f"No existing data for {s3_key}, creating new file.")
        except Exception as e:
            logger.error(f"Error reading existing data from {s3_key}: {e}")
            all_writes_succeeded = False
            continue # Skip writing this day if read failed

        # Append new entries
        original_count = len(day_data)
        day_data.extend(entries_for_day)
        logger.debug(f"Appending {len(entries_for_day)} new entries to {s3_key}. New total: {len(day_data)}")

        # Write the combined data back ONCE for the day
        try:
            logger.debug(f"Attempting to write {len(day_data)} total entries to {s3_key}")
            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=json.dumps(day_data),
                ContentType="application/json"
            )
            logger.debug(f"[STORE DAY WRITE OK] Successfully wrote to {s3_key}")
        except Exception as e:
            logger.error(f"Error writing data to {s3_key}: {e}")
            all_writes_succeeded = False
            # Continue trying other days

    if all_writes_succeeded:
         logger.info(f"[STORE END] Successfully stored data chunk for {ticker} ({days_processed} days).")
    else:
         logger.error(f"[STORE END] Encountered errors storing data chunk for {ticker} ({days_processed} days attempted).")

    return all_writes_succeeded


def lambda_handler(event, context):
    """
    Processes ONE chunk for ALL tickers per invocation.
    Updates manifest after each ticker if fetch and store succeed.
    """
    request_id = context.aws_request_id if context else 'local'
    logger.info(f"--- Starting Tiingo History Lambda --- Request ID: {request_id}")
    if not api_key:
        logger.error("Tiingo API key not configured. Exiting.")
        return {'statusCode': 500, 'body': json.dumps("API key not configured.")}

    manifest = load_manifest()
    if not manifest:
         logger.error("Failed to load or initialize manifest. Exiting.")
         return {'statusCode': 500, 'body': json.dumps("Manifest load error.")}

    results = []
    manifest_updated_in_run = False # Track if any update happened in this run

    api_call_count = 0 # Initialize API call counter
    logger.info(f"--- Processing {len(tickers)} tickers ---")
    for ticker_idx, ticker_obj in enumerate(tickers):
        ticker = ticker_obj['symbol']
        ticker_type = ticker_obj['type']
        logger.info(f"--- Loop Iteration {ticker_idx+1}/{len(tickers)}: Processing ticker: {ticker} ---")
        logger.info(f"[{ticker}] Manifest state BEFORE processing: {manifest}")
        manifest_updated_this_ticker = False # Flag for THIS iteration
        chunks_processed_this_ticker = 0

        # Get current earliest date from manifest for this ticker
        try:
            current_earliest_str = manifest.get(ticker, datetime.now().strftime('%Y-%m-%d'))
            logger.debug(f"[{ticker}] Manifest date string: {current_earliest_str}")
            current_earliest = datetime.strptime(current_earliest_str, '%Y-%m-%d')
            logger.debug(f"[{ticker}] Parsed manifest date: {current_earliest.date()}")
        except ValueError:
             logger.error(f"[{ticker}] Invalid date format '{manifest.get(ticker)}' in manifest. Skipping.")
             results.append(f"Error: Invalid manifest date for {ticker}.")
             continue # Skip to next ticker

        # Check if already fully backfilled
        if current_earliest.date() <= earliest_possible_date.date():
            logger.info(f"[{ticker}] Already fully backfilled to {current_earliest_str}. Skipping.")
            # Ensure the manifest reflects it's fully backfilled if it wasn't exact
            if manifest.get(ticker) != earliest_possible_date.strftime('%Y-%m-%d'):
                 logger.info(f"[{ticker}] Correcting manifest to exact earliest date.")
                 manifest[ticker] = earliest_possible_date.strftime('%Y-%m-%d')
                 manifest_updated_this_ticker = True
                 chunks_processed_this_ticker += 1
            results.append(f"{ticker}: Already backfilled.")
            # Go save manifest if needed, then continue to next ticker
            if manifest_updated_this_ticker:
                logger.info(f"[{ticker}] Saving manifest after marking as fully backfilled.")
                # *** LOG MANIFEST STATE BEFORE SAVE ***
                logger.info(f"[{ticker}] Manifest state BEFORE save (already backfilled): {manifest}")
                save_manifest(manifest)
                manifest_updated_in_run = True
            logger.info(f"--- Finished Iteration {ticker_idx+1}/{len(tickers)} for {ticker} (Already Backfilled). Chunks processed this iteration: {chunks_processed_this_ticker} ---")
            if chunks_processed_this_ticker > 1: logger.critical(f"CRITICAL WARNING: Processed {chunks_processed_this_ticker} chunks for {ticker} in one iteration!")
            continue

        # Calculate date range for this chunk
        end_date = current_earliest
        start_date = end_date - timedelta(days=chunk_days)
        logger.debug(f"[{ticker}] Calculated date range (end): {end_date.strftime('%Y-%m-%d')}")
        logger.debug(f"[{ticker}] Calculated date range (start): {start_date.strftime('%Y-%m-%d')}")

        # Clamp start_date
        if start_date < earliest_possible_date:
            start_date = earliest_possible_date
            logger.info(f"[{ticker}] Clamped start date to earliest possible: {start_date.strftime('%Y-%m-%d')}")

        # Check if reached limit
        if start_date >= end_date:
            logger.info(f"[{ticker}] Reached earliest possible date {earliest_possible_date.strftime('%Y-%m-%d')}. Marking as fully backfilled.")
            new_manifest_date = earliest_possible_date.strftime('%Y-%m-%d')
            if manifest.get(ticker) != new_manifest_date:
                 logger.info(f"[{ticker}] Updating manifest to final earliest date.")
                 manifest[ticker] = new_manifest_date
                 manifest_updated_this_ticker = True
                 chunks_processed_this_ticker += 1
            results.append(f"{ticker}: Reached earliest date.")
            # Go save manifest if needed, then continue to next ticker
            if manifest_updated_this_ticker:
                logger.info(f"[{ticker}] Saving manifest after reaching earliest date.")
                # *** LOG MANIFEST STATE BEFORE SAVE ***
                logger.info(f"[{ticker}] Manifest state BEFORE save (reached earliest): {manifest}")
                save_manifest(manifest)
                manifest_updated_in_run = True
            logger.info(f"--- Finished Iteration {ticker_idx+1}/{len(tickers)} for {ticker} (Reached Earliest). Chunks processed this iteration: {chunks_processed_this_ticker} ---")
            if chunks_processed_this_ticker > 1: logger.critical(f"CRITICAL WARNING: Processed {chunks_processed_this_ticker} chunks for {ticker} in one iteration!")
            continue

        # Proceed with fetching and storing this chunk
        logger.info(f"[{ticker}] Processing chunk: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        try:
            api_call_count += 1
            data = fetch_data_from_tiingo(ticker, ticker_type, start_date, end_date)

            if data is None: # API call failed
                 results.append(f"Error: API call failed for {ticker}.")
                 logger.warning(f"[{ticker}] API fetch failed. Manifest not updated for this chunk.")
            elif len(data) > 0:
                storage_success = store_data_in_s3(ticker, data)
                if storage_success:
                    logger.info(f"[{ticker}] Storage successful. Updating manifest to {start_date.strftime('%Y-%m-%d')}.")
                    manifest[ticker] = start_date.strftime('%Y-%m-%d')
                    manifest_updated_this_ticker = True
                    chunks_processed_this_ticker += 1
                    results.append(f"{ticker}: Successfully processed chunk {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}.")
                else:
                    results.append(f"Error: Storage failed for {ticker} chunk ending {end_date.strftime('%Y-%m-%d')}. Manifest not updated.")
                    logger.error(f"[{ticker}] Storage failed. Manifest not updated for this chunk.")
            else: # API call succeeded but returned empty list
                 logger.info(f"[{ticker}] No data returned by Tiingo in range {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}. Considering this range complete.")
                 manifest[ticker] = start_date.strftime('%Y-%m-%d')
                 manifest_updated_this_ticker = True
                 chunks_processed_this_ticker += 1
                 results.append(f"{ticker}: No data in range {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}, marked complete.")

        except Exception as e:
            # Catch any unexpected errors during processing
            logger.exception(f"[{ticker}] An unexpected error occurred processing chunk: {e}")
            results.append(f"Error: Unexpected exception processing {ticker}: {e}")

        # --- Save manifest after each ticker IF it was updated ---
        if manifest_updated_this_ticker:
            logger.info(f"[{ticker}] Attempting to save manifest after processing.")
            # *** LOG MANIFEST STATE BEFORE SAVE ***
            logger.info(f"[{ticker}] Manifest state BEFORE save (after processing): {manifest}")
            try:
                save_manifest(manifest)
                manifest_updated_in_run = True
            except Exception as e:
                 logger.error(f"[{ticker}] Failed to save updated manifest: {e}")

        logger.info(f"--- Finished Iteration {ticker_idx+1}/{len(tickers)} for {ticker}. Chunks processed this iteration: {chunks_processed_this_ticker} ---")
        # <<< Add critical warning if counter > 1 >>>
        if chunks_processed_this_ticker > 1:
            logger.critical(f"CRITICAL WARNING: Processed {chunks_processed_this_ticker} chunks for {ticker} in one iteration!")


    logger.info("--- Finished processing all tickers loop ---")
    final_message = "Historical data processing summary: " + " | ".join(results)
    logger.info(final_message)
    logger.info(f"Total API calls made in this run: {api_call_count}")
    logger.info(f"--- Ending Tiingo History Lambda --- Request ID: {request_id}")
    return {
        'statusCode': 200, # Return 200, check body/logs for outcome
        'body': json.dumps(final_message)
    }
