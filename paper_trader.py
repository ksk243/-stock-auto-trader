# ============================================================

# FIX11 / Stage6 Forward Shadow Trader V4.1

# ============================================================

#

# 実注文なし / Forward Paper Replay

#

# TRACKS

#   LONG

#   SHORT_BASE

#   SHORT_FILTER

#

# ------------------------------------------------------------

# SHORT_FILTER 固定除外条件

# ------------------------------------------------------------

#   ATR14_pct_prev >= 7.0

#   AND RVOL20 >= 2.5

#   AND RS20_corrected <= 5.0

#

# ------------------------------------------------------------

# Formal rules

# ------------------------------------------------------------

#   ORB      09:00-09:14

#   Signal   09:15-

#   Entry    breakout後の次の実在1分足 OPEN

#   Turnover >= 3億円

#   RVOL20   >= 2.0

#

# LONG

#   RS >= 80

#   SL 2.5%

#   Trigger 2.5%

#   Trail 1.0%

#   Max 10 trading days

#

# SHORT

#   RS <= 20

#   貸借のみ

#   SL 1.5%

#   Trigger 2.0%

#   Trail 2.0%

#   Carry unlimited

#

# ------------------------------------------------------------

# V4.1

# ------------------------------------------------------------

#

# 1. 当日snapshotがGCSに存在すれば最優先で利用

# 2. daily featureを日付別にGCS cache

# 3. RVOL20を高速化

#    定義はFormalのまま:

#      現在累積出来高 /

#      過去20取引日の同時刻までの累積出来高中央値

#    exact-minute bar不要

#    その時刻までbarなし = 0

# 4. stateはログ生成後、最後に保存

# 5. 保有銘柄データ不足時はLastProcessedを進めない

# 6. 保存済snapshotを使ったcatch-up対応

#

# ------------------------------------------------------------

# CRITICAL

# ------------------------------------------------------------

#

# ・12:40打ち切りなし

# ・resultでも新規ENTRY可能

# ・LastProcessedDatetime以前は再処理しない

# ・同一Side最大1position

# ・EXITと同時刻ENTRYは禁止

# ・1日複数回可能

# ・売買ルールはV4から変更しない

#

# ※ Stage6 strategy shadow。

# ※ 1557再投資・金利等を含む完全FIX11 broker layerではない。

#

# ============================================================

import os

import io

import json

import math

import time

import traceback

from datetime import datetime, timedelta, timezone

import numpy as np

import pandas as pd

import yfinance as yf

from flask import Flask, request, Response

from google.cloud import storage

# ============================================================

# SETTINGS

# ============================================================

JST = timezone(timedelta(hours=9))

INITIAL_CAPITAL = 1_117_792.0

LONG_LEVERAGE = 1.0

SHORT_LEVERAGE = 0.5

LOT_SIZE = 100

TURNOVER_MIN_OKU = 3.0

RVOL_MIN = 2.0

LONG_RS_MIN = 80.0

SHORT_RS_MAX = 20.0

LONG_SL = 0.025

LONG_TRIGGER = 0.025

LONG_TRAIL_WIDTH = 0.010

LONG_MAX_TRADING_DAYS = 10

SHORT_SL = 0.015

SHORT_TRIGGER = 0.020

SHORT_TRAIL_WIDTH = 0.020

FILTER_ATR_MIN = 7.0

FILTER_RVOL_MIN = 2.5

FILTER_RS_MAX = 5.0

ORB_START = "09:00"

ORB_END = "09:14"

SIGNAL_START = "09:15"

MORNING_LAST_BAR = "11:30"

FULL_DAY_LAST_BAR = "15:25"

GCS_BUCKET = os.environ.get(

    "GCS_BUCKET",

    "stock-auto-trader-506100-paper"

)

GCS_PREFIX = os.environ.get(

    "FIX11_DATA_DIR",

    "fix11_forward"

).strip("/")

UNIVERSE_PATH = "data/universe.csv"

DAILY_BATCH_SIZE = 150

MINUTE_BATCH_SIZE = 80

REQUEST_SLEEP = 0.15

# ============================================================

# FLASK

# ============================================================

app = Flask(__name__)

# ============================================================

# BASIC

# ============================================================

def now_jst():

    return datetime.now(JST)

def fmt_dt(x):

    if x is None or pd.isna(x):

        return None

    x = pd.Timestamp(x)

    if x.tzinfo is not None:

        x = (

            x

            .tz_convert("Asia/Tokyo")

            .tz_localize(None)

        )

    return x.strftime("%Y-%m-%d %H:%M:%S")

def parse_dt(x):

    if x in [None, "", "None"]:

        return None

    return pd.Timestamp(x)

def normalize_code(x):

    x = str(x).strip()

    if x.endswith(".0"):

        x = x[:-2]

    return x.upper()

def ticker_from_code(code):

    code = normalize_code(code)

    if len(code) == 5 and code.endswith("0"):

        return code[:-1] + ".T"

    return code + ".T"

def safe_float(x, default=np.nan):

    try:

        v = float(x)

        if np.isfinite(v):

            return v

    except Exception:

        pass

    return default

def chunks(xs, n):

    for i in range(0, len(xs), n):

        yield xs[i:i+n]

def empty_minute_df():

    return pd.DataFrame(

        columns=[

            "Datetime",

            "Code",

            "Open",

            "High",

            "Low",

            "Close",

            "Volume"

        ]

    )

def normalize_minute_df(df):

    if df is None or len(df) == 0:

        return empty_minute_df()

    df = df.copy()

    required = [

        "Datetime",

        "Code",

        "Open",

        "High",

        "Low",

        "Close",

        "Volume"

    ]

    missing = [

        c for c in required

        if c not in df.columns

    ]

    if missing:

        raise RuntimeError(

            f"minute columns missing: {missing}"

        )

    df["Datetime"] = pd.to_datetime(

        df["Datetime"],

        errors="coerce"

    )

    if getattr(

        df["Datetime"].dt,

        "tz",

        None

    ) is not None:

        df["Datetime"] = (

            df["Datetime"]

            .dt.tz_convert("Asia/Tokyo")

            .dt.tz_localize(None)

        )

    df["Code"] = (

        df["Code"]

        .map(normalize_code)

    )

    for c in [

        "Open",

        "High",

        "Low",

        "Close",

        "Volume"

    ]:

        df[c] = pd.to_numeric(

            df[c],

            errors="coerce"

        )

    df = df.dropna(

        subset=[

            "Datetime",

            "Code"

        ]

    )

    # all OHLC NaN placeholder除去

    df = df.dropna(

        subset=[

            "Open",

            "High",

            "Low",

            "Close"

        ],

        how="all"

    )

    if df.empty:

        return empty_minute_df()

    hhmm = (

        df["Datetime"]

        .dt.strftime("%H:%M")

    )

    df = df[

        (hhmm >= "09:00")

        & (hhmm <= "15:30")

    ]

    return (

        df

        .sort_values(

            [

                "Datetime",

                "Code"

            ]

        )

        .drop_duplicates(

            [

                "Datetime",

                "Code"

            ],

            keep="last"

        )

        .reset_index(drop=True)

    )

# ============================================================

# GCS

# ============================================================

def gcs_client():

    return storage.Client()

def bucket():

    return gcs_client().bucket(

        GCS_BUCKET

    )

def gcs_name(path):

    return (

        f"{GCS_PREFIX}/{path}"

        .replace("//", "/")

    )

def gcs_exists(path):

    return bucket().blob(

        gcs_name(path)

    ).exists()

def gcs_upload_bytes(

    path,

    data,

    content_type=None

):

    bucket().blob(

        gcs_name(path)

    ).upload_from_string(

        data,

        content_type=content_type

    )

def gcs_download_bytes(path):

    b = bucket().blob(

        gcs_name(path)

    )

    if not b.exists():

        return None

    return b.download_as_bytes()

def gcs_upload_json(

    path,

    obj

):

    raw = json.dumps(

        obj,

        ensure_ascii=False,

        indent=2,

        default=str

    ).encode("utf-8")

    gcs_upload_bytes(

        path,

        raw,

        "application/json"

    )

