# ============================================================

# FIX11 / Stage6 Forward Shadow Trader V3

# ============================================================

#

# 実注文なし / Forward Paper Replay

#

# TRACKS

#   LONG

#   SHORT_BASE

#   SHORT_FILTER

#

# SHORT_FILTER 固定除外条件

#   ATR14_pct_prev >= 7.0

#   AND RVOL20 >= 2.5

#   AND RS20_corrected <= 5.0

#

# Formal rules

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

# 重要

#   decision = 新規ENTRY + 既存POSITIONのEXIT処理

#   result   = EXIT処理のみ。新規ENTRY禁止

#   snapshot = RVOL20用の引け後1分足保存

#

# ※ Stage6 strategy shadow。

# ※ 1557再投資・金利等を含む完全FIX11 broker layerではない。

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

# 12:45実行時点では12:40までの確定1分足を使用

DECISION_LAST_BAR = "12:40"

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

        x = x.tz_convert("Asia/Tokyo").tz_localize(None)

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

    """

    J-Quants canonical -> Yahoo

      63270 -> 6327.T

      278A0 -> 278A.T

      130A0 -> 130A.T

    """

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

# ============================================================

# GCS

# ============================================================

def gcs_client():

    return storage.Client()

def bucket():

    return gcs_client().bucket(GCS_BUCKET)

def gcs_name(path):

    return f"{GCS_PREFIX}/{path}".replace("//", "/")

def gcs_upload_bytes(path, data, content_type=None):

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

def gcs_upload_json(path, obj):

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

    raw = gcs_download_bytes(path)

    if raw is None:

        return None

    return json.loads(

        raw.decode("utf-8")

    )

def gcs_upload_df_parquet(path, df):

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

    raw = gcs_download_bytes(path)

    if raw is None:

        return None

    return pd.read_parquet(

        io.BytesIO(raw)

    )

def gcs_upload_df_csv(path, df):

    gcs_upload_bytes(

        path,

        df.to_csv(

            index=False

        ).encode("utf-8"),

        "text/csv"

    )

def list_snapshot_dates(before_date=None):

    prefix = gcs_name(

        "snapshots/"

    )

    blobs = gcs_client().list_blobs(

        GCS_BUCKET,

        prefix=prefix

    )

    out = []

    for b in blobs:

        name = b.name.split("/")[-1]

        if not name.endswith(".parquet"):

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

        dtype={"Code": str}

    )

    if not {

        "Code",

        "is_lending"

    }.issubset(df.columns):

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

        .isin([

            "true",

            "1",

            "yes"

        ])

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

            .tz_convert("Asia/Tokyo")

            .tz_localize(None)

        )

    df.index = idx

    return df

def extract_ticker_frame(

    raw,

    ticker,

    batch_count

):

    if raw is None or len(raw) == 0:

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

    return normalize_yf_index(x)

# ============================================================

# DAILY FEATURES

# ============================================================

def fetch_daily_features(

    universe,

    today

):

    """

    今日の日足は使用しない。

    完成済み date < today の日足だけ。

    """

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

            code = ticker_to_code[

                ticker

            ]

            x = extract_ticker_frame(

                raw,

                ticker,

                len(batch)

            )

            if x is None or len(x) == 0:

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

            x = x[

                x.index.date < today

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

                    "Return20_prev": return20,

                    "turnover_median_20d_oku": turnover20,

                    "ATR14_pct_prev": atr_pct

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

    feat["RS20_corrected"] = (

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

    return feat

# ============================================================

# INTRADAY

# ============================================================

def fetch_intraday_codes(

    codes

):

    codes = list(

        dict.fromkeys(

            normalize_code(c)

            for c in codes

        )

    )

    if not codes:

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

            if x is None or len(x) == 0:

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

                    "Open": pd.to_numeric(

                        x["Open"],

                        errors="coerce"

                    ),

                    "High": pd.to_numeric(

                        x["High"],

                        errors="coerce"

                    ),

                    "Low": pd.to_numeric(

                        x["Low"],

                        errors="coerce"

                    ),

                    "Close": pd.to_numeric(

                        x["Close"],

                        errors="coerce"

                    ),

                    "Volume": pd.to_numeric(

                        x["Volume"],

                        errors="coerce"

                    )

                }

            )

            # placeholder除去

            y = y.dropna(

                subset=[

                    "Open",

                    "High",

                    "Low",

                    "Close"

                ],

                how="all"

            )

            if y.empty:

                continue

            hhmm = (

                y["Datetime"]

                .dt.strftime("%H:%M")

            )

            y = y[

                (hhmm >= "09:00")

                & (hhmm <= "15:30")

            ]

            if len(y):

                frames.append(

                    y

                )

        time.sleep(

            REQUEST_SLEEP

        )

    if not frames:

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

    out = pd.concat(

        frames,

        ignore_index=True

    )

    out = (

        out

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

        .reset_index(

            drop=True

        )

    )

    return out

