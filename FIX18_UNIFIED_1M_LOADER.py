# ============================================================
# FIX18 UNIFIED 1-MIN LOADER
#
# VERIFIED:
#   FIX18 STEP 7
#   UNIFIED LOADER SMOKE TEST = PASS
#
# Data chain:
#
# A) Historical raw 1m
#    2024-08-01 ～ 2026-07-31
#    Google Drive
#    equities_bars_minute_YYYYMM.csv.gz
#
# B) Old Paper Trader snapshots
#    GCS
#    stock-auto-trader-506100-paper
#    fix11_forward/snapshots/YYYY-MM-DD.parquet
#
# C) New FIX17 saved 1m
#    GCS
#    stock-auto-trader-506100-fix17-1m-data
#    fix17/minute_1m/date=YYYY-MM-DD/
#
# Unified output:
#    Datetime
#    Code
#    Open
#    High
#    Low
#    Close
#    Volume
#
# Rules:
#   ・previous trading day cutoff
#   ・No-Future
#   ・missing trading day = error in strict mode
#   ・Code normalization
#   ・Code + Datetime duplicate prohibited
#   ・core NULL prohibited
#   ・load only required months / days
#
# FIX17 trading conditions are NOT modified here.
# ============================================================

import os
import re
import gc
from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import google.auth
import jpholiday

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.cloud import storage


# ============================================================
# CONFIG
# ============================================================

PROJECT_ID = "stock-auto-trader-506100"

JST = ZoneInfo("Asia/Tokyo")

CACHE_DIR = Path(
    "/content/fix18_cache"
)

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# HISTORICAL BOUNDARY
# ============================================================

HIST_FIRST_DATE = date(
    2024, 8, 1
)

HIST_LAST_DATE = date(
    2026, 7, 31
)


# ============================================================
# OLD SNAPSHOTS
# ============================================================

OLD_BUCKET = (
    "stock-auto-trader-506100-paper"
)

OLD_PREFIX = (
    "fix11_forward/snapshots/"
)


# ============================================================
# NEW FIX17 1-MIN
# ============================================================

NEW_BUCKET = (
    "stock-auto-trader-506100-fix17-1m-data"
)

NEW_PREFIX = (
    "fix17/minute_1m/"
)


# ============================================================
# EXACT HISTORICAL DRIVE IDS
# ============================================================

HISTORICAL_FILES = {

    "202408":
        "1PbhxyE9UBBaK0S34hbGttcoTDZhfTqcb",

    "202409":
        "1JHaGtSLj61UY7mE4lSpkPN2J_oiBaa24",

    "202410":
        "1vz3t9cytlBtfSZN4Y5ndamXfJizZQL_A",

    "202411":
        "1HWenacd_SZjVpOwWdzy5L5EwDAl_wWHk",

    "202412":
        "1IWYJHHDSeS4-yvNDZOgJ4hM3rIF-NoXf",

    "202501":
        "1JxkzKLDNdEwEonAvupooZbT04Je_9pVD",

    "202502":
        "1RjO23STmPp3jdLtFE8f7zKJVZqPQ3uvT",

    "202503":
        "1Bfm__p_6OTK6MqOTe0r8k9rM0hcw2JR6",

    "202504":
        "1uao86TKKBjJkZOWZ9XD3Dt4wQBSjq04l",

    "202505":
        "1KRO5V9MmPwtdzamcl09gl3UkwkG40nPV",

    "202506":
        "1eAkb9xfKYHfTXhGw0J0RZF_n0ukn1Q3V",

    "202507":
        "15m4BRUBix9FNSzWD-wahQFDNSM-pdjf0",

    "202508":
        "1MpXhBGxxv9HrCSpipwcwKYc09h-T0yjv",

    "202509":
        "1begE5r2G4nKNwGSP25sULwHIZC2y_66x",

    "202510":
        "15JMHs3nk5PNlaTvgHepQogSVC8JMisX-",

    "202511":
        "1rm5IR9B3CWDNmL-ISKZZ8jHRLXr53y39",

    "202512":
        "1KaeIjjivVSxzqtMkpZ6rtXUlgx4ERqA9",

    "202601":
        "1s1Lgft3Fgb0a0Fcqhb_8oKD5hue_sWo5",

    "202602":
        "1_q6qkkF9ISnm8SPrMqTZdDsO32Hj85h1",

    "202603":
        "1j2cqV0IlulVl8WxYpiONJoilZSu2reQX",

    "202604":
        "1q1ismUp4wu0OhWYHmwzuzGILsIGh3-ud",

    "202605":
        "1FWe37KwbLO11B7kOM2-8ftiaS8taTvxO",

    "202606":
        "1wLnV9yIZkbj4cj6UuwJIXCSbhMzBGqMt",

    "202607":
        "1Vo-3_JhhQDqQ52xsj1bt9uqOWkTtXL6q",
}


