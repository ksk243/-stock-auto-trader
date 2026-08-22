import os

import io

import json

import ssl

import smtplib

import urllib.request

import urllib.parse

import warnings

import traceback

from email.mime.text import MIMEText

from email.header import Header

from datetime import datetime

warnings.filterwarnings("ignore")

import yfinance as yf

import pandas as pd

import numpy as np

from flask import Flask, jsonify

VERSION = "v33.20"

JST = "Asia/Tokyo"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")

CACHE_DIR = os.path.join(DATA_DIR, "cache")

RESEARCH_DIR = os.path.join(DATA_DIR, "research")

os.makedirs(DATA_DIR, exist_ok=True)

os.makedirs(CACHE_DIR, exist_ok=True)

os.makedirs(RESEARCH_DIR, exist_ok=True)

DAILY_CACHE_FILE = os.path.join(CACHE_DIR, "daily_cache.pkl")

PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")

TRADE_FILE = os.path.join(DATA_DIR, "paper_trades.csv")

CANDIDATE_FILE = os.path.join(DATA_DIR, "paper_candidates.csv")

RESULT_FILE = os.path.join(DATA_DIR, "latest_result.txt")

RESEARCH_FILE = os.path.join(RESEARCH_DIR, "screening_history.csv")

GCS_BUCKET = os.environ.get("GCS_BUCKET", "")

GCS_RESEARCH_PATH = "research/screening_history.csv"

GCS_RESULT_PATH = "latest_result.txt"

GCS_PORTFOLIO_PATH = "portfolio/v29_4_portfolio.json"

GCS_TRADE_PATH = "trades/v29_4_trades.csv"

SMTP_HOST = os.environ.get("SMTP_HOST", "")

SMTP_PORT = os.environ.get("SMTP_PORT", "")

SMTP_USER = os.environ.get("SMTP_USER", "")

SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD") or os.environ.get("MAIL_PASS", "")

MAIL_USER = os.environ.get("MAIL_USER") or SMTP_USER

MAIL_PASS = os.environ.get("MAIL_PASS") or SMTP_PASSWORD

MAIL_TO = os.environ.get("MAIL_TO", "")

INITIAL_CAPITAL = 1_117_792

LONG_LEVERAGE = 1.0

SHORT_LEVERAGE = 1.0

MAX_LONG_POSITIONS = 1

MAX_SHORT_POSITIONS = 1

LONG_RS_THRESHOLD = 70.0

SHORT_RS_THRESHOLD = 30.0

RS_LOOKBACK = 20

TP = 0.020

SL = 0.015

LOT_SIZE = 100

DECISION_TIME = "12:45"

ENTRY_TIME = "12:50"

RESULT_TIME = "15:45"

TICKERS = [

    "1332.T","1605.T","1801.T","1802.T","1803.T",

    "1925.T","1928.T","1963.T","2002.T","2267.T",

    "2413.T","2502.T","2503.T","2801.T","2914.T",

    "3086.T","3092.T","3099.T","3382.T","3401.T",

    "3402.T","3407.T","3436.T","3659.T","3861.T",

    "4004.T","4005.T","4021.T","4042.T","4061.T",

    "4062.T","4183.T","4188.T","4208.T","4307.T",

    "4324.T","4385.T","4452.T","4502.T","4503.T",

    "4506.T","4507.T","4519.T","4523.T","4543.T",

    "4568.T","4578.T","4661.T","4689.T","4704.T",

    "4751.T","4755.T","4901.T","4911.T","5020.T",

    "5101.T","5108.T","5201.T","5214.T","5232.T",

    "5233.T","5301.T","5332.T","5333.T","5401.T",

    "5406.T","5411.T","5631.T","5706.T","5711.T",

    "5713.T","5714.T","5801.T","5802.T","5803.T",

    "5831.T","6098.T","6103.T","6113.T","6301.T",

    "6302.T","6305.T","6326.T","6361.T","6367.T",

    "6471.T","6472.T","6473.T","6479.T","6501.T",

    "6503.T","6504.T","6506.T","6526.T","6594.T",

    "6645.T","6674.T","6701.T","6702.T","6723.T",

    "6724.T","6752.T","6758.T","6762.T","6770.T",

    "6841.T","6857.T","6861.T","6869.T","6902.T",

    "6920.T","6952.T","6954.T","6971.T","6976.T",

    "6981.T","7003.T","7004.T","7011.T","7012.T",

    "7013.T","7182.T","7201.T","7202.T","7203.T",

    "7206.T","7207.T","7261.T","7267.T","7269.T",

    "7270.T","7272.T","7309.T","7731.T","7733.T",

    "7735.T","7741.T","7751.T","7752.T"

]

EXCLUDED_TICKERS = {"7205.T", "7206.T", "7207.T"}

TICKERS = list(dict.fromkeys(x for x in TICKERS if x not in EXCLUDED_TICKERS))

if len(TICKERS) != 137:

    raise RuntimeError(f"Universe error: expected 137 tickers, got {len(TICKERS)}")

app = Flask(__name__)

# ============================================================

# GCS REST

# ============================================================

def gcs_token():

    try:

        req = urllib.request.Request(

            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",

            headers={"Metadata-Flavor": "Google"}

        )

        with urllib.request.urlopen(req, timeout=10) as r:

            return json.loads(r.read().decode())["access_token"]

    except Exception:

        return None