# ============================================================

# SNAPSHOT HISTORY / RVOL20

# ============================================================

def load_previous_20_snapshots(

    today

):

    dates = list_snapshot_dates(

        before_date=today

    )[-20:]

    frames = []

    for d in dates:

        x = gcs_download_df_parquet(

            f"snapshots/{d}.parquet"

        )

        if x is None or len(x) == 0:

            continue

        x = x.copy()

        x["SnapshotDate"] = (

            pd.Timestamp(d)

        )

        frames.append(

            x

        )

    if not frames:

        return (

            dates,

            pd.DataFrame()

        )

    return (

        dates,

        pd.concat(

            frames,

            ignore_index=True

        )

    )

def build_rvol_lookup(

    minute_today,

    history,

    history_dates

):

    if (

        len(history_dates) < 20

        or history.empty

        or minute_today.empty

    ):

        return {}

    hist_by_code = {

        c: g.copy()

        for c, g

        in history.groupby(

            "Code"

        )

    }

    lookup = {}

    for code, cur in minute_today.groupby(

        "Code"

    ):

        hist = hist_by_code.get(

            code

        )

        if hist is None:

            continue

        if (

            hist["SnapshotDate"]

            .dt.date

            .nunique()

            < 20

        ):

            continue

        cur = (

            cur

            .sort_values(

                "Datetime"

            )

            .copy()

        )

        cur["CumVolume"] = (

            pd.to_numeric(

                cur["Volume"],

                errors="coerce"

            )

            .fillna(0)

            .cumsum()

        )

        for _, r in cur.iterrows():

            dt = pd.Timestamp(

                r["Datetime"]

            )

            minute = dt.strftime(

                "%H:%M"

            )

            h = hist[

                hist["Datetime"]

                .dt.strftime("%H:%M")

                <= minute

            ]

            if h.empty:

                continue

            cumulative = (

                h.groupby(

                    h["SnapshotDate"]

                    .dt.date

                )["Volume"]

                .sum(

                    min_count=1

                )

            )

            cumulative = (

                pd.to_numeric(

                    cumulative,

                    errors="coerce"

                )

                .dropna()

            )

            if len(cumulative) < 20:

                continue

            med = safe_float(

                cumulative

                .tail(20)

                .median()

            )

            if (

                not np.isfinite(med)

                or med <= 0

            ):

                continue

            lookup[

                (

                    code,

                    dt

                )

            ] = (

                safe_float(

                    r["CumVolume"]

                )

                / med

            )

    return lookup

# ============================================================

# SIGNAL ENGINE - METHOD B

# ============================================================