def gcs_download_json(path):

    raw = gcs_download_bytes(

        path

    )

    if raw is None:

        return None

    return json.loads(

        raw.decode("utf-8")

    )

def gcs_upload_df_parquet(

    path,

    df

):

    bio = io.BytesIO()

    df.to_parquet(

        bio,

        index=False

    )

    gcs_upload_bytes(

        path,

        bio.getvalue(),

        "application/octet-stream"

    )

def gcs_download_df_parquet(path):

    raw = gcs_download_bytes(

        path

    )

    if raw is None:

        return None

    return pd.read_parquet(

        io.BytesIO(raw)

    )

def gcs_upload_df_csv(

    path,

    df

):

    raw = (

        df

        .to_csv(index=False)

        .encode("utf-8")

    )

    gcs_upload_bytes(

        path,

        raw,

        "text/csv"

    )

def list_snapshot_dates(

    before_date=None

):

    prefix = gcs_name(

        "snapshots/"

    )

    blobs = gcs_client().list_blobs(

        GCS_BUCKET,

        prefix=prefix

    )

    out = []

    for b in blobs:

        name = (

            b.name

            .split("/")[-1]

        )

        if not name.endswith(

            ".parquet"

        ):

            continue

        try:

            d = pd.Timestamp(

                name[:-8]

            ).date()

        except Exception:

            continue

        if (

            before_date is not None

            and d >= before_date

        ):

            continue

        out.append(d)

    return sorted(

        set(out)

    )

# ============================================================

# UNIVERSE

# ============================================================

def load_universe():

    if not os.path.exists(

        UNIVERSE_PATH

    ):

        raise RuntimeError(

            f"{UNIVERSE_PATH} がありません"

        )

    df = pd.read_csv(

        UNIVERSE_PATH,

        dtype={

            "Code": str

        }

    )

    if not {

        "Code",

        "is_lending"

    }.issubset(

        df.columns

    ):

        raise RuntimeError(

            "universe.csv に Code,is_lending が必要"

        )

    df["Code"] = (

        df["Code"]

        .map(normalize_code)

    )

    df["is_lending"] = (

        df["is_lending"]

        .astype(str)

        .str.strip()

        .str.lower()

        .isin(

            [

                "true",

                "1",

                "yes"

            ]

        )

    )

    df = (

        df[

            [

                "Code",

                "is_lending"

            ]

        ]

        .drop_duplicates("Code")

        .reset_index(drop=True)

    )

    if len(df) != 4208:

        raise RuntimeError(

            f"Universe != 4208: {len(df)}"

        )

    return df

# ============================================================

# YAHOO HELPERS

# ============================================================

def normalize_yf_index(df):

    if df is None or len(df) == 0:

        return df

    df = df.copy()

    idx = pd.to_datetime(

        df.index

    )

    if idx.tz is not None:

        idx = (

            idx

            .tz_convert(

                "Asia/Tokyo"

            )

            .tz_localize(None)

        )

    df.index = idx

    return df

def extract_ticker_frame(

    raw,

    ticker,

    batch_count

):

    if (

        raw is None

        or len(raw) == 0

    ):

        return None

    if isinstance(

        raw.columns,

        pd.MultiIndex

    ):

        level0 = (

            raw.columns

            .get_level_values(0)

        )

        if ticker in level0:

            x = raw[ticker].copy()

        else:

            level1 = (

                raw.columns

                .get_level_values(1)

            )

            if ticker not in level1:

                return None

            x = raw.xs(

                ticker,

                axis=1,

                level=1

            ).copy()

    else:

        if batch_count != 1:

            return None

        x = raw.copy()

    return normalize_yf_index(

        x

    )

# ============================================================

# DAILY FEATURES

# ============================================================

def daily_cache_path(today):

    return (

        "daily_features/"

        f"{today}.parquet"

    )

def load_daily_cache(

    universe,

    today

):

    path = daily_cache_path(

        today

    )

    if not gcs_exists(path):

        return None

    try:

        feat = gcs_download_df_parquet(

            path

        )

        if feat is None or feat.empty:

            return None

        required = {

            "Code",

            "Return20_prev",

            "turnover_median_20d_oku",

            "ATR14_pct_prev",

            "RS20_corrected",

            "is_lending"

        }

        if not required.issubset(

            feat.columns

        ):

            return None

        feat = feat.copy()

        feat["Code"] = (

            feat["Code"]

            .map(normalize_code)

        )

        # universeとの整合だけ確認

        valid_codes = set(

            universe["Code"]

        )

        feat = feat[

            feat["Code"].isin(

                valid_codes

            )

        ].copy()

        if feat.empty:

            return None

        print(

            f"daily cache HIT: "

            f"{path} / "

            f"{len(feat)} rows",

            flush=True

        )

        return feat

    except Exception as e:

        print(

            f"daily cache invalid: {e}",

            flush=True

        )

        return None

def fetch_daily_features(

    universe,

    today

):

    cached = load_daily_cache(

        universe,

        today

    )

    if cached is not None:

        return cached

    print(

        "daily cache MISS -> Yahoo",

        flush=True

    )

    codes = universe[

        "Code"

    ].tolist()

    ticker_to_code = {

        ticker_from_code(c): c

        for c in codes

    }

    tickers = list(

        ticker_to_code.keys()

    )

    rows = []

    total_batches = math.ceil(

        len(tickers)

        / DAILY_BATCH_SIZE

    )

    for bi, batch in enumerate(

        chunks(

            tickers,

            DAILY_BATCH_SIZE

        ),

        1

    ):

        print(

            f"daily {bi}/{total_batches}",

            flush=True

        )

        try:

            raw = yf.download(

                tickers=batch,

                period="3mo",

                interval="1d",

                auto_adjust=False,

                actions=False,

                group_by="ticker",

                threads=True,

                progress=False

            )

        except Exception as e:

            print(

                f"daily error: {e}",

                flush=True

            )

            continue

        for ticker in batch:

            code = (

                ticker_to_code[

                    ticker

                ]

            )

            x = extract_ticker_frame(

                raw,

                ticker,

                len(batch)

            )

            if (

                x is None

                or len(x) == 0

            ):

                continue

            required = [

                "High",

                "Low",

                "Close",

                "Volume"

            ]

            if not all(

                c in x.columns

                for c in required

            ):

                continue

            # 今日の日足は使用しない

            x = x[

                x.index.date

                < today

            ].sort_index()

            if len(x) < 21:

                continue

            raw_close = pd.to_numeric(

                x["Close"],

                errors="coerce"

            )

            high = pd.to_numeric(

                x["High"],

                errors="coerce"

            )

            low = pd.to_numeric(

                x["Low"],

                errors="coerce"

            )

            volume = pd.to_numeric(

                x["Volume"],

                errors="coerce"

            )

            if "Adj Close" in x.columns:

                adj_close = pd.to_numeric(

                    x["Adj Close"],

                    errors="coerce"

                )

            else:

                adj_close = (

                    raw_close.copy()

                )

            factor = (

                adj_close

                / raw_close.replace(

                    0,

                    np.nan

                )

            )

            adj_high = (

                high * factor

            )

            adj_low = (

                low * factor

            )

            c_now = safe_float(

                adj_close.iloc[-1]

            )

            c20 = safe_float(

                adj_close.iloc[-21]

            )

            if (

                not np.isfinite(c_now)

                or not np.isfinite(c20)

                or c20 <= 0

            ):

                continue

            return20 = (

                c_now / c20 - 1.0

            ) * 100.0

            turnover = (

                raw_close

                * volume

                / 1e8

            )

            turnover20 = safe_float(

                turnover

                .tail(20)

                .median()

            )

            prev_close = (

                adj_close.shift(1)

            )

            tr = pd.concat(

                [

                    adj_high - adj_low,

                    (

                        adj_high

                        - prev_close

                    ).abs(),

                    (

                        adj_low

                        - prev_close

                    ).abs()

                ],

                axis=1

            ).max(axis=1)

            atr14 = (

                tr

                .rolling(

                    14,

                    min_periods=14

                )

                .mean()

            )

            atr_last = safe_float(

                atr14.iloc[-1]

            )

            atr_pct = np.nan

            if (

                np.isfinite(atr_last)

                and c_now > 0

            ):

                atr_pct = (

                    atr_last

                    / c_now

                    * 100.0

                )

            rows.append(

                {

                    "Code": code,

                    "Return20_prev":

                        return20,

                    "turnover_median_20d_oku":

                        turnover20,

                    "ATR14_pct_prev":

                        atr_pct

                }

            )

        time.sleep(

            REQUEST_SLEEP

        )

    feat = pd.DataFrame(

        rows

    )

    if feat.empty:

        raise RuntimeError(

            "DailyReady = 0"

        )

    feat[

        "RS20_corrected"

    ] = (

        feat[

            "Return20_prev"

        ]

        .rank(

            method="average",

            pct=True

        )

        * 100.0

    )

    feat = feat.merge(

        universe,

        on="Code",

        how="left",

        validate="one_to_one"

    )

    # 同じtarget dateなら

    # decision/resultで再利用

    gcs_upload_df_parquet(

        daily_cache_path(today),

        feat

    )

    print(

        f"daily cache SAVED: "

        f"{daily_cache_path(today)}",

        flush=True

    )

    return feat

