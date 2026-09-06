# YouTube Channel ETL Pipeline

An ETL pipeline that pulls video and comment data for a list of YouTube channels via the YouTube Data API v3, stores the raw payloads as JSON, flattens them into tables, and loads them into BigQuery.

Channels are defined in `artists.json` and processed one after another in a single run.

## Data flow

```
YouTube Data API v3
      │
      ▼  extract.py    — call API, paginate, handle errors
  data/raw/*.json      — raw payload, verbatim, one file per artist
      │
      ▼  transform.py  — flatten, normalise data types
  data/staged/*.csv    — processed tables, one file per artist
      │
      ▼  load.py       — add source + ingested_at
  BigQuery             — all artists in one table
```

The raw payload is saved **before** any processing. If the transform logic turns out to be wrong, the JSON can be reloaded without calling the API again — this saves quota and avoids losing data that may no longer be available.

## The four API calls

Run once per artist:

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
├── main.py                 # CLI entry point, loops over artists
├── artists.json            # input: which channels to pull
├── run.sh                  # wrapper script for cron
├── test.ipynb              # scratch notebook for 1 artist
├── requirements.txt
├── .env                    # credentials (not committed)
├── example.env             # template, no real values
├── .gitignore
├── etl/
│   ├── __init__.py
│   ├── extract.py          # API calls, pagination, error handling
│   ├── transform.py        # flatten JSON → DataFrame, save raw/staged
│   └── load.py             # load DataFrame into BigQuery
├── data/
│   ├── raw/                # video_raw_<slug>.json, comment_raw_<slug>.json
│   └── staged/             # video_table_<slug>.csv, comment_table_<slug>.csv
└── logs/
    └── cron.log
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.10+ (uses `list[dict]` and `str | None` type hints).

## Configuration

Create `.env` in the project root:

```
api_key=<YouTube Data API v3 key>
base_url=https://www.googleapis.com/youtube/v3
BQ_DATASET=jde_k1
GOOGLE_APPLICATION_CREDENTIALS=/home/trang/keys/service-account.json
```

**Getting an API key:** Google Cloud Console → APIs & Services → enable *YouTube Data API v3* → Credentials → Create API key.

**Service account:** keep the JSON file **outside** the project directory. Two IAM roles are required:

| Role | Grants |
|---|---|
| `roles/bigquery.jobUser` | run load jobs |
| `roles/bigquery.dataEditor` | create tables, write data |

The dataset must exist before loading. The load job creates tables automatically but not datasets:

```bash
bq mk --location=asia-southeast1 jde_k1
```

## Defining the artists

`artists.json` is a JSON **list** of objects (hand filling). Both fields are required:

```json
[
  {"handle": "@sontungmtp", "artist_name": "Sơn Tùng M-TP"},
  {"handle": "@denvauofficial", "artist_name": "Đen Vâu"}
]
```

| Field | Meaning |
|---|---|
| `handle` | The channel handle from the URL — `youtube.com/@sontungmtp` → `@sontungmtp`. Passed straight to `/channels?forHandle=`. Case-insensitive. |
| `artist_name` | A label we choose, written into every row. Not an API field. |

`handle` also determines the output filenames. `handle_slug()` strips the `@`, lowercases, and replaces anything outside `[a-z0-9]` with `_`:

```
@Son-Tung.MTP  →  son_tung_mtp  →  data/staged/video_table_son_tung_mtp.csv
```


**Verify handles before the first run.** A handle that does not exist returns an HTTP error and the artist is skipped, but a handle that resolves to the *wrong* channel fails silently — the pipeline will happily ingest someone else's videos under your `artist_name`. Open `youtube.com/<handle>` in a browser for each entry.

## Running

```bash
python main.py                          # all artists in artists.json
python main.py --skip-load              # extract + transform only, no BigQuery write
python main.py --top-n 3                # 3 videos per artist instead of 10
python main.py --artist-file test.json  # a different artist list
python main.py --help
```

### Parameters

| Parameter | Default | Description |
|---|---|---|
| `--artist-file` | `artists.json` | Path to the JSON list of channels |
| `--top-n` | `10` | Videos per artist to pull comments for (highest view count) |
| `--write-disposition` | `WRITE_TRUNCATE` | Applies to the **first** artist only — see below |
| `--skip-load` | off | Run extract + transform, write CSV, skip BigQuery |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--max-pages` | `20` | **Not wired up** — see Known gaps |

For a first run, use `--top-n 3 --skip-load` to exercise the whole pipeline cheaply without touching BigQuery.

### Write disposition across multiple artists

`WRITE_TRUNCATE` replaces the whole table. Applying it to every artist in the loop would mean each artist wipes the previous one, leaving only the last artist's data. `main.py` therefore applies the flag to the first artist only:

```python
disposition = args.write_disposition if i == 0 else "WRITE_APPEND"
```

| Run | Artist 1 | Artists 2–10 | Result |
|---|---|---|---|
| `--write-disposition WRITE_TRUNCATE` (default) | truncate + write | append | table holds exactly this run |
| `--write-disposition WRITE_APPEND` | append | append | this run is added to what was already there |

**Consequence of loading inside the loop:** if artist 5 fails, artists 1–4 are already in BigQuery. The run leaves a partial table rather than rolling back. Acceptable here because the next full run truncates anyway.

### Failure handling

Each artist is wrapped in `try/except`. A failure logs the traceback and moves on, so one dead channel does not lose the other nine:

```
[ericnamofficial] FAILED, skipping
Traceback (most recent call last):
  ...