# ============================================================
# CLIENTS
# ============================================================

def build_clients():

    creds, _ = google.auth.default()

    drive = build(
        "drive",
        "v3",
        credentials=creds,
        cache_discovery=False,
    )

    gcs = storage.Client(
        project=PROJECT_ID,
        credentials=creds,
    )

    return drive, gcs


# ============================================================
# JPX TRADING DAY
# ============================================================

def is_trading_day(d):

    if isinstance(d, pd.Timestamp):
        d = d.date()

    if d.weekday() >= 5:
        return False

    if jpholiday.is_holiday(d):
        return False

    if (
        d.month == 1
        and d.day <= 3
    ):
        return False

    if (
        d.month == 12
        and d.day == 31
    ):
        return False

    return True


def previous_trading_day(
    base_date=None,
):

    if base_date is None:

        base_date = (
            datetime.now(JST)
            .date()
        )

    d = (
        base_date
        - timedelta(days=1)
    )

    while not is_trading_day(d):
        d -= timedelta(days=1)

    return d


def trading_days_between(
    start_date,
    end_date,
):

    d = start_date
    out = []

    while d <= end_date:

        if is_trading_day(d):
            out.append(d)

        d += timedelta(days=1)

    return out


# ============================================================
# CODE NORMALIZATION
# ============================================================

def normalize_code(value):

    if pd.isna(value):
        return None

    s = str(value).strip()

    if s.endswith(".0"):
        s = s[:-2]

    if (
        len(s) == 5
        and
        s.endswith("0")
    ):
        s = s[:-1]

    return s


# ============================================================
# OLD SNAPSHOT INDEX
# ============================================================

def get_old_snapshot_index(
    gcs,
):

    result = {}

    for blob in gcs.list_blobs(
        OLD_BUCKET,
        prefix=OLD_PREFIX,
    ):

        if not blob.name.endswith(
            ".parquet"
        ):
            continue

        m = re.search(
            r"(\d{4}-\d{2}-\d{2})\.parquet$",
            blob.name,
        )

        if not m:
            continue

        d = pd.Timestamp(
            m.group(1)
        ).date()

        result[d] = blob.name

    return dict(
        sorted(
            result.items()
        )
    )


# ============================================================
# NEW FIX17 INDEX
# ============================================================

def get_new_fix17_index(
    gcs,
):

    result = {}

    for blob in gcs.list_blobs(
        NEW_BUCKET,
        prefix=NEW_PREFIX,
    ):

        if not blob.name.endswith(
            ".parquet"
        ):
            continue

        m = re.search(
            r"date=(\d{4}-\d{2}-\d{2})/",
            blob.name,
        )

        if not m:
            continue

        d = pd.Timestamp(
            m.group(1)
        ).date()

        result[d] = blob.name

    return dict(
        sorted(
            result.items()
        )
    )


# ============================================================
# DRIVE MONTH DOWNLOAD
# ============================================================