# ============================================================

# INTRADAY YAHOO

# ============================================================

def fetch_intraday_codes(codes):

    codes = list(

        dict.fromkeys(

            normalize_code(c)

            for c in codes

        )

    )

    if not codes:

        return empty_minute_df()

    ticker_to_code = {

        ticker_from_code(c): c

        for c in codes

    }

    tickers = list(

        ticker_to_code.keys()

    )

    frames = []

    total_batches = math.ceil(

        len(tickers)

        / MINUTE_BATCH_SIZE

    )

    for bi, batch in enumerate(

        chunks(

            tickers,

            MINUTE_BATCH_SIZE

        ),

        1

    ):

        print(

            f"1m {bi}/{total_batches}",

            flush=True

        )

        try:

            raw = yf.download(

                tickers=batch,

                period="1d",

                interval="1m",

                auto_adjust=False,

                actions=False,

                group_by="ticker",

                threads=True,

                prepost=False,

                progress=False

            )

        except Exception as e:

            print(

                f"1m error: {e}",

                flush=True

            )

            continue

        for ticker in batch:

            code = ticker_to_code[

                ticker

            ]

            x = extract_ticker_frame(

                raw,

                ticker,

                len(batch)

            )

            if (

                x is None

                or len(x) == 0

            ):

                continue

            required = [

                "Open",

                "High",

                "Low",

                "Close",

                "Volume"

            ]

            if not all(

                c in x.columns

                for c in required

            ):

                continue

            y = pd.DataFrame(

                {

                    "Datetime": x.index,

                    "Code": code,

                    "Open":

                        pd.to_numeric(

                            x["Open"],

                            errors="coerce"

                        ),

                    "High":

                        pd.to_numeric(

                            x["High"],

                            errors="coerce"

                        ),

                    "Low":

                        pd.to_numeric(

                            x["Low"],

                            errors="coerce"

                        ),

                    "Close":

                        pd.to_numeric(

                            x["Close"],

                            errors="coerce"

                        ),

                    "Volume":

                        pd.to_numeric(

                            x["Volume"],

                            errors="coerce"

                        )

                }

            )

            y = normalize_minute_df(

                y

            )

            if len(y):

                frames.append(y)

        time.sleep(

            REQUEST_SLEEP

        )

    if not frames:

        return empty_minute_df()

    return normalize_minute_df(

        pd.concat(

            frames,

            ignore_index=True

        )

    )

# ============================================================

# CURRENT DAY SNAPSHOT

# ============================================================

def snapshot_path(d):

    return (

        "snapshots/"

        f"{d}.parquet"

    )

def load_snapshot_date(d):

    path = snapshot_path(d)

    if not gcs_exists(path):

        return None

    x = gcs_download_df_parquet(

        path

    )

    if x is None or x.empty:

        return None

    x = normalize_minute_df(

        x

    )

    if x.empty:

        return None

    return x

def get_today_intraday(

    today,

    fetch_codes

):

    """

    当日snapshotが存在する場合は

    Yahoo再取得をしない。

    snapshotは全銘柄保存なので、

    必要銘柄だけfilterして使用。

    無い場合だけYahoo。

    """

    snap = load_snapshot_date(

        today

    )

    wanted = set(

        normalize_code(c)

        for c in fetch_codes

    )

    if snap is not None:

        print(

            f"TODAY SNAPSHOT HIT: "

            f"{snapshot_path(today)} "

            f"rows={len(snap):,} "

            f"codes={snap['Code'].nunique()}",

            flush=True

        )

        x = snap[

            snap["Code"].isin(

                wanted

            )

        ].copy()

        return (

            normalize_minute_df(x),

            "GCS_SNAPSHOT"

        )

    print(

        "TODAY SNAPSHOT MISS -> Yahoo 1m",

        flush=True

    )

    x = fetch_intraday_codes(

        sorted(wanted)

    )

    return (

        x,

        "YAHOO"

    )

# ============================================================

# SNAPSHOT HISTORY

# ============================================================

def load_previous_20_snapshots(today):

    dates = (

        list_snapshot_dates(

            before_date=today

        )[-20:]

    )

    frames = []

    for d in dates:

        print(

            f"history snapshot: {d}",

            flush=True

        )

        x = load_snapshot_date(d)

        if (

            x is None

            or x.empty

        ):

            continue

        x = x.copy()

        x["SnapshotDate"] = (

            pd.Timestamp(d)

        )

        frames.append(x)

    if not frames:

        return (

            dates,

            pd.DataFrame()

        )

    history = pd.concat(

        frames,

        ignore_index=True

    )

    history[

        "SnapshotDate"

    ] = pd.to_datetime(

        history[

            "SnapshotDate"

        ]

    )

    return (

        dates,

        history

    )

# ============================================================

# RVOL20 FAST

# ============================================================

def minute_number(series):

    return (

        series.dt.hour * 60

        + series.dt.minute

    ).to_numpy(

        dtype=np.int32

    )

def build_rvol_lookup(

    minute_today,

    history,

    history_dates

):

    """

    Formal RVOL20

    current cumulative volume through signal minute

    /

    median(

      previous 20 snapshot dates cumulative volume

      through same minute

    )

    ・exact-minute bar不要

    ・その時刻までbarなし = 0

    ・20日必要

    V4の逐次filter方式を高速化。

    """

    if (

        len(history_dates) < 20

        or history.empty

        or minute_today.empty

    ):

        return {}

    history_dates = sorted(

        history_dates

    )[-20:]

    hist = history.copy()

    hist["Code"] = (

        hist["Code"]

        .map(normalize_code)

    )

    hist["SnapshotDateOnly"] = (

        hist["SnapshotDate"]

        .dt.date

    )

    hist["MinuteNo"] = (

        hist["Datetime"]

        .dt.hour * 60

        + hist["Datetime"]

        .dt.minute

    )

    hist["Volume"] = (

        pd.to_numeric(

            hist["Volume"],

            errors="coerce"

        )

        .fillna(0.0)

    )

    # 同一Code/日付/分に複数あれば合算

    hist_min = (

        hist

        .groupby(

            [

                "Code",

                "SnapshotDateOnly",

                "MinuteNo"

            ],

            as_index=False

        )["Volume"]

        .sum()

    )

    hist_by_code = {

        code: g.copy()

        for code, g

        in hist_min.groupby(

            "Code",

            sort=False

        )

    }

    lookup = {}

    total_codes = (

        minute_today["Code"]

        .nunique()

    )

    for ci, (code, cur) in enumerate(

        minute_today.groupby(

            "Code",

            sort=False

        ),

        1

    ):

        if (

            ci == 1

            or ci % 100 == 0

            or ci == total_codes

        ):

            print(

                f"RVOL {ci}/{total_codes}",

                flush=True

            )

        hg = hist_by_code.get(

            code

        )

        if hg is None:

            continue

        available_dates = set(

            hg[

                "SnapshotDateOnly"

            ]

        )

        # このcode自身に20日必要

        if not all(

            d in available_dates

            for d in history_dates

        ):

            continue

        cur = (

            cur

            .sort_values(

                "Datetime"

            )

            .copy()

        )

        cur["Volume"] = (

            pd.to_numeric(

                cur["Volume"],

                errors="coerce"

            )

            .fillna(0.0)

        )

        cur["CumVolume"] = (

            cur["Volume"]

            .cumsum()

        )

        cur_minutes = (

            cur["Datetime"]

            .dt.hour * 60

            + cur["Datetime"]

            .dt.minute

        ).to_numpy(

            dtype=np.int32

        )

        hist_matrix = []

        for d in history_dates:

            day = hg[

                hg[

                    "SnapshotDateOnly"

                ] == d

            ].sort_values(

                "MinuteNo"

            )

            hm = (

                day["MinuteNo"]

                .to_numpy(

                    dtype=np.int32

                )

            )

            hv = (

                day["Volume"]

                .to_numpy(

                    dtype=float

                )

            )

            hc = np.cumsum(hv)

            # <= current minute の最後

            idx = (

                np.searchsorted(

                    hm,

                    cur_minutes,

                    side="right"

                )

                - 1

            )

            vals = np.zeros(

                len(cur_minutes),

                dtype=float

            )

            valid = idx >= 0

            vals[valid] = (

                hc[idx[valid]]

            )

            hist_matrix.append(

                vals

            )

        hist_matrix = np.vstack(

            hist_matrix

        )

        med = np.median(

            hist_matrix,

            axis=0

        )

        cur_cum = (

            cur["CumVolume"]

            .to_numpy(

                dtype=float

            )

        )

        rvol = np.full(

            len(cur),

            np.nan,

            dtype=float

        )

        good = (

            np.isfinite(med)

            & (med > 0)

        )

        rvol[good] = (

            cur_cum[good]

            / med[good]

        )

        dts = (

            cur["Datetime"]

            .tolist()

        )

        for dt, rv in zip(

            dts,

            rvol

        ):

            if np.isfinite(rv):

                lookup[

                    (

                        code,

                        pd.Timestamp(dt)

                    )

                ] = float(rv)

    print(

        f"RVOL lookup: "

        f"{len(lookup):,}",

        flush=True

    )

    return lookup