def gcs_download(remote_path, local_path):

    if not GCS_BUCKET:

        return False

    token = gcs_token()

    if not token:

        return False

    url = (

        "https://storage.googleapis.com/storage/v1/b/"

        + urllib.parse.quote(GCS_BUCKET, safe="")

        + "/o/"

        + urllib.parse.quote(remote_path, safe="")

        + "?alt=media"

    )

    try:

        req = urllib.request.Request(

            url,

            headers={"Authorization": f"Bearer {token}"}

        )

        with urllib.request.urlopen(req, timeout=30) as r:

            data = r.read()

        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        with open(local_path, "wb") as f:

            f.write(data)

        return True

    except Exception as e:

        print(f"GCS download failed: {remote_path}: {e}")

        return False

def gcs_upload(local_path, remote_path, content_type="application/octet-stream"):

    if not GCS_BUCKET or not os.path.exists(local_path):

        return False

    token = gcs_token()

    if not token:

        return False

    url = (

        "https://storage.googleapis.com/upload/storage/v1/b/"

        + urllib.parse.quote(GCS_BUCKET, safe="")

        + "/o?uploadType=media&name="

        + urllib.parse.quote(remote_path, safe="")

    )

    try:

        with open(local_path, "rb") as f:

            data = f.read()

        req = urllib.request.Request(

            url,

            data=data,

            method="POST",

            headers={

                "Authorization": f"Bearer {token}",

                "Content-Type": content_type,

                "Content-Length": str(len(data))

            }

        )

        with urllib.request.urlopen(req, timeout=60) as r:

            r.read()

        print(f"GCS upload completed: gs://{GCS_BUCKET}/{remote_path}")

        return True

    except Exception as e:

        print(f"GCS upload failed: {remote_path}: {e}")

        return False

def restore_state_from_gcs():

    if not GCS_BUCKET:

        return

    if not os.path.exists(PORTFOLIO_FILE):

        gcs_download(

            GCS_PORTFOLIO_PATH,

            PORTFOLIO_FILE

        )

    if not os.path.exists(TRADE_FILE):

        gcs_download(

            GCS_TRADE_PATH,

            TRADE_FILE

        )

    if not os.path.exists(RESEARCH_FILE):

        gcs_download(

            GCS_RESEARCH_PATH,

            RESEARCH_FILE

        )

def upload_state_to_gcs():

    gcs_upload(

        PORTFOLIO_FILE,

        GCS_PORTFOLIO_PATH,

        "application/json"

    )

    gcs_upload(

        TRADE_FILE,

        GCS_TRADE_PATH,

        "text/csv"

    )

    gcs_upload(

        RESEARCH_FILE,

        GCS_RESEARCH_PATH,

        "text/csv"

    )

# ============================================================

# EMAIL

# ============================================================

def send_email(subject, body):

    if not MAIL_TO:

        print("MAIL_TO not set")

        return False

    if not SMTP_HOST or not SMTP_PORT:

        print("SMTP settings not set")

        return False

    if not SMTP_USER or not SMTP_PASSWORD:

        print("SMTP credentials not set")

        return False

    try:

        port = int(SMTP_PORT)

        msg = MIMEText(

            body,

            "plain",

            "utf-8"

        )

        msg["Subject"] = str(

            Header(subject, "utf-8")

        )

        msg["From"] = MAIL_USER or SMTP_USER

        msg["To"] = MAIL_TO

        if port == 465:

            with smtplib.SMTP_SSL(

                SMTP_HOST,

                port,

                timeout=30

            ) as server:

                server.login(

                    SMTP_USER,

                    SMTP_PASSWORD

                )

                server.sendmail(

                    MAIL_USER or SMTP_USER,

                    [MAIL_TO],

                    msg.as_string()

                )

        else:

            with smtplib.SMTP(

                SMTP_HOST,

                port,

                timeout=30

            ) as server:

                server.ehlo()

                server.starttls(

                    context=ssl.create_default_context()

                )

                server.ehlo()

                server.login(

                    SMTP_USER,

                    SMTP_PASSWORD

                )

                server.sendmail(

                    MAIL_USER or SMTP_USER,

                    [MAIL_TO],

                    msg.as_string()

                )

        print("Email sent successfully")

        return True

    except Exception as e:

        print(f"Email send failed: {type(e).__name__}: {e}")

        return False

# ============================================================

# RESULT

# ============================================================

