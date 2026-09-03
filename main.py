"""Run by order from extract -> transform -> load to bigquery
"""

import argparse
import logging
import os
from dotenv import load_dotenv

from etl.extract import setup_logging, get_playlist_id,get_video_id,get_videos_raw,get_comment_raw
from etl.transform import build_video_table,top_n_video, build_comment_table,save_json, save_csv
from etl.load import load


logger = logging.getLogger(__name__)
load_dotenv()

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description = "ETL pipeline for Youtube channel")
    parser.add_argument("--handle", default = "@Sontungmtp", help = "Channel handle")
    parser.add_argument("--artist-name", default = "Son Tung M-TP", help = "Artist name")
    parser.add_argument("--top-n", type = int, default = 10, help = "Number of videos to get comment")
    parser.add_argument("--write-disposition", default = "WRITE_TRUNCATE", choices = ["WRITE_APPEND","WRITE_TRUNCATE"])
    parser.add_argument("--log-level", default = "INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def run(handle: str, artist_name: str, top_n:int, write_disposition: str):
    """Run one function to access full pipeline
    """
    api_key = os.getenv("api_key")
    base_url = os.getenv("base_url")
    #extract information
    view_count, uploads_id = get_playlist_id(handle,api_key,base_url)
    video_id = get_video_id(uploads_id,api_key,base_url,50)
    video_raw = get_videos_raw(video_id, base_url, api_key)

    #transform video table
    video_table = build_video_table(video_raw, artist_name)
    save_json(video_raw, "data/raw/video_raw.json")
    save_csv(video_table, "data/staged/video_table.csv")

    #choose top 10 video with highest view_count
    top_10 = top_n_video(video_table,top_n)

    #extract comment information of top 10 video
    comment_raw = get_comment_raw(top_10, base_url, api_key,100)
    
    #transform comment table
    comment_table = build_comment_table(comment_raw,artist_name)
    save_json(comment_raw, "data/raw/comment_raw.json")
    save_csv(comment_table, "data/staged/comment_table.csv")

    #load table to bigquery
    load(df = video_table,table_name = "youtube_video_table",write_disposition = write_disposition)
    load(df = comment_table, table_name= "youtube_comment_table", write_disposition = write_disposition)

if __name__ == "__main__":
    args = parse_args()
    setup_logging(args.log_level)
    run(args.handle, args.artist_name, args.top_n, args.write_disposition)
