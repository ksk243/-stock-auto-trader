 json

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

# FIX11

# ============================================================

INITIAL_CAPITAL = 1_117_792.0

LONG_LEVERAGE = 1.00

SHORT_LEVERAGE = 0.50

LOT_SIZE = 100

MIN_MARGIN_RATIO = 0.30

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

# EXIT

# ============================================================

LONG_SL = 0.025

LONG_TRAIL_TRIGGER = 0.025

LONG_TRAIL_WIDTH = 0.010

LONG_MAX_TRADING_DAYS = 10

SHORT_SL = 0.015

SHORT_TRAIL_TRIGGER = 0.020

SHORT_TRAIL_WIDTH = 0.020

# ============================================================

# RESEARCH FILTER

# ============================================================

FILTER_ATR_MIN = 7.0

FILTER_RVOL_MIN = 2.5

FILTER_RS_MAX = 5.0

# ============================================================

# PATHS

# ============================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = Path(

    os.getenv(

        "FIX11_DATA_DIR",

        str(BASE_DIR / "data" / "fix11"),

    )

)

RAW_DIR = DATA_DIR / "yahoo_1m"

STATE_DIR = DATA_DIR / "state"

UNIVERSE_FILE = BASE_DIR / "data" / "universe.csv"

RESULT_FILE = DATA_DIR / "latest_result.txt"

DATA_DIR.mkdir(parents=True, exist_ok=True)

RAW_DIR.mkdir(parents=True, exist_ok=True)

STATE_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================

# GCS

# ============================================================

GCS_BUCKET = os.getenv("GCS_BUCKET", "").strip()

GCS_PREFIX = "fix11_forward"

def get_bucket():

    if not GCS_BUCKET:

        raise RuntimeError("GCS_BUCKET is empty")

    client = storage.Client()

    return client.bucket(GCS_BUCKET)

def gcs_download_bytes(path):

    bucket = get_bucket()

    blob = bucket.blob(path)

    if not blob.exists():

        return None

    return blob.download_as_bytes()

def gcs_upload_bytes(data, path):

    bucket = get_bucket()

    blob = bucket.blob(path)

    blob.upload_from_string(data)

def gcs_upload_file(local_path, gcs_path):

    local_path = Path(local_path)

    if not local_path.exists():

        return False

    bucket = get_bucket()

    blob = bucket.blob(gcs_path)

    blob.upload_from_filename(str(local_path))

    return True

# ============================================================

# HELPERS

# ============================================================

def now_jst_naive():

    return (

        pd.Timestamp.now(tz=TZ)

        .tz_localize(None)

    )

def normalize_code(x):

    s = str(x).strip()

    if s.endswith(".T"):

        s = s[:-2]

    if s.endswith(".0"):

        s = s[:-2]

    return s

def ticker_from_code(code):

    code = normalize_code(code)

    # J-Quants 5-char format:

    # 63270 -> 6327.T

    # 278A0 -> 278A.T

    if len(code) == 5 and code.endswith("0"):

        code = code[:-1]

    return f"{code}.T"

def safe_float(x, default=np.nan):

    try:

        x = float(x)

        if np.isfinite(x):

            return x

    except Exception:

        pass

    return default

def dumps_json(obj):

    return json.dumps(

        obj,

        ensure_ascii=False,

        indent=2,

        default=str,

    ).encode("utf-8")

# ============================================================

# UNIVERSE

# ============================================================

def load_universe():

    if not UNIVERSE_FILE.exists():

        raise RuntimeError(

            f"Universe file missing: {UNIVERSE_FILE}"

        )

    df = pd.read_csv(

        UNIVERSE_FILE,

        dtype=str,

    )

    if "Code" not in df.columns:

        raise RuntimeError(

            "universe.csv requires Code column"

        )

    codes = (

        df["Code"]

        .dropna()

        .astype(str)

        .map(normalize_code)

        .drop_duplicates()

        .tolist()

    )

    if not codes:

        raise RuntimeError("Universe empty")

    return codes

# ============================================================

# STATE

# ============================================================

TRACKS = [

    "LONG",

    "SHORT_BASE",

    "SHORT_FILTER",

]

def initial_track():

    return {

        "equity": INITIAL_CAPITAL,

        "position": None,

        "closed_trades": 0,

        "realized_pnl": 0.0,

    }

def initial_state():

    return {

        "version": VERSION,

        "tracks": {

            name: initial_track()

            for name in TRACKS

        },

        "last_snapshot": None,

        "last_decision": None,

        "last_result": None,

    }

def state_gcs_path():

    return f"{GCS_PREFIX}/state/portfolio.json"

def load_state():

    raw = gcs_download_bytes(

        state_gcs_path()

    )

    if raw is None:

        return initial_state()

    try:

        state = json.loads(

            raw.decode("utf-8")

        )

    except Exception:

        return initial_state()

    state.setdefault("tracks", {})

    for name in TRACKS:

        if name not in state["tracks"]:

            state["tracks"][name] = initial_track()

    return state

def save_state(state):

    gcs_upload_bytes(

        dumps_json(state),

        state_gcs_path(),

    )

