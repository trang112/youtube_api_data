# YouTube Channel ETL Pipeline

An ETL pipeline that pulls video and comment data for a YouTube channel via the YouTube Data API v3, stores the raw payloads as JSON, flattens them into tables, and loads them into BigQuery.

## Data flow

```
YouTube Data API v3
      │
      ▼  extract.py    — call API, paginate, handle errors
  data/raw/*.json      — raw payload, verbatim
      │
      ▼  transform.py  — flatten, normalise data types
  data/staged/*.csv    — processed tables
      │
      ▼  load.py       — add source + ingested_at
  BigQuery
```

The raw payload is saved **before** any processing. If the transform logic turns out to be wrong, the JSON can be reloaded without calling the API again — this saves quota and avoids losing data that may no longer be available.

## The four API calls

| Step | Endpoint | Input | Output |
|---|---|---|---|
| 1 | `/channels` | handle | `uploads_id`, `video_count` |
| 2 | `/playlistItems` | `uploads_id` | list of `video_id` |
| 3 | `/videos` | `video_id` (batches of 50) | video details |
| 4 | `/commentThreads` | top N `video_id` | comments + replies |

Each step feeds the next. There is no endpoint that goes directly from a channel ID to comments.

## Project structure

```
Big Project 1/
├── main.py                 # CLI entry point, orchestrates the pipeline
├── run.sh                  # wrapper script for cron
├── requirements.txt
├── .env                    # credentials (not committed)
├── example.env             # template, no real values
├── .gitignore
├── etl/
│   ├── __init__.py
│   ├── extract.py          # API calls, 
│   ├── transform.py        # flatten JSON → 
│   └── load.py             # load DataFrame into BigQuery
├── data/
│   ├── raw/                # video_raw.json, 
│   └── staged/             # video_table.csv, 
└── logs/
    └── cron.log
```

## Setup

```bash
git clone https://github.com/trang112/youtube_api_data.git
cd youtube_api_data
 
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pandas-gbq
 
cp example.env .env        # then fill it in — see below
python main.py --top-n 3 --skip-load
```


Requires Python 3.10+ (uses `list[dict]` type hints).

### Configuration
 
`.env` is **different on the VM than on a local machine**. This is the one file that is not managed by git.
 
### Local
 
```
api_key=<YouTube Data API v3 key>
base_url=https://www.googleapis.com/youtube/v3
BQ_DATASET=jde_k1
GOOGLE_APPLICATION_CREDENTIALS=/home/trang/keys/service-account.json
```
 
### On the VM — three lines only
 
```
api_key=<YouTube Data API v3 key>
base_url=https://www.googleapis.com/youtube/v3
BQ_DATASET=jde_k1
```
 
`GOOGLE_APPLICATION_CREDENTIALS` **must be omitted on the VM.**


**Getting an API key:** Google Cloud Console → APIs & Services → enable *YouTube Data API v3* → Credentials → Create API key.

**Service account:** keep the JSON file **outside** the project directory and restrict it with `chmod 600`. Two IAM roles are required:

| Role | Grants |
|---|---|
| `roles/bigquery.jobUser` | run load jobs |
| `roles/bigquery.dataEditor` | create tables, write data |

The dataset must exist before loading. The load job creates tables automatically but not datasets:

```bash
bq mk --location=asia-southeast1 jde_k1
```

## Running

```bash
python main.py
python main.py --handle "@denvau" --artist-name "Đen Vâu"
python main.py --top-n 3 --max-pages 2
python main.py --help
```

### Parameters

| Parameter | Default | Description |
|---|---|---|
| `--handle` | `@Sontungmtp` | Channel handle |
| `--artist-name` | `Son Tung M-TP` | Business label, not taken from the API |
| `--top-n` | `10` | Number of videos to pull comments for (highest view count) |
| `--max-pages` | `20` | Max comment pages per video (100 comments per page) |
| `--write-disposition` | `WRITE_TRUNCATE` | `WRITE_APPEND` to append / `WRITE_TRUNCATE` to replace (Applies to the first artist only- the following artists use write append)|
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

For a first run, use `--top-n 3 --max-pages 2` to exercise the whole pipeline for roughly 10 quota units.

## Quota