# ============================================================

# SIGNAL ENGINE - METHOD B

# ============================================================

def build_signal_candidates(

    feature_df,

    minute_df,

    rvol_lookup,

    last_bar

):

    if minute_df.empty:

        return pd.DataFrame()

    feat_map = (

        feature_df

        .set_index("Code")

        .to_dict("index")

    )

    rows = []

    for code, g in minute_df.groupby(

        "Code"

    ):

        f = feat_map.get(

            code

        )

        if f is None:

            continue

        rs = safe_float(

            f.get(

                "RS20_corrected"

            )

        )

        turnover = safe_float(

            f.get(

                "turnover_median_20d_oku"

            )

        )

        atr = safe_float(

            f.get(

                "ATR14_pct_prev"

            )

        )

        lending = bool(

            f.get(

                "is_lending",

                False

            )

        )

        if (

            not np.isfinite(rs)

            or not np.isfinite(atr)

            or not np.isfinite(turnover)

            or turnover

            < TURNOVER_MIN_OKU

        ):

            continue

        if rs >= LONG_RS_MIN:

            side = "LONG"

        elif (

            rs <= SHORT_RS_MAX

            and lending

        ):

            side = "SHORT"

        else:

            continue

        g = (

            g

            .sort_values(

                "Datetime"

            )

            .reset_index(

                drop=True

            )

        )

        hhmm = (

            g["Datetime"]

            .dt.strftime("%H:%M")

        )

        orb = g[

            (hhmm >= ORB_START)

            & (hhmm <= ORB_END)

        ]

        if orb.empty:

            continue

        orb_high = safe_float(

            orb["High"].max()

        )

        orb_low = safe_float(

            orb["Low"].min()

        )

        if (

            not np.isfinite(orb_high)

            or not np.isfinite(orb_low)

        ):

            continue

        prev_close = (

            g["Close"]

            .shift(1)

        )

        found = None

        for i, r in g.iterrows():

            dt = pd.Timestamp(

                r["Datetime"]

            )

            minute = dt.strftime(

                "%H:%M"

            )

            if minute < SIGNAL_START:

                continue

            if minute > last_bar:

                break

            pc = safe_float(

                prev_close.iloc[i]

            )

            close = safe_float(

                r["Close"]

            )

            if (

                not np.isfinite(pc)

                or not np.isfinite(close)

            ):

                continue

            if side == "LONG":

                breakout = (

                    pc <= orb_high

                    and close > orb_high

                )

            else:

                breakout = (

                    pc >= orb_low

                    and close < orb_low

                )

            if not breakout:

                continue

            rv = rvol_lookup.get(

                (

                    code,

                    dt

                ),

                np.nan

            )

            # METHOD B:

            # RVOL不足なら後のbreakoutを探す

            if (

                not np.isfinite(rv)

                or rv < RVOL_MIN

            ):

                continue

            later = g[

                g["Datetime"] > dt

            ]

            if later.empty:

                continue

            entry_bar = (

                later.iloc[0]

            )

            entry_dt = pd.Timestamp(

                entry_bar[

                    "Datetime"

                ]

            )

            if (

                entry_dt

                .strftime("%H:%M")

                > last_bar

            ):

                continue

            entry_price = safe_float(

                entry_bar["Open"]

            )

            if (

                not np.isfinite(

                    entry_price

                )

                or entry_price <= 0

            ):

                continue

            found = {

                "Side": side,

                "Code": code,

                "SignalDatetime": dt,

                "EntryDatetime": entry_dt,

                "EntryPrice": entry_price,

                "RS20_corrected": rs,

                "RVOL20": rv,

                "turnover_median_20d_oku":

                    turnover,

                "ATR14_pct_prev":

                    atr,

                "is_lending":

                    lending,

                "ORBHigh":

                    orb_high,

                "ORBLow":

                    orb_low

            }

            break

        if found is not None:

            rows.append(

                found

            )

    if not rows:

        return pd.DataFrame()

    return (

        pd.DataFrame(rows)

        .sort_values(

            [

                "EntryDatetime",

                "Code"

            ]

        )

        .reset_index(

            drop=True

        )

    )

# ============================================================

# FILTER / RANKING

# ============================================================

def rank_group(

    df,

    side

):

    if side == "LONG":

        return df.sort_values(

            [

                "RS20_corrected",

                "RVOL20",

                "turnover_median_20d_oku",

                "Code"

            ],

            ascending=[

                False,

                False,

                False,

                True

            ]

        )

    return df.sort_values(

        [

            "RS20_corrected",

            "RVOL20",

            "turnover_median_20d_oku",

            "Code"

        ],

        ascending=[

            True,

            False,

            False,

            True

        ]

    )

def candidates_for_track(

    candidates,

    track_name

):

    if candidates.empty:

        return candidates.copy()

    if track_name == "LONG":

        return candidates[

            candidates["Side"]

            == "LONG"

        ].copy()

    x = candidates[

        candidates["Side"]

        == "SHORT"

    ].copy()

    x = x[

        x["is_lending"] == True

    ].copy()

    if track_name == "SHORT_FILTER":

        exclude = (

            (

                x[

                    "ATR14_pct_prev"

                ]

                >= FILTER_ATR_MIN

            )

            &

            (

                x["RVOL20"]

                >= FILTER_RVOL_MIN

            )

            &

            (

                x[

                    "RS20_corrected"

                ]

                <= FILTER_RS_MAX

            )

        )

        x = x[

            ~exclude

        ].copy()

    return x

# ============================================================

# STATE

# ============================================================

def new_track():

    return {

        "Equity":

            INITIAL_CAPITAL,

        "Position":

            None,

        "LastExitDatetime":

            None,

        "LastProcessedDatetime":

            None,

        "Trades":

            0,

        "Wins":

            0,

        "RealizedPnL":

            0.0

    }

def new_state():

    return {

        "version":

            "FIX11_STAGE6_FORWARD_V4",

        "created_at":

            fmt_dt(now_jst()),

        "LONG":

            new_track(),

        "SHORT_BASE":

            new_track(),

        "SHORT_FILTER":

            new_track()

    }

