import json
import boto3
import gzip
import io
import zipfile
import re
import os
from datetime import datetime

s3_client = boto3.client('s3')

# Define relevant themes for filtering
RELEVANT_THEMES = [
    'GOLD', 'SILVER', 'PLATINUM', 'PALLADIUM', 'PRECIOUS METALS',
    'INFLATION', 'CURRENCY', 'MONETARY POLICY', 'INTEREST RATES',
    'FINANCIAL MARKETS', 'COMMODITIES', 'STOCK MARKET',
    'ECONOMIC CRISIS', 'GEOPOLITICAL', 'RECESSION', 'FEDERAL RESERVE',
    'CENTRAL BANK', 'SAFE HAVEN', 'MARKET VOLATILITY', 'US DOLLAR',
    'CURRENCY EXCHANGE', 'ECONOMIC INDICATORS', 'GLOBAL MARKETS',
    'ECONOMY', 'TRADE', 'POLITICS', 'CLIMATE', 'HEALTH', 'MILITARY', 'WAR', 'TERRORISM'
]

# PROCESSED_PREFIX removed, will use environment variable S3_PROCESSED_FOLDER_PATH
# RAW_PREFIX removed, relying on EventBridge rule filter in template.yaml

def extract_timestamp_from_key(key):
    """Extracts timestamp from the S3 key (e.g., gdelt/raw/YYYY/MM/DD/HHMMSS_filename.zip)"""
    match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/(\d{6})_', key)
    if match:
        year, month, day, hms = match.groups()
        try:
            # Construct datetime from path components
            # Note: GDELT filenames use HHMMSS, so we parse that directly
            timestamp_str = f"{year}{month}{day}{hms}"
            return datetime.strptime(timestamp_str, '%Y%m%d%H%M%S')
        except ValueError:
            print(f"Error parsing timestamp from key: {key}")
            return None
    else:
        # Fallback: try extracting from filename like 20191116000000.gkg.csv.zip
        filename_match = re.search(r'(\d{14})\.gkg\.csv\.zip$', key)
        if filename_match:
             timestamp_str = filename_match.group(1)
             try:
                 return datetime.strptime(timestamp_str, '%Y%m%d%H%M%S')
             except ValueError:
                 print(f"Error parsing timestamp from filename in key: {key}")
                 return None
    print(f"Could not extract timestamp from key: {key}")
    return None


def process_csv_data(csv_file):
    """Processes the CSV content, filters rows, and returns a list of dictionaries."""
    print('Start processing CSV data')
    filtered_rows = []
    line_number = 0

    try:
        # Try decoding with utf-8 first
        decoded_content = io.TextIOWrapper(csv_file, encoding='utf-8', errors='strict')
        reader = decoded_content
    except UnicodeDecodeError:
        print('Warning: Failed to decode using utf-8, trying iso-8859-1 encoding.')
        csv_file.seek(0)  # Reset file pointer
        decoded_content = io.TextIOWrapper(csv_file, encoding='iso-8859-1', errors='replace')
        reader = decoded_content

    for line in reader:
        line_number += 1
        try:
            # Manually split the line by tab
            row = line.strip().split('\t')

            # Basic check for expected number of columns (GDELT GKG has many)
            if len(row) < 16: # Need at least up to V2Tone (index 15)
                # print(f'Warning: Skipping line {line_number} due to insufficient columns.')
                continue

            # Check if any relevant theme is present in V2Themes (index 7)
            themes_str = row[7] if len(row) > 7 else ''
            matched = any(theme in themes_str.upper() for theme in RELEVANT_THEMES)

            if matched:
                # Exclude rows containing 'GOLDMAN SACHS' in any field (case-insensitive)
                full_text_upper = '\t'.join(row).upper()
                if 'GOLDMAN SACHS' not in full_text_upper:
                    filtered_rows.append({
                        'GKGRecordID': row[0] if len(row) > 0 else '',
                        'Date': row[1] if len(row) > 1 else '',
                        # 'SourceCollectionIdentifier': row[2] if len(row) > 2 else '', # Often 1
                        'SourceCommonName': row[3] if len(row) > 3 else '',
                        'DocumentIdentifier': row[4] if len(row) > 4 else '',
                        'V2Themes': themes_str,
                        'V2Locations': row[9] if len(row) > 9 else '',
                        'V2Tone': row[15] if len(row) > 15 else '',
                        # Add other fields if needed, e.g., AllNames
                        'AllNames': row[31] if len(row) > 31 else '',
                    })
        except Exception as e:
            # Log errors on specific lines but continue processing
            print(f'Warning: Skipping line {line_number} due to error: {str(e)}')
            continue

    print(f'Finished processing CSV. Found {len(filtered_rows)} relevant records.')
    return filtered_rows


