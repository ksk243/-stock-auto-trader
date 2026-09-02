# ============================================================

# FIX11 FORMAL STAGE6 FORWARD PAPER TRADER

#

# GitHub Actions / Cloud Run Service

# PAPER TRADE ONLY - NO REAL ORDERS

#

# ------------------------------------------------------------

# FORMAL SIGNAL

# ------------------------------------------------------------

#

# ORB15:

#   09:00 - 09:14 actual 1m bars

#

# Signal:

#   09:15 onward

#

# LONG:

#   RS20_corrected >= 80

#   turnover20 >= 3 oku yen

#   RVOL20 >= 2.0

#   previous actual close <= ORB15 High

#   current actual close  > ORB15 High

#

# SHORT:

#   lending eligible

#   RS20_corrected <= 20

#   turnover20 >= 3 oku yen

#   RVOL20 >= 2.0

#   previous actual close >= ORB15 Low

#   current actual close  < ORB15 Low

#

# Entry:

#   next actual 1m Open

#

# ------------------------------------------------------------

# PORTFOLIOS

# ------------------------------------------------------------

#

# BASE

#   LONG  1.00x

#   SHORT 0.50x

#

# FILTER

#   LONG  = same formal LONG

#   SHORT = formal SHORT after locked exclusion

#

# LOCKED SHORT FILTER:

#

#   EXCLUDE if ALL true:

#

#       ATR14_pct_prev >= 7.0

#       RVOL20         >= 2.5

#       RS20_corrected <= 5.0

#

# IMPORTANT:

#   filter BEFORE same-time ranking.

#

# ------------------------------------------------------------

# EXIT

# ------------------------------------------------------------

#

# LONG:

#   fixed SL       -2.5%

#   trail trigger  +2.5%

#   trail width     1.0%

#   max 10 trading days

#

# SHORT:

#   fixed SL       -1.5%

#   trail trigger  +2.0%

#   trail width     2.0%

#   unlimited carry

#

# Entry bar:

#   no exit

#   favorable extreme may activate trailing

#   new trail stop effective from NEXT actual bar

#

# ------------------------------------------------------------

# IMPORTANT

# ------------------------------------------------------------

#

# * NO REAL ORDERS

# * No-Future

# * raw Yahoo 1m snapshots saved

# * missing history => NOT_READY

# * BASE / FILTER independent state

# * GCS persistent storage

#

# ============================================================

from __future__ import annotations

import os

import io

import json

import math

import traceback

from pathlib import Path

from datetime import datetime

import numpy as np

import pandas as pd

import yfinance as yf

from flask import Flask, Response, jsonify, request

from google.cloud import storage

# ============================================================

# VERSION

# ============================================================

VERSION = "FIX11_STAGE6_FORWARD_V1"

TZ = "Asia/Tokyo"

# ============================================================

# SETTINGS

# ============================================================

INITIAL_CAPITAL = 1_117_792.0

LONG_LEVERAGE = 1.00

SHORT_LEVERAGE = 0.50

LOT_SIZE = 100

MIN_MARGIN_RATIO = 0.30

SUBSTITUTE_HAIRCUT = 0.80

# ============================================================

# SIGNAL

# ============================================================

RS_LONG_MIN = 80.0

RS_SHORT_MAX = 20.0

TURNOVER_MIN_OKU = 3.0

RVOL_MIN = 2.0

ORB_START = "09:00"

ORB_END = "09:14"

SIGNAL_START = "09:15"

# ============================================================

# LOCKED RESEARCH SHORT FILTER

# ============================================================

FILTER_ATR_MIN = 7.0

FILTER_RVOL_MIN = 2.5

FILTER_RS_MAX = 5.0

# ============================================================

# EXIT RULES

# ============================================================

LONG_SL = 0.025

LONG_TRAIL_TRIGGER = 0.025

LONG_TRAIL_WIDTH = 0.010

LONG_MAX_TRADING_DAYS = 10

SHORT_SL = 0.015

SHORT_TRAIL_TRIGGER = 0.020

SHORT_TRAIL_WIDTH = 0.020

# ============================================================

# FINANCING

# ============================================================

LONG_INTEREST_RATE = 0.0285

SHORT_LENDING_RATE = 0.0110

DAY_COUNT = 365.0

# ============================================================

# PATHS

# ============================================================

BASE_DIR = Path(

    os.path.dirname(

        os.path.abspath(__file__)

    )

)

DATA_DIR = BASE_DIR / "data" / "fix11"

RAW_DIR = DATA_DIR / "yahoo_1m"

CACHE_DIR = DATA_DIR / "cache"

UNIVERSE_FILE = BASE_DIR / "data" / "universe.csv"

STATE_FILE = DATA_DIR / "portfolio.json"

TRADES_FILE = DATA_DIR / "paper_trades.csv"

SCREEN_FILE = DATA_DIR / "screening_history.csv"

SIGNALS_FILE = DATA_DIR / "signals.csv"

DAILY_CACHE_FILE = CACHE_DIR / "daily_features.parquet"

LATEST_FILE = BASE_DIR / "latest_result.txt"

for p in [

    DATA_DIR,

    RAW_DIR,

    CACHE_DIR,

]:

    p.mkdir(

        parents=True,

        exist_ok=True

    )

# ============================================================

# GCS

# ============================================================

GCS_BUCKET = os.getenv(

    "GCS_BUCKET",

    ""

)

GCS_PREFIX = "fix11_forward"

GCS_STATE = f"{GCS_PREFIX}/portfolio.json"

GCS_TRADES = f"{GCS_PREFIX}/paper_trades.csv"

GCS_SCREEN = f"{GCS_PREFIX}/screening_history.csv"

GCS_SIGNALS = f"{GCS_PREFIX}/signals.csv"

GCS_DAILY = f"{GCS_PREFIX}/daily_features.parquet"

GCS_LATEST = f"{GCS_PREFIX}/latest_result.txt"

GCS_RAW_PREFIX = f"{GCS_PREFIX}/yahoo_1m"

# ============================================================

# FLASK

# ============================================================

app = Flask(__name__)

# ============================================================

# GENERAL HELPERS

# ============================================================

def now_jst():

    return pd.Timestamp.now(

        tz=TZ

    )

def today_naive():

    return (

        now_jst()

        .tz_localize(None)

        .normalize()

    )

def safe_float(

    value,

    default=np.nan

):

    try:

        x = float(value)

        if np.isfinite(x):

            return x

    except Exception:

        pass

    return default

def normalize_code(value):

    s = str(value).strip()

    if s.endswith(".T"):

        s = s[:-2]

    if s.endswith(".0"):

        s = s[:-2]

    return s

def ticker_from_code(code):

    code = normalize_code(code)

    if code.endswith("0") and len(code) == 5:

        code = code[:-1]

    return f"{code}.T"

def json_default(obj):

    if isinstance(

        obj,

        (

            pd.Timestamp,

            datetime,

        )

    ):

        return str(obj)

    if isinstance(

        obj,

        np.integer

    ):

        return int(obj)

    if isinstance(

        obj,

        np.floating

    ):

        return float(obj)

    if isinstance(

        obj,

        np.bool_

    ):

        return bool(obj)

    return str(obj)

def atomic_json_save(

    obj,

    path

):

    path = Path(path)

    path.parent.mkdir(

        parents=True,

        exist_ok=True

    )

    tmp = Path(

        str(path) + ".tmp"

    )

    with open(

        tmp,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            obj,

            f,

            ensure_ascii=False,

            indent=2,

            default=json_default

        )

    os.replace(

        tmp,

        path

    )

