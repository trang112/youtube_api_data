"""LOADING STEPS — Ingested dataframe to Bigquery.
"""
import os

import pandas as pd
import logging
from dotenv import load_dotenv
from google.cloud import bigquery


logger = logging.getLogger(__name__)
load_dotenv()


def load(df, table_name: str, write_disposition: str, source: str = "youtube_api_v3"):
  """Ingest DataFrame to BigQuery table.

  write_disposition:
    - WRITE_APPEND   : default - append data 
    - WRITE_TRUNCATE : delete and full load
  """

  df = df.copy()
  df["source"] = source
  df["ingested_at"] = pd.Timestamp.now(tz="UTC")

  client = bigquery.Client()

  dataset = os.getenv("BQ_DATASET")
  if not dataset:
      raise RuntimeError("BQ_DATASET is missing in .env")
  table_id = f"{client.project}.{dataset}.{table_name}"  
  job_config = bigquery.LoadJobConfig(write_disposition=write_disposition)
  job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
  job.result()  # chặn tới khi job nạp xong
  logger.info("[load] ingested %d rows to %s (%s)",len(df),table_id,write_disposition)