# ============================================================

# TRADE LOG

# ============================================================

def trade_log_path():

    return f"{GCS_PREFIX}/trades/paper_trades.csv"

def append_trade_log(rows):

    if not rows:

        return

    new = pd.DataFrame(rows)

    raw = gcs_download_bytes(

        trade_log_path()

    )

    if raw:

        try:

            old = pd.read_csv(

                io.BytesIO(raw)

            )

            new = pd.concat(

                [old, new],

                ignore_index=True,

            )

        except Exception:

            pass

    new = new.drop_duplicates(

        subset=[

            "Track",

            "Code",

            "EntryDatetime",

            "Event",

            "EventDatetime",

        ],

        keep="last",

    )

    gcs_upload_bytes(

        new.to_csv(

            index=False

        ).encode("utf-8"),

        trade_log_path(),

    )

# ============================================================

# RAW 1M

# ============================================================

def normalize_yahoo_1m(raw):

    if raw is None or len(raw) == 0:

        return pd.DataFrame()

    x = raw.copy()

    if isinstance(

        x.columns,

        pd.MultiIndex,

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

        "Date",

    ]:

        if c in x.columns:

            dt_col = c

            break

    if dt_col is None:

        return pd.DataFrame()

    dt = pd.to_datetime(

        x[dt_col],

        errors="coerce",

        utc=True,

    )

    x["Datetime"] = (

        dt

        .dt.tz_convert(TZ)

        .dt.tz_localize(None)

    )

    x = x.rename(

        columns={

            "Open": "O",

            "High": "H",

            "Low": "L",

            "Close": "C",

            "Volume": "V",

        }

    )

    required = [

        "Datetime",

        "O",

        "H",

        "L",

        "C",

        "V",

    ]

    if any(

        c not in x.columns

        for c in required

    ):

        return pd.DataFrame()

    x = x[required].copy()

    for c in [

        "O",

        "H",

        "L",

        "C",

        "V",

    ]:

        x[c] = pd.to_numeric(

            x[c],

            errors="coerce",

        )

    # placeholder row is NOT an actual bar

    x = x.dropna(

        subset=[

            "Datetime",

            "O",

            "H",

            "L",

            "C",

            "V",

        ]

    )

    x = x[

        ~(

            x[

                [

                    "O",

                    "H",

                    "L",

                    "C",

                    "V",

                ]

            ]

            .isna()

            .all(axis=1)

        )

    ]

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

        .sort_values("Datetime")

        .drop_duplicates(

            "Datetime",

            keep="last",

        )

        .reset_index(drop=True)

    )

def fetch_today_1m(code):

    ticker = ticker_from_code(code)

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

        x = normalize_yahoo_1m(raw)

        if x.empty:

            return x

        today = now_jst_naive().normalize()

        x = x[

            x["Date"] == today

        ].copy()

        x["Code"] = normalize_code(code)

        return x

    except Exception:

        return pd.DataFrame()

# ============================================================

# GCS RAW SNAPSHOT

# ============================================================

def raw_gcs_path(date, code):

    date = pd.Timestamp(date)

    return (

        f"{GCS_PREFIX}/yahoo_1m/"

        f"{date:%Y/%m}/"

        f"{date:%Y-%m-%d}_{code}.parquet"

    )

def save_raw_snapshot(df):

    if df.empty:

        return

    date = pd.Timestamp(

        df["Date"].iloc[0]

    )

    code = normalize_code(

        df["Code"].iloc[0]

    )

    path = raw_gcs_path(

        date,

        code,

    )

    old_raw = gcs_download_bytes(

        path

    )

    if old_raw:

        try:

            old = pd.read_parquet(

                io.BytesIO(old_raw)

            )

            z = pd.concat(

                [old, df],

                ignore_index=True,

            )

        except Exception:

            z = df.copy()

    else:

        z = df.copy()

    z["Datetime"] = pd.to_datetime(

        z["Datetime"]

    )

    # first observation preserved

    z = (

        z

        .sort_values("Datetime")

        .drop_duplicates(

            "Datetime",

            keep="first",

        )

    )

    bio = io.BytesIO()

    z.to_parquet(

        bio,

        index=False,

    )

    gcs_upload_bytes(

        bio.getvalue(),

        path,

    )

# ============================================================

# HISTORICAL SNAPSHOT LIST

# ============================================================

def previous_snapshot_dates(

    code,

    before_date,

    max_days=20,

):

    bucket = get_bucket()

    prefix = (

        f"{GCS_PREFIX}/yahoo_1m/"

    )

    suffix = f"_{code}.parquet"

    dates = []

    for blob in bucket.list_blobs(

        prefix=prefix

    ):

        name = blob.name

        if not name.endswith(suffix):

            continue

        filename = name.rsplit(

            "/",

            1,

        )[-1]

        try:

            date = pd.Timestamp(

                filename[:10]

            )

        except Exception:

            continue

        if date < before_date:

            dates.append(date)

    dates = sorted(set(dates))

    return dates[-max_days:]