# ============================================================

# GCS HELPERS

# ============================================================

def get_bucket():

    if not GCS_BUCKET:

        return None

    client = storage.Client()

    return client.bucket(

        GCS_BUCKET

    )

def gcs_download(

    gcs_path,

    local_path

):

    bucket = get_bucket()

    if bucket is None:

        return False

    try:

        blob = bucket.blob(

            gcs_path

        )

        if not blob.exists():

            return False

        local_path = Path(

            local_path

        )

        local_path.parent.mkdir(

            parents=True,

            exist_ok=True

        )

        blob.download_to_filename(

            str(local_path)

        )

        print(

            "GCS restore:",

            gcs_path

        )

        return True

    except Exception as e:

        print(

            "GCS restore failed:",

            gcs_path,

            e

        )

        return False

def gcs_upload(

    local_path,

    gcs_path

):

    local_path = Path(

        local_path

    )

    if not local_path.exists():

        return False

    bucket = get_bucket()

    if bucket is None:

        return False

    try:

        blob = bucket.blob(

            gcs_path

        )

        blob.upload_from_filename(

            str(local_path)

        )

        print(

            "GCS upload:",

            gcs_path

        )

        return True

    except Exception as e:

        print(

            "GCS upload failed:",

            gcs_path,

            e

        )

        return False

# ============================================================

# RESULT

# ============================================================