def write_result(text):

    with open(

        RESULT_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        f.write(text)

    print(text)

    gcs_upload(

        RESULT_FILE,

        GCS_RESULT_PATH,

        "text/plain"

    )

    mode = os.environ.get("RUN_MODE", "test")

    send_email(

        f"{VERSION} {mode.upper()}",

        text

    )

# ============================================================

# PORTFOLIO

# ============================================================

def load_portfolio():

    restore_state_from_gcs()

    if not os.path.exists(PORTFOLIO_FILE):

        return {

            "equity": INITIAL_CAPITAL,

            "positions": []

        }

    try:

        with open(

            PORTFOLIO_FILE,

            "r",

            encoding="utf-8"

        ) as f:

            data = json.load(f)

    except Exception:

        return {

            "equity": INITIAL_CAPITAL,

            "positions": []

        }

    data.setdefault("equity", INITIAL_CAPITAL)

    data.setdefault("positions", [])

    return data

def save_portfolio(data):

    with open(

        PORTFOLIO_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            data,

            f,

            ensure_ascii=False,

            indent=2

        )

    gcs_upload(

        PORTFOLIO_FILE,

        GCS_PORTFOLIO_PATH,

        "application/json"

    )

# ============================================================

# INDEX

# ============================================================

def normalize_index(df):

    if df is None or df.empty:

        return df

    try:

        if getattr(df.index, "tz", None) is not None:

            df.index = (

                df.index

                .tz_convert(JST)

                .tz_localize(None)

            )

    except Exception:

        pass

    return df

# ============================================================

# 5MIN

# ============================================================

def download_5m():

    try:

        data = yf.download(

            tickers=TICKERS,

            period="1d",

            interval="5m",

            auto_adjust=False,

            progress=False,

            threads=True,

            group_by="ticker"

        )

    except Exception as e:

        print(f"5m download failed: {e}")

        return {}

    if data is None or data.empty:

        return {}

    data = normalize_index(data)

    if not isinstance(data.columns, pd.MultiIndex):

        return {}

    result = {}

    level0 = set(data.columns.get_level_values(0))

    level1 = set(data.columns.get_level_values(1))

    required = [

        "Open",

        "High",

        "Low",

        "Close",

        "Volume"

    ]

    if any(t in level0 for t in TICKERS):

        for ticker in TICKERS:

            if ticker not in level0:

                continue

            try:

                df = data[ticker].copy()

                if not all(c in df.columns for c in required):

                    continue

                df = df[required]

                df = df.dropna(subset=["Close"])

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    elif any(t in level1 for t in TICKERS):

        for ticker in TICKERS:

            if ticker not in level1:

                continue

            try:

                df = data.xs(

                    ticker,

                    axis=1,

                    level=1

                ).copy()

                if not all(c in df.columns for c in required):

                    continue

                df = df[required]

                df = df.dropna(subset=["Close"])

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    return result

# ============================================================

# DAILY CACHE

# ============================================================

def load_daily_cache():

    if not os.path.exists(DAILY_CACHE_FILE):

        return {}

    try:

        return pd.read_pickle(DAILY_CACHE_FILE)

    except Exception:

        return {}

def create_daily_cache():

    cache = load_daily_cache()

    if cache:

        valid = True

        for ticker in TICKERS:

            if ticker not in cache:

                valid = False

                break

            df = cache[ticker]

            if (

                df is None

                or df.empty

                or len(df) < RS_LOOKBACK + 5

            ):

                valid = False

                break

        if valid:

            return cache

    try:

        data = yf.download(

            tickers=TICKERS,

            period="6mo",

            interval="1d",

            auto_adjust=False,

            progress=False,

            threads=True,

            group_by="ticker"

        )

    except Exception as e:

        print(f"daily download failed: {e}")

        return cache

    if data is None or data.empty:

        return cache

    data = normalize_index(data)

    if not isinstance(data.columns, pd.MultiIndex):

        return cache

    result = {}

    required = [

        "Open",

        "High",

        "Low",

        "Close",

        "Volume"

    ]

    level0 = set(data.columns.get_level_values(0))

    level1 = set(data.columns.get_level_values(1))

    if any(t in level0 for t in TICKERS):

        for ticker in TICKERS:

            if ticker not in level0:

                continue

            try:

                df = data[ticker].copy()

                if not all(c in df.columns for c in required):

                    continue

                df = df[required].dropna(

                    subset=["Close"]

                )

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    elif any(t in level1 for t in TICKERS):

        for ticker in TICKERS:

            if ticker not in level1:

                continue

            try:

                df = data.xs(

                    ticker,

                    axis=1,

                    level=1

                ).copy()

                if not all(c in df.columns for c in required):

                    continue

                df = df[required].dropna(

                    subset=["Close"]

                )

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    if result:

        try:

            pd.to_pickle(

                result,

                DAILY_CACHE_FILE

            )

        except Exception:

            pass

        return result

    return cache

# ============================================================

# BUSINESS DAY

# ============================================================

def get_last_business_day():

    now = pd.Timestamp.now(

        tz=JST

    ).tz_localize(None)

    date = now.normalize()

    while date.weekday() >= 5:

        date -= pd.Timedelta(days=1)

    return date

# ============================================================

# RS

# ============================================================

def calc_rs(daily_df, target_date):

    if daily_df is None or daily_df.empty:

        return np.nan

    past = daily_df[

        daily_df.index.date < target_date.date()

    ]

    if len(past) < RS_LOOKBACK + 1:

        return np.nan

    current = float(

        past["Close"].iloc[-1]

    )

    old = float(

        past["Close"].iloc[-RS_LOOKBACK - 1]

    )

    if old <= 0:

        return np.nan

    return current / old - 1

# ============================================================

# CANDIDATE

# ============================================================

def make_candidate(

    ticker,

    intraday,

    daily,

    target_date

):

    if (

        intraday is None

        or daily is None

        or intraday.empty

        or daily.empty

    ):

        return None

    target = target_date.date()

    day = intraday[

        intraday.index.date == target

    ]

    if day.empty:

        return None

    decision_ts = pd.Timestamp(

        f"{target_date:%Y-%m-%d} {DECISION_TIME}:00"

    )

    before = day[

        day.index <= decision_ts

    ]

    if before.empty:

        return None

    decision_bar = before.iloc[-1]

    close_1245 = float(

        decision_bar["Close"]

    )

    morning = day[

        day.index <

        pd.Timestamp(

            f"{target_date:%Y-%m-%d} 12:00:00"

        )

    ]

    if morning.empty:

        return None

    morning_high = float(

        morning["High"].max()

    )

    morning_low = float(

        morning["Low"].min()

    )

    volume = (

        before["Volume"]

        .fillna(0)

        .astype(float)

    )

    if volume.sum() > 0:

        vwap = float(

            (

                before["Close"] * volume

            ).sum()

            / volume.sum()

        )

    else:

        vwap = close_1245

    past = daily[

        daily.index.date < target

    ]

    if past.empty:

        return None

    prev_close = float(

        past["Close"].iloc[-1]

    )

    if prev_close <= 0:

        return None

    day_return = close_1245 / prev_close - 1

    afternoon = before[

        before.index >=

        pd.Timestamp(

            f"{target_date:%Y-%m-%d} 12:00:00"

        )

    ]

    if not afternoon.empty:

        afternoon_open = float(

            afternoon["Open"].iloc[0]

        )

        if afternoon_open > 0:

            afternoon_return = (

                close_1245 /

                afternoon_open -

                1

            )

        else:

            afternoon_return = 0.0

    else:

        afternoon_return = 0.0

    recent = before.tail(3)

    if len(recent) >= 2:

        first_close = float(

            recent["Close"].iloc[0]

        )

        if first_close > 0:

            recent_return = (

                close_1245 /

                first_close -

                1

            )

        else:

            recent_return = 0.0

    else:

        recent_return = 0.0

    raw_rs = calc_rs(

        daily,

        target_date

    )

    if pd.isna(raw_rs):

        return None

    return {

        "ticker": ticker,

        "date": str(target),

        "morning_high": morning_high,

        "morning_low": morning_low,

        "close_1245": close_1245,

        "vwap": vwap,

        "prev_close": prev_close,

        "day_return": day_return,

        "afternoon_return": afternoon_return,

        "recent_return": recent_return,

        "raw_rs": raw_rs

    }

# ============================================================

# SELECT

# ============================================================

def select_candidates(

    intraday,

    daily,

    target_date

):

    rows = []

    for ticker in TICKERS:

        try:

            row = make_candidate(

                ticker,

                intraday.get(ticker),

                daily.get(ticker),

                target_date

            )

            if row is not None:

                rows.append(row)

        except Exception:

            continue

    if not rows:

        return pd.DataFrame(), pd.DataFrame()

    df = pd.DataFrame(rows)

    df["RS"] = (

        df["raw_rs"].rank(pct=True) * 100

    )

    day_score = (

        df["day_return"].rank(pct=True) * 100

    )

    afternoon_score = (

        df["afternoon_return"].rank(pct=True) * 100

    )

    recent_score = (

        df["recent_return"].rank(pct=True) * 100

    )

    df["score"] = (

        df["RS"] * 0.30

        + day_score * 0.30

        + afternoon_score * 0.25

        + recent_score * 0.15

    )

    df["long_rs_ok"] = (

        df["RS"] >= LONG_RS_THRESHOLD

    )

    df["long_breakout"] = (

        df["close_1245"] > df["morning_high"]

    )

    df["long_candidate"] = (

        df["long_rs_ok"] &

        df["long_breakout"]

    )

    df["short_rs_ok"] = (

        df["RS"] <= SHORT_RS_THRESHOLD

    )

    df["short_breakdown"] = (

        df["close_1245"] < df["morning_low"]

    )

    df["short_candidate"] = (

        df["short_rs_ok"] &

        df["short_breakdown"]

    )

    df["selected_side"] = ""

    return df, pd.DataFrame()

# ============================================================

# SHARES

# ============================================================

def calculate_shares(

    entry_price,

    equity,

    leverage

):

    if entry_price <= 0:

        return 0

    max_value = equity * leverage

    shares = int(

        max_value // entry_price

    )

    shares = (

        shares // LOT_SIZE

    ) * LOT_SIZE

    return max(shares, 0)

# ============================================================

# POSITIONS

# ============================================================

def create_positions(

    selected_df,

    intraday,

    equity,

    target_date

):

    positions = []

    if selected_df.empty:

        return positions

    for _, row in selected_df.iterrows():

        ticker = row["ticker"]

        side = row["side"]

        df = intraday.get(ticker)

        if df is None or df.empty:

            continue

        entry_ts = pd.Timestamp(

            f"{target_date:%Y-%m-%d} {ENTRY_TIME}:00"

        )

        entry_rows = df[

            df.index >= entry_ts

        ]

        if entry_rows.empty:

            continue

        entry_price = float(

            entry_rows.iloc[0]["Open"]

        )

        if entry_price <= 0:

            continue

        leverage = (

            LONG_LEVERAGE

            if side == "LONG"

            else SHORT_LEVERAGE

        )

        shares = calculate_shares(

            entry_price,

            equity,

            leverage

        )

        if shares < LOT_SIZE:

            continue

        entry_value = (

            entry_price * shares

        )

        if side == "LONG":

            tp_price = entry_price * (1 + TP)

            sl_price = entry_price * (1 - SL)

        else:

            tp_price = entry_price * (1 - TP)

            sl_price = entry_price * (1 + SL)

        positions.append({

            "ticker": ticker,

            "side": side,

            "shares": int(shares),

            "entry_price": entry_price,

            "entry_value": entry_value,

            "tp_price": tp_price,

            "sl_price": sl_price,

            "entry_time": str(entry_ts),

            "entry_date": str(target_date.date())

        })

    return positions

# ============================================================

# POSITION CHECK

# ============================================================

def check_position(position, intraday):

    ticker = position["ticker"]

    df = intraday.get(ticker)

    if df is None or df.empty:

        return False, None, None, None

    entry_time = pd.Timestamp(

        position["entry_time"]

    )

    after = df[

        df.index > entry_time

    ]

    if after.empty:

        return False, None, None, None

    side = position["side"]

    tp_price = float(position["tp_price"])

    sl_price = float(position["sl_price"])

    for idx, bar in after.iterrows():

        high = float(bar["High"])

        low = float(bar["Low"])

        if side == "LONG":

            if low <= sl_price:

                return True, sl_price, "SL", idx

            if high >= tp_price:

                return True, tp_price, "TP", idx

        else:

            if high >= sl_price:

                return True, sl_price, "SL", idx

            if low <= tp_price:

                return True, tp_price, "TP", idx

    return False, None, None, None

# ============================================================

# RESEARCH

# ============================================================

def prepare_research_rows(

    df,

    intraday,

    target_date,

    selected_positions

):

    if df is None or df.empty:

        return pd.DataFrame()

    result = []

    selected_map = {

        p["ticker"]: p

        for p in selected_positions

    }

    for _, row in df.iterrows():

        ticker = row["ticker"]

        item = {

            "date": row["date"],

            "ticker": ticker,

            "close_1245": row["close_1245"],

            "morning_high": row["morning_high"],

            "morning_low": row["morning_low"],

            "vwap": row["vwap"],

            "prev_close": row["prev_close"],

            "day_return": row["day_return"],

            "afternoon_return": row["afternoon_return"],

            "recent_return": row["recent_return"],

            "raw_rs": row["raw_rs"],

            "RS": row["RS"],

            "score": row["score"],

            "long_rs_ok": bool(row["long_rs_ok"]),

            "long_breakout": bool(row["long_breakout"]),

            "long_candidate": bool(row["long_candidate"]),

            "short_rs_ok": bool(row["short_rs_ok"]),

            "short_breakdown": bool(row["short_breakdown"]),

            "short_candidate": bool(row["short_candidate"]),

            "selected_side": row["selected_side"]

        }

        stock_df = intraday.get(ticker)

        entry_price = np.nan

        post_high = np.nan

        post_low = np.nan

        close_1545 = np.nan

        long_tp_hit = False

        long_sl_hit = False

        short_tp_hit = False

        short_sl_hit = False

        hypothetical_result = ""

        if stock_df is not None and not stock_df.empty:

            entry_ts = pd.Timestamp(

                f"{target_date:%Y-%m-%d} {ENTRY_TIME}:00"

            )

            result_ts = pd.Timestamp(

                f"{target_date:%Y-%m-%d} {RESULT_TIME}:00"

            )

            after_entry = stock_df[

                (stock_df.index >= entry_ts) &

                (stock_df.index <= result_ts)

            ]

            if not after_entry.empty:

                entry_price = float(

                    after_entry.iloc[0]["Open"]

                )

                post_high = float(

                    after_entry["High"].max()

                )

                post_low = float(

                    after_entry["Low"].min()

                )

                close_1545 = float(

                    after_entry.iloc[-1]["Close"]

                )

                long_tp = entry_price * (1 + TP)

                long_sl = entry_price * (1 - SL)

                short_tp = entry_price * (1 - TP)

                short_sl = entry_price * (1 + SL)

                long_tp_hit = post_high >= long_tp

                long_sl_hit = post_low <= long_sl

                short_tp_hit = post_low <= short_tp

                short_sl_hit = post_high >= short_sl

        item["entry_1250"] = entry_price

        item["post_1250_high"] = post_high

        item["post_1250_low"] = post_low

        item["close_1545"] = close_1545

        item["long_tp_hit"] = long_tp_hit

        item["long_sl_hit"] = long_sl_hit

        item["short_tp_hit"] = short_tp_hit

        item["short_sl_hit"] = short_sl_hit

        if ticker in selected_map:

            side = selected_map[ticker]["side"]

            if side == "LONG":

                if long_sl_hit:

                    hypothetical_result = "SL"

                elif long_tp_hit:

                    hypothetical_result = "TP"

                else:

                    hypothetical_result = "HOLD"

            else:

                if short_sl_hit:

                    hypothetical_result = "SL"

                elif short_tp_hit:

                    hypothetical_result = "TP"

                else:

                    hypothetical_result = "HOLD"

        item["hypothetical_result"] = hypothetical_result

        if (

            not pd.isna(entry_price)

            and not pd.isna(close_1545)

            and entry_price > 0

        ):

            item["long_return_1250_1545"] = (

                close_1545 / entry_price - 1

            )

            item["short_return_1250_1545"] = (

                entry_price / close_1545 - 1

            )

        else:

            item["long_return_1250_1545"] = np.nan

            item["short_return_1250_1545"] = np.nan

        result.append(item)

    return pd.DataFrame(result)

def save_research_data(

    research_df,

    target_date

):

    if research_df is None or research_df.empty:

        return

    date_str = target_date.strftime("%Y-%m-%d")

    if os.path.exists(RESEARCH_FILE):

        try:

            old_df = pd.read_csv(RESEARCH_FILE)

        except Exception:

            old_df = pd.DataFrame()

    else:

        old_df = pd.DataFrame()

    if (

        not old_df.empty

        and "date" in old_df.columns

    ):

        old_df = old_df[

            old_df["date"].astype(str) != date_str

        ]

    combined = pd.concat(

        [old_df, research_df],

        ignore_index=True

    )

    combined = combined.sort_values(

        ["date", "ticker"]

    )

    combined.to_csv(

        RESEARCH_FILE,

        index=False,

        encoding="utf-8-sig"

    )

    gcs_upload(

        RESEARCH_FILE,

        GCS_RESEARCH_PATH,

        "text/csv"

    )

def update_research_after_close(

    intraday,

    target_date

):

    if not os.path.exists(RESEARCH_FILE):

        return

    try:

        research = pd.read_csv(RESEARCH_FILE)

    except Exception:

        return

    if research.empty:

        return

    date_str = target_date.strftime("%Y-%m-%d")

    mask = (

        research["date"].astype(str) == date_str

    )

    if not mask.any():

        return

    for idx in research.index[mask]:

        ticker = research.loc[idx, "ticker"]

        df = intraday.get(ticker)

        if df is None or df.empty:

            continue

        entry_ts = pd.Timestamp(

            f"{date_str} {ENTRY_TIME}:00"

        )

        result_ts = pd.Timestamp(

            f"{date_str} {RESULT_TIME}:00"

        )

        after = df[

            (df.index >= entry_ts) &

            (df.index <= result_ts)

        ]

        if after.empty:

            continue

        try:

            entry_price = float(

                after.iloc[0]["Open"]

            )

            post_high = float(

                after["High"].max()

            )

            post_low = float(

                after["Low"].min()

            )

            close_price = float(

                after.iloc[-1]["Close"]

            )

        except Exception:

            continue

        research.loc[idx, "entry_1250"] = entry_price

        research.loc[idx, "post_1250_high"] = post_high

        research.loc[idx, "post_1250_low"] = post_low

        research.loc[idx, "close_1545"] = close_price

        long_tp = entry_price * (1 + TP)

        long_sl = entry_price * (1 - SL)

        short_tp = entry_price * (1 - TP)

        short_sl = entry_price * (1 + SL)

        research.loc[idx, "long_tp_hit"] = (

            post_high >= long_tp

        )

        research.loc[idx, "long_sl_hit"] = (

            post_low <= long_sl

        )

        research.loc[idx, "short_tp_hit"] = (

            post_low <= short_tp

        )

        research.loc[idx, "short_sl_hit"] = (

            post_high >= short_sl

        )

        research.loc[idx, "long_return_1250_1545"] = (

            close_price / entry_price - 1

        )

        research.loc[idx, "short_return_1250_1545"] = (

            entry_price / close_price - 1

        )

        selected_side = str(

            research.loc[idx, "selected_side"]

        )

        if selected_side == "LONG":

            if post_low <= long_sl:

                result = "SL"

            elif post_high >= long_tp:

                result = "TP"

            else:

                result = "HOLD"

            research.loc[

                idx,

                "hypothetical_result"

            ] = result

        elif selected_side == "SHORT":

            if post_high >= short_sl:

                result = "SL"

            elif post_low <= short_tp:

                result = "TP"

            else:

                result = "HOLD"

            research.loc[

                idx,

                "hypothetical_result"

            ] = result

    research.to_csv(

        RESEARCH_FILE,

        index=False,

        encoding="utf-8-sig"

    )

    gcs_upload(

        RESEARCH_FILE,

        GCS_RESEARCH_PATH,

        "text/csv"

    )

# ============================================================

# RESULT MODE

# ============================================================

def run_result():

    portfolio = load_portfolio()

    old_equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

    intraday = download_5m()

    now = pd.Timestamp.now(

        tz=JST

    ).tz_localize(None)

    target_date = now.normalize()

    update_research_after_close(

        intraday,

        target_date

    )

    if not positions:

        text = (

            "15:45 結果\n\n"

            f"前資産: ¥{old_equity:,.0f}\n"

            "損益: ¥0\n"

            f"現在資産: ¥{old_equity:,.0f}\n\n"

            "決済: なし\n"

            "持越し: なし\n\n"

            "研究データ更新: 完了\n"

            f"保存: {len(TICKERS)}銘柄\n"

        )

        write_result(text)

        return

    remaining = []

    closed = []

    total_pnl = 0.0

    for position in positions:

        hit, exit_price, reason, exit_time = (

            check_position(

                position,

                intraday

            )

        )

        if not hit:

            remaining.append(position)

            continue

        entry_price = float(

            position["entry_price"]

        )

        shares = int(

            position["shares"]

        )

        side = position["side"]

        if side == "LONG":

            ret = exit_price / entry_price - 1

        else:

            ret = entry_price / exit_price - 1

        pnl = (

            entry_price *

            shares *

            ret

        )

        total_pnl += pnl

        closed.append({

            "date": str(exit_time.date()),

            "ticker": position["ticker"],

            "side": side,

            "shares": shares,

            "entry": entry_price,

            "exit": exit_price,

            "return": ret,

            "pnl": pnl,

            "reason": reason,

            "entry_time": position["entry_time"],

            "exit_time": str(exit_time)

        })

    new_equity = old_equity + total_pnl

    portfolio["equity"] = new_equity

    portfolio["positions"] = remaining

    portfolio["last_update"] = datetime.now().strftime(

        "%Y-%m-%d %H:%M:%S"

    )

    save_portfolio(portfolio)

    if closed:

        trade_df = pd.DataFrame(closed)

        if os.path.exists(TRADE_FILE):

            try:

                old_df = pd.read_csv(TRADE_FILE)

                trade_df = pd.concat(

                    [old_df, trade_df],

                    ignore_index=True

                )

            except Exception:

                pass

        trade_df.to_csv(

            TRADE_FILE,

            index=False,

            encoding="utf-8-sig"

        )

        gcs_upload(

            TRADE_FILE,

            GCS_TRADE_PATH,

            "text/csv"

        )

    lines = [

        "15:45 結果",

        "",

        f"前資産: ¥{old_equity:,.0f}",

        f"損益: ¥{total_pnl:,.0f}",

        f"現在資産: ¥{new_equity:,.0f}",

        ""

    ]

    if closed:

        lines.append("決済:")

        for trade in closed:

            lines.append(

                f"{trade['side']} "

                f"{trade['ticker']} "

                f"{trade['shares']}株 "

                f"{trade['reason']} "

                f"損益 ¥{trade['pnl']:,.0f}"

            )

    else:

        lines.append("決済: なし")

    lines.append("")

    if remaining:

        lines.append("持越し:")

        for position in remaining:

            lines.append(

                f"{position['side']} "

                f"{position['ticker']} "

                f"{position['shares']}株 "

                f"建値 {position['entry_price']:,.1f}円"

            )

    else:

        lines.append("持越し: なし")

    lines.extend([

        "",

        "研究データ更新: 完了",

        f"保存: {len(TICKERS)}銘柄"

    ])

    write_result(

        "\n".join(lines)

    )

# ============================================================

# DECISION

# ============================================================

def run_decision(

    target_date=None,

    test_mode=False

):

    portfolio = load_portfolio()

    equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

    if target_date is None:

        now = pd.Timestamp.now(

            tz=JST

        ).tz_localize(None)

        target_date = now.normalize()

    long_count = sum(

        1 for p in positions

        if p.get("side") == "LONG"

    )

    short_count = sum(

        1 for p in positions

        if p.get("side") == "SHORT"

    )

    intraday = download_5m()

    daily = load_daily_cache()

    if not daily:

        daily = create_daily_cache()

    if target_date.weekday() >= 5:

        text = (

            f"12:45 {'TEST' if test_mode else ''}判定\n"

            f"判定日: {target_date:%Y-%m-%d}\n"

            f"現在資産: ¥{equity:,.0f}\n"

            "LONG: なし\n"

            "SHORT: なし\n"

            "新規取引: 0件\n"

            "------------------------------\n"

            "判定結果: 休場日\n"

        )

        write_result(text)

        return

    all_df, _ = select_candidates(

        intraday,

        daily,

        target_date

    )

    target_count = len(all_df)

    if not all_df.empty:

        long_rs_count = int(

            all_df["long_rs_ok"].sum()

        )

        long_breakout_count = int(

            (

                all_df["long_rs_ok"] &

                all_df["long_breakout"]

            ).sum()

        )

        long_candidate_count = int(

            all_df["long_candidate"].sum()

        )

        short_rs_count = int(

            all_df["short_rs_ok"].sum()

        )

        short_breakdown_count = int(

            (

                all_df["short_rs_ok"] &

                all_df["short_breakdown"]

            ).sum()

        )

        short_candidate_count = int(

            all_df["short_candidate"].sum()

        )

    else:

        long_rs_count = 0

        long_breakout_count = 0

        long_candidate_count = 0

        short_rs_count = 0

        short_breakdown_count = 0

        short_candidate_count = 0

    selected_rows = []

    if (

        not all_df.empty

        and long_count < MAX_LONG_POSITIONS

    ):

        long_df = all_df[

            all_df["long_candidate"]

        ].copy()

        if not long_df.empty:

            long_df = long_df.sort_values(

                "score",

                ascending=False

            )

            row = long_df.iloc[0].copy()

            row["side"] = "LONG"

            selected_rows.append(row)

    if (

        not all_df.empty

        and short_count < MAX_SHORT_POSITIONS

    ):

        short_df = all_df[

            all_df["short_candidate"]

        ].copy()

        if not short_df.empty:

            short_df = short_df.sort_values(

                "score",

                ascending=True

            )

            row = short_df.iloc[0].copy()

            row["side"] = "SHORT"

            selected_rows.append(row)

    selected_df = (

        pd.DataFrame(selected_rows)

        if selected_rows

        else pd.DataFrame()

    )

    new_positions = create_positions(

        selected_df,

        intraday,

        equity,

        target_date

    )

    if new_positions and not test_mode:

        portfolio["positions"].extend(

            new_positions

        )

        portfolio["last_update"] = (

            datetime.now().strftime(

                "%Y-%m-%d %H:%M:%S"

            )

        )

        save_portfolio(portfolio)

    research_df = prepare_research_rows(

        all_df,

        intraday,

        target_date,

        new_positions

    )

    if not research_df.empty:

        save_research_data(

            research_df,

            target_date

        )

    if not selected_df.empty:

        selected_df.to_csv(

            CANDIDATE_FILE,

            index=False,

            encoding="utf-8-sig"

        )

    lines = [

        "12:45 TEST判定" if test_mode else "12:45 判定",

        "",

        f"判定日: {target_date:%Y-%m-%d}",

        "",

        f"現在資産: ¥{equity:,.0f}",

        ""

    ]

    long_positions = [

        p for p in new_positions

        if p["side"] == "LONG"

    ]

    if long_positions:

        p = long_positions[0]

        lines.extend([

            f"LONG: {p['ticker']}",

            f"12:50 OPEN: {p['entry_price']:,.1f}円",

            f"株数: {p['shares']}株",

            f"建玉金額: ¥{p['entry_value']:,.0f}",

            f"TP: {p['tp_price']:,.1f}円",

            f"SL: {p['sl_price']:,.1f}円"

        ])

    else:

        lines.append("LONG: なし")

    lines.append("")

    short_positions = [

        p for p in new_positions

        if p["side"] == "SHORT"

    ]

    if short_positions:

        p = short_positions[0]

        lines.extend([

            f"SHORT: {p['ticker']}",

            f"12:50 OPEN: {p['entry_price']:,.1f}円",

            f"株数: {p['shares']}株",

            f"建玉金額: ¥{p['entry_value']:,.0f}",

            f"TP: {p['tp_price']:,.1f}円",

            f"SL: {p['sl_price']:,.1f}円"

        ])

    else:

        lines.append("SHORT: なし")

    lines.extend([

        "",

        f"新規取引: {len(new_positions)}件",

        "------------------------------",

        "判定状況",

        f"5分足取得: {len(intraday)}/{len(TICKERS)}",

        f"日足取得: {len(daily)}/{len(TICKERS)}",

        f"判定対象: {target_count}銘柄",

        "",

        "LONG",

        f"RS70以上: {long_rs_count}",

        f"前場高値突破: {long_breakout_count}",

        f"最終候補: {long_candidate_count}",

        "",

        "SHORT",

        f"RS30以下: {short_rs_count}",

        f"前場安値割れ: {short_breakdown_count}",

        f"最終候補: {short_candidate_count}",

        "",

        "LONG上位候補:"

    ])

    if not all_df.empty:

        long_top = all_df[

            all_df["long_rs_ok"]

        ].sort_values(

            "RS",

            ascending=False

        ).head(3)

        for _, r in long_top.iterrows():

            lines.append(

                f"{r['ticker']} "

                f"RS {r['RS']:.1f} "

                f"12:45 {r['close_1245']:,.1f} "

                f"前場高値 {r['morning_high']:,.1f}"

            )

    else:

        lines.append("なし")

    lines.append("SHORT上位候補:")

    if not all_df.empty:

        short_top = all_df[

            all_df["short_rs_ok"]

        ].sort_values(

            "RS",

            ascending=True

        ).head(3)

        for _, r in short_top.iterrows():

            lines.append(

                f"{r['ticker']} "

                f"RS {r['RS']:.1f} "

                f"12:45 {r['close_1245']:,.1f} "

                f"前場安値 {r['morning_low']:,.1f}"

            )

    else:

        lines.append("なし")

    lines.append("")

    if new_positions:

        lines.append(

            f"判定結果: {len(new_positions)}件取引"

        )

    elif target_count == 0:

        lines.append(

            "判定結果: 判定対象データなし"

        )

    else:

        lines.append(

            "判定結果: 条件一致なし"

        )

    lines.extend([

        "------------------------------",

        f"研究データ保存: {len(research_df)}銘柄"

    ])

    if test_mode:

        lines.extend([

            "TESTモード",

            "実際のポートフォリオには取引を追加していません",

            "最終営業日の判定を再現しました"

        ])

    write_result(

        "\n".join(lines)

    )

# ============================================================

# TEST

# ============================================================

def run_test():

    run_decision(

        target_date=get_last_business_day(),

        test_mode=True

    )

# ============================================================

# RUN

# ============================================================

def get_run_mode():

    mode = os.environ.get(

        "RUN_MODE",

        ""

    ).strip().lower()

    if mode in (

        "decision",

        "result",

        "test"

    ):

        return mode

    now = pd.Timestamp.now(

        tz=JST

    )

    return (

        "decision"

        if now.hour < 14

        else "result"

    )

def execute():

    restore_state_from_gcs()

    mode = get_run_mode()

    print(f"{VERSION} START")

    print(f"RUN MODE: {mode}")

    print(f"UNIVERSE: {len(TICKERS)}")

    try:

        if mode == "decision":

            run_decision()

        elif mode == "result":

            run_result()

        elif mode == "test":

            run_test()

        else:

            raise ValueError(

                f"Unknown RUN_MODE: {mode}"

            )

    except Exception as e:

        error_text = (

            f"{VERSION} ERROR\n\n"

            f"RUN MODE: {mode}\n\n"

            f"{type(e).__name__}: {e}\n\n"

            f"{traceback.format_exc()}"

        )

        write_result(error_text)

        raise

    finally:

        upload_state_to_gcs()

        print(f"{VERSION} END")

# ============================================================

# CLOUD RUN

# ============================================================

@app.get("/")

def health():

    return jsonify({

        "status": "ok",

        "version": VERSION

    })

@app.get("/run")

def cloud_run_execute():

    try:

        execute()

        return jsonify({

            "status": "success",

            "version": VERSION,

            "run_mode": os.environ.get(

                "RUN_MODE",

                ""

            )

        })

    except Exception as e:

        return jsonify({

            "status": "error",

            "error": str(e)

        }), 500
