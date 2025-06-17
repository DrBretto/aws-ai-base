import os
import json
import boto3
import requests
import pandas as pd
import zipfile
import io
from datetime import datetime, timedelta
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME")
GDELT_PREFIX = "GDELT"

s3_client = boto3.client("s3")

def get_gdelt_url(dt):
    # GDELT GKG files: http://data.gdeltproject.org/gdeltv2/YYYYMMDDHHMMSS.gkg.csv.zip (seconds always 00)
    return f"http://data.gdeltproject.org/gdeltv2/{dt.strftime('%Y%m%d%H%M')}00.gkg.csv.zip"

def find_available_gdelt_file(target_dt, max_rollback=8):
    # Try the target 15-min mark, then roll back by 15-min intervals up to max_rollback
    for rollback in range(max_rollback):
        dt = target_dt - timedelta(minutes=15 * rollback)
        url = get_gdelt_url(dt)
        logger.info(f"Trying GDELT GKG file for interval: {dt.strftime('%Y-%m-%d %H:%M')} ({url})")
        try:
            r = requests.get(url, stream=True, timeout=10)
            if r.status_code == 200:
                r.close()
                return url, dt
            r.close()
        except Exception as e:
            logger.warning(f"GET request failed for {url}: {e}")
    return None, None

def extract_relevant_data(df):
    keywords = ["gold", "etf", "fund", "finance", "commodity", "precious metal"]
    mask = df.apply(lambda row: any(kw in str(row).lower() for kw in keywords), axis=1)
    filtered = df[mask]
    keep_cols = [
        "GKGRecordID", "Date", "SourceCommonName", "DocumentIdentifier", "V2Themes",
        "V2Locations", "V2Tone", "AllNames"
    ]
    filtered = filtered[keep_cols].fillna("")
    return filtered.to_dict(orient="records")

def save_to_s3(data, s3_dt):
    if not data:
        logger.info("No relevant data to save for this interval.")
        return
    day_str = s3_dt.strftime("%Y/%m/%d")
    time_str = s3_dt.strftime("%H%M")
    s3_key = f"{GDELT_PREFIX}/{day_str}/{time_str}.json"
    tmp_path = f"/tmp/gdelt_{s3_dt.strftime('%Y%m%d%H%M')}.json"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    s3_client.upload_file(tmp_path, S3_BUCKET_NAME, s3_key)
    os.remove(tmp_path)
    logger.info(f"Saved {len(data)} records to s3://{S3_BUCKET_NAME}/{s3_key}")

def lambda_handler(event, context):
    now = datetime.utcnow()
    # Always target 15 minutes ago, aligned to the previous 15-min mark
    target_time = now - timedelta(minutes=15)
    target_time = target_time.replace(minute=(target_time.minute // 15) * 15, second=0, microsecond=0)
    logger.info(f"UTC now: {now.isoformat()}, using previous 15-min mark as target: {target_time.isoformat()}")
    if "year" in event and "month" in event and "day" in event and "hour" in event and "minute" in event:
        target_time = datetime(
            int(event["year"]), int(event["month"]), int(event["day"]),
            int(event["hour"]), int(event["minute"])
        )
        logger.info(f"Override: using provided datetime {target_time.isoformat()}")
    url, file_dt = find_available_gdelt_file(target_time)
    if not url:
        logger.error("No GDELT GKG file found for target or previous intervals.")
        return {"statusCode": 404, "body": "No GDELT file found."}
    logger.info(f"Downloading GDELT GKG file: {url}")
    r = requests.get(url, timeout=30)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        csv_name = z.namelist()[0]
        with z.open(csv_name) as f:
            # GDELT GKG files are tab-delimited, no header
            df = pd.read_csv(f, sep="\t", header=None, low_memory=False)
            # Assign columns for GKG v2 (partial, for relevant fields)
            df.columns = [
                "GKGRecordID", "Date", "SourceCollectionIdentifier", "SourceCommonName", "DocumentIdentifier",
                "V1Counts", "V2Counts", "V2Themes", "V2EnhancedThemes", "V2Locations", "V2EnhancedLocations",
                "V2Persons", "V2Organizations", "V2Tone", "Dates", "GCAM", "SharingImage", "RelatedImages",
                "SocialImageEmbeds", "SocialVideoEmbeds", "Quotations", "AllNames", "Amounts", "TranslationInfo", "ExtrasXML"
            ][:df.shape[1]]
    relevant_data = extract_relevant_data(df)
    save_to_s3(relevant_data, target_time)
    return {"statusCode": 200, "body": f"Processed {len(relevant_data)} records for {target_time} (file may have been pulled from a previous interval)."}