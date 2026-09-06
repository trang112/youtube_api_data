"""Run by order from extract -> transform -> load to bigquery
"""

import argparse
import logging
import os
import re
import json
import unicodedata 
import pandas as pd

from dotenv import load_dotenv

from etl.extract import setup_logging, get_playlist_id,get_video_id,get_videos_raw,get_comment_raw
from etl.transform import build_video_table,top_n_video, build_comment_table,save_json, save_csv
from etl.load import load


logger = logging.getLogger(__name__)
load_dotenv()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = "ETL pipeline for Youtube channel")
    parser.add_argument("--artist-file", default = "artists.json", help = "Channel handle and artist information")
    parser.add_argument("--top-n", type = int, default = 10, help = "Number of videos to get comment")
    parser.add_argument("--write-disposition", default = "WRITE_TRUNCATE", choices = ["WRITE_APPEND","WRITE_TRUNCATE"])
    parser.add_argument("--log-level", default = "INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--max-pages",   type=int, default=20)
    parser.add_argument("--skip-load",   action="store_true")
    return parser.parse_args()


def handle_slug(handle: str) -> str:
    """'@Son-Tung.MTP' -> 'son_tung_mtp'"""
    return re.sub(r"[^a-z0-9]+", "_", handle.strip("@").lower()).strip("_")


def run(handle: str, artist_name: str, top_n:int, write_disposition: str, skip_load: bool = False, max_pages: int = 20):
    """Run one function to access full pipeline
    """
    api_key = os.getenv("api_key")
    base_url = os.getenv("base_url")
    slug = handle_slug(handle)
    #extract information
    view_count, uploads_id = get_playlist_id(handle,api_key,base_url)
    video_id = get_video_id(uploads_id,api_key,base_url,50)
    video_raw = get_videos_raw(video_id, base_url, api_key)
    logger.info("channel %s: view count = %s and upload id = %s", slug, view_count, uploads_id)
    
    #transform video table
    video_table = build_video_table(video_raw, artist_name)
    save_json(video_raw, f"data/raw/video_raw_{slug}.json")
    save_csv(video_table, f"data/staged/video_table_{slug}.csv")

    #choose top 10 video with highest view_count
    top_videos = top_n_video(video_table,top_n)

    #extract comment information of top 10 video
    comment_raw = get_comment_raw(top_videos, base_url, api_key,100, max_pages)
    
    #transform comment table
    comment_table = build_comment_table(comment_raw,artist_name)
    save_json(comment_raw, f"data/raw/comment_raw_{slug}.json")
    save_csv(comment_table, f"data/staged/comment_table_{slug}.csv")

    #load table to bigquery
    #load table to bigquery
    if skip_load:
        logger.info("[%s] skip-load: %d videos, %d comments not loaded",
                    slug, len(video_table), len(comment_table))
    else:

        load(df = video_table,table_name = "youtube_video_table",write_disposition = write_disposition)
        load(df = comment_table, table_name= "youtube_comment_table", write_disposition = write_disposition)

if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)
    with open(args.artist_file, encoding="utf-8") as f:
        artists = json.load(f)
    for i, artist in enumerate(artists):
        # only the first artist may truncate; the rest must append
        disposition = args.write_disposition if i == 0 else "WRITE_APPEND"
        try: 
            run(handle = artist["handle"], 
                artist_name = artist["artist_name"], 
                top_n = args.top_n, 
                write_disposition = disposition, 
                skip_load = args.skip_load,
                max_pages = args.max_pages,)
        except Exception:
            logger.exception("[%s] FAILED, skipping", handle_slug(artist["handle"]))