def write_result(lines):

    if isinstance(

        lines,

        str

    ):

        text = lines

    else:

        text = "\n".join(

            str(x)

            for x in lines

        )

    print(text)

    with open(

        LATEST_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        f.write(

            text + "\n"

        )

    gcs_upload(

        LATEST_FILE,

        GCS_LATEST

    )

    return text

# ============================================================

# UNIVERSE

# ============================================================

def load_universe():

    if not UNIVERSE_FILE.exists():

        raise RuntimeError(

            "data/universe.csv がありません"

        )

    df = pd.read_csv(

        UNIVERSE_FILE,

        dtype=str

    )

    source_col = None

    for c in [

        "Code",

        "code",

        "Ticker",

        "ticker",

    ]:

        if c in df.columns:

            source_col = c

            break

    if source_col is None:

        raise RuntimeError(

            "universe.csv に Code 列がありません"

        )

    codes = []

    for x in df[source_col]:

        if pd.isna(x):

            continue

        code = normalize_code(

            x

        )

        if code:

            codes.append(

                code

            )

    codes = sorted(

        set(codes)

    )

    if not codes:

        raise RuntimeError(

            "Universe empty"

        )

    return codes

# ============================================================

# STATE

# ============================================================

def empty_strategy_state():

    return {

        "equity":

            INITIAL_CAPITAL,

        "cash":

            INITIAL_CAPITAL,

        "positions": {

            "LONG":

                None,

            "SHORT":

                None,

        },

        "last_financing_date":

            None,

    }

def initial_state():

    return {

        "version":

            VERSION,

        "BASE":

            empty_strategy_state(),

        "FILTER":

            empty_strategy_state(),

        "last_run":

            None,

    }

def load_state():

    gcs_download(

        GCS_STATE,

        STATE_FILE

    )

    if not STATE_FILE.exists():

        state = initial_state()

        save_state(

            state

        )

        return state

    try:

        with open(

            STATE_FILE,

            "r",

            encoding="utf-8"

        ) as f:

            state = json.load(

                f

            )

    except Exception:

        state = initial_state()

    state.setdefault(

        "BASE",

        empty_strategy_state()

    )

    state.setdefault(

        "FILTER",

        empty_strategy_state()

    )

    return state

def save_state(state):

    atomic_json_save(

        state,

        STATE_FILE

    )

    gcs_upload(

        STATE_FILE,

        GCS_STATE

    )

# ============================================================

# CSV APPEND

# ============================================================

def append_csv(

    path,

    rows,

    gcs_path=None

):

    if not rows:

        return

    path = Path(path)

    if (

        gcs_path

        and

        not path.exists()

    ):

        gcs_download(

            gcs_path,

            path

        )

    new = pd.DataFrame(

        rows

    )

    if path.exists():

        try:

            old = pd.read_csv(

                path

            )

        except Exception:

            old = pd.DataFrame()

        if not old.empty:

            new = pd.concat(

                [

                    old,

                    new

                ],

                ignore_index=True

            )

    new.to_csv(

        path,

        index=False,

        encoding="utf-8-sig"

    )

    if gcs_path:

        gcs_upload(

            path,

            gcs_path

        )

# ============================================================

# YAHOO NORMALIZATION

# ============================================================

def normalize_yahoo_1m(

    raw,

    code

):

    if (

        raw is None

        or

        len(raw) == 0

    ):

        return pd.DataFrame()

    x = raw.copy()

    if isinstance(

        x.columns,

        pd.MultiIndex

    ):

        x.columns = [

            c[0]

            if isinstance(c, tuple)

            else c

            for c in x.columns

        ]

    x = x.reset_index()

    dt_col = None

    for c in [

        "Datetime",

        "Date"

    ]:

        if c in x.columns:

            dt_col = c

            break

    if dt_col is None:

        return pd.DataFrame()

    dt = pd.to_datetime(

        x[dt_col],

        errors="coerce",

        utc=True

    )

    x["Datetime"] = (

        dt

        .dt.tz_convert(TZ)

        .dt.tz_localize(None)

    )

    rename = {

        "Open":

            "Open",

        "High":

            "High",

        "Low":

            "Low",

        "Close":

            "Close",

        "Volume":

            "Volume",

    }

    x = x.rename(

        columns=rename

    )

    required = [

        "Datetime",

        "Open",

        "High",

        "Low",

        "Close",

        "Volume",

    ]

    if any(

        c not in x.columns

        for c in required

    ):

        return pd.DataFrame()

    x = x[

        required

    ].copy()

    for c in [

        "Open",

        "High",

        "Low",

        "Close",

        "Volume",

    ]:

        x[c] = pd.to_numeric(

            x[c],

            errors="coerce"

        )

    # Remove synthetic placeholder rows.

    x = x.dropna(

        subset=[

            "Open",

            "High",

            "Low",

            "Close",

        ],

        how="all"

    )

    x = x.dropna(

        subset=[

            "Datetime",

            "Open",

            "High",

            "Low",

            "Close",

        ]

    )

    x["Code"] = normalize_code(

        code

    )

    x["Date"] = (

        x["Datetime"]

        .dt.normalize()

    )

    x["Time"] = (

        x["Datetime"]

        .dt.strftime("%H:%M")

    )

    return (

        x

        .sort_values(

            "Datetime"

        )

        .drop_duplicates(

            "Datetime",

            keep="first"

        )

        .reset_index(

            drop=True

        )

    )

# ============================================================

# FETCH TODAY 1M

# ============================================================

def fetch_today_1m(code):

    ticker = ticker_from_code(

        code

    )

    try:

        raw = yf.download(

            ticker,

            period="1d",

            interval="1m",

            auto_adjust=False,

            prepost=False,

            progress=False,

            threads=False,

        )

    except Exception as e:

        print(

            "1m error:",

            code,

            e

        )

        return pd.DataFrame()

    x = normalize_yahoo_1m(

        raw,

        code

    )

    if x.empty:

        return x

    today = today_naive()

    return (

        x[

            x["Date"]

            ==

            today

        ]

        .copy()

        .reset_index(

            drop=True

        )

    )

# ============================================================

# RAW SNAPSHOT

# ============================================================

def raw_local_path(

    date,

    code

):

    date = pd.Timestamp(

        date

    )

    return (

        RAW_DIR

        /

        date.strftime("%Y")

        /

        date.strftime("%m")

        /

        f"{date:%Y-%m-%d}_{code}.parquet"

    )

def raw_gcs_path(

    date,

    code

):

    date = pd.Timestamp(

        date

    )

    return (

        f"{GCS_RAW_PREFIX}/"

        f"{date:%Y}/"

        f"{date:%m}/"

        f"{date:%Y-%m-%d}_{code}.parquet"

    )

def save_raw_snapshot(df):

    if df.empty:

        return

    date = pd.Timestamp(

        df["Date"].iloc[0]

    )

    code = str(

        df["Code"].iloc[0]

    )

    path = raw_local_path(

        date,

        code

    )

    gcs_path = raw_gcs_path(

        date,

        code

    )

    path.parent.mkdir(

        parents=True,

        exist_ok=True

    )

    if not path.exists():

        gcs_download(

            gcs_path,

            path

        )

    if path.exists():

        try:

            old = pd.read_parquet(

                path

            )

        except Exception:

            old = pd.DataFrame()

        z = pd.concat(

            [

                old,

                df

            ],

            ignore_index=True

        )

    else:

        z = df.copy()

    z["Datetime"] = pd.to_datetime(

        z["Datetime"]

    )

    z = (

        z

        .sort_values(

            "Datetime"

        )

        .drop_duplicates(

            "Datetime",

            keep="first"

        )

    )

    z.to_parquet(

        path,

        index=False

    )

    gcs_upload(

        path,

        gcs_path

    )

# ============================================================

# DAILY DOWNLOAD

# ============================================================

def download_daily(universe):

    tickers = [

        ticker_from_code(

            c

        )

        for c in universe

    ]

    rows = []

    for start in range(

        0,

        len(tickers),

        50

    ):

        batch = tickers[

            start:

            start + 50

        ]

        try:

            raw = yf.download(

                batch,

                period="3mo",

                interval="1d",

                auto_adjust=False,

                group_by="ticker",

                progress=False,

                threads=True,

            )

        except Exception as e:

            print(

                "daily batch error:",

                e

            )

            continue

        for ticker in batch:

            code = normalize_code(

                ticker

            )

            try:

                if len(batch) == 1:

                    d = raw.copy()

                else:

                    if not isinstance(

                        raw.columns,

                        pd.MultiIndex

                    ):

                        continue

                    if ticker not in set(

                        raw.columns.get_level_values(0)

                    ):

                        continue

                    d = raw[

                        ticker

                    ].copy()

                if d.empty:

                    continue

                d = d.reset_index()

                d["Date"] = pd.to_datetime(

                    d["Date"],

                    errors="coerce"

                ).dt.normalize()

                for c in [

                    "Open",

                    "High",

                    "Low",

                    "Close",

                    "Volume",

                ]:

                    d[c] = pd.to_numeric(

                        d[c],

                        errors="coerce"

                    )

                if "Adj Close" in d.columns:

                    d["AdjClose"] = pd.to_numeric(

                        d["Adj Close"],

                        errors="coerce"

                    )

                else:

                    d["AdjClose"] = d[

                        "Close"

                    ]

                factor = (

                    d["AdjClose"]

                    /

                    d["Close"]

                )

                factor = factor.replace(

                    [

                        np.inf,

                        -np.inf

                    ],

                    np.nan

                )

                factor = factor.fillna(

                    1.0

                )

                d["AdjHigh"] = (

                    d["High"]

                    *

                    factor

                )

                d["AdjLow"] = (

                    d["Low"]

                    *

                    factor

                )

                d["Code"] = code

                rows.append(

                    d[

                        [

                            "Date",

                            "Code",

                            "Open",

                            "High",

                            "Low",

                            "Close",

                            "Volume",

                            "AdjClose",

                            "AdjHigh",

                            "AdjLow",

                        ]

                    ]

                )

            except Exception:

                continue

    if not rows:

        return pd.DataFrame()

    return (

        pd.concat(

            rows,

            ignore_index=True

        )

        .sort_values(

            [

                "Code",

                "Date"

            ]

        )

        .reset_index(

            drop=True

        )

    )

# ============================================================

# DAILY FEATURES

# ============================================================

def build_daily_features(

    daily,

    target_date

):

    if daily.empty:

        return pd.DataFrame()

    d = daily.copy()

    d = d[

        d["Date"]

        <

        target_date

    ].copy()

    d = d.sort_values(

        [

            "Code",

            "Date"

        ]

    )

    # --------------------------------------------------------

    # ATR14

    # --------------------------------------------------------

    d["PrevAdjClose"] = (

        d.groupby(

            "Code"

        )["AdjClose"]

        .shift(1)

    )

    tr1 = (

        d["AdjHigh"]

        -

        d["AdjLow"]

    ).abs()

    tr2 = (

        d["AdjHigh"]

        -

        d["PrevAdjClose"]

    ).abs()

    tr3 = (

        d["AdjLow"]

        -

        d["PrevAdjClose"]

    ).abs()

    d["TR"] = pd.concat(

        [

            tr1,

            tr2,

            tr3

        ],

        axis=1

    ).max(

        axis=1

    )

    d["ATR14"] = (

        d.groupby(

            "Code"

        )["TR"]

        .transform(

            lambda s:

            s.rolling(

                14,

                min_periods=14

            ).mean()

        )

    )

    d["ATR14_pct"] = (

        d["ATR14"]

        /

        d["AdjClose"]

        *

        100.0

    )

    # --------------------------------------------------------

    # 20 observation return

    # --------------------------------------------------------

    d["Return20"] = (

        d.groupby(

            "Code"

        )["AdjClose"]

        .pct_change(

            20

        )

    )

    latest_rows = []

    for code, g in d.groupby(

        "Code",

        sort=False

    ):

        g = (

            g

            .sort_values(

                "Date"

            )

            .reset_index(

                drop=True

            )

        )

        if len(g) < 21:

            continue

        last = g.iloc[-1]

        tail20 = g.tail(

            20

        )

        turnover = (

            tail20["Close"]

            *

            tail20["Volume"]

            /

            1e8

        )

        latest_rows.append({

            "Code":

                code,

            "Return20_prev":

                safe_float(

                    last["Return20"]

                ),

            "ATR14_pct_prev":

                safe_float(

                    last["ATR14_pct"]

                ),

            "turnover_median_20d_oku":

                safe_float(

                    turnover.median()

                ),

            "PrevDailyClose":

                safe_float(

                    last["Close"]

                ),

        })

    f = pd.DataFrame(

        latest_rows

    )

    if f.empty:

        return f

    valid = f[

        f["Return20_prev"]

        .notna()

    ].copy()

    valid[

        "RS20_corrected"

    ] = (

        valid[

            "Return20_prev"

        ]

        .rank(

            pct=True,

            method="average"

        )

        *

        100.0

    )

    f = f.merge(

        valid[

            [

                "Code",

                "RS20_corrected",

            ]

        ],

        on="Code",

        how="left"

    )

    return f

# ============================================================

# PREPARE DAILY

# ============================================================

def run_prepare():

    universe = load_universe()

    print(

        "Daily download..."

    )

    daily = download_daily(

        universe

    )

    if daily.empty:

        raise RuntimeError(

            "daily download empty"

        )

    target = today_naive()

    features = build_daily_features(

        daily,

        target

    )

    if features.empty:

        raise RuntimeError(

            "daily features empty"

        )

    features.to_parquet(

        DAILY_CACHE_FILE,

        index=False

    )

    gcs_upload(

        DAILY_CACHE_FILE,

        GCS_DAILY

    )

    return (

        "PREPARE OK\n"

        f"universe={len(universe)}\n"

        f"daily_rows={len(daily)}\n"

        f"feature_rows={len(features)}"

    )

# ============================================================

# LOAD DAILY FEATURES

# ============================================================

def load_daily_features():

    if not DAILY_CACHE_FILE.exists():

        gcs_download(

            GCS_DAILY,

            DAILY_CACHE_FILE

        )

    if not DAILY_CACHE_FILE.exists():

        return pd.DataFrame()

    try:

        return pd.read_parquet(

            DAILY_CACHE_FILE

        )

    except Exception:

        return pd.DataFrame()

# ============================================================

# RVOL HISTORY

# ============================================================

def get_previous_raw_files(

    code,

    current_date

):

    files = []

    # Local

    for p in RAW_DIR.rglob(

        f"*_{code}.parquet"

    ):

        try:

            d = pd.Timestamp(

                p.name[:10]

            )

        except Exception:

            continue

        if d < current_date:

            files.append(

                (

                    d,

                    p

                )

            )

    files = sorted(

        files,

        key=lambda x:

        x[0]

    )

    return files[-20:]

def calc_rvol20(

    code,

    current_df,

    signal_dt

):

    date = pd.Timestamp(

        signal_dt

    ).normalize()

    minute = pd.Timestamp(

        signal_dt

    ).strftime(

        "%H:%M"

    )

    hist_files = get_previous_raw_files(

        code,

        date

    )

    if len(hist_files) < 20:

        return np.nan, len(hist_files)

    current_cut = current_df[

        current_df["Datetime"]

        <=

        signal_dt

    ]

    current_cum = float(

        current_cut[

            "Volume"

        ]

        .fillna(0)

        .sum()

    )

    hist_cums = []

    for hist_date, path in hist_files:

        try:

            h = pd.read_parquet(

                path

            )

            h["Datetime"] = pd.to_datetime(

                h["Datetime"]

            )

            h["Time"] = (

                h["Datetime"]

                .dt.strftime(

                    "%H:%M"

                )

            )

            cut = h[

                h["Time"]

                <=

                minute

            ]

            if cut.empty:

                cum = 0.0

            else:

                cum = float(

                    pd.to_numeric(

                        cut["Volume"],

                        errors="coerce"

                    )

                    .fillna(0)

                    .sum()

                )

            hist_cums.append(

                cum

            )

        except Exception:

            hist_cums.append(

                0.0

            )

    if len(hist_cums) != 20:

        return np.nan, len(hist_cums)

    baseline = float(

        np.median(

            hist_cums

        )

    )

    if (

        not np.isfinite(

            baseline

        )

        or

        baseline <= 0

    ):

        return np.nan, 20

    return (

        current_cum

        /

        baseline,

        20

    )

# ============================================================

# SIGNAL GENERATION

# ============================================================

def find_signals_for_code(

    code,

    minute,

    feature

):

    if minute.empty:

        return []

    rs = safe_float(

        feature.get(

            "RS20_corrected"

        )

    )

    atr = safe_float(

        feature.get(

            "ATR14_pct_prev"

        )

    )

    turnover = safe_float(

        feature.get(

            "turnover_median_20d_oku"

        )

    )

    if not np.isfinite(

        rs

    ):

        return []

    if not np.isfinite(

        atr

    ):

        return []

    if (

        not np.isfinite(

            turnover

        )

        or

        turnover

        <

        TURNOVER_MIN_OKU

    ):

        return []

    x = (

        minute

        .sort_values(

            "Datetime"

        )

        .reset_index(

            drop=True

        )

    )

    orb = x[

        (

            x["Time"]

            >=

            ORB_START

        )

        &

        (

            x["Time"]

            <=

            ORB_END

        )

    ]

    if orb.empty:

        return []

    orb_high = float(

        orb["High"].max()

    )

    orb_low = float(

        orb["Low"].min()

    )

    post = x[

        x["Time"]

        >=

        SIGNAL_START

    ]

    if post.empty:

        return []

    results = []

    for idx in post.index:

        current = x.loc[

            idx

        ]

        before = x[

            x["Datetime"]

            <

            current["Datetime"]

        ]

        if before.empty:

            continue

        prev = before.iloc[-1]

        dt = pd.Timestamp(

            current["Datetime"]

        )

        prev_close = float(

            prev["Close"]

        )

        close = float(

            current["Close"]

        )

        rvol, hist_n = calc_rvol20(

            code,

            x,

            dt

        )

        if not np.isfinite(

            rvol

        ):

            continue

        # METHOD B:

        # Breakout can occur earlier with RVOL < 2.

        # Continue scanning later breakouts.

        long_break = (

            prev_close

            <=

            orb_high

            and

            close

            >

            orb_high

        )

        short_break = (

            prev_close

            >=

            orb_low

            and

            close

            <

            orb_low

        )

        side = None

        if (

            rs >= RS_LONG_MIN

            and

            rvol >= RVOL_MIN

            and

            long_break

        ):

            side = "LONG"

        elif (

            rs <= RS_SHORT_MAX

            and

            rvol >= RVOL_MIN

            and

            short_break

        ):

            side = "SHORT"

        if side is None:

            continue

        after = x[

            x["Datetime"]

            >

            dt

        ]

        if after.empty:

            continue

        nxt = after.iloc[0]

        results.append({

            "Side":

                side,

            "Code":

                code,

            "SignalDatetime":

                dt,

            "EntryDatetime":

                pd.Timestamp(

                    nxt["Datetime"]

                ),

            "EntryPrice":

                float(

                    nxt["Open"]

                ),

            "RS20_corrected":

                rs,

            "ATR14_pct_prev":

                atr,

            "RVOL20":

                float(

                    rvol

                ),

            "turnover_median_20d_oku":

                turnover,

            "ORBHigh":

                orb_high,

            "ORBLow":

                orb_low,

            "Prev20N":

                hist_n,

        })

        # First qualifying signal per

        # Date + Code + Side.

        break

    return results

# ============================================================

# SHORT LENDING

# ============================================================

def is_short_lending_eligible(code):

    # --------------------------------------------------------

    # Forward version:

    #

    # Exact J-Quants lending master should ultimately be used.

    #

    # Until a lending master file is supplied to GitHub,

    # SHORT must NOT be guessed.

    # --------------------------------------------------------

    path = (

        BASE_DIR

        /

        "data"

        /

        "lending_universe.csv"

    )

    if not path.exists():

        return False

    try:

        d = pd.read_csv(

            path,

            dtype=str

        )

    except Exception:

        return False

    if "Code" not in d.columns:

        return False

    eligible = set(

        d["Code"]

        .dropna()

        .map(

            normalize_code

        )

    )

    return (

        normalize_code(

            code

        )

        in

        eligible

    )

# ============================================================

# LOCKED FILTER

# ============================================================

def short_danger(signal):

    return (

        signal["Side"]

        ==

        "SHORT"

        and

        safe_float(

            signal[

                "ATR14_pct_prev"

            ]

        )

        >=

        FILTER_ATR_MIN

        and

        safe_float(

            signal[

                "RVOL20"

            ]

        )

        >=

        FILTER_RVOL_MIN

        and

        safe_float(

            signal[

                "RS20_corrected"

            ]

        )

        <=

        FILTER_RS_MAX

    )

# ============================================================

# FORMAL RANKING

# ============================================================

def rank_same_timestamp(

    signals,

    side

):

    x = [

        s

        for s in signals

        if s["Side"]

        ==

        side

    ]

    if not x:

        return None

    df = pd.DataFrame(

        x

    )

    earliest = df[

        "EntryDatetime"

    ].min()

    df = df[

        df["EntryDatetime"]

        ==

        earliest

    ].copy()

    if side == "LONG":

        df = df.sort_values(

            [

                "RS20_corrected",

                "RVOL20",

                "turnover_median_20d_oku",

                "Code",

            ],

            ascending=[

                False,

                False,

                False,

                True,

            ],

            kind="stable"

        )

    else:

        df = df.sort_values(

            [

                "RS20_corrected",

                "RVOL20",

                "turnover_median_20d_oku",

                "Code",

            ],

            ascending=[

                True,

                False,

                False,

                True,

            ],

            kind="stable"

        )

    return df.iloc[

        0

    ].to_dict()

# ============================================================

# POSITION SIZE

# ============================================================

def calc_qty(

    equity,

    leverage,

    price

):

    target = (

        float(equity)

        *

        float(leverage)

    )

    lot_notional = (

        float(price)

        *

        LOT_SIZE

    )

    if lot_notional <= 0:

        return 0, target

    lots = math.floor(

        target

        /

        lot_notional

    )

    qty = int(

        max(

            0,

            lots

            *

            LOT_SIZE

        )

    )

    return (

        qty,

        target

    )

# ============================================================

# POSITION CREATION

# ============================================================

def make_position(

    signal,

    equity,

    strategy_name

):

    side = signal[

        "Side"

    ]

    price = float(

        signal[

            "EntryPrice"

        ]

    )

    leverage = (

        LONG_LEVERAGE

        if side == "LONG"

        else

        SHORT_LEVERAGE

    )

    qty, target = calc_qty(

        equity,

        leverage,

        price

    )

    if qty < LOT_SIZE:

        return None, "LOT_TOO_LARGE"

    actual = (

        qty

        *

        price

    )

    return {

        "Strategy":

            strategy_name,

        "Side":

            side,

        "Code":

            signal["Code"],

        "SignalDatetime":

            str(

                signal[

                    "SignalDatetime"

                ]

            ),

        "EntryDatetime":

            str(

                signal[

                    "EntryDatetime"

                ]

            ),

        "EntryPrice":

            price,

        "Quantity":

            qty,

        "TargetNotional":

            target,

        "ActualNotional":

            actual,

        "RS20_corrected":

            signal[

                "RS20_corrected"

            ],

        "ATR14_pct_prev":

            signal[

                "ATR14_pct_prev"

            ],

        "RVOL20":

            signal[

                "RVOL20"

            ],

        "turnover_median_20d_oku":

            signal[

                "turnover_median_20d_oku"

            ],

        "BestPrice":

            price,

        "TrailActive":

            False,

        "ActiveTrailStop":

            None,

        "PendingTrailStop":

            None,

        "TradingDaysHeld":

            1,

        "LastProcessedDatetime":

            str(

                signal[

                    "EntryDatetime"

                ]

            ),

    }, "OK"

# ============================================================

# EXIT ENGINE

# ============================================================

def process_position_bars(

    position,

    minute

):

    if position is None:

        return (

            None,

            None

        )

    side = position[

        "Side"

    ]

    entry_dt = pd.Timestamp(

        position[

            "EntryDatetime"

        ]

    )

    entry = float(

        position[

            "EntryPrice"

        ]

    )

    last_processed = pd.Timestamp(

        position.get(

            "LastProcessedDatetime",

            position[

                "EntryDatetime"

            ]

        )

    )

    x = minute[

        minute["Datetime"]

        >

        last_processed

    ].copy()

    if x.empty:

        return (

            position,

            None

        )

    best = float(

        position.get(

            "BestPrice",

            entry

        )

    )

    trail_active = bool(

        position.get(

            "TrailActive",

            False

        )

    )

    active_trail = safe_float(

        position.get(

            "ActiveTrailStop"

        )

    )

    pending_trail = safe_float(

        position.get(

            "PendingTrailStop"

        )

    )

    qty = int(

        position[

            "Quantity"

        ]

    )

    for _, bar in x.iterrows():

        dt = pd.Timestamp(

            bar[

                "Datetime"

            ]

        )

        o = float(

            bar[

                "Open"

            ]

        )

        h = float(

            bar[

                "High"

            ]

        )

        l = float(

            bar[

                "Low"

            ]

        )

        # ----------------------------------------------------

        # Pending trail becomes active at this actual bar.

        # ----------------------------------------------------

        if np.isfinite(

            pending_trail

        ):

            active_trail = (

                pending_trail

            )

            pending_trail = np.nan

        # ----------------------------------------------------

        # Fixed SL

        # ----------------------------------------------------

        if side == "LONG":

            fixed_sl = (

                entry

                *

                (

                    1

                    -

                    LONG_SL

                )

            )

            stops = [

                fixed_sl

            ]

            if np.isfinite(

                active_trail

            ):

                stops.append(

                    active_trail

                )

            stop = max(

                stops

            )

            # GAP

            if o <= stop:

                exit_price = o

                reason = (

                    "TRAIL_GAP"

                    if (

                        np.isfinite(

                            active_trail

                        )

                        and

                        active_trail

                        >=

                        fixed_sl

                    )

                    else

                    "SL_GAP"

                )

                ret = (

                    exit_price

                    /

                    entry

                    -

                    1

                )

                return (

                    None,

                    {

                        "ExitDatetime":

                            dt,

                        "ExitPrice":

                            exit_price,

                        "ReturnPct":

                            ret

                            *

                            100.0,

                        "Reason":

                            reason,

                        "PnL":

                            entry

                            *

                            qty

                            *

                            ret,

                    }

                )

            if l <= stop:

                exit_price = stop

                reason = (

                    "TRAIL"

                    if (

                        np.isfinite(

                            active_trail

                        )

                        and

                        active_trail

                        >=

                        fixed_sl

                    )

                    else

                    "SL"

                )

                ret = (

                    exit_price

                    /

                    entry

                    -

                    1

                )

                return (

                    None,

                    {

                        "ExitDatetime":

                            dt,

                        "ExitPrice":

                            exit_price,

                        "ReturnPct":

                            ret

                            *

                            100.0,

                        "Reason":

                            reason,

                        "PnL":

                            entry

                            *

                            qty

                            *

                            ret,

                    }

                )

            # Favorable extreme

            best = max(

                best,

                h

            )

            trigger = (

                entry

                *

                (

                    1

                    +

                    LONG_TRAIL_TRIGGER

                )

            )

            if best >= trigger:

                trail_active = True

                new_stop = (

                    best

                    *

                    (

                        1

                        -

                        LONG_TRAIL_WIDTH

                    )

                )

                if np.isfinite(

                    active_trail

                ):

                    new_stop = max(

                        new_stop,

                        active_trail

                    )

                pending_trail = (

                    new_stop

                )

        else:

            fixed_sl = (

                entry

                *

                (

                    1

                    +

                    SHORT_SL

                )

            )

            stops = [

                fixed_sl

            ]

            if np.isfinite(

                active_trail

            ):

                stops.append(

                    active_trail

                )

            stop = min(

                stops

            )

            # GAP

            if o >= stop:

                exit_price = o

                reason = (

                    "TRAIL_GAP"

                    if (

                        np.isfinite(

                            active_trail

                        )

                        and

                        active_trail

                        <=

                        fixed_sl

                    )

                    else

                    "SL_GAP"

                )

                ret = (

                    entry

                    /

                    exit_price

                    -

                    1

                )

                return (

                    None,

                    {

                        "ExitDatetime":

                            dt,

                        "ExitPrice":

                            exit_price,

                        "ReturnPct":

                            ret

                            *

                            100.0,

                        "Reason":

                            reason,

                        "PnL":

                            entry

                            *

                            qty

                            *

                            ret,

                    }

                )

            if h >= stop:

                exit_price = stop

                reason = (

                    "TRAIL"

                    if (

                        np.isfinite(

                            active_trail

                        )

                        and

                        active_trail

                        <=

                        fixed_sl

                    )

                    else

                    "SL"

                )

                ret = (

                    entry

                    /

                    exit_price

                    -

                    1

                )

                return (

                    None,

                    {

                        "ExitDatetime":

                            dt,

                        "ExitPrice":

                            exit_price,

                        "ReturnPct":

                            ret

                            *

                            100.0,

                        "Reason":

                            reason,

                        "PnL":

                            entry

                            *

                            qty

                            *

                            ret,

                    }

                )

            # Favorable extreme

            best = min(

                best,

                l

            )

            trigger = (

                entry

                *

                (

                    1

                    -

                    SHORT_TRAIL_TRIGGER

                )

            )

            if best <= trigger:

                trail_active = True

                new_stop = (

                    best

                    *

                    (

                        1

                        +

                        SHORT_TRAIL_WIDTH

                    )

                )

                if np.isfinite(

                    active_trail

                ):

                    new_stop = min(

                        new_stop,

                        active_trail

                    )

                pending_trail = (

                    new_stop

                )

        position[

            "LastProcessedDatetime"

        ] = str(

            dt

        )

    position[

        "BestPrice"

    ] = best

    position[

        "TrailActive"

    ] = trail_active

    position[

        "ActiveTrailStop"

    ] = (

        None

        if not np.isfinite(

            active_trail

        )

        else float(

            active_trail

        )

    )

    position[

        "PendingTrailStop"

    ] = (

        None

        if not np.isfinite(

            pending_trail

        )

        else float(

            pending_trail

        )

    )

    return (

        position,

        None

    )

# ============================================================

# FINANCING

# ============================================================

def apply_daily_financing(

    strategy_state,

    target_date

):

    last = strategy_state.get(

        "last_financing_date"

    )

    if last is None:

        strategy_state[

            "last_financing_date"

        ] = str(

            target_date.date()

        )

        return 0.0

    last = pd.Timestamp(

        last

    ).normalize()

    days = (

        target_date

        -

        last

    ).days

    if days <= 0:

        return 0.0

    total = 0.0

    for side in [

        "LONG",

        "SHORT"

    ]:

        p = strategy_state[

            "positions"

        ].get(

            side

        )

        if not p:

            continue

        notional = safe_float(

            p.get(

                "ActualNotional"

            ),

            0.0

        )

        rate = (

            LONG_INTEREST_RATE

            if side == "LONG"

            else

            SHORT_LENDING_RATE

        )

        fee = (

            notional

            *

            rate

            *

            days

            /

            DAY_COUNT

        )

        total += fee

    strategy_state[

        "equity"

    ] -= total

    strategy_state[

        "cash"

    ] -= total

    strategy_state[

        "last_financing_date"

    ] = str(

        target_date.date()

    )

    return total

# ============================================================

# EXIT CURRENT POSITIONS

# ============================================================

def update_existing_positions(

    state,

    minute_map,

    target_date

):

    trade_rows = []

    for strategy_name in [

        "BASE",

        "FILTER"

    ]:

        strategy = state[

            strategy_name

        ]

        financing = apply_daily_financing(

            strategy,

            target_date

        )

        if financing:

            trade_rows.append({

                "RunDatetime":

                    now_jst()

                    .tz_localize(None),

                "Strategy":

                    strategy_name,

                "Status":

                    "FINANCING",

                "PnL":

                    -financing,

            })

        for side in [

            "LONG",

            "SHORT"

        ]:

            position = strategy[

                "positions"

            ].get(

                side

            )

            if not position:

                continue

            code = position[

                "Code"

            ]

            minute = minute_map.get(

                code

            )

            if (

                minute is None

                or

                minute.empty

            ):

                continue

            new_position, exit_info = (

                process_position_bars(

                    position,

                    minute

                )

            )

            if exit_info is None:

                strategy[

                    "positions"

                ][side] = (

                    new_position

                )

                continue

            pnl = float(

                exit_info[

                    "PnL"

                ]

            )

            strategy[

                "equity"

            ] += pnl

            strategy[

                "cash"

            ] += pnl

            trade_rows.append({

                "RunDatetime":

                    now_jst()

                    .tz_localize(None),

                "Strategy":

                    strategy_name,

                "Status":

                    "EXIT",

                "Side":

                    side,

                "Code":

                    code,

                "EntryDatetime":

                    position[

                        "EntryDatetime"

                    ],

                "EntryPrice":

                    position[

                        "EntryPrice"

                    ],

                "ExitDatetime":

                    exit_info[

                        "ExitDatetime"

                    ],

                "ExitPrice":

                    exit_info[

                        "ExitPrice"

                    ],

                "Quantity":

                    position[

                        "Quantity"

                    ],

                "ReturnPct":

                    exit_info[

                        "ReturnPct"

                    ],

                "PnL":

                    pnl,

                "Reason":

                    exit_info[

                        "Reason"

                    ],

            })

            strategy[

                "positions"

            ][side] = None

    return trade_rows

# ============================================================

# ENTRY

# ============================================================

def try_entry(

    strategy_name,

    strategy_state,

    signal

):

    side = signal[

        "Side"

    ]

    if strategy_state[

        "positions"

    ].get(

        side

    ):

        return None

    position, status = make_position(

        signal,

        strategy_state[

            "equity"

        ],

        strategy_name

    )

    if position is None:

        return {

            "RunDatetime":

                now_jst()

                .tz_localize(None),

            "Strategy":

                strategy_name,

            "Status":

                status,

            **signal,

        }

    # --------------------------------------------------------

    # Simplified entry margin guard.

    # --------------------------------------------------------

    gross = 0.0

    for p in strategy_state[

        "positions"

    ].values():

        if p:

            gross += safe_float(

                p.get(

                    "ActualNotional"

                ),

                0.0

            )

    gross += position[

        "ActualNotional"

    ]

    collateral = safe_float(

        strategy_state[

            "cash"

        ],

        0.0

    )

    margin = (

        np.inf

        if gross <= 0

        else

        collateral

        /

        gross

    )

    if margin < MIN_MARGIN_RATIO:

        return {

            "RunDatetime":

                now_jst()

                .tz_localize(None),

            "Strategy":

                strategy_name,

            "Status":

                "MARGIN_SKIP",

            "PostMarginPct":

                margin

                *

                100.0,

            **signal,

        }

    strategy_state[

        "positions"

    ][side] = position

    return {

        "RunDatetime":

            now_jst()

            .tz_localize(None),

        "Strategy":

            strategy_name,

        "Status":

            "ENTRY",

        "Side":

            side,

        "Code":

            signal[

                "Code"

            ],

        "SignalDatetime":

            signal[

                "SignalDatetime"

            ],

        "EntryDatetime":

            signal[

                "EntryDatetime"

            ],

        "EntryPrice":

            signal[

                "EntryPrice"

            ],

        "Quantity":

            position[

                "Quantity"

            ],

        "ActualNotional":

            position[

                "ActualNotional"

            ],

        "RS20_corrected":

            signal[

                "RS20_corrected"

            ],

        "ATR14_pct_prev":

            signal[

                "ATR14_pct_prev"

            ],

        "RVOL20":

            signal[

                "RVOL20"

            ],

        "Danger":

            short_danger(

                signal

            ),

        "PostMarginPct":

            margin

            *

            100.0,

    }

# ============================================================

# DECISION

# ============================================================

def run_decision(

    test_mode=False

):

    run_time = (

        now_jst()

        .tz_localize(None)

    )

    target_date = (

        run_time

        .normalize()

    )

    universe = load_universe()

    state = load_state()

    features = load_daily_features()

    if features.empty:

        raise RuntimeError(

            "daily feature cache empty. /prepare を先に実行してください"

        )

    feature_map = (

        features

        .set_index(

            "Code"

        )

        .to_dict(

            orient="index"

        )

    )

    minute_map = {}

    all_signals = []

    screen_rows = []

    success = 0

    failed = 0

    not_ready = 0

    # ========================================================

    # FETCH + SAVE RAW

    # ========================================================

    for i, code in enumerate(

        universe,

        1

    ):

        minute = fetch_today_1m(

            code

        )

        if minute.empty:

            failed += 1

            continue

        success += 1

        minute_map[

            code

        ] = minute

        save_raw_snapshot(

            minute

        )

        feature = feature_map.get(

            code

        )

        if feature is None:

            screen_rows.append({

                "RunDatetime":

                    run_time,

                "Code":

                    code,

                "Status":

                    "NOT_READY_DAILY",

            })

            not_ready += 1

            continue

        hist_n = len(

            get_previous_raw_files(

                code,

                target_date

            )

        )

        if hist_n < 20:

            screen_rows.append({

                "RunDatetime":

                    run_time,

                "Code":

                    code,

                "Status":

                    "NOT_READY_RVOL20",

                "HistoryDays":

                    hist_n,

            })

            not_ready += 1

            continue

        signals = find_signals_for_code(

            code,

            minute,

            feature

        )

        for sig in signals:

            if (

                sig["Side"]

                ==

                "SHORT"

                and

                not is_short_lending_eligible(

                    code

                )

            ):

                screen_rows.append({

                    "RunDatetime":

                        run_time,

                    "Code":

                        code,

                    "Status":

                        "SHORT_NOT_LENDING",

                    **sig,

                })

                continue

            all_signals.append(

                sig

            )

            screen_rows.append({

                "RunDatetime":

                    run_time,

                "Status":

                    "SIGNAL",

                "Danger":

                    short_danger(

                        sig

                    ),

                **sig,

            })

        if i % 50 == 0:

            print(

                f"{i}/{len(universe)} "

                f"success={success} "

                f"failed={failed}"

            )

    # ========================================================

    # UPDATE EXISTING POSITIONS FIRST

    # ========================================================

    trade_rows = update_existing_positions(

        state,

        minute_map,

        target_date

    )

    # ========================================================

    # BASE SELECTION

    # ========================================================

    base_long = rank_same_timestamp(

        all_signals,

        "LONG"

    )

    base_short = rank_same_timestamp(

        all_signals,

        "SHORT"

    )

    # ========================================================

    # FILTER SELECTION

    #

    # Filter BEFORE ranking.

    # ========================================================

    filtered_signals = [

        s

        for s in all_signals

        if not short_danger(

            s

        )

    ]

    filter_long = rank_same_timestamp(

        filtered_signals,

        "LONG"

    )

    filter_short = rank_same_timestamp(

        filtered_signals,

        "SHORT"

    )

    chosen = {

        "BASE": {

            "LONG":

                base_long,

            "SHORT":

                base_short,

        },

        "FILTER": {

            "LONG":

                filter_long,

            "SHORT":

                filter_short,

        },

    }

    # ========================================================

    # TEST MODE:

    #

    # Calculate only.

    # Do not modify portfolio.

    # ========================================================

    if test_mode:

        lines = [

            "FIX11 STAGE6 TEST",

            f"Run: {run_time}",

            f"Universe: {len(universe)}",

            f"1m success: {success}",

            f"1m failed: {failed}",

            f"NOT_READY: {not_ready}",

            f"Signals: {len(all_signals)}",

            f"SHORT danger signals: "

            f"{sum(short_danger(s) for s in all_signals)}",

            "",

        ]

        for strategy_name in [

            "BASE",

            "FILTER"

        ]:

            lines.append(

                f"【{strategy_name}】"

            )

            for side in [

                "LONG",

                "SHORT"

            ]:

                c = chosen[

                    strategy_name

                ][side]

                if c is None:

                    lines.append(

                        f"{side}: NONE"

                    )

                else:

                    lines.append(

                        f"{side}: "

                        f"{c['Code']} "

                        f"Entry={c['EntryDatetime']} "

                        f"Price={c['EntryPrice']:.2f} "

                        f"RS={c['RS20_corrected']:.2f} "

                        f"ATR={c['ATR14_pct_prev']:.2f} "

                        f"RVOL={c['RVOL20']:.2f}"

                    )

            lines.append("")

        append_csv(

            SCREEN_FILE,

            screen_rows,

            GCS_SCREEN

        )

        append_csv(

            SIGNALS_FILE,

            [

                {

                    "RunDatetime":

                        run_time,

                    "Danger":

                        short_danger(

                            s

                        ),

                    **s,

                }

                for s in all_signals

            ],

            GCS_SIGNALS

        )

        return write_result(

            lines

        )

    # ========================================================

    # REAL PAPER ENTRY

    # ========================================================

    for strategy_name in [

        "BASE",

        "FILTER"

    ]:

        strategy_state = state[

            strategy_name

        ]

        for side in [

            "LONG",

            "SHORT"

        ]:

            signal = chosen[

                strategy_name

            ][side]

            if signal is None:

                continue

            result = try_entry(

                strategy_name,

                strategy_state,

                signal

            )

            if result:

                trade_rows.append(

                    result

                )

    state[

        "last_run"

    ] = str(

        run_time

    )

    save_state(

        state

    )

    append_csv(

        TRADES_FILE,

        trade_rows,

        GCS_TRADES

    )

    append_csv(

        SCREEN_FILE,

        screen_rows,

        GCS_SCREEN

    )

    append_csv(

        SIGNALS_FILE,

        [

            {

                "RunDatetime":

                    run_time,

                "Danger":

                    short_danger(

                        s

                    ),

                **s,

            }

            for s in all_signals

        ],

        GCS_SIGNALS

    )

    # ========================================================

    # EMAIL / RESULT TEXT

    # ========================================================

    lines = [

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",

        "FIX11 FORMAL STAGE6",

        "FORWARD PAPER TRADER",

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",

        "",

        f"Run: {run_time}",

        f"Universe: {len(universe)}",

        f"1m success: {success}",

        f"1m failed: {failed}",

        f"NOT_READY: {not_ready}",

        f"Signals: {len(all_signals)}",

        "",

    ]

    for strategy_name in [

        "BASE",

        "FILTER"

    ]:

        strategy = state[

            strategy_name

        ]

        lines.extend([

            f"【{strategy_name}】",

            f"Equity: "

            f"¥{strategy['equity']:,.0f}",

        ])

        for side in [

            "LONG",

            "SHORT"

        ]:

            p = strategy[

                "positions"

            ].get(

                side

            )

            if p:

                lines.append(

                    f"{side}: "

                    f"{p['Code']} "

                    f"{p['Quantity']}株 "

                    f"@ {p['EntryPrice']:,.2f}"

                )

            else:

                lines.append(

                    f"{side}: FLAT"

                )

        lines.append("")

    base_short_code = (

        None

        if base_short is None

        else

        base_short["Code"]

    )

    filter_short_code = (

        None

        if filter_short is None

        else

        filter_short["Code"]

    )

    lines.extend([

        "【SHORT比較】",

        f"BASE   : {base_short_code}",

        f"FILTER : {filter_short_code}",

        "",

        "LOCKED FILTER:",

        "ATR14_pct_prev >= 7",

        "RVOL20 >= 2.5",

        "RS20_corrected <= 5",

        "→ 3条件すべて一致したSHORT候補を",

        "   ランキング前に除外",

        "",

        "※ PAPER TRADE ONLY",

        "※ 実注文なし",

    ])

    return write_result(

        lines

    )

# ============================================================

# RESULT MODE

# ============================================================

def run_result():

    # --------------------------------------------------------

    # Result mode re-fetches today's actual 1m bars,

    # updates open positions and saves exits.

    # No new entries.

    # --------------------------------------------------------

    run_time = (

        now_jst()

        .tz_localize(None)

    )

    target_date = (

        run_time

        .normalize()

    )

    state = load_state()

    universe = load_universe()

    needed = set()

    for strategy_name in [

        "BASE",

        "FILTER"

    ]:

        for side in [

            "LONG",

            "SHORT"

        ]:

            p = state[

                strategy_name

            ][

                "positions"

            ].get(

                side

            )

            if p:

                needed.add(

                    p[

                        "Code"

                    ]

                )

    minute_map = {}

    for code in sorted(

        needed

    ):

        minute = fetch_today_1m(

            code

        )

        if minute.empty:

            continue

        minute_map[

            code

        ] = minute

        save_raw_snapshot(

            minute

        )

    trade_rows = update_existing_positions(

        state,

        minute_map,

        target_date

    )

    state[

        "last_run"

    ] = str(

        run_time

    )

    save_state(

        state

    )

    append_csv(

        TRADES_FILE,

        trade_rows,

        GCS_TRADES

    )

    lines = [

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",

        "FIX11 STAGE6 RESULT",

        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",

        "",

        f"Run: {run_time}",

        "",

    ]

    exits = [

        r

        for r in trade_rows

        if r.get(

            "Status"

        )

        ==

        "EXIT"

    ]

    if exits:

        lines.append(

            "【EXIT】"

        )

        for r in exits:

            lines.extend([

                (

                    f"{r['Strategy']} "

                    f"{r['Side']} "

                    f"{r['Code']}"

                ),

                (

                    f"{r['Reason']} "

                    f"{r['ReturnPct']:+.3f}% "

                    f"¥{r['PnL']:+,.0f}"

                ),

                "",

            ])

    else:

        lines.extend([

            "【EXIT】",

            "なし",

            "",

        ])

    for strategy_name in [

        "BASE",

        "FILTER"

    ]:

        strategy = state[

            strategy_name

        ]

        lines.extend([

            f"【{strategy_name}】",

            (

                f"Equity "

                f"¥{strategy['equity']:,.0f}"

            ),

        ])

        for side in [

            "LONG",

            "SHORT"

        ]:

            p = strategy[

                "positions"

            ].get(

                side

            )

            if p:

                lines.append(

                    f"{side}: "

                    f"{p['Code']} "

                    f"{p['Quantity']}株 "

                    f"@ {p['EntryPrice']:,.2f}"

                )

            else:

                lines.append(

                    f"{side}: FLAT"

                )

        lines.append("")

    return write_result(

        lines

    )

# ============================================================

# RESEARCH MODE

# ============================================================

def run_research():

    return (

        "FIX11 research data is saved "

        "during decision/test mode."

    )

# ============================================================

# MODE

# ============================================================

def get_run_mode():

    mode = os.getenv(

        "RUN_MODE",

        ""

    ).strip().lower()

    if mode in [

        "decision",

        "result",

        "test",

        "research",

    ]:

        return mode

    return "test"

def execute_mode(mode):

    print("=" * 100)

    print(VERSION)

    print(

        "MODE:",

        mode

    )

    print("=" * 100)

    if mode == "decision":

        return run_decision(

            test_mode=False

        )

    if mode == "test":

        return run_decision(

            test_mode=True

        )

    if mode == "result":

        return run_result()

    if mode == "research":

        return run_research()

    raise RuntimeError(

        f"Unknown mode: {mode}"

    )

# ============================================================

# HTTP

# ============================================================

@app.get("/")

def health():

    return jsonify({

        "status":

            "ok",

        "version":

            VERSION,

        "paper_only":

            True,

        "long_leverage":

            LONG_LEVERAGE,

        "short_leverage":

            SHORT_LEVERAGE,

        "short_filter": {

            "ATR14_pct_prev_gte":

                FILTER_ATR_MIN,

            "RVOL20_gte":

                FILTER_RVOL_MIN,

            "RS20_corrected_lte":

                FILTER_RS_MAX,

        }

    })

@app.get("/prepare")

def prepare_endpoint():

    try:

        result = run_prepare()

        return Response(

            result,

            status=200,

            mimetype=(

                "text/plain; "

                "charset=utf-8"

            )

        )

    except Exception as e:

        error = (

            "FIX11 PREPARE ERROR\n\n"

            f"{type(e).__name__}: "

            f"{e}\n\n"

            f"{traceback.format_exc()}"

        )

        return Response(

            error,

            status=500,

            mimetype=(

                "text/plain; "

                "charset=utf-8"

            )

        )

@app.get("/run")

def run_endpoint():

    mode = request.args.get(

        "mode",

        get_run_mode()

    ).strip().lower()

    try:

        result = execute_mode(

            mode

        )

        return Response(

            str(result),

            status=200,

            mimetype=(

                "text/plain; "

                "charset=utf-8"

            )

        )

    except Exception as e:

        error = (

            "FIX11 FORWARD ERROR\n\n"

            f"MODE: {mode}\n\n"

            f"{type(e).__name__}: "

            f"{e}\n\n"

            f"{traceback.format_exc()}"

        )

        try:

            write_result(

                error

            )

        except Exception:

            pass

        return Response(

            error,

            status=500,

            mimetype=(

                "text/plain; "

                "charset=utf-8"

            )

        )

# ============================================================

# LOCAL ENTRYPOINT

# ============================================================

if __name__ == "__main__":

    execute_mode(

        get_run_mode()

    )
