"""
Pulling data from Son Tung MTP channel and save information to json file
    1. Extract playlist id of the channel through the end point /channels
    2. Extract video id of the channel through the end point /playlistItems
    3. Extract video information through the end point /videos
    4. Get video id of top 10 videos with highest view count
    5. Extract comment information of top 10 videos through the end point /commentThreads
"""

import requests
import json
import os
from dotenv import load_dotenv
import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
load_dotenv()

handle = "@Sontungmtp"
api_key = os.getenv("api_key")
base_url = os.getenv("base_url")


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def get_playlist_id(handle:str, api_key:str, base_url:str) -> str:
    """
    Get playlist id of the channel through the end point /channels
    """
    video_count = None
    uploads_id = None
    params = {
        "part":"id,snippet,contentDetails,statistics",
        "forHandle":handle,
        "key":api_key
    }
    try:
        response = requests.get(f"{base_url}/channels",params = params, timeout = 30)
        response.raise_for_status()
        data = response.json()
        video_count = data["items"][0]["statistics"]["videoCount"]
        uploads_id = data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    except requests.exceptions.HTTPError as http_error:
        logger.error("HTTP error occured: %s", http_error)
        # 429 Too Many Requests: API đang giới hạn số lượt gọi trong một khoảng thời gian
        # (rate limit) — đây là lỗi rất thường gặp khi gọi API liên tục, không phải bug.
    except Exception as err:
        logger.error("Other error occured: %s", err)
    return video_count, uploads_id


def get_video_id(uploads_id:str, api_key:str, base_url:str, maxResults:int = 50) -> list:
    """get all information of video id through upload_id in the playlist items
       1. Call API with end point //playlistItems
       2. Do the loop to get next page token till the last page
       3. Access to video id, and store them in a list video id
    """
    video_id = []
    page_token = None

    while True:
        try:
            response2 = requests.get(f"{base_url}/playlistItems",params = {
                "part":"contentDetails",
                "playlistId": uploads_id,
                "key": api_key,
                "maxResults":maxResults,
                "pageToken": page_token
            }, timeout = 30)
            response2.raise_for_status()
            data2 = response2.json()
            video_id += [i["contentDetails"]["videoId"] for i in data2["items"]]
            logger.info("Got %d video_id", len(video_id))

            page_token = data2.get("nextPageToken")
            if not page_token:
                break

        except requests.exceptions.HTTPError as http_error:
            logger.error("HTTP error occured: %s", http_error)
            break
            # 429 Too Many Requests: API đang giới hạn số lượt gọi trong một khoảng thời gian
            # (rate limit) — đây là lỗi rất thường gặp khi gọi API liên tục, không phải bug.
        except Exception as err:
            logger.error("Other error occured: %s", err)
            break
    return video_id


def get_videos_raw(video_id:list, base_url: str, api_key:str) -> list[dict]:
    """
    Call the end point /videos in batch of 50 ids. Return the raw payload per batch.
    """

    video_raw = []
    for start in range(0, len(video_id), 50):
        batch = video_id[start:start+50]
        try:
            r = requests.get(f"{base_url}/videos", timeout=30, params={
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
                "key": api_key,
            })
            r.raise_for_status()
            data3 = r.json()
            data3["_extracted_at"] = datetime.now(timezone.utc).isoformat()
            video_raw.append(data3)
            logger.info("Got batch %d/%d videos",min(start + 50, len(video_id)), len(video_id))

        except requests.exceptions.HTTPError as http_error:
                logger.error("HTTP error occured: %s", http_error)
                # 429 Too Many Requests: API đang giới hạn số lượt gọi trong một khoảng thời gian
                # (rate limit) — đây là lỗi rất thường gặp khi gọi API liên tục, không phải bug.
        except Exception as err:
            logger.error("Other error occured: %s", err)

    expected_batch = math.ceil(len(video_id) / 50)    # làm tròn lên
    if len(video_raw) < expected_batch:
        logger.warning("Missing batches: got %d of %d", len(video_raw), expected_batch)
    return video_raw


def get_comment_raw(video_id: list, base_url:str, api_key: str, maxResults:int = 100) -> list[dict]:
    """
    Call the end point /commentThreads for each video, paginate up to max_pages.
    Return the raw payload per page.
    """
    comment_raw = []
    for vid in video_id:
        page_token2 = None
        page = 0
        while page < 20:
            try:
                r_comment = requests.get(f"{base_url}/commentThreads", timeout=30, params={
                    "part": "snippet,replies",
                    "videoId": vid,
                    "maxResults": 100,
                    "order": "time",
                    "textFormat": "plainText",
                    "pageToken":page_token2,
                    "key": api_key,
                })
                r_comment.raise_for_status()
                data_comment = r_comment.json()
                data_comment["_extracted_at"] = datetime.now(timezone.utc).isoformat()
                comment_raw.append(data_comment)
                page += 1
                page_token2 = data_comment.get("nextPageToken")
                
                if not page_token2:
                    break

            except requests.exceptions.HTTPError as http_error:
                logger.error("HTTP error occured: %s", http_error)
                break
                # 429 Too Many Requests: API đang giới hạn số lượt gọi trong một khoảng thời gian
                # (rate limit) — đây là lỗi rất thường gặp khi gọi API liên tục, không phải bug.
            except Exception as err:
                logger.error("Other error occured: %s", err)
                break
    return comment_raw

if __name__ == "__main__":

    setup_logging("INFO")

    logger.info("start pulling playlist...")
    view_count, uploads_id = get_playlist_id(handle,api_key,base_url)
    logger.info("view count = %s and upload id = %s", view_count, uploads_id)

    logger.info("start pulling list of video ids...")
    video_id = get_video_id(uploads_id,api_key,base_url,50)
    logger.info("got %d video_id", len(video_id))

    logger.info("start pulling detailed information of video ids...")
    video_raw = get_videos_raw(video_id, base_url, api_key)
    logger.info("got %d batches", len(video_raw))

    logger.info("start pulling comments for videos...")
    comment_raw = get_comment_raw(video_id, base_url, api_key,100)
    logger.info('got %d',len(comment_raw))
    
   
    