def get_historical_month_file(
    drive,
    ym,
):

    if ym not in HISTORICAL_FILES:

        raise RuntimeError(
            f"Historical month not registered: {ym}"
        )

    local = (
        CACHE_DIR
        /
        f"equities_bars_minute_{ym}.csv.gz"
    )

    if local.exists():
        return local

    file_id = (
        HISTORICAL_FILES[ym]
    )

    meta = (
        drive.files()
        .get(
            fileId=file_id,
            fields="id,name,size",
        )
        .execute()
    )

    expected_name = (
        f"equities_bars_minute_{ym}.csv.gz"
    )

    if meta["name"] != expected_name:

        raise RuntimeError(
            "Historical Drive file mismatch\n"
            f"Expected: {expected_name}\n"
            f"Actual  : {meta['name']}"
        )

    request = (
        drive.files()
        .get_media(
            fileId=file_id
        )
    )

    with open(
        local,
        "wb",
    ) as fh:

        downloader = MediaIoBaseDownload(
            fh,
            request,
            chunksize=16 * 1024 * 1024,
        )

        done = False

        while not done:

            _, done = (
                downloader.next_chunk()
            )

    return local


# ============================================================
# HISTORICAL MONTH READER
# ============================================================

def load_historical_month(
    drive,
    ym,
    wanted_dates,
    codes=None,
):

    local = get_historical_month_file(
        drive,
        ym,
    )

    wanted_str = {
        str(d)
        for d in wanted_dates
    }

    code_filter = None

    if codes is not None:

        code_filter = {
            normalize_code(x)
            for x in codes
        }

    parts = []

    for chunk in pd.read_csv(
        local,
        compression="gzip",
        usecols=[
            "Date",
            "Time",
            "Code",
            "O",
            "H",
            "L",
            "C",
            "Vo",
        ],
        chunksize=250_000,
        low_memory=False,
    ):

        mask = (
            chunk["Date"]
            .astype(str)
            .isin(wanted_str)
        )

        if not mask.any():
            continue

        x = (
            chunk.loc[
                mask
            ]
            .copy()
        )

        x["Code"] = (
            x["Code"]
            .map(normalize_code)
        )

        if code_filter is not None:

            x = x[
                x["Code"].isin(
                    code_filter
                )
            ]

            if x.empty:
                continue

        x["Datetime"] = pd.to_datetime(
            x["Date"].astype(str)
            + " "
            + x["Time"].astype(str),
            errors="raise",
        )

        x = x.rename(
            columns={
                "O": "Open",
                "H": "High",
                "L": "Low",
                "C": "Close",
                "Vo": "Volume",
            }
        )

        x = x[
            [
                "Datetime",
                "Code",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
            ]
        ]

        parts.append(x)

    if not parts:

        return pd.DataFrame(
            columns=[
                "Datetime",
                "Code",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
            ]
        )

    return pd.concat(
        parts,
        ignore_index=True,
    )


# ============================================================
# GCS PARQUET CACHE
# ============================================================

def get_gcs_parquet(
    gcs,
    bucket_name,
    object_name,
):

    safe_name = (
        object_name
        .replace("/", "__")
        .replace("=", "_")
    )

    local = (
        CACHE_DIR
        /
        safe_name
    )

    if local.exists():
        return local

    bucket = gcs.bucket(
        bucket_name
    )

    blob = bucket.blob(
        object_name
    )

    if not blob.exists():

        raise RuntimeError(
            "GCS object missing:\n"
            f"gs://{bucket_name}/{object_name}"
        )

    blob.download_to_filename(
        str(local)
    )

    return local


# ============================================================
# NORMALIZE PARQUET
# ============================================================