def load_snapshot(date, code):

    raw = gcs_download_bytes(

        raw_gcs_path(

            date,

            code,

        )

    )

    if not raw:

        return pd.DataFrame()

    try:

        return pd.read_parquet(

            io.BytesIO(raw)

        )

    except Exception:

        return pd.DataFrame()

# ============================================================

# DAILY DATA

# ============================================================

def fetch_daily_batch(codes):

    frames = []

    tickers = [

        ticker_from_code(c)

        for c in codes

    ]

    for start in range(

        0,

        len(tickers),

        100,

    ):

        batch = tickers[

            start:start + 100

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

        except Exception:

            continue

        for ticker in batch:

            try:

                if len(batch) == 1:

                    d = raw.copy()

                else:

                    d = raw[ticker].copy()

                if d.empty:

                    continue

                d = d.reset_index()

                if "Date" not in d.columns:

                    continue

                d["Date"] = pd.to_datetime(

                    d["Date"],

                    errors="coerce",

                ).dt.normalize()

                raw_close = pd.to_numeric(

                    d["Close"],

                    errors="coerce",

                )

                if "Adj Close" in d.columns:

                    adj_close = pd.to_numeric(

                        d["Adj Close"],

                        errors="coerce",

                    )

                else:

                    adj_close = raw_close

                volume = pd.to_numeric(

                    d["Volume"],

                    errors="coerce",

                )

                code = ticker.replace(

                    ".T",

                    "",

                )

                frames.append(

                    pd.DataFrame({

                        "Date": d["Date"],

                        "Code": normalize_code(code),

                        "AdjC": adj_close,

                        "RawC": raw_close,

                        "Volume": volume,

                    })

                )

            except Exception:

                continue

    if not frames:

        return pd.DataFrame()

    return pd.concat(

        frames,

        ignore_index=True,

    )

# ============================================================

# DAILY FEATURES

# ============================================================

def build_daily_features(

    daily,

    today,

):

    if daily.empty:

        return pd.DataFrame()

    d = daily.copy()

    d = d[

        d["Date"] < today

    ].copy()

    d = d.sort_values(

        [

            "Code",

            "Date",

        ]

    )

    d["Return20"] = (

        d.groupby("Code")["AdjC"]

        .pct_change(20)

    )

    rows = []

    for code, g in d.groupby(

        "Code",

        sort=False,

    ):

        g = g.sort_values(

            "Date"

        )

        if len(g) < 21:

            continue

        last = g.iloc[-1]

        tail20 = g.tail(20)

        turnover = (

            tail20["RawC"]

            *

            tail20["Volume"]

            /

            1e8

        )

        rows.append({

            "Code": code,

            "Return20_prev":

                safe_float(

                    last["Return20"]

                ),

            "turnover_median_20d_oku":

                safe_float(

                    turnover.median()

                ),

        })

    f = pd.DataFrame(rows)

    if f.empty:

        return f

    valid = f[

        f["Return20_prev"].notna()

    ].copy()

    valid[

        "RS20_corrected"

    ] = (

        valid[

            "Return20_prev"

        ]

        .rank(

            pct=True,

            method="average",

        )

        *

        100.0

    )

    return f.merge(

        valid[

            [

                "Code",

                "RS20_corrected",

            ]

        ],

        on="Code",

        how="left",

    )

# ============================================================

# ATR14 PREVIOUS DAY

# ============================================================

def fetch_atr_feature(code):

    ticker = ticker_from_code(code)

    try:

        raw = yf.download(

            ticker,

            period="2mo",

            interval="1d",

            auto_adjust=True,

            progress=False,

            threads=False,

        )

    except Exception:

        return np.nan

    if raw is None or raw.empty:

        return np.nan

    if isinstance(

        raw.columns,

        pd.MultiIndex,

    ):

        raw.columns = [

            c[0]

            if isinstance(c, tuple)

            else c

            for c in raw.columns

        ]

    required = [

        "High",

        "Low",

        "Close",

    ]

    if any(

        c not in raw.columns

        for c in required

    ):

        return np.nan

    h = pd.to_numeric(

        raw["High"],

        errors="coerce",

    )

    l = pd.to_numeric(

        raw["Low"],

        errors="coerce",

    )

    c = pd.to_numeric(

        raw["Close"],

        errors="coerce",

    )

    prev = c.shift(1)

    tr = pd.concat(

        [

            h - l,

            (h - prev).abs(),

            (l - prev).abs(),

        ],

        axis=1,

    ).max(axis=1)

    atr = tr.rolling(

        14

    ).mean()

    atr_pct = (

        atr

        /

        c.shift(1)

        *

        100.0

    )

    valid = atr_pct.dropna()

    if valid.empty:

        return np.nan

    return safe_float(

        valid.iloc[-1]

    )

# ============================================================

# RVOL20

# ============================================================

def calc_rvol20(

    code,

    current_df,

    signal_dt,

):

    signal_dt = pd.Timestamp(

        signal_dt

    )

    date = signal_dt.normalize()

    history_dates = (

        previous_snapshot_dates(

            code,

            date,

            max_days=20,

        )

    )

    if len(history_dates) != 20:

        return np.nan, len(history_dates)

    current_cut = current_df[

        current_df["Datetime"]

        <=

        signal_dt

    ]

    if current_cut.empty:

        current_cum = 0.0

    else:

        current_cum = float(

            pd.to_numeric(

                current_cut["V"],

                errors="coerce",

            )

            .fillna(0)

            .sum()

        )

    minute = signal_dt.strftime(

        "%H:%M"

    )

    hist = []

    for hist_date in history_dates:

        h = load_snapshot(

            hist_date,

            code,

        )

        if h.empty:

            hist.append(0.0)

            continue

        h["Datetime"] = pd.to_datetime(

            h["Datetime"]

        )

        cut = h[

            h["Datetime"].dt.strftime(

                "%H:%M"

            )

            <= minute

        ]

        if cut.empty:

            hist.append(0.0)

        else:

            hist.append(

                float(

                    pd.to_numeric(

                        cut["V"],

                        errors="coerce",

                    )

                    .fillna(0)

                    .sum()

                )

            )

    if len(hist) != 20:

        return np.nan, len(hist)

    baseline = float(

        np.median(hist)

    )

    if (

        not np.isfinite(baseline)

        or

        baseline <= 0

    ):

        return np.nan, 20

    return (

        current_cum / baseline,

        20,

    )

# ============================================================

# METHOD B SIGNAL SCAN

# ============================================================

def find_signals_for_code(

    code,

    minute,

    feature,

):

    if minute.empty:

        return []

    x = minute.copy()

    x = x[

        x["Time"] >= ORB_START

    ]

    orb = x[

        (x["Time"] >= ORB_START)

        &

        (x["Time"] <= ORB_END)

    ]

    if orb.empty:

        return []

    orb_high = safe_float(

        orb["H"].max()

    )

    orb_low = safe_float(

        orb["L"].min()

    )

    if (

        not np.isfinite(orb_high)

        or

        not np.isfinite(orb_low)

    ):

        return []

    rs = safe_float(

        feature.get(

            "RS20_corrected"

        )

    )

    turnover = safe_float(

        feature.get(

            "turnover_median_20d_oku"

        )

    )

    atr = safe_float(

        feature.get(

            "ATR14_pct_prev"

        )

    )

    if (

        not np.isfinite(rs)

        or

        not np.isfinite(turnover)

        or

        not np.isfinite(atr)

    ):

        return []

    if turnover < TURNOVER_MIN_OKU:

        return []

    post = x[

        x["Time"] >= SIGNAL_START

    ].copy()

    signals = []

    for _, row in post.iterrows():

        dt = pd.Timestamp(

            row["Datetime"]

        )

        before = x[

            x["Datetime"] < dt

        ]

        if before.empty:

            continue

        prev_close = safe_float(

            before.iloc[-1]["C"]

        )

        close = safe_float(

            row["C"]

        )

        if (

            not np.isfinite(prev_close)

            or

            not np.isfinite(close)

        ):

            continue

        long_break = (

            prev_close <= orb_high

            and

            close > orb_high

        )

        short_break = (

            prev_close >= orb_low

            and

            close < orb_low

        )

        if not (

            long_break

            or

            short_break

        ):

            continue

        rvol, n = calc_rvol20(

            code,

            x,

            dt,

        )

        if not np.isfinite(rvol):

            continue

        # METHOD B:

        # failed RVOL breakout does NOT terminate scan.

        if rvol < RVOL_MIN:

            continue

        side = None

        if (

            long_break

            and

            rs >= RS_LONG_MIN

        ):

            side = "LONG"

        elif (

            short_break

            and

            rs <= RS_SHORT_MAX

        ):

            side = "SHORT"

        if side is None:

            continue

        after = x[

            x["Datetime"] > dt

        ]

        if after.empty:

            continue

        nxt = after.iloc[0]

        signals.append({

            "Side": side,

            "Code": code,

            "SignalDatetime": dt,

            "EntryDatetime":

                pd.Timestamp(

                    nxt["Datetime"]

                ),

            "EntryPrice":

                safe_float(

                    nxt["O"]

                ),

            "RS20_corrected": rs,

            "RVOL20": rvol,

            "ATR14_pct_prev": atr,

            "turnover_median_20d_oku":

                turnover,

            "ORBHigh": orb_high,

            "ORBLow": orb_low,

            "Prev20N": n,

        })

        # First qualifying signal per

        # Date+Code+Side.

        break

    return signals

# ============================================================

# FILTER

# ============================================================

def is_short_filter_excluded(row):

    return (

        safe_float(

            row["ATR14_pct_prev"]

        )

        >= FILTER_ATR_MIN

        and

        safe_float(

            row["RVOL20"]

        )

        >= FILTER_RVOL_MIN

        and

        safe_float(

            row["RS20_corrected"]

        )

        <= FILTER_RS_MAX

    )

# ============================================================

# FORMAL RANKING

# ============================================================

def rank_signals(

    signals,

    side,

):

    rows = [

        x

        for x in signals

        if x["Side"] == side

    ]

    if not rows:

        return []

    df = pd.DataFrame(rows)

    earliest = (

        df["EntryDatetime"]

        .min()

    )

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

            kind="stable",

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

            kind="stable",

        )

    return df.to_dict(

        orient="records"

    )