def save_processed_data_to_s3(data, bucket, target_time):
    """Saves the processed data as gzipped JSON to the processed S3 path from env vars."""
    processed_prefix = os.environ.get('S3_PROCESSED_FOLDER_PATH')
    if not processed_prefix:
        print("Error: S3_PROCESSED_FOLDER_PATH environment variable not set.")
        # Failing is safer than using a default or potentially wrong path.
        return None # Indicate failure
    if not processed_prefix.endswith('/'):
        processed_prefix += '/' # Ensure trailing slash

    if not target_time:
        print("Error: Cannot save data without a valid target_time.")
        return None

    # Construct the output key using the timestamp and env var path
    s3_key = f"{processed_prefix}{target_time.strftime('%Y/%m/%d/%H%M%S')}.json.gz"

    try:
        # Convert data to JSON and compress
        json_data = json.dumps(data)
        compressed_data = gzip.compress(bytes(json_data, 'utf-8'))

        # Upload to S3
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=compressed_data,
            ContentType='application/json',
            ContentEncoding='gzip'
        )
        print(f'Processed data successfully saved to s3://{bucket}/{s3_key}')
        return s3_key
    except Exception as e:
        print(f"Error saving processed data to s3://{bucket}/{s3_key}: {str(e)}")
        return None


def delete_s3_object(bucket, key):
    """Deletes an object from S3."""
    try:
        s3_client.delete_object(Bucket=bucket, Key=key)
        print(f"Successfully deleted s3://{bucket}/{key}")
    except Exception as e:
        print(f"Error deleting s3://{bucket}/{key}: {str(e)}")


def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")

    # Get bucket and key from the S3 event notification
    try:
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
    except (KeyError, IndexError):
        print("Error: Could not parse bucket/key from event.")
        return {'statusCode': 400, 'body': 'Invalid S3 event format'}

    # Note: The check for RAW_PREFIX is removed.
    # The EventBridge rule in template.yaml already filters for objects
    # created under the 'gdelt/raw/' prefix defined there.

    print(f"Processing raw file: s3://{bucket}/{key}")

    # Extract timestamp from the key
    target_time = extract_timestamp_from_key(key)
    if not target_time:
        print(f"Error: Could not determine timestamp for key {key}. Skipping.")
        # Optionally, move the file to an error location instead of deleting
        return {'statusCode': 400, 'body': 'Could not extract timestamp from key'}

    try:
        # Download the raw zip file
        response = s3_client.get_object(Bucket=bucket, Key=key)
        zip_content = response['Body'].read()
        print(f"Successfully downloaded raw file: {key}")

        processed_data = []
        # Process the CSV content inside the zip file
        with io.BytesIO(zip_content) as zip_buffer:
            # Check if it's actually a zip file
            if not zipfile.is_zipfile(zip_buffer):
                 print(f"Error: File s3://{bucket}/{key} is not a valid zip file.")
                 # Consider moving to an error location
                 return {'statusCode': 400, 'body': 'File is not a valid zip file'}

            zip_buffer.seek(0) # Reset buffer position after is_zipfile check
            with zipfile.ZipFile(zip_buffer) as zip_file:
                for file_name in zip_file.namelist():
                    # Expecting only one CSV file per zip usually
                    if file_name.lower().endswith('.csv'):
                        print(f'Processing CSV file within zip: {file_name}')
                        with zip_file.open(file_name) as csv_file:
                            processed_data = process_csv_data(csv_file)
                        break # Process only the first CSV found
                else:
                     print(f"Warning: No .csv file found within zip: {key}")
                     # If no CSV, nothing to process further for this file

        # Save processed data (if any)
        if processed_data:
            saved_key = save_processed_data_to_s3(processed_data, bucket, target_time)
            if saved_key:
                # Delete the original raw zip file only after successful processing and saving
                delete_s3_object(bucket, key)
                return {'statusCode': 200, 'body': f'Successfully processed {key} to {saved_key}'}
            else:
                # Failed to save processed data, keep raw file for investigation
                print(f"Error: Failed to save processed data for {key}. Raw file kept.")
                return {'statusCode': 500, 'body': f'Failed to save processed data for {key}'}
        else:
            # No relevant data found after processing, still delete raw file
            print(f"No relevant data found in {key}. Deleting raw file.")
            delete_s3_object(bucket, key)
            return {'statusCode': 200, 'body': f'No relevant data in {key}, raw file deleted'}

    except Exception as e:
        print(f"An unexpected error occurred processing {key}: {str(e)}")
        # Keep the raw file in case of unexpected errors during processing
        return {'statusCode': 500, 'body': f'Error processing {key}: {str(e)}'}