def normalize_parquet_1m(
    df,
):

    lower = {
        str(c).lower(): c
        for c in df.columns
    }


    def pick(*names):

        for n in names:

            if n.lower() in lower:
                return lower[n.lower()]

        return None


    dt_col = pick(
        "Datetime",
        "timestamp",
    )

    code_col = pick(
        "Code",
        "Ticker",
        "Symbol",
    )

    open_col = pick(
        "Open",
        "O",
    )

    high_col = pick(
        "High",
        "H",
    )

    low_col = pick(
        "Low",
        "L",
    )

    close_col = pick(
        "Close",
        "C",
    )

    volume_col = pick(
        "Volume",
        "Vo",
    )


    required = {
        "Datetime": dt_col,
        "Code": code_col,
        "Open": open_col,
        "High": high_col,
        "Low": low_col,
        "Close": close_col,
        "Volume": volume_col,
    }


    missing = [
        k
        for k, v in required.items()
        if v is None
    ]

    if missing:

        raise RuntimeError(
            "Unsupported parquet schema. "
            f"Missing={missing}\n"
            f"Columns={list(df.columns)}"
        )


    return pd.DataFrame({

        "Datetime":
            pd.to_datetime(
                df[dt_col],
                errors="raise",
            ),

        "Code":
            df[code_col]
            .map(normalize_code),

        "Open":
            pd.to_numeric(
                df[open_col],
                errors="raise",
            ),

        "High":
            pd.to_numeric(
                df[high_col],
                errors="raise",
            ),

        "Low":
            pd.to_numeric(
                df[low_col],
                errors="raise",
            ),

        "Close":
            pd.to_numeric(
                df[close_col],
                errors="raise",
            ),

        "Volume":
            pd.to_numeric(
                df[volume_col],
                errors="raise",
            ),
    })


# ============================================================
# OLD SNAPSHOT DAY
# ============================================================

def load_old_snapshot_day(
    gcs,
    d,
    object_name,
    codes=None,
):

    local = get_gcs_parquet(
        gcs,
        OLD_BUCKET,
        object_name,
    )

    df = pd.read_parquet(
        local
    )

    out = normalize_parquet_1m(
        df
    )

    del df

    if codes is not None:

        wanted = {
            normalize_code(x)
            for x in codes
        }

        out = out[
            out["Code"].isin(
                wanted
            )
        ]

    if out.empty:
        return out

    actual_dates = set(
        out["Datetime"]
        .dt.date
        .unique()
    )

    if actual_dates != {d}:

        raise RuntimeError(
            f"Snapshot date mismatch: "
            f"expected={d}, actual={actual_dates}"
        )

    return out


# ============================================================
# NEW FIX17 DAY
# ============================================================

def load_new_fix17_day(
    gcs,
    d,
    object_name,
    codes=None,
):

    local = get_gcs_parquet(
        gcs,
        NEW_BUCKET,
        object_name,
    )

    df = pd.read_parquet(
        local
    )

    out = normalize_parquet_1m(
        df
    )

    del df

    if codes is not None:

        wanted = {
            normalize_code(x)
            for x in codes
        }

        out = out[
            out["Code"].isin(
                wanted
            )
        ]

    if out.empty:
        return out

    actual_dates = set(
        out["Datetime"]
        .dt.date
        .unique()
    )

    if actual_dates != {d}:

        raise RuntimeError(
            f"FIX17 date mismatch: "
            f"expected={d}, actual={actual_dates}"
        )

    return out


# ============================================================
# MAIN FIX18 LOADER
# ============================================================