```

Note that `extract.py` also swallows HTTP errors internally and returns empty results, so some failures surface as an artist with 0 videos rather than as an exception. Check the row counts in the log, not just the absence of tracebacks.

## Quota

The default limit is **10,000 units per day**, resetting at midnight Pacific time (around 14:00–15:00 Vietnam time).

| Endpoint | Cost |
|---|---|
| `channels`, `playlistItems`, `videos`, `commentThreads` | 1 |
| `search` | **100** — not used in this pipeline |

This pipeline deliberately avoids `search.list`. Listing a channel's videos goes through the `uploads` playlist (1 unit) instead of `search` (100 units).

Rough cost for one artist with ~220 videos, `--top-n 10`:

| Step | Calls |
|---|---|
| `/channels` | 1 |
| `/playlistItems` | 5 (50 ids per page) |
| `/videos` | 5 (50 ids per batch) |
| `/commentThreads` | up to 200 (10 videos × 20 pages) |
| **Total** | **~210** |

**Ten artists is roughly 2,100 units, so about 4 full runs per day.** Comments dominate the cost: they are ~95% of the total. Lowering `--top-n` is the cheapest lever.

## Output tables

Both tables hold **all artists together**, separated by `artist_name`.

### `youtube_video_table`

| Group | Columns |
|---|---|
| Identifiers | `artist_name`, `channel_id`, `channel_title`, `video_id` |
| Content | `video_title`, `description`, `published_at`, `duration`, `tags`, `category_id` |
| Statistics | `view_count`, `like_count`, `comment_count` |
| Pipeline | `_extracted_at`, `source`, `ingested_at` |

### `youtube_comment_table`

| Group | Columns |
|---|---|
| Identifiers | `artist_name`, `channel_id`, `video_id`, `comment_id`, `parent_id` |
| Content | `author_name`, `comment_text`, `published_at`, `updated_at` |
| Engagement | `like_count`, `reply_count` |
| Pipeline | `_extracted_at`, `source`, `ingested_at` |

Top-level comments and replies live in the **same table**, distinguished by `parent_id`:

| Type | `parent_id` | `reply_count` |
|---|---|---|
| Top-level comment | `NULL` | actual reply count |
| Reply | parent's `comment_id` | `NULL` |

## Data notes

**`artist_name` is a label we set ourselves**, not an API field. `channel_title` can be changed by the channel owner at any time, so it is not safe to use as a grouping key. Group by `artist_name` or `channel_id`.

**`_extracted_at` keeps its leading underscore.** It is injected into the raw payload in `extract.py` and carried through, so the BigQuery column is `_extracted_at`, not `extracted_at`.

**`tags` are joined with `|`**, not `,`, because YouTube tags can contain commas. To split them back out in BigQuery:

```sql
SELECT tag, COUNT(*) AS n
FROM youtube_video_table, UNNEST(SPLIT(tags, '|')) AS tag
GROUP BY tag ORDER BY n DESC
```

**`NULL` is not `0`.** When a channel owner hides likes, the `likeCount` field is **absent** from the response — the pipeline writes `NULL`, not `0`. Same for `reply_count` on replies, which is `NULL` because a reply cannot have child replies.

**The `uploads` playlist only contains public and unlisted videos.** If the number of videos retrieved is lower than the channel's `video_count`, the difference is private videos — not a pipeline bug.

**`replies` returns at most 5 replies per comment.** Getting all of them requires the `/comments` endpoint with `parentId`, one request per top-level comment, which is not viable within the quota. This is a known limitation, not a bug.

**Channels with comments disabled return an empty comment table, not an error.** `build_comment_table` declares its columns explicitly so the DataFrame keeps its schema at 0 rows and the BigQuery load still succeeds.

## Logging

Logs are written to both the terminal and, under cron, to `logs/cron.log`:

```
17:50:53 [INFO] channel sontungmtp: view count = 222 and upload id = UU...
17:50:53 [INFO] Number of video = 222
17:50:53 [INFO] Saved data/raw/video_raw_sontungmtp.json
17:53:10 [INFO] Saved data/staged/comment_table_sontungmtp.csv: 27661 rows
17:53:19 [INFO] [load] ingested 27661 rows to ...youtube_comment_table (WRITE_TRUNCATE)
```

Each artist's lines are prefixed with its slug, so `grep` isolates one channel out of a ten-artist run:

```bash
grep sontungmtp logs/cron.log
```

## Scheduling with cron

```bash
chmod +x run.sh
./run.sh                              # always test manually first
tail -50 logs/cron.log
```

The path inside `run.sh` is absolute and must match the real directory. Schedule for 07:00 and 23:00 daily:

```bash
crontab -e
```

```
0 7,23 * * * "/home/trang/Documents/jde/Big Project 1 (Copy)/run.sh"
```

Two runs a day at ~2,100 units each stays within the 10,000 unit quota.

**Limitation:** cron runs on the local machine. If the machine is off or suspended at 07:00, that run is simply skipped — cron does not catch up. For catch-up behaviour, use a `systemd` timer with `Persistent=true`, or move the job to Cloud Run Jobs with Cloud Scheduler.

## Verifying a load

```python
from google.cloud import bigquery
client = bigquery.Client()

# Did every artist make it in?
sql = f"""
SELECT artist_name, COUNT(*) AS n_videos, MAX(ingested_at) AS last_load
FROM `{client.project}.jde_k1.youtube_video_table`
GROUP BY artist_name ORDER BY n_videos DESC
"""
for row in client.query(sql).result():
    print(dict(row))

# Are the column types right? view_count should be INT64
table = client.get_table(f"{client.project}.jde_k1.youtube_video_table")
for f in table.schema:
    print(f.name, f.field_type)
```

A missing `artist_name` means that artist failed or its handle resolved to nothing — check the log for its slug.