def load_state():

    state = gcs_download_json(

        "portfolio.json"

    )

    if state is None:

        return new_state()

    for name in [

        "LONG",

        "SHORT_BASE",

        "SHORT_FILTER"

    ]:

        if name not in state:

            state[name] = (

                new_track()

            )

    state["version"] = (

        "FIX11_STAGE6_FORWARD_V4"

    )

    return state

def save_state(state):

    state["updated_at"] = (

        fmt_dt(now_jst())

    )

    gcs_upload_json(

        "portfolio.json",

        state

    )

def current_position_codes(

    state

):

    codes = []

    for name in [

        "LONG",

        "SHORT_BASE",

        "SHORT_FILTER"

    ]:

        p = (

            state[name]

            .get("Position")

        )

        if p is not None:

            code = normalize_code(

                p["Code"]

            )

            if code not in codes:

                codes.append(code)

    return codes

# ============================================================

# POSITION

# ============================================================

def side_for_track(

    track_name

):

    if track_name == "LONG":

        return "LONG"

    return "SHORT"

def leverage_for_track(

    track_name

):

    if track_name == "LONG":

        return LONG_LEVERAGE

    return SHORT_LEVERAGE

def initial_stop(

    side,

    entry

):

    if side == "LONG":

        return (

            entry

            * (1.0 - LONG_SL)

        )

    return (

        entry

        * (1.0 + SHORT_SL)

    )

def open_position(

    track,

    track_name,

    candidate,

    minute_df,

    activity_log

):

    side = side_for_track(

        track_name

    )

    entry = safe_float(

        candidate["EntryPrice"]

    )

    equity = safe_float(

        track["Equity"],

        INITIAL_CAPITAL

    )

    target_notional = (

        equity

        * leverage_for_track(

            track_name

        )

    )

    qty = int(

        math.floor(

            target_notional

            / entry

            / LOT_SIZE

        )

        * LOT_SIZE

    )

    if qty < LOT_SIZE:

        return (

            False,

            "LOT_TOO_LARGE"

        )

    entry_dt = pd.Timestamp(

        candidate[

            "EntryDatetime"

        ]

    )

    fixed_stop = initial_stop(

        side,

        entry

    )

    p = {

        "Side":

            side,

        "Code":

            candidate["Code"],

        "EntryDatetime":

            fmt_dt(entry_dt),

        "EntryPrice":

            entry,

        "Qty":

            qty,

        "FixedStop":

            fixed_stop,

        "EffectiveStop":

            fixed_stop,

        "EffectiveStopType":

            "SL",

        "PendingStop":

            None,

        "PendingStopType":

            None,

        "BestPrice":

            entry,

        "EntryDate":

            entry_dt.date()

            .isoformat(),

        "LastBarDatetime":

            None,

        "RS20_corrected":

            safe_float(

                candidate[

                    "RS20_corrected"

                ]

            ),

        "RVOL20":

            safe_float(

                candidate[

                    "RVOL20"

                ]

            ),

        "ATR14_pct_prev":

            safe_float(

                candidate[

                    "ATR14_pct_prev"

                ]

            )

    }

    # ENTRY BAR

    # Exit判定禁止

    # favorable extreme更新

    # pending stopは次bar有効

    eb = minute_df[

        (

            minute_df["Code"]

            == p["Code"]

        )

        &

        (

            minute_df["Datetime"]

            == entry_dt

        )

    ]

    if len(eb):

        r = eb.iloc[0]

        if side == "LONG":

            high = safe_float(

                r["High"],

                entry

            )

            best = max(

                entry,

                high

            )

            p["BestPrice"] = best

            trigger = (

                entry

                * (

                    1.0

                    + LONG_TRIGGER

                )

            )

            if best >= trigger:

                trail = (

                    best

                    * (

                        1.0

                        - LONG_TRAIL_WIDTH

                    )

                )

                pending = max(

                    fixed_stop,

                    trail

                )

                p["PendingStop"] = (

                    pending

                )

                p[

                    "PendingStopType"

                ] = (

                    "TRAIL"

                    if pending

                    > fixed_stop

                    else "SL"

                )

        else:

            low = safe_float(

                r["Low"],

                entry

            )

            best = min(

                entry,

                low

            )

            p["BestPrice"] = best

            trigger = (

                entry

                * (

                    1.0

                    - SHORT_TRIGGER

                )

            )

            if best <= trigger:

                trail = (

                    best

                    * (

                        1.0

                        + SHORT_TRAIL_WIDTH

                    )

                )

                pending = min(

                    fixed_stop,

                    trail

                )

                p["PendingStop"] = (

                    pending

                )

                p[

                    "PendingStopType"

                ] = (

                    "TRAIL"

                    if pending

                    < fixed_stop

                    else "SL"

                )

        p[

            "LastBarDatetime"

        ] = fmt_dt(

            entry_dt

        )

    track["Position"] = p

    activity_log.append(

        {

            "Type":

                "ENTRY",

            "Track":

                track_name,

            "Side":

                side,

            "Code":

                p["Code"],

            "Datetime":

                fmt_dt(entry_dt),

            "Price":

                entry,

            "Qty":

                qty,

            "RS20_corrected":

                p[

                    "RS20_corrected"

                ],

            "RVOL20":

                p["RVOL20"],

            "ATR14_pct_prev":

                p[

                    "ATR14_pct_prev"

                ]

        }

    )

    return (

        True,

        None

    )

# ============================================================

# EXIT

# ============================================================

def formal_return(

    side,

    entry,

    exit_price

):

    if side == "LONG":

        return (

            exit_price

            / entry

            - 1.0

        )

    return (

        entry

        / exit_price

        - 1.0

    )

def close_position(

    track,

    track_name,

    exit_dt,

    exit_price,

    reason,

    trade_log,

    activity_log

):

    p = track[

        "Position"

    ]

    side = p["Side"]

    entry = safe_float(

        p["EntryPrice"]

    )

    qty = int(

        p["Qty"]

    )

    ret = formal_return(

        side,

        entry,

        exit_price

    )

    if side == "LONG":

        pnl = (

            exit_price

            - entry

        ) * qty

    else:

        pnl = (

            entry

            - exit_price

        ) * qty

    track["Equity"] = (

        safe_float(

            track["Equity"]

        )

        + pnl

    )

    track["RealizedPnL"] = (

        safe_float(

            track.get(

                "RealizedPnL",

                0.0

            ),

            0.0

        )

        + pnl

    )

    track["Trades"] = (

        int(

            track.get(

                "Trades",

                0

            )

        )

        + 1

    )

    if pnl > 0:

        track["Wins"] = (

            int(

                track.get(

                    "Wins",

                    0

                )

            )

            + 1

        )

    row = {

        "Track":

            track_name,

        "Side":

            side,

        "Code":

            p["Code"],

        "EntryDatetime":

            p[

                "EntryDatetime"

            ],

        "EntryPrice":

            entry,

        "Qty":

            qty,

        "ExitDatetime":

            fmt_dt(exit_dt),

        "ExitPrice":

            exit_price,

        "ReturnPct":

            ret * 100.0,

        "PnL":

            pnl,

        "ExitReason":

            reason,

        "EquityAfter":

            track["Equity"]

    }

    trade_log.append(

        row

    )

    activity_log.append(

        {

            "Type":

                "EXIT",

            "Track":

                track_name,

            "Side":

                side,

            "Code":

                p["Code"],

            "Datetime":

                fmt_dt(exit_dt),

            "Price":

                exit_price,

            "Qty":

                qty,

            "ReturnPct":

                ret * 100.0,

            "PnL":

                pnl,

            "ExitReason":

                reason

        }

    )

    track[

        "LastExitDatetime"

    ] = fmt_dt(

        exit_dt

    )

    track["Position"] = None

