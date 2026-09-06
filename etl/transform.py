"""
Transforming data pulled: 
    1. Transform the video raws to dataframe
    2. Transform comment raws to dataframe
"""

import json
import os
import logging
import pandas as pd

logger = logging.getLogger(__name__)

def build_video_table(video_raw: list[dict], artist_name:str) -> pd.DataFrame:
    """Build video table inlcude all requirement fields: 
          Identifier: artist_name, channel_id, channel_title, video_id
          Video details: video_title, description, published_at, duration, tags, category_id
          Statistics: view_count, like_count, comment_count
    """
    result_video = []
    for page in video_raw: 
        extracted_at = page.get("_extracted_at")
        for i in page.get("items",[]):
            dict_video_info = {}
            dict_video_info["artist_name"] = artist_name
            dict_video_info["channel_id"] = i["snippet"]["channelId"]
            dict_video_info["channel_title"] = i["snippet"]["channelTitle"]
            dict_video_info["video_id"] = i["id"]
            dict_video_info["video_title"] = i["snippet"]["title"]
            dict_video_info["description"] = i["snippet"]["description"]
            dict_video_info["published_at"] = i["snippet"]["publishedAt"]
            dict_video_info["duration"] = i["contentDetails"]["duration"]
            tags = i["snippet"].get("tags")
            dict_video_info["tags"] = "|".join(tags) if tags else None
            dict_video_info["category_id"] = i["snippet"]["categoryId"]
            stats = i.get("statistics",{})
            dict_video_info["view_count"] = stats.get("viewCount")
            dict_video_info["like_count"] = stats.get("likeCount")
            dict_video_info["comment_count"] = stats.get("commentCount")
            dict_video_info["_extracted_at"] = extracted_at
            result_video.append(dict_video_info) 
    logger.info("Number of video = %d", len(result_video))
    df_video = pd.DataFrame(result_video)
    return df_video


def top_n_video(df:pd.DataFrame, top_n: int) -> list:
    """Pick 10 videos with highest view_count and add them to the list
    """
    if df.empty:
         logger.warning("DataFrame is empty - no video to choose")
         return []
    
    df = df.copy()
    df["view_count"] = pd.to_numeric(df["view_count"], errors="coerce")
    top_videos = df.nlargest(top_n,"view_count")["video_id"].tolist()
    logger.info("choose %d videos with highest views", len(top_videos))
    return top_videos


def build_comment_table(comment_raw:list[dict], artist_name: str) -> pd.DataFrame:
    comment = []
    for page in comment_raw:
        extracted_at = page.get("_extracted_at")
        for i in page["items"]:
            dict_c_info = {}
            dict_c_info["artist_name"] = artist_name
            dict_c_info["channel_id"] = i["snippet"]["channelId"]
            dict_c_info["video_id"] = i["snippet"]["videoId"]
            dict_c_info["comment_id"] = i["snippet"]["topLevelComment"]["id"]
            dict_c_info["parent_id"] = None
            dict_c_info["author_name"] = i["snippet"]["topLevelComment"]["snippet"]["authorDisplayName"]
            dict_c_info["comment_text"] = i["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            dict_c_info["published_at"] = i["snippet"]["topLevelComment"]["snippet"]["publishedAt"]
            dict_c_info["updated_at"] = i["snippet"]["topLevelComment"]["snippet"]["updatedAt"]
            dict_c_info["like_count"] = i["snippet"]["topLevelComment"]["snippet"]["likeCount"]
            dict_c_info["reply_count"] = i["snippet"]["totalReplyCount"]
            dict_c_info["_extracted_at"] = extracted_at
            comment.append(dict_c_info)

            for r in i.get("replies",{}).get("comments",[]):
                dict_r_info = {}
                dict_r_info["artist_name"] = artist_name
                dict_r_info["channel_id"] = r["snippet"]["channelId"]
                dict_r_info["video_id"] = r["snippet"]["videoId"]
                dict_r_info["comment_id"] = r["id"]
                dict_r_info["parent_id"] = r["snippet"]["parentId"]
                dict_r_info["author_name"] = r["snippet"]["authorDisplayName"]
                dict_r_info["comment_text"] = r["snippet"]["textDisplay"]
                dict_r_info["published_at"] = r["snippet"]["publishedAt"]
                dict_r_info["updated_at"] = r["snippet"]["updatedAt"]
                dict_r_info["like_count"] = r["snippet"]["likeCount"]
                dict_r_info["reply_count"] = None
                dict_r_info["_extracted_at"] = extracted_at
                comment.append(dict_r_info)

    comment_columns = [
        "artist_name", "channel_id", "video_id", "comment_id", "parent_id",
        "author_name", "comment_text", "published_at", "updated_at",
        "like_count", "reply_count", "_extracted_at",
    ] #make sure data frame got columns even comment is turned off
    logger.info("Number of comments = %d", len(comment))
    df_comment = pd.DataFrame(comment, columns=comment_columns)
    return df_comment


def save_json (result, path: str) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("Saved %s", path)



def save_csv(df, path) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    logger.info("Saved %s: %d rows", path, len(df))


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    from extract import (setup_logging, get_playlist_id, get_video_id,
                             get_videos_raw, get_comment_raw)
    load_dotenv()
    setup_logging("INFO")
    handle = "@Sontungmtp"
    api_key = os.getenv("api_key")
    base_url = os.getenv("base_url")
    artist_name = "Son Tung M-TP"

    view_count, uploads_id = get_playlist_id(handle,api_key,base_url)
    video_id = get_video_id(uploads_id,api_key,base_url,50)
    video_raw = get_videos_raw(video_id, base_url, api_key)
    video_table = build_video_table(video_raw, artist_name)
    save_json(video_raw, "data/raw/video_raw.json")
    save_csv(video_table, "data/staged/video_table.csv")

    top_videos = top_n_video(video_table, 10)
    comment_raw = get_comment_raw(top_videos, base_url, api_key,100,1)
    comment_table = build_comment_table(comment_raw,artist_name)
    save_json(comment_raw, "data/raw/comment_raw.json")
    save_csv(comment_table, "data/staged/comment_table.csv")
    

