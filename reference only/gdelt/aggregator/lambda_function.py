import json
import boto3
import gzip
import io
from collections import defaultdict
import re

s3 = boto3.client('s3')

def map_theme_to_category(theme):
    theme_upper = theme.upper()
    
    # Health
    if any(keyword in theme_upper for keyword in ['HEALTH', 'MEDICAL', 'TAX_DISEASE', 'WB_621_HEALTH']):
        return 'HEALTH'
    # Economy
    elif any(keyword in theme_upper for keyword in ['EPU_', 'ECON_', 'WB_2670_JOBS', 'WB_2689_JOBS']):
        return 'ECONOMY'
    # Politics
    elif any(keyword in theme_upper for keyword in ['USPEC_POLITICS', 'ELECTION', 'GOVERNMENT', 'TAX_FNCACT_PRESIDENT', 'EPU_POLICY_POLITICAL']):
        return 'POLITICS'
    # Security
    elif any(keyword in theme_upper for keyword in ['CRISISLEX_C07_SAFETY', 'CRISISLEX_CRISISLEXREC', 'TERRORISM', 'CRIME', 'EPU_CATS_NATIONAL_SECURITY']):
        return 'SECURITY'
    # Environment
    elif any(keyword in theme_upper for keyword in ['ENV_', 'UNGP_FORESTS_RIVERS_OCEANS']):
        return 'ENVIRONMENT'
    # Education
    elif any(keyword in theme_upper for keyword in ['EDUCATION', 'SOC_POINTSOFINTEREST_SCHOOL', 'TAX_FNCACT_STUDENT', 'SOC_POINTSOFINTEREST_UNIVERSITY']):
        return 'EDUCATION'
    # Social
    elif any(keyword in theme_upper for keyword in ['SOC_', 'TAX_ETHNICITY', 'SOC_SUICIDE', 'CRISISLEX_T11_UPDATESSYMPATHY']):
        return 'SOCIAL'
    # Technology
    elif any(keyword in theme_upper for keyword in ['TECH_', 'WB_1331_HEALTH_TECHNOLOGIES', 'WB_1350_PHARMACEUTICALS']):
        return 'TECHNOLOGY'
    else:
        return 'OTHER'

def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    processed_key = None # Keep track of the key for deletion

    try:
        # Get the bucket and object key from the event
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
        processed_key = key # Store key for potential deletion later

        # Ensure the file is in the processed prefix
        if not key.startswith('gdelt/processed/'):
             print(f"Ignoring file outside 'gdelt/processed/': {key}")
             return {'statusCode': 200, 'body': 'File ignored (not in processed prefix)'}

        print(f"Processing file s3://{bucket}/{key}")

        # Download the object
        response = s3.get_object(Bucket=bucket, Key=key)
        print(f"Downloaded object: {key}")

        gzipped_content = response['Body'].read()
        print("Read gzipped content")

        # Decompress the content
        with gzip.GzipFile(fileobj=io.BytesIO(gzipped_content)) as gzipfile:
            content = gzipfile.read()
            print("Decompressed content")
            data = json.loads(content)
            print(f"Loaded JSON data with {len(data)} records")

    except Exception as e:
        print(f"Error during download/decompression of {key}: {str(e)}")
        # Cannot proceed if download/decompression fails
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error downloading/decompressing file: {str(e)}')
        }

        # Initialize structures for aggregation
        aggregated_data = defaultdict(lambda: defaultdict(list))

        required_keys = ['Date', 'V2Themes', 'V2Tone']

        # Process each record
        for idx, record in enumerate(data):
            try:
                missing_keys = [k for k in required_keys if k not in record]
                if missing_keys:
                    print(f"Record {idx} is missing keys: {missing_keys}")
                    continue  # Skip this record

                if idx < 5:  # Limit logging to first 5 records
                    print(f"Processing record {idx}: {record}")

                timestamp_str = record.get('Date')
                themes_str = record.get('V2Themes', '')
                tone_str = record.get('V2Tone', '')

                # Parse and clean timestamp
                if not timestamp_str:
                    continue
                timestamp = str(timestamp_str)

                # Parse themes
                themes = themes_str.strip(';').split(';')
                themes = [theme.strip() for theme in themes if theme.strip()]

                if not themes:
                    continue  # Skip records with no themes

                # Map themes to categories
                theme_categories = [map_theme_to_category(theme) for theme in themes]

                # Parse tone
                tone_values = tone_str.split(',')
                if tone_values and tone_values[0]:
                    try:
                        tone = float(tone_values[0])
                    except ValueError:
                        tone = 0.0
                else:
                    tone = 0.0

                # Aggregate data per category
                for category in theme_categories:
                    aggregated_data[timestamp][category].append(tone)

            except Exception as e:
                print(f"Error processing record {idx}: {e}")
                continue  # Skip to the next record

        print(f"Aggregated data contains {len(aggregated_data)} timestamps")

        # Prepare the output data
        processed_records = []
        for timestamp, categories in aggregated_data.items():
            category_tones = {}
            for category, tones in categories.items():
                avg_tone = sum(tones) / len(tones) if tones else 0.0
                category_tones[category] = avg_tone
            processed_record = {
                'timestamp': timestamp,
                'themes': category_tones
            }
            processed_records.append(processed_record)

        print(f"Prepared {len(processed_records)} processed records")
        if processed_records:
            print(f"First processed record: {processed_records[0]}")

        # Convert processed records to JSON
        output_content = json.dumps(processed_records)
        print("Prepared output content")

        # Determine output key - change from processed to processed_reduced
        # Construct output key, replacing directory and removing .gz extension
        output_key = key.replace('gdelt/processed/', 'gdelt/processed_reduced/').replace('.gz', '')

        # Write aggregated data to S3
        try:
            s3.put_object(Bucket=bucket, Key=output_key, Body=output_content, ContentType='application/json')
            print(f"Successfully saved aggregated data to {output_key}")

            # Delete the original processed file after successful aggregation
            try:
                s3.delete_object(Bucket=bucket, Key=processed_key)
                print(f"Successfully deleted original processed file: {processed_key}")
            except Exception as del_e:
                print(f"Error deleting original processed file {processed_key}: {str(del_e)}")
                # Log error but don't fail the whole process just for deletion failure

            return {
                'statusCode': 200,
                'body': json.dumps(f'Processed {processed_key} and saved to {output_key}. Original deleted.')
            }
        except Exception as put_e:
            print(f"Error saving aggregated data to {output_key}: {str(put_e)}")
            # Keep the processed file if saving the aggregated one fails
            return {
                'statusCode': 500,
                'body': json.dumps(f'Error saving aggregated data: {str(put_e)}')
            }

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error processing file: {str(e)}')
        }