def evaluate_open_position(

    track,

    track_name,

    minute_df,

    trading_dates,

    until_dt,

    trade_log,

    activity_log,

    allow_forced_close

):

    p = track.get(

        "Position"

    )

    if p is None:

        return True

    code = normalize_code(

        p["Code"]

    )

    side = p["Side"]

    entry = safe_float(

        p["EntryPrice"]

    )

    last_bar = parse_dt(

        p.get(

            "LastBarDatetime"

        )

    )

    x = minute_df[

        minute_df["Code"]

        == code

    ].copy()

    # 重要:

    # 保有銘柄の1分足が無いなら

    # 「処理済み」にしない

    if x.empty:

        print(

            f"WARNING {track_name}: "

            f"{code} minute data missing",

            flush=True

        )

        return False

    x = x[

        x["Datetime"]

        <= until_dt

    ]

    if last_bar is not None:

        x = x[

            x["Datetime"]

            > last_bar

        ]

    x = x.sort_values(

        "Datetime"

    )

    # last_bar以降に新しいbarが無くても

    # 既にuntil_dt以上まで取得済みか確認

    code_max = (

        minute_df[

            minute_df["Code"]

            == code

        ]["Datetime"]

        .max()

    )

    sufficient_coverage = (

        pd.notna(code_max)

        and pd.Timestamp(code_max)

        >= until_dt.floor("min")

    )

    for _, r in x.iterrows():

        dt = pd.Timestamp(

            r["Datetime"]

        )

        pending = p.get(

            "PendingStop"

        )

        if pending is not None:

            p["EffectiveStop"] = (

                safe_float(

                    pending

                )

            )

            p[

                "EffectiveStopType"

            ] = (

                p.get(

                    "PendingStopType"

                )

                or "TRAIL"

            )

            p["PendingStop"] = None

            p["PendingStopType"] = None

        stop = safe_float(

            p[

                "EffectiveStop"

            ]

        )

        stop_type = (

            p.get(

                "EffectiveStopType"

            )

            or "SL"

        )

        o = safe_float(

            r["Open"]

        )

        h = safe_float(

            r["High"]

        )

        l = safe_float(

            r["Low"]

        )

        # EXIT

        if side == "LONG":

            if (

                np.isfinite(o)

                and o <= stop

            ):

                close_position(

                    track,

                    track_name,

                    dt,

                    o,

                    f"{stop_type}_GAP",

                    trade_log,

                    activity_log

                )

                return True

            if (

                np.isfinite(l)

                and l <= stop

            ):

                close_position(

                    track,

                    track_name,

                    dt,

                    stop,

                    stop_type,

                    trade_log,

                    activity_log

                )

                return True

        else:

            if (

                np.isfinite(o)

                and o >= stop

            ):

                close_position(

                    track,

                    track_name,

                    dt,

                    o,

                    f"{stop_type}_GAP",

                    trade_log,

                    activity_log

                )

                return True

            if (

                np.isfinite(h)

                and h >= stop

            ):

                close_position(

                    track,

                    track_name,

                    dt,

                    stop,

                    stop_type,

                    trade_log,

                    activity_log

                )

                return True

        # favorable extreme

        if side == "LONG":

            best = max(

                safe_float(

                    p[

                        "BestPrice"

                    ],

                    entry

                ),

                h

            )

            p["BestPrice"] = (

                best

            )

            trigger = (

                entry

                * (

                    1.0

                    + LONG_TRIGGER

                )

            )

            if best >= trigger:

                trail = (

                    best

                    * (

                        1.0

                        - LONG_TRAIL_WIDTH

                    )

                )

                new_stop = max(

                    safe_float(

                        p[

                            "FixedStop"

                        ]

                    ),

                    trail

                )

                effective = (

                    safe_float(

                        p[

                            "EffectiveStop"

                        ]

                    )

                )

                pending_now = (

                    p.get(

                        "PendingStop"

                    )

                )

                pending_value = (

                    safe_float(

                        pending_now,

                        -np.inf

                    )

                    if pending_now

                    is not None

                    else -np.inf

                )

                if (

                    new_stop

                    > effective

                    and new_stop

                    > pending_value

                ):

                    p[

                        "PendingStop"

                    ] = new_stop

                    p[

                        "PendingStopType"

                    ] = (

                        "TRAIL"

                        if new_stop

                        > safe_float(

                            p[

                                "FixedStop"

                            ]

                        )

                        else "SL"

                    )

        else:

            best = min(

                safe_float(

                    p[

                        "BestPrice"

                    ],

                    entry

                ),

                l

            )

            p["BestPrice"] = (

                best

            )

            trigger = (

                entry

                * (

                    1.0

                    - SHORT_TRIGGER

                )

            )

            if best <= trigger:

                trail = (

                    best

                    * (

                        1.0

                        + SHORT_TRAIL_WIDTH

                    )

                )

                new_stop = min(

                    safe_float(

                        p[

                            "FixedStop"

                        ]

                    ),

                    trail

                )

                effective = (

                    safe_float(

                        p[

                            "EffectiveStop"

                        ]

                    )

                )

                pending_now = (

                    p.get(

                        "PendingStop"

                    )

                )

                pending_value = (

                    safe_float(

                        pending_now,

                        np.inf

                    )

                    if pending_now

                    is not None

                    else np.inf

                )

                if (

                    new_stop

                    < effective

                    and new_stop

                    < pending_value

                ):

                    p[

                        "PendingStop"

                    ] = new_stop

                    p[

                        "PendingStopType"

                    ] = (

                        "TRAIL"

                        if new_stop

                        < safe_float(

                            p[

                                "FixedStop"

                            ]

                        )

                        else "SL"

                    )

        p[

            "LastBarDatetime"

        ] = fmt_dt(

            dt

        )

    # LONG 10 trading days

    if (

        track.get(

            "Position"

        )

        is not None

        and side == "LONG"

        and allow_forced_close

    ):

        entry_date = (

            pd.Timestamp(

                p["EntryDate"]

            ).date()

        )

        dates = sorted(

            set(

                trading_dates

            )

        )

        if entry_date in dates:

            i = dates.index(

                entry_date

            )

            deadline_i = (

                i

                + LONG_MAX_TRADING_DAYS

                - 1

            )

            if deadline_i < len(

                dates

            ):

                deadline = dates[

                    deadline_i

                ]

                if (

                    until_dt.date()

                    >= deadline

                ):

                    z = minute_df[

                        (

                            minute_df["Code"]

                            == code

                        )

                        &

                        (

                            minute_df[

                                "Datetime"

                            ]

                            .dt.date

                            == deadline

                        )

                    ].sort_values(

                        "Datetime"

                    )

                    if len(z):

                        last = (

                            z.iloc[-1]

                        )

                        close_position(

                            track,

                            track_name,

                            pd.Timestamp(

                                last[

                                    "Datetime"

                                ]

                            ),

                            safe_float(

                                last[

                                    "Close"

                                ]

                            ),

                            "FORCED_10D",

                            trade_log,

                            activity_log

                        )

                        return True

    return sufficient_coverage

# ============================================================

# FORMAL MULTI REPLAY

# ============================================================

def replay_formal_track(

    state,

    track_name,

    candidates,

    minute_df,

    trading_dates,

    until_dt,

    trade_log,

    activity_log,

    allow_forced_close

):

    track = state[

        track_name

    ]

    c = candidates_for_track(

        candidates,

        track_name

    )

    last_processed = parse_dt(

        track.get(

            "LastProcessedDatetime"

        )

    )

    if not c.empty:

        c = c[

            c[

                "EntryDatetime"

            ] <= until_dt

        ].copy()

        if last_processed is not None:

            c = c[

                c[

                    "EntryDatetime"

                ]

                > last_processed

            ].copy()

        c = c.sort_values(

            "EntryDatetime"

        )

    coverage_ok = True

    if not c.empty:

        for entry_dt, group in c.groupby(

            "EntryDatetime",

            sort=True

        ):

            entry_dt = pd.Timestamp(

                entry_dt

            )

            ok = evaluate_open_position(

                track,

                track_name,

                minute_df,

                trading_dates,

                entry_dt,

                trade_log,

                activity_log,

                False

            )

            if not ok:

                coverage_ok = False

                break

            if (

                track.get(

                    "Position"

                )

                is not None

            ):

                continue

            last_exit = parse_dt(

                track.get(

                    "LastExitDatetime"

                )

            )

            if (

                last_exit is not None

                and entry_dt

                <= last_exit

            ):

                continue

            ranked = rank_group(

                group,

                side_for_track(

                    track_name

                )

            )

            if ranked.empty:

                continue

            winner = (

                ranked.iloc[0]

            )

            ok_entry, reason = (

                open_position(

                    track,

                    track_name,

                    winner,

                    minute_df,

                    activity_log

                )

            )

            if not ok_entry:

                print(

                    f"{track_name} "

                    f"{winner['Code']} "

                    f"SKIP {reason}",

                    flush=True

                )

    if coverage_ok:

        coverage_ok = (

            evaluate_open_position(

                track,

                track_name,

                minute_df,

                trading_dates,

                until_dt,

                trade_log,

                activity_log,

                allow_forced_close

            )

        )

    # FLATの場合はminute data欠落問題なし。

    # OPENの場合のみcoverage確認が必要。

    if (

        track.get("Position")

        is None

    ):

        coverage_ok = True

    if coverage_ok:

        track[

            "LastProcessedDatetime"

        ] = fmt_dt(

            until_dt

        )

    else:

        print(

            f"WARNING: "

            f"{track_name} "

            f"LastProcessedDatetime "

            f"NOT advanced",

            flush=True

        )

    return coverage_ok