def load_fix18_1m(
    start_date,
    end_date=None,
    codes=None,
    strict=True,
    base_date=None,
):

    drive, gcs = build_clients()


    # --------------------------------------------------------
    # Dates
    # --------------------------------------------------------

    start_date = (
        pd.Timestamp(
            start_date
        ).date()
    )

    cutoff = previous_trading_day(
        base_date=base_date
    )

    if end_date is None:

        end_date = cutoff

    else:

        end_date = (
            pd.Timestamp(
                end_date
            ).date()
        )


    # --------------------------------------------------------
    # No-Future
    # --------------------------------------------------------

    if end_date > cutoff:

        end_date = cutoff


    if start_date > end_date:

        raise ValueError(
            f"Invalid range: "
            f"{start_date} -> {end_date}"
        )


    if start_date < HIST_FIRST_DATE:

        raise ValueError(
            "FIX18 raw 1m begins at "
            f"{HIST_FIRST_DATE}"
        )


    # --------------------------------------------------------
    # Source indexes
    # --------------------------------------------------------

    old_index = (
        get_old_snapshot_index(
            gcs
        )
    )

    new_index = (
        get_new_fix17_index(
            gcs
        )
    )


    old_last = (
        max(old_index)
        if old_index
        else None
    )


    requested_days = (
        trading_days_between(
            start_date,
            end_date,
        )
    )


    # --------------------------------------------------------
    # Source plan
    # --------------------------------------------------------

    historical_by_month = {}

    old_days = []

    new_days = []

    missing_days = []


    for d in requested_days:

        if d <= HIST_LAST_DATE:

            ym = (
                f"{d.year}{d.month:02d}"
            )

            historical_by_month.setdefault(
                ym,
                []
            ).append(d)

            continue


        if d in old_index:

            old_days.append(d)
            continue


        if d in new_index:

            new_days.append(d)
            continue


        missing_days.append(d)


    # --------------------------------------------------------
    # Missing-day strict gate
    # --------------------------------------------------------

    if (
        strict
        and
        missing_days
    ):

        raise RuntimeError(
            "FIX18 DATA GAP\n"
            "Missing trading days:\n"
            + "\n".join(
                str(d)
                for d in missing_days
            )
        )


    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    parts = []

    source_stats = []


    for ym, days in sorted(
        historical_by_month.items()
    ):

        x = load_historical_month(
            drive,
            ym,
            days,
            codes=codes,
        )

        if not x.empty:
            parts.append(x)

        source_stats.append({
            "source": "HISTORICAL",
            "key": ym,
            "days": len(days),
            "rows": len(x),
        })


    for d in old_days:

        x = load_old_snapshot_day(
            gcs,
            d,
            old_index[d],
            codes=codes,
        )

        if not x.empty:
            parts.append(x)

        source_stats.append({
            "source": "OLD_SNAPSHOT",
            "key": str(d),
            "days": 1,
            "rows": len(x),
        })


    for d in new_days:

        x = load_new_fix17_day(
            gcs,
            d,
            new_index[d],
            codes=codes,
        )

        if not x.empty:
            parts.append(x)

        source_stats.append({
            "source": "NEW_FIX17",
            "key": str(d),
            "days": 1,
            "rows": len(x),
        })


    if not parts:

        out = pd.DataFrame(
            columns=[
                "Datetime",
                "Code",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
            ]
        )

    else:

        out = pd.concat(
            parts,
            ignore_index=True,
        )


    # --------------------------------------------------------
    # Final audit
    # --------------------------------------------------------

    if not out.empty:

        out["Code"] = (
            out["Code"]
            .map(normalize_code)
        )

        out["Datetime"] = (
            pd.to_datetime(
                out["Datetime"],
                errors="raise",
            )
        )


        null_rows = int(
            out[
                [
                    "Datetime",
                    "Code",
                    "Open",
                    "High",
                    "Low",
                    "Close",
                    "Volume",
                ]
            ]
            .isna()
            .any(axis=1)
            .sum()
        )

        if null_rows:

            raise RuntimeError(
                f"Core NULL rows: {null_rows}"
            )


        dup = int(
            out.duplicated(
                [
                    "Code",
                    "Datetime",
                ]
            ).sum()
        )

        if dup:

            raise RuntimeError(
                f"Code+Datetime duplicates: {dup}"
            )


        out = (
            out
            .sort_values(
                [
                    "Datetime",
                    "Code",
                ]
            )
            .reset_index(
                drop=True
            )
        )


        actual_min = (
            out["Datetime"]
            .min()
            .date()
        )

        actual_max = (
            out["Datetime"]
            .max()
            .date()
        )


        if actual_min < start_date:

            raise RuntimeError(
                "Loaded data before requested start"
            )


        if actual_max > end_date:

            raise RuntimeError(
                "Loaded data after requested end"
            )


        if actual_max > cutoff:

            raise RuntimeError(
                "NO-FUTURE VIOLATION"
            )


    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

    meta = {

        "requested_start":
            start_date,

        "requested_end":
            end_date,

        "previous_trading_day":
            cutoff,

        "old_snapshot_last":
            old_last,

        "historical_months":
            sorted(
                historical_by_month
            ),

        "old_snapshot_days":
            old_days,

        "new_fix17_days":
            new_days,

        "missing_days":
            missing_days,

        "rows":
            len(out),

        "codes":
            (
                out["Code"].nunique()
                if not out.empty
                else 0
            ),

        "source_stats":
            source_stats,
    }


    gc.collect()

    return out, meta