def build_signal_candidates(

    feature_df,

    minute_df,

    rvol_lookup

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

            or turnover < TURNOVER_MIN_OKU

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

            g["Close"].shift(1)

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

            if minute > DECISION_LAST_BAR:

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

            # RVOL不足なら後のbreakoutを探索継続

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

            entry_bar = later.iloc[0]

            entry_dt = pd.Timestamp(

                entry_bar[

                    "Datetime"

                ]

            )

            # 12:40までの確定範囲

            if (

                entry_dt.strftime(

                    "%H:%M"

                )

                > DECISION_LAST_BAR

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

                "turnover_median_20d_oku": turnover,

                "ATR14_pct_prev": atr,

                "is_lending": lending,

                "ORBHigh": orb_high,

                "ORBLow": orb_low

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

    # SHORTは必ず貸借

    x = x[

        x["is_lending"] == True

    ].copy()

    if track_name == "SHORT_FILTER":

        exclude = (

            (

                x["ATR14_pct_prev"]

                >= FILTER_ATR_MIN

            )

            &

            (

                x["RVOL20"]

                >= FILTER_RVOL_MIN

            )

            &

            (

                x["RS20_corrected"]

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

        "Equity": INITIAL_CAPITAL,

        "Position": None,

        "LastExitDatetime": None,

        "LastProcessedDatetime": None,

        "Trades": 0,

        "Wins": 0,

        "RealizedPnL": 0.0

    }

def new_state():

    return {

        "version": "FIX11_STAGE6_FORWARD_V3",

        "created_at": fmt_dt(

            now_jst()

        ),

        "LONG": new_track(),

        "SHORT_BASE": new_track(),

        "SHORT_FILTER": new_track()

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

            state[name] = new_track()

    state["version"] = (

        "FIX11_STAGE6_FORWARD_V3"

    )

    return state

def save_state(state):

    state["updated_at"] = fmt_dt(

        now_jst()

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

        p = state[

            name

        ].get(

            "Position"

        )

        if p is not None:

            code = normalize_code(

                p["Code"]

            )

            if code not in codes:

                codes.append(

                    code

                )

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

    minute_df

):

    side = side_for_track(

        track_name

    )

    entry = safe_float(

        candidate[

            "EntryPrice"

        ]

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

        "Side": side,

        "Code": candidate["Code"],

        "EntryDatetime": fmt_dt(

            entry_dt

        ),

        "EntryPrice": entry,

        "Qty": qty,

        "FixedStop": fixed_stop,

        "EffectiveStop": fixed_stop,

        "EffectiveStopType": "SL",

        "PendingStop": None,

        "PendingStopType": None,

        "BestPrice": entry,

        "EntryDate": (

            entry_dt.date()

            .isoformat()

        ),

        "LastBarDatetime": None,

        "RS20_corrected": safe_float(

            candidate[

                "RS20_corrected"

            ]

        ),

        "RVOL20": safe_float(

            candidate[

                "RVOL20"

            ]

        ),

        "ATR14_pct_prev": safe_float(

            candidate[

                "ATR14_pct_prev"

            ]

        )

    }

    # --------------------------------------------------------

    # ENTRY BAR

    #

    # Exit判定は禁止。

    # favorable extreme は更新。

    # Trail trigger は許可。

    # 新stopはPendingとして次の実在barから有効。

    # --------------------------------------------------------

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

                p["PendingStopType"] = (

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

                p["PendingStopType"] = (

                    "TRAIL"

                    if pending

                    < fixed_stop

                    else "SL"

                )

        p["LastBarDatetime"] = (

            fmt_dt(entry_dt)

        )

    track["Position"] = p

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

    # Formal SHORT reciprocal

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

    trade_log

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

    trade_log.append(

        {

            "Track": track_name,

            "Side": side,

            "Code": p["Code"],

            "EntryDatetime": (

                p["EntryDatetime"]

            ),

            "EntryPrice": entry,

            "Qty": qty,

            "ExitDatetime": fmt_dt(

                exit_dt

            ),

            "ExitPrice": exit_price,

            "ReturnPct": (

                ret * 100.0

            ),

            "PnL": pnl,

            "ExitReason": reason,

            "EquityAfter": (

                track["Equity"]

            )

        }

    )

    track["LastExitDatetime"] = (

        fmt_dt(exit_dt)

    )

    track["Position"] = None

def evaluate_open_position(

    track,

    track_name,

    minute_df,

    trading_dates,

    until_dt,

    trade_log,

    allow_forced_close

):

    p = track.get(

        "Position"

    )

    if p is None:

        return

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

    if x.empty:

        return

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

    for _, r in x.iterrows():

        dt = pd.Timestamp(

            r["Datetime"]

        )

        # Pending stopは次の実在bar開始時に有効化

        pending = p.get(

            "PendingStop"

        )

        if pending is not None:

            p["EffectiveStop"] = (

                safe_float(

                    pending

                )

            )

            p["EffectiveStopType"] = (

                p.get(

                    "PendingStopType"

                )

                or "TRAIL"

            )

            p["PendingStop"] = None

            p["PendingStopType"] = None

        stop = safe_float(

            p["EffectiveStop"]

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

        # ----------------------------------------------------

        # EXIT判定

        # ----------------------------------------------------

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

                    trade_log

                )

                return

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

                    trade_log

                )

                return

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

                    trade_log

                )

                return

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

                    trade_log

                )

                return

        # ----------------------------------------------------

        # 生存したbarの favorable extreme 更新

        # 新stopは次barから

        # ----------------------------------------------------

        if side == "LONG":

            best = max(

                safe_float(

                    p["BestPrice"],

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

                        p["FixedStop"]

                    ),

                    trail

                )

                effective = safe_float(

                    p["EffectiveStop"]

                )

                pending_now = p.get(

                    "PendingStop"

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

                    new_stop > effective

                    and new_stop

                    > pending_value

                ):

                    p["PendingStop"] = (

                        new_stop

                    )

                    p["PendingStopType"] = (

                        "TRAIL"

                        if new_stop

                        > safe_float(

                            p["FixedStop"]

                        )

                        else "SL"

                    )

        else:

            best = min(

                safe_float(

                    p["BestPrice"],

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

                        p["FixedStop"]

                    ),

                    trail

                )

                effective = safe_float(

                    p["EffectiveStop"]

                )

                pending_now = p.get(

                    "PendingStop"

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

                    new_stop < effective

                    and new_stop

                    < pending_value

                ):

                    p["PendingStop"] = (

                        new_stop

                    )

                    p["PendingStopType"] = (

                        "TRAIL"

                        if new_stop

                        < safe_float(

                            p["FixedStop"]

                        )

                        else "SL"

                    )

        p["LastBarDatetime"] = (

            fmt_dt(dt)

        )

    # --------------------------------------------------------

    # LONG 10 trading days

    # --------------------------------------------------------

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

                            minute_df[

                                "Code"

                            ]

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

                        last = z.iloc[-1]

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

                            trade_log

                        )

# ============================================================

# DECISION REPLAY

# ============================================================

def replay_decision_track(

    state,

    track_name,

    candidates,

    minute_df,

    trading_dates,

    until_dt,

    trade_log

):

    """

    decisionのみ新規ENTRYを許可。

    """

    track = state[

        track_name

    ]

    c = candidates_for_track(

        candidates,

        track_name

    )

    # まず既存positionを現在時刻まで進める

    if c.empty:

        evaluate_open_position(

            track,

            track_name,

            minute_df,

            trading_dates,

            until_dt,

            trade_log,

            False

        )

        track[

            "LastProcessedDatetime"

        ] = fmt_dt(

            until_dt

        )

        return

    c = c[

        c["EntryDatetime"]

        <= until_dt

    ].copy()

    c = c.sort_values(

        "EntryDatetime"

    )

    for entry_dt, group in c.groupby(

        "EntryDatetime",

        sort=True

    ):

        entry_dt = pd.Timestamp(

            entry_dt

        )

        # candidate時刻まで既存positionを処理

        evaluate_open_position(

            track,

            track_name,

            minute_df,

            trading_dates,

            entry_dt,

            trade_log,

            False

        )

        # まだ保有中

        if (

            track.get(

                "Position"

            )

            is not None

        ):

            continue

        # 同時刻 EXIT -> ENTRY 禁止

        last_exit = parse_dt(

            track.get(

                "LastExitDatetime"

            )

        )

        if (

            last_exit is not None

            and entry_dt <= last_exit

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

        winner = ranked.iloc[0]

        ok, reason = open_position(

            track,

            track_name,

            winner,

            minute_df

        )

        if not ok:

            print(

                f"{track_name} "

                f"{winner['Code']} "

                f"SKIP {reason}",

                flush=True

            )

    # 12:40まで処理

    evaluate_open_position(

        track,

        track_name,

        minute_df,

        trading_dates,

        until_dt,

        trade_log,

        False

    )

    track[

        "LastProcessedDatetime"

    ] = fmt_dt(

        until_dt

    )

# ============================================================

# RESULT REPLAY

# ============================================================

def replay_result_track(

    state,

    track_name,

    minute_df,

    trading_dates,

    until_dt,

    trade_log

):

    """

    RESULTはEXIT処理のみ。

    新規ENTRYは絶対に行わない。

    """

    track = state[

        track_name

    ]

    evaluate_open_position(

        track,

        track_name,

        minute_df,

        trading_dates,

        until_dt,

        trade_log,

        True

    )

    track[

        "LastProcessedDatetime"

    ] = fmt_dt(

        until_dt

    )

# ============================================================

# LOG

# ============================================================

def append_trade_log(

    new_rows

):

    if not new_rows:

        return

    path = "trades.csv"

    raw = gcs_download_bytes(

        path

    )

    if raw is None:

        old = pd.DataFrame()

    else:

        old = pd.read_csv(

            io.BytesIO(raw)

        )

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

    z = z.drop_duplicates(

        subset=[

            "Track",

            "Code",

            "EntryDatetime",

            "ExitDatetime"

        ],

        keep="last"

    )

    gcs_upload_df_csv(

        path,

        z

    )

def append_screening_log(

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

        "Timestamp": fmt_dt(

            now_jst()

        ),

        "Mode": mode,

        "DailyReady": len(

            feat

        ),

        "LONGCandidates": (

            long_n

        ),

        "SHORTCandidates": (

            short_n

        )

    }

    path = (

        "screening_history.csv"

    )

    raw = gcs_download_bytes(

        path

    )

    if raw is None:

        old = pd.DataFrame()

    else:

        old = pd.read_csv(

            io.BytesIO(raw)

        )

    z = pd.concat(

        [

            old,

            pd.DataFrame(

                [row]

            )

        ],

        ignore_index=True

    )

    gcs_upload_df_csv(

        path,

        z

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

        f"  Position    : {pos}"

    )

def build_report(

    mode,

    universe,

    feat,

    minute_df,

    history_dates,

    candidates,

    state,

    new_trades

):

    lines = [

        "FIX11 Stage6 Forward Shadow V3",

        f"MODE: {mode}",

        f"TIME: {fmt_dt(now_jst())}",

        "",

        f"Universe    : {len(universe)}",

        f"Lending     : {int(universe['is_lending'].sum())}",

        f"DailyReady  : {len(feat)}",

        f"1m rows     : {len(minute_df):,}",

        f"RVOL history: {len(history_dates)}/20"

    ]

    if len(

        history_dates

    ) < 20:

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

            f"Candidates LONG        : {long_n}",

            f"Candidates SHORT BASE  : {short_n}",

            f"Candidates SHORT FILTER: {filter_n}",

            "",

            track_report(

                "LONG",

                state["LONG"]

            ),

            "",

            track_report(

                "SHORT_BASE",

                state["SHORT_BASE"]

            ),

            "",

            track_report(

                "SHORT_FILTER",

                state["SHORT_FILTER"]

            )

        ]

    )

    if new_trades:

        lines.extend(

            [

                "",

                f"New exits: {len(new_trades)}"

            ]

        )

        for t in new_trades[

            -10:

        ]:

            lines.append(

                f"  {t['Track']} "

                f"{t['Code']} "

                f"{t['ReturnPct']:+.2f}% "

                f"{t['ExitReason']}"

            )

    return "\n".join(

        lines

    )