# ============================================================

# LOG HELPERS

# ============================================================

def build_appended_csv(

    path,

    new_rows,

    dedupe_subset

):

    raw = gcs_download_bytes(

        path

    )

    if raw is None:

        old = pd.DataFrame()

    else:

        old = pd.read_csv(

            io.BytesIO(raw)

        )

    if not new_rows:

        return old

    new = pd.DataFrame(

        new_rows

    )

    z = pd.concat(

        [

            old,

            new

        ],

        ignore_index=True

    )

    subset = [

        c

        for c in dedupe_subset

        if c in z.columns

    ]

    if subset:

        z = z.drop_duplicates(

            subset=subset,

            keep="last"

        )

    return z

def prepare_trade_log(

    new_rows

):

    return build_appended_csv(

        "trades.csv",

        new_rows,

        [

            "Track",

            "Code",

            "EntryDatetime",

            "ExitDatetime"

        ]

    )

def prepare_activity_log(

    new_rows

):

    return build_appended_csv(

        "activity.csv",

        new_rows,

        [

            "Type",

            "Track",

            "Code",

            "Datetime"

        ]

    )

def prepare_screening_log(

    mode,

    feat,

    candidates

):

    if candidates.empty:

        long_n = 0

        short_n = 0

    else:

        long_n = int(

            (

                candidates["Side"]

                == "LONG"

            ).sum()

        )

        short_n = int(

            (

                candidates["Side"]

                == "SHORT"

            ).sum()

        )

    row = {

        "Timestamp":

            fmt_dt(now_jst()),

        "Mode":

            mode,

        "DailyReady":

            len(feat),

        "LONGCandidates":

            long_n,

        "SHORTCandidates":

            short_n

    }

    raw = gcs_download_bytes(

        "screening_history.csv"

    )

    if raw is None:

        old = pd.DataFrame()

    else:

        old = pd.read_csv(

            io.BytesIO(raw)

        )

    return pd.concat(

        [

            old,

            pd.DataFrame(

                [row]

            )

        ],

        ignore_index=True

    )

# ============================================================

# REPORT

# ============================================================

def track_report(

    name,

    track

):

    p = track.get(

        "Position"

    )

    if p is None:

        pos = "FLAT"

    else:

        pos = (

            f"{p['Code']} "

            f"{p['Side']} "

            f"{p['Qty']}株 "

            f"@{p['EntryPrice']:.2f}"

        )

    trades = int(

        track.get(

            "Trades",

            0

        )

    )

    wins = int(

        track.get(

            "Wins",

            0

        )

    )

    winrate = (

        wins / trades * 100.0

        if trades

        else 0.0

    )

    return (

        f"{name}\n"

        f"  Equity      : "

        f"{safe_float(track['Equity']):,.0f}\n"

        f"  RealizedPnL : "

        f"{safe_float(track.get('RealizedPnL',0)):,.0f}\n"

        f"  Trades      : {trades}\n"

        f"  WinRate     : {winrate:.1f}%\n"

        f"  LastProcess : "

        f"{track.get('LastProcessedDatetime')}\n"

        f"  Position    : {pos}"

    )

def build_report(

    mode,

    universe,

    feat,

    minute_df,

    minute_source,

    history_dates,

    candidates,

    state,

    activity_log

):

    if mode == "decision":

        title = (

            "FIX11 Stage6 Forward V4.1 "

            "- 前場報告"

        )

        period_text = (

            "09:15 ～ 前場終了"

        )

    else:

        title = (

            "FIX11 Stage6 Forward V4.1 "

            "- 後場 + 1日報告"

        )

        period_text = (

            "終日 ～ 15:25"

        )

    lines = [

        title,

        f"MODE: {mode}",

        f"TIME: {fmt_dt(now_jst())}",

        f"PERIOD: {period_text}",

        "",

        f"Universe    : {len(universe)}",

        f"Lending     : "

        f"{int(universe['is_lending'].sum())}",

        f"DailyReady  : {len(feat)}",

        f"1m rows     : "

        f"{len(minute_df):,}",

        f"1m source   : "

        f"{minute_source}",

        f"RVOL history: "

        f"{len(history_dates)}/20"

    ]

    if len(history_dates) < 20:

        lines.append(

            "RVOL20 STATUS: NOT READY"

        )

    lines.append("")

    if candidates.empty:

        long_n = 0

        short_n = 0

        filter_n = 0

    else:

        long_n = int(

            (

                candidates["Side"]

                == "LONG"

            ).sum()

        )

        short_n = int(

            (

                candidates["Side"]

                == "SHORT"

            ).sum()

        )

        filter_n = len(

            candidates_for_track(

                candidates,

                "SHORT_FILTER"

            )

        )

    lines.extend(

        [

            f"Candidates LONG        : "

            f"{long_n}",

            f"Candidates SHORT BASE  : "

            f"{short_n}",

            f"Candidates SHORT FILTER: "

            f"{filter_n}",

            ""

        ]

    )

    entries = [

        x

        for x in activity_log

        if x.get("Type")

        == "ENTRY"

    ]

    exits = [

        x

        for x in activity_log

        if x.get("Type")

        == "EXIT"

    ]

    lines.append(

        f"New entries: "

        f"{len(entries)}"

    )

    for x in entries[-20:]:

        lines.append(

            f"  {x['Track']} "

            f"{x['Code']} "

            f"{x['Datetime']} "

            f"{x['Qty']}株 "

            f"@{x['Price']:.2f}"

        )

    lines.append("")

    lines.append(

        f"New exits: "

        f"{len(exits)}"

    )

    for x in exits[-20:]:

        lines.append(

            f"  {x['Track']} "

            f"{x['Code']} "

            f"{x['Datetime']} "

            f"{x['ReturnPct']:+.2f}% "

            f"{x['ExitReason']}"

        )

    lines.extend(

        [

            "",

            track_report(

                "LONG",

                state["LONG"]

            ),

            "",

            track_report(

                "SHORT_BASE",

                state[

                    "SHORT_BASE"

                ]

            ),

            "",

            track_report(

                "SHORT_FILTER",

                state[

                    "SHORT_FILTER"

                ]

            )

        ]

    )

    return "\n".join(

        lines

    )

# ============================================================

# MAIN

# ============================================================