The default limit is **10,000 units per day**, resetting at midnight Pacific time (around 14:00–15:00 Vietnam time).


| Step | Calls |
|---|---|
| `/channels` | 1 |
| `/playlistItems` | 5 (50 ids per page) |
| `/videos` | 5 (50 ids per batch) |
| `/commentThreads` | up to 200 (10 videos × 20 pages) |
| **Total** | **~210** |
 
**Ten artists is roughly 2,100 units, so about 4 full runs per day.**

## Output tables

### `youtube_video_table`

| Group | Columns |
|---|---|
| Identifiers | `artist_name`, `channel_id`, `channel_title`, `video_id` |
| Content | `video_title`, `description`, `published_at`, `duration`, `tags`, `category_id` |
| Statistics | `view_count`, `like_count`, `comment_count` |
| Pipeline | `extracted_at`, `source`, `ingested_at` |

### `youtube_comment_table`

| Group | Columns |
|---|---|
| Identifiers | `artist_name`, `channel_id`, `video_id`, `comment_id`, `parent_id` |
| Content | `author_name`, `comment_text`, `published_at`, `updated_at` |
| Engagement | `like_count`, `reply_count` |
| Pipeline | `extracted_at`, `source`, `ingested_at` |

Top-level comments and replies live in the **same table**, distinguished by `parent_id`:

| Type | `parent_id` | `reply_count` |
|---|---|---|
| Top-level comment | `NULL` | actual reply count |
| Reply | parent's `comment_id` | `NULL` |

## Data notes

**`artist_name` is a label we set ourselves**, not an API field. `channel_title` can be changed by the channel owner at any time, so it is not safe to use as a grouping key.

**`tags` are joined with `|`**, not `,`, because YouTube tags can contain commas. 

**`NULL` is not `0`.** When a channel owner hides likes, the `likeCount` field is **absent** from the response — the pipeline writes `NULL`, not `0`. Same for `reply_count` on replies, which is `NULL` because a reply cannot have child replies.

**The `uploads` playlist only contains public and unlisted videos.** If the number of videos retrieved is lower than the channel's `video_count`, the difference is private videos — not a pipeline bug.

**`replies` returns at most 5 replies per comment.** Getting all of them requires the `/comments` endpoint with `parentId`, one request per top-level comment, which is not viable within the quota. This is a known limitation, not a bug.

**`Comment counts`** are incomplete for some videos. For a heavily-commented video, pagination can stop before the end when the API rejects a page token with 400 invalidPageToken, or when the max_pages cap is reached

## Logging
 
Logs go to the terminal, and under `run.sh` to `logs/cron.log`:

```
17:50:53 [INFO] Number of video = 222
17:50:53 [INFO] Saved data/raw/video_raw.json
17:53:10 [INFO] Saved data/staged/comment_table.csv: 27661 rows
17:53:19 [INFO] [load] Loaded 27661 rows into ...youtube_comment_table (WRITE_TRUNCATE)

```


## Scheduling with cron

```bash
chmod +x run.sh
./run.sh                              # always #test manually first
tail -50 logs/cron.log

#Schedule for 07:00 and 23:00 daily:
crontab -e

0 7,23 * * * "/home/trang/Documents/jde/Big Project 1/run.sh"
```


**Limitation:** cron runs on the local machine. If the machine is off or suspended at 07:00, that run is simply skipped — cron does not catch up. For catch-up behaviour, move the job to Cloud Run Jobs with Cloud Scheduler.
## Deployment on Google Cloud

1. Connect to the VM from a terminal
2. Clone the repo onto the VM
3. Put .env on the VM
4. Grant the VM's service account access to datasets
5. Reserve a static external IP (optional)
6. Schedule with cron

Install it:
 
```bash
chmod +x run.sh
export EDITOR=nano
crontab -e
#add in the end
0 7,23 * * * /home/trangbui112huyen/youtube_api_data/run.sh
```

## To do

- [ ] Add a quota counter in `get_comment_raw` so the script stops before hitting the daily limit
- [ ] Declare the BigQuery schema explicitly instead of relying on pandas type inference
- [ ] Continue to transform data in Bigquery to create ready data for Data Analyst 
- [ ] Connect with PBI to analyze data crawl