# ============================================================

# MAIN RUN

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

    # --------------------------------------------------------

    # Universe

    # --------------------------------------------------------

    universe = load_universe()

    # --------------------------------------------------------

    # TEST

    #

    # Universe + lending + GCS state読込だけ。

    # Yahoo大量取得しない。

    # stateも変更しない。

    # --------------------------------------------------------

    if mode == "test":

        state = load_state()

        report = (

            "FIX11 Stage6 Forward V3 TEST PASS\n"

            f"Universe : {len(universe)}\n"

            f"Lending  : {int(universe['is_lending'].sum())}\n"

            f"NonLend  : {int((~universe['is_lending']).sum())}\n"

            f"StateVer : {state.get('version')}\n"

            f"Elapsed  : {time.time()-start:.1f}s"

        )

        return report

    # --------------------------------------------------------

    # SNAPSHOT

    #

    # 引け後に4208銘柄の当日1分足を保存。

    # RVOL20 baseline。

    # --------------------------------------------------------

    if mode == "snapshot":

        minute_df = fetch_intraday_codes(

            universe[

                "Code"

            ].tolist()

        )

        if minute_df.empty:

            raise RuntimeError(

                "snapshot rows = 0"

            )

        path = (

            f"snapshots/"

            f"{today}.parquet"

        )

        gcs_upload_df_parquet(

            path,

            minute_df

        )

        return (

            "FIX11 Stage6 SNAPSHOT SAVED\n"

            f"Date     : {today}\n"

            f"Universe : {len(universe)}\n"

            f"Rows     : {len(minute_df):,}\n"

            f"Codes    : {minute_df['Code'].nunique()}\n"

            f"Path     : {GCS_PREFIX}/{path}\n"

            f"Elapsed  : {time.time()-start:.1f}s"

        )

    # --------------------------------------------------------

    # decision / result

    # --------------------------------------------------------

    state = load_state()

    # 完成済み前日までの日足

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

    # --------------------------------------------------------

    # CRITICAL FIX:

    #

    # 現在保有中の銘柄はRS等から外れても

    # 必ず1分足取得対象へ追加。

    # --------------------------------------------------------

    fetch_codes = set(

        pre["Code"].tolist()

    )

    for code in current_position_codes(

        state

    ):

        fetch_codes.add(

            code

        )

    minute_df = fetch_intraday_codes(

        sorted(

            fetch_codes

        )

    )

    if minute_df.empty:

        until_dt = pd.Timestamp(

            now.replace(

                tzinfo=None

            )

        )

    else:

        until_dt = pd.Timestamp(

            minute_df[

                "Datetime"

            ].max()

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

        set(

            trading_dates

        )

    )

    new_trades = []

    # ========================================================

    # RESULT

    #

    # CRITICAL:

    # EXIT ONLY

    # 新規signal / ENTRYは一切作らない。

    # ========================================================

    if mode == "result":

        candidates = pd.DataFrame()

        for track_name in [

            "LONG",

            "SHORT_BASE",

            "SHORT_FILTER"

        ]:

            replay_result_track(

                state,

                track_name,

                minute_df,

                trading_dates,

                until_dt,

                new_trades

            )

        save_state(

            state

        )

        append_trade_log(

            new_trades

        )

        history_dates = (

            list_snapshot_dates(

                before_date=today

            )[-20:]

        )

        append_screening_log(

            mode,

            feat,

            candidates

        )

        report = build_report(

            mode,

            universe,

            feat,

            minute_df,

            history_dates,

            candidates,

            state,

            new_trades

        )

        report += (

            f"\n\nElapsed: "

            f"{time.time()-start:.1f}s"

        )

        gcs_upload_bytes(

            "latest_result.txt",

            report.encode(

                "utf-8"

            ),

            "text/plain"

        )

        return report

    # ========================================================

    # DECISION

    #

    # 新規signal + ENTRYを許可。

    # ========================================================

    cap = pd.Timestamp(

        f"{today} "

        f"{DECISION_LAST_BAR}:59"

    )

    until_dt = min(

        until_dt,

        cap

    )

    history_dates, history = (

        load_previous_20_snapshots(

            today

        )

    )

    if (

        len(history_dates) >= 20

        and not history.empty

        and not minute_df.empty

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

    # 20日履歴がない場合は正式signalを作らない

    if len(history_dates) < 20:

        candidates = pd.DataFrame()

    else:

        candidates = (

            build_signal_candidates(

                feat,

                minute_df,

                rvol_lookup

            )

        )

    for track_name in [

        "LONG",

        "SHORT_BASE",

        "SHORT_FILTER"

    ]:

        replay_decision_track(

            state,

            track_name,

            candidates,

            minute_df,

            trading_dates,

            until_dt,

            new_trades

        )

    save_state(

        state

    )

    append_trade_log(

        new_trades

    )

    append_screening_log(

        mode,

        feat,

        candidates

    )

    # Candidate audit

    if not candidates.empty:

        audit = (

            candidates.copy()

        )

        audit["RunMode"] = (

            mode

        )

        audit[

            "RunTimestamp"

        ] = fmt_dt(

            now

        )

        gcs_upload_df_csv(

            (

                "candidate_audit/"

                f"{today}_decision.csv"

            ),

            audit

        )

    report = build_report(

        mode,

        universe,

        feat,

        minute_df,

        history_dates,

        candidates,

        state,

        new_trades

    )

    report += (

        f"\n\nElapsed: "

        f"{time.time()-start:.1f}s"

    )

    gcs_upload_bytes(

        "latest_result.txt",

        report.encode(

            "utf-8"

        ),

        "text/plain"

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

        "FIX11 Stage6 Forward V3 OK\n",

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

            mode = (

                request.args.get(

                    "mode",

                    "test"

                )

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

        err = traceback.format_exc()

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