def run(mode):

    mode = str(

        mode

    ).strip().lower()

    if mode not in {

        "test",

        "snapshot",

        "decision",

        "result"

    }:

        raise RuntimeError(

            f"Unknown mode: {mode}"

        )

    start = time.time()

    now = now_jst()

    today = now.date()

    universe = load_universe()

    # --------------------------------------------------------

    # TEST

    # --------------------------------------------------------

    if mode == "test":

        state = load_state()

        return (

            "FIX11 Stage6 Forward V4.1 TEST PASS\n"

            f"Universe : {len(universe)}\n"

            f"Lending  : "

            f"{int(universe['is_lending'].sum())}\n"

            f"NonLend  : "

            f"{int((~universe['is_lending']).sum())}\n"

            f"StateVer : "

            f"{state.get('version')}\n"

            f"Elapsed  : "

            f"{time.time()-start:.1f}s"

        )

    # --------------------------------------------------------

    # SNAPSHOT

    # --------------------------------------------------------

    if mode == "snapshot":

        path = snapshot_path(

            today

        )

        # 既に保存済みなら上書きしない

        existing = load_snapshot_date(

            today

        )

        if existing is not None:

            return (

                "FIX11 Stage6 SNAPSHOT EXISTS\n"

                f"Date     : {today}\n"

                f"Universe : {len(universe)}\n"

                f"Rows     : "

                f"{len(existing):,}\n"

                f"Codes    : "

                f"{existing['Code'].nunique()}\n"

                f"Path     : "

                f"{GCS_PREFIX}/{path}\n"

                f"Elapsed  : "

                f"{time.time()-start:.1f}s"

            )

        minute_df = fetch_intraday_codes(

            universe[

                "Code"

            ].tolist()

        )

        if minute_df.empty:

            raise RuntimeError(

                "snapshot rows = 0"

            )

        gcs_upload_df_parquet(

            path,

            minute_df

        )

        return (

            "FIX11 Stage6 SNAPSHOT SAVED\n"

            f"Date     : {today}\n"

            f"Universe : {len(universe)}\n"

            f"Rows     : "

            f"{len(minute_df):,}\n"

            f"Codes    : "

            f"{minute_df['Code'].nunique()}\n"

            f"Path     : "

            f"{GCS_PREFIX}/{path}\n"

            f"Elapsed  : "

            f"{time.time()-start:.1f}s"

        )

    # --------------------------------------------------------

    # DECISION / RESULT

    # --------------------------------------------------------

    state = load_state()

    # 前日までの日足

    feat = fetch_daily_features(

        universe,

        today

    )

    # Formal daily prefilter

    pre = feat[

        (

            feat[

                "turnover_median_20d_oku"

            ]

            >= TURNOVER_MIN_OKU

        )

        &

        (

            (

                feat[

                    "RS20_corrected"

                ]

                >= LONG_RS_MIN

            )

            |

            (

                (

                    feat[

                        "RS20_corrected"

                    ]

                    <= SHORT_RS_MAX

                )

                &

                (

                    feat[

                        "is_lending"

                    ]

                    == True

                )

            )

        )

    ].copy()

    fetch_codes = set(

        pre["Code"].tolist()

    )

    # 保有銘柄は必ず対象

    for code in current_position_codes(

        state

    ):

        fetch_codes.add(code)

    minute_df, minute_source = (

        get_today_intraday(

            today,

            fetch_codes

        )

    )

    if minute_df.empty:

        raise RuntimeError(

            "minute_df = 0"

        )

    # --------------------------------------------------------

    # MODE CAP

    # --------------------------------------------------------

    if mode == "decision":

        cap = pd.Timestamp(

            f"{today} "

            f"{MORNING_LAST_BAR}:59"

        )

    else:

        cap = pd.Timestamp(

            f"{today} "

            f"{FULL_DAY_LAST_BAR}:59"

        )

    available_until = pd.Timestamp(

        minute_df[

            "Datetime"

        ].max()

    )

    until_dt = min(

        available_until,

        cap

    )

    print(

        f"minute source={minute_source}",

        flush=True

    )

    print(

        f"available_until="

        f"{available_until}",

        flush=True

    )

    print(

        f"until_dt={until_dt}",

        flush=True

    )

    # --------------------------------------------------------

    # Trading dates

    # --------------------------------------------------------

    trading_dates = (

        list_snapshot_dates()

    )

    if today not in trading_dates:

        trading_dates.append(

            today

        )

    trading_dates = sorted(

        set(trading_dates)

    )

    # --------------------------------------------------------

    # RVOL HISTORY

    # --------------------------------------------------------

    history_dates, history = (

        load_previous_20_snapshots(

            today

        )

    )

    if (

        len(history_dates) >= 20

        and not history.empty

    ):

        rvol_lookup = (

            build_rvol_lookup(

                minute_df,

                history,

                history_dates

            )

        )

    else:

        rvol_lookup = {}

    # --------------------------------------------------------

    # CANDIDATES

    # --------------------------------------------------------

    if len(history_dates) < 20:

        candidates = (

            pd.DataFrame()

        )

    else:

        last_bar = (

            MORNING_LAST_BAR

            if mode == "decision"

            else FULL_DAY_LAST_BAR

        )

        candidates = (

            build_signal_candidates(

                feat,

                minute_df,

                rvol_lookup,

                last_bar

            )

        )

    new_trades = []

    activity_log = []

    # --------------------------------------------------------

    # FORMAL MULTI REPLAY

    # --------------------------------------------------------

    coverage = {}

    for track_name in [

        "LONG",

        "SHORT_BASE",

        "SHORT_FILTER"

    ]:

        coverage[

            track_name

        ] = replay_formal_track(

            state,

            track_name,

            candidates,

            minute_df,

            trading_dates,

            until_dt,

            new_trades,

            activity_log,

            allow_forced_close=(

                mode == "result"

            )

        )

    print(

        f"COVERAGE={coverage}",

        flush=True

    )

    # 保有銘柄欠落などがあれば

    # stateを保存せずfail closed

    if not all(

        coverage.values()

    ):

        raise RuntimeError(

            "DATA COVERAGE INCOMPLETE. "

            "portfolio.json was NOT saved."

        )

    # --------------------------------------------------------

    # REPORTをstate保存前に生成

    # --------------------------------------------------------

    report = build_report(

        mode,

        universe,

        feat,

        minute_df,

        minute_source,

        history_dates,

        candidates,

        state,

        activity_log

    )

    report += (

        f"\n\nElapsed: "

        f"{time.time()-start:.1f}s"

    )

    # --------------------------------------------------------

    # 保存用データを先にメモリ上で構築

    # --------------------------------------------------------

    trade_df = prepare_trade_log(

        new_trades

    )

    activity_df = (

        prepare_activity_log(

            activity_log

        )

    )

    screening_df = (

        prepare_screening_log(

            mode,

            feat,

            candidates

        )

    )

    # --------------------------------------------------------

    # Candidate audit

    # --------------------------------------------------------

    audit = None

    if not candidates.empty:

        audit = candidates.copy()

        audit["RunMode"] = mode

        audit[

            "RunTimestamp"

        ] = fmt_dt(now)

    # --------------------------------------------------------

    # GCS SAVE

    #

    # stateを最後にする

    # --------------------------------------------------------

    if len(trade_df):

        gcs_upload_df_csv(

            "trades.csv",

            trade_df

        )

    if len(activity_df):

        gcs_upload_df_csv(

            "activity.csv",

            activity_df

        )

    gcs_upload_df_csv(

        "screening_history.csv",

        screening_df

    )

    if audit is not None:

        gcs_upload_df_csv(

            (

                "candidate_audit/"

                f"{today}_{mode}.csv"

            ),

            audit

        )

    gcs_upload_bytes(

        "latest_result.txt",

        report.encode(

            "utf-8"

        ),

        "text/plain"

    )

    # 最後にstate

    save_state(

        state

    )

    print(

        "STATE SAVE COMPLETE",

        flush=True

    )

    return report

# ============================================================

# ROUTES

# ============================================================

@app.route(

    "/",

    methods=["GET"]

)

def health():

    return Response(

        "FIX11 Stage6 Forward V4.1 OK\n",

        status=200,

        mimetype="text/plain"

    )

@app.route(

    "/run",

    methods=[

        "GET",

        "POST"

    ]

)

def run_route():

    try:

        if request.method == "POST":

            data = (

                request.get_json(

                    silent=True

                )

                or {}

            )

            mode = data.get(

                "mode",

                request.args.get(

                    "mode",

                    "test"

                )

            )

        else:

            mode = request.args.get(

                "mode",

                "test"

            )

        text = run(

            mode

        )

        return Response(

            text + "\n",

            status=200,

            mimetype="text/plain"

        )

    except Exception:

        err = (

            traceback.format_exc()

        )

        print(

            err,

            flush=True

        )

        return Response(

            "ERROR\n\n" + err,

            status=500,

            mimetype="text/plain"

        )

# ============================================================

# LOCAL

# ============================================================

if __name__ == "__main__":

    port = int(

        os.environ.get(

            "PORT",

            "8080"

        )

    )

    app.run(

        host="0.0.0.0",

        port=port

    )