# ============================================================

# QUANTITY

# ============================================================

def calculate_qty(

    equity,

    leverage,

    price,

):

    target = (

        float(equity)

        *

        float(leverage)

    )

    lot_value = (

        float(price)

        *

        LOT_SIZE

    )

    if lot_value <= 0:

        return 0, target

    lots = math.floor(

        target

        /

        lot_value

    )

    return (

        max(

            0,

            int(lots) * LOT_SIZE,

        ),

        target,

    )

# ============================================================

# ENTRY

# ============================================================

def open_position(

    track,

    candidate,

    leverage,

):

    price = safe_float(

        candidate["EntryPrice"]

    )

    qty, target = calculate_qty(

        track["equity"],

        leverage,

        price,

    )

    if qty < LOT_SIZE:

        return None, {

            "Status":

                "LOT_TOO_LARGE",

            **candidate,

        }

    position = {

        "Code":

            candidate["Code"],

        "EntryDatetime":

            str(

                candidate[

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

            qty * price,

        "RS20_corrected":

            candidate[

                "RS20_corrected"

            ],

        "RVOL20":

            candidate["RVOL20"],

        "ATR14_pct_prev":

            candidate[

                "ATR14_pct_prev"

            ],

        "BestPrice":

            price,

        "TrailActive":

            False,

        "TrailStop":

            None,

        "TradingDates": [

            str(

                pd.Timestamp(

                    candidate[

                        "EntryDatetime"

                    ]

                ).date()

            )

        ],

    }

    return position, None

# ============================================================

# EXIT ENGINE

# ============================================================

def evaluate_position(

    position,

    minute,

    side,

):

    if minute.empty:

        return None

    entry_dt = pd.Timestamp(

        position["EntryDatetime"]

    )

    entry = float(

        position["EntryPrice"]

    )

    x = minute[

        minute["Datetime"]

        >

        entry_dt

    ].copy()

    if x.empty:

        return None

    best = safe_float(

        position.get(

            "BestPrice",

            entry,

        ),

        entry,

    )

    trail_active = bool(

        position.get(

            "TrailActive",

            False,

        )

    )

    trail_stop = safe_float(

        position.get(

            "TrailStop"

        )

    )

    if side == "LONG":

        fixed_stop = (

            entry

            *

            (1 - LONG_SL)

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

        for _, bar in x.iterrows():

            o = float(bar["O"])

            h = float(bar["H"])

            l = float(bar["L"])

            dt = pd.Timestamp(

                bar["Datetime"]

            )

            effective_stop = fixed_stop

            if (

                trail_active

                and

                np.isfinite(trail_stop)

            ):

                effective_stop = max(

                    effective_stop,

                    trail_stop,

                )

            if o <= effective_stop:

                return {

                    "ExitDatetime": dt,

                    "ExitPrice": o,

                    "ExitReason":

                        (

                            "TRAIL_GAP"

                            if trail_active

                            else "SL_GAP"

                        ),

                }

            if l <= effective_stop:

                return {

                    "ExitDatetime": dt,

                    "ExitPrice":

                        effective_stop,

                    "ExitReason":

                        (

                            "TRAIL"

                            if trail_active

                            else "SL"

                        ),

                }

            best = max(

                best,

                h,

            )

            if best >= trigger:

                trail_active = True

                trail_stop = (

                    best

                    *

                    (

                        1

                        -

                        LONG_TRAIL_WIDTH

                    )

                )

    else:

        fixed_stop = (

            entry

            *

            (1 + SHORT_SL)

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

        for _, bar in x.iterrows():

            o = float(bar["O"])

            h = float(bar["H"])

            l = float(bar["L"])

            dt = pd.Timestamp(

                bar["Datetime"]

            )

            effective_stop = fixed_stop

            if (

                trail_active

                and

                np.isfinite(trail_stop)

            ):

                effective_stop = min(

                    effective_stop,

                    trail_stop,

                )

            if o >= effective_stop:

                return {

                    "ExitDatetime": dt,

                    "ExitPrice": o,

                    "ExitReason":

                        (

                            "TRAIL_GAP"

                            if trail_active

                            else "SL_GAP"

                        ),

                }

            if h >= effective_stop:

                return {

                    "ExitDatetime": dt,

                    "ExitPrice":

                        effective_stop,

                    "ExitReason":

                        (

                            "TRAIL"

                            if trail_active

                            else "SL"

                        ),

                }

            best = min(

                best,

                l,

            )

            if best <= trigger:

                trail_active = True

                trail_stop = (

                    best

                    *

                    (

                        1

                        +

                        SHORT_TRAIL_WIDTH

                    )

                )

    position["BestPrice"] = best

    position["TrailActive"] = trail_active

    if np.isfinite(

        safe_float(trail_stop)

    ):

        position["TrailStop"] = (

            trail_stop

        )

    return None

# ============================================================

# RESULT WRITER

# ============================================================

def write_result(lines):

    text = "\n".join(

        str(x)

        for x in lines

    )

    print(text)

    RESULT_FILE.parent.mkdir(

        parents=True,

        exist_ok=True,

    )

    RESULT_FILE.write_text(

        text + "\n",

        encoding="utf-8",

    )

    gcs_upload_bytes(

        text.encode("utf-8"),

        f"{GCS_PREFIX}/latest_result.txt",

    )

    return text

# ============================================================

# FETCH ALL TODAY

# ============================================================

def fetch_all_today(

    universe,

):

    result = {}

    success = 0

    failed = 0

    for i, code in enumerate(

        universe,

        1,

    ):

        df = fetch_today_1m(

            code

        )

        if df.empty:

            failed += 1

        else:

            success += 1

            result[code] = df

            save_raw_snapshot(

                df

            )

        if i % 100 == 0:

            print(

                f"1m {i}/{len(universe)} "

                f"OK={success} "

                f"NG={failed}"

            )

    return (

        result,

        success,

        failed,

    )

# ============================================================

# SNAPSHOT

# ============================================================

def run_snapshot():

    universe = load_universe()

    minute_map, ok, ng = (

        fetch_all_today(

            universe

        )

    )

    state = load_state()

    state["last_snapshot"] = str(

        now_jst_naive()

    )

    save_state(state)

    return write_result([

        VERSION,

        "",

        "SNAPSHOT COMPLETE",

        f"Universe: {len(universe)}",

        f"1m success: {ok}",

        f"1m failed: {ng}",

        "",

        "No real orders.",

    ])

# ============================================================

# DECISION

# ============================================================

def run_decision(

    test_mode=False,

):

    now = now_jst_naive()

    today = now.normalize()

    universe = load_universe()

    state = load_state()

    # --------------------------------------------------------

    # Daily

    # --------------------------------------------------------

    print("Daily data...")

    daily = fetch_daily_batch(

        universe

    )

    features = build_daily_features(

        daily,

        today,

    )

    if features.empty:

        raise RuntimeError(

            "Daily features empty"

        )

    # ATR

    # --------------------------------------------------------

    # Only calculate ATR for signal-capable

    # RS/liquidity universe later.

    # --------------------------------------------------------

    feature_map = (

        features

        .set_index("Code")

        .to_dict(

            orient="index"

        )

    )

    # --------------------------------------------------------

    # Intraday

    # --------------------------------------------------------

    minute_map, ok, ng = (

        fetch_all_today(

            universe

        )

    )

    signals = []

    not_ready = 0

    for i, code in enumerate(

        universe,

        1,

    ):

        minute = minute_map.get(

            code

        )

        if minute is None:

            continue

        feature = feature_map.get(

            code

        )

        if not feature:

            continue

        rs = safe_float(

            feature.get(

                "RS20_corrected"

            )

        )

        turnover = safe_float(

            feature.get(

                "turnover_median_20d_oku"

            )

        )

        if (

            not np.isfinite(rs)

            or

            not np.isfinite(turnover)

            or

            turnover

            <

            TURNOVER_MIN_OKU

        ):

            continue

        # Only LONG/SHORT RS tails need ATR.

        if not (

            rs >= RS_LONG_MIN

            or

            rs <= RS_SHORT_MAX

        ):

            continue

        hist_dates = (

            previous_snapshot_dates(

                code,

                today,

                20,

            )

        )

        if len(hist_dates) != 20:

            not_ready += 1

            continue

        atr = fetch_atr_feature(

            code

        )

        if not np.isfinite(atr):

            continue

        feature[

            "ATR14_pct_prev"

        ] = atr

        rows = find_signals_for_code(

            code,

            minute,

            feature,

        )

        signals.extend(rows)

    # --------------------------------------------------------

    # LONG

    # --------------------------------------------------------

    long_rank = rank_signals(

        signals,

        "LONG",

    )

    # --------------------------------------------------------

    # SHORT BASE

    # --------------------------------------------------------

    short_base_rank = rank_signals(

        signals,

        "SHORT",

    )

    # --------------------------------------------------------

    # SHORT FILTER

    #

    # Filter first -> rerank.

    # --------------------------------------------------------

    short_filtered_signals = [

        x

        for x in signals

        if (

            x["Side"] != "SHORT"

            or

            not is_short_filter_excluded(

                x

            )

        )

    ]

    short_filter_rank = rank_signals(

        short_filtered_signals,

        "SHORT",

    )

    trade_rows = []

    new_entries = []

    # --------------------------------------------------------

    # LONG

    # --------------------------------------------------------

    long_track = state[

        "tracks"

    ]["LONG"]

    if (

        long_track["position"]

        is None

        and

        long_rank

    ):

        pos, skip = open_position(

            long_track,

            long_rank[0],

            LONG_LEVERAGE,

        )

        if pos is not None:

            if not test_mode:

                long_track[

                    "position"

                ] = pos

            new_entries.append(

                (

                    "LONG",

                    pos,

                )

            )

    # --------------------------------------------------------

    # SHORT BASE

    # --------------------------------------------------------

    base_track = state[

        "tracks"

    ]["SHORT_BASE"]

    if (

        base_track["position"]

        is None

        and

        short_base_rank

    ):

        pos, skip = open_position(

            base_track,

            short_base_rank[0],

            SHORT_LEVERAGE,

        )

        if pos is not None:

            if not test_mode:

                base_track[

                    "position"

                ] = pos

            new_entries.append(

                (

                    "SHORT_BASE",

                    pos,

                )

            )

    # --------------------------------------------------------

    # SHORT FILTER

    # --------------------------------------------------------

    filter_track = state[

        "tracks"

    ]["SHORT_FILTER"]

    if (

        filter_track["position"]

        is None

        and

        short_filter_rank

    ):

        pos, skip = open_position(

            filter_track,

            short_filter_rank[0],

            SHORT_LEVERAGE,

        )

        if pos is not None:

            if not test_mode:

                filter_track[

                    "position"

                ] = pos

            new_entries.append(

                (

                    "SHORT_FILTER",

                    pos,

                )

            )

    if not test_mode:

        state[

            "last_decision"

        ] = str(now)

        save_state(state)

        for track_name, pos in (

            new_entries

        ):

            trade_rows.append({

                "Track": track_name,

                "Event": "ENTRY",

                "EventDatetime":

                    pos[

                        "EntryDatetime"

                    ],

                "Code":

                    pos["Code"],

                "EntryDatetime":

                    pos[

                        "EntryDatetime"

                    ],

                "EntryPrice":

                    pos[

                        "EntryPrice"

                    ],

                "Quantity":

                    pos[

                        "Quantity"

                    ],

                "PnL":

                    0.0,

            })

        append_trade_log(

            trade_rows

        )

    # --------------------------------------------------------

    # Output

    # --------------------------------------------------------

    lines = [

        VERSION,

        "",

        (

            "TEST"

            if test_mode

            else "DECISION"

        ),

        f"Run: {now}",

        f"Universe: {len(universe)}",

        f"1m success: {ok}",

        f"1m failed: {ng}",

        f"RVOL20 NOT_READY: {not_ready}",

        f"Signals: {len(signals)}",

        "",

    ]

    for name in TRACKS:

        track = state[

            "tracks"

        ][name]

        pos = track.get(

            "position"

        )

        lines.append(

            f"[{name}]"

        )

        if pos:

            lines.append(

                f"OPEN {pos['Code']} "

                f"{pos['Quantity']}株 "

                f"@ {pos['EntryPrice']:,.2f}"

            )

        else:

            # test entry display

            found = [

                p

                for n, p

                in new_entries

                if n == name

            ]

            if found:

                p = found[0]

                lines.append(

                    f"TEST ENTRY "

                    f"{p['Code']} "

                    f"{p['Quantity']}株 "

                    f"@ {p['EntryPrice']:,.2f}"

                )

            else:

                lines.append(

                    "FLAT"

                )

        lines.append("")

    lines.extend([

        "SHORT FILTER:",

        (

            "ATR>=7 AND "

            "RVOL>=2.5 AND "

            "RS<=5 -> EXCLUDE"

        ),

        "",

        "No real orders.",

    ])

    return write_result(

        lines

    )

# ============================================================

# RESULT / EXIT CHECK

# ============================================================

def run_result():

    now = now_jst_naive()

    state = load_state()

    universe_needed = set()

    for name in TRACKS:

        pos = (

            state[

                "tracks"

            ][name]

            .get(

                "position"

            )

        )

        if pos:

            universe_needed.add(

                pos["Code"]

            )

    if not universe_needed:

        state[

            "last_result"

        ] = str(now)

        save_state(state)

        return write_result([

            VERSION,

            "",

            "RESULT",

            f"Run: {now}",

            "",

            "No open positions.",

            "",

            "No real orders.",

        ])

    minute_map = {}

    for code in sorted(

        universe_needed

    ):

        minute = fetch_today_1m(

            code

        )

        if not minute.empty:

            minute_map[

                code

            ] = minute

            save_raw_snapshot(

                minute

            )

    trade_rows = []

    closed_text = []

    for name in TRACKS:

        track = state[

            "tracks"

        ][name]

        pos = track.get(

            "position"

        )

        if not pos:

            continue

        code = pos["Code"]

        minute = minute_map.get(

            code

        )

        if minute is None:

            continue

        side = (

            "LONG"

            if name == "LONG"

            else "SHORT"

        )

        exit_event = (

            evaluate_position(

                pos,

                minute,

                side,

            )

        )

        if exit_event is None:

            # Update trading-date count.

            dates = set(

                pos.get(

                    "TradingDates",

                    []

                )

            )

            today_str = str(

                now.date()

            )

            dates.add(

                today_str

            )

            pos[

                "TradingDates"

            ] = sorted(dates)

            # LONG 10 trading-day forced close

            if (

                side == "LONG"

                and

                len(dates)

                >=

                LONG_MAX_TRADING_DAYS

                and

                not minute.empty

            ):

                last = (

                    minute

                    .sort_values(

                        "Datetime"

                    )

                    .iloc[-1]

                )

                exit_event = {

                    "ExitDatetime":

                        pd.Timestamp(

                            last[

                                "Datetime"

                            ]

                        ),

                    "ExitPrice":

                        float(

                            last["C"]

                        ),

                    "ExitReason":

                        "FORCED_10D",

                }

        if exit_event is None:

            continue

        entry = float(

            pos["EntryPrice"]

        )

        exit_price = float(

            exit_event[

                "ExitPrice"

            ]

        )

        qty = int(

            pos["Quantity"]

        )

        if side == "LONG":

            ret = (

                exit_price

                /

                entry

                -

                1.0

            )

        else:

            # Formal SHORT reciprocal convention.

            ret = (

                entry

                /

                exit_price

                -

                1.0

            )

        pnl = (

            entry

            *

            qty

            *

            ret

        )

        track[

            "equity"

        ] = (

            float(

                track["equity"]

            )

            +

            pnl

        )

        track[

            "realized_pnl"

        ] = (

            float(

                track.get(

                    "realized_pnl",

                    0.0,

                )

            )

            +

            pnl

        )

        track[

            "closed_trades"

        ] = (

            int(

                track.get(

                    "closed_trades",

                    0,

                )

            )

            +

            1

        )

        track[

            "position"

        ] = None

        trade_rows.append({

            "Track": name,

            "Event": "EXIT",

            "EventDatetime":

                str(

                    exit_event[

                        "ExitDatetime"

                    ]

                ),

            "Code": code,

            "EntryDatetime":

                pos[

                    "EntryDatetime"

                ],

            "EntryPrice":

                entry,

            "ExitPrice":

                exit_price,

            "Quantity":

                qty,

            "ReturnPct":

                ret * 100.0,

            "PnL":

                pnl,

            "ExitReason":

                exit_event[

                    "ExitReason"

                ],

        })

        closed_text.append(

            (

                f"{name} {code} "

                f"{exit_event['ExitReason']} "

                f"{ret * 100:+.3f}% "

                f"{pnl:+,.0f}円"

            )

        )

    state[

        "last_result"

    ] = str(now)

    save_state(state)

    append_trade_log(

        trade_rows

    )

    lines = [

        VERSION,

        "",

        "RESULT",

        f"Run: {now}",

        "",

    ]

    if closed_text:

        lines.append(

            "CLOSED"

        )

        lines.extend(

            closed_text

        )

    else:

        lines.append(

            "No exits."

        )

    lines.append("")

    for name in TRACKS:

        track = state[

            "tracks"

        ][name]

        lines.append(

            (

                f"{name}: "

                f"equity="

                f"{track['equity']:,.0f} "

                f"realized="

                f"{track['realized_pnl']:+,.0f} "

                f"closed="

                f"{track['closed_trades']}"

            )

        )

        pos = track.get(

            "position"

        )

        if pos:

            lines.append(

                (

                    f"  OPEN "

                    f"{pos['Code']} "

                    f"{pos['Quantity']}株 "

                    f"@ "

                    f"{pos['EntryPrice']:,.2f}"

                )

            )

        else:

            lines.append(

                "  FLAT"

            )

    lines.extend([

        "",

        "No real orders.",

    ])

    return write_result(

        lines

    )

# ============================================================

# TEST

# ============================================================

def run_test():

    return run_decision(

        test_mode=True

    )

# ============================================================

# EXECUTE

# ============================================================

def execute_mode(mode):

    mode = str(

        mode

    ).strip().lower()

    print("=" * 80)

    print(VERSION)

    print("MODE:", mode)

    print("=" * 80)

    if mode == "snapshot":

        return run_snapshot()

    if mode == "decision":

        return run_decision(

            test_mode=False

        )

    if mode == "result":

        return run_result()

    if mode == "test":

        return run_test()

    raise ValueError(

        f"Unknown mode: {mode}"

    )

# ============================================================

# FLASK

# ============================================================

app = Flask(__name__)

@app.get("/")

def health():

    return jsonify({

        "status": "ok",

        "version": VERSION,

        "paper_only": True,

        "tracks": TRACKS,

        "short_filter": {

            "ATR14_pct_prev_gte":

                FILTER_ATR_MIN,

            "RVOL20_gte":

                FILTER_RVOL_MIN,

            "RS20_corrected_lte":

                FILTER_RS_MAX,

        },

    })

@app.get("/run")

def run_endpoint():

    mode = request.args.get(

        "mode",

        "test",

    )

    try:

        text = execute_mode(

            mode

        )

        return Response(

            text,

            status=200,

            mimetype=(

                "text/plain; "

                "charset=utf-8"

            ),

        )

    except Exception as e:

        error = (

            f"{VERSION} ERROR\n\n"

            f"MODE: {mode}\n\n"

            f"{type(e).__name__}: "

            f"{e}\n\n"

            f"{traceback.format_exc()}"

        )

        print(error)

        return Response(

            error,

            status=500,

            mimetype=(

                "text/plain; "

                "charset=utf-8"

            ),

        )

# ============================================================

# LOCAL

# ============================================================

if __name__ == "__main__":

    mode = os.getenv(

        "RUN_MODE",

        "test",

    )

    execute_mode(

        mode

    )
