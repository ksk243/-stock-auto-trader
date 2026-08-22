# ============================================================

# v33.16 Cloud Run Paper Trader

# ============================================================

import os

import json

import traceback

import warnings

import time

from datetime import datetime

warnings.filterwarnings("ignore")

import yfinance as yf

import pandas as pd

import numpy as np

# ============================================================

# VERSION

# ============================================================

VERSION = "v33.16"

# ============================================================

# PATH

# ============================================================

BASE_DIR = os.path.dirname(

    os.path.abspath(__file__)

)

DATA_DIR = os.path.join(

    BASE_DIR,

    "data"

)

CACHE_DIR = os.path.join(

    DATA_DIR,

    "cache"

)

os.makedirs(DATA_DIR, exist_ok=True)

os.makedirs(CACHE_DIR, exist_ok=True)

PORTFOLIO_FILE = os.path.join(

    DATA_DIR,

    "portfolio.json"

)

TRADE_FILE = os.path.join(

    DATA_DIR,

    "paper_trades.csv"

)

CANDIDATE_FILE = os.path.join(

    DATA_DIR,

    "paper_candidates.csv"

)

RESULT_FILE = os.path.join(

    DATA_DIR,

    "latest_result.txt"

)

DAILY_CACHE_FILE = os.path.join(

    CACHE_DIR,

    "daily_cache.pkl"

)

# ============================================================

# CAPITAL

# ============================================================

INITIAL_CAPITAL = 1_117_792

# ============================================================

# POSITION / LEVERAGE

# ============================================================

LONG_LEVERAGE = 1.0

SHORT_LEVERAGE = 1.0

MAX_LONG_POSITIONS = 1

MAX_SHORT_POSITIONS = 1

LOT_SIZE = 100

# ============================================================

# STRATEGY

# ============================================================

LONG_RS_THRESHOLD = 70.0

SHORT_RS_THRESHOLD = 30.0

RS_LOOKBACK = 20

TP = 0.020

SL = 0.015

# ============================================================

# TIME

# ============================================================

DECISION_TIME = "12:45"

ENTRY_TIME = "12:50"

# ============================================================

# SPEED

#

# RS条件を満たす銘柄のうち、

# 5分足を取得する最大数

#

# LONG 15

# SHORT 15

# 最大30銘柄

# ============================================================

MAX_LONG_INTRADAY = 15

MAX_SHORT_INTRADAY = 15

# ============================================================

# UNIVERSE

# ============================================================

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

    "7261.T","7267.T","7269.T","7270.T","7272.T",

    "7309.T","7731.T","7733.T","7735.T","7741.T",

    "7751.T","7752.T"

]

# ============================================================

# 除外銘柄

#

# Yahoo Financeで404 / No dataが発生する銘柄

# ============================================================

INVALID_TICKERS = {

    "7205.T",

    "7206.T",

    "7207.T"

}

TICKERS = [

    t

    for t in dict.fromkeys(TICKERS)

    if t not in INVALID_TICKERS

]

# ============================================================

# TIME LOGGER

# ============================================================

def log_time(label, start, total_start):

    elapsed = time.perf_counter() - start

    total = time.perf_counter() - total_start

    print(

        f"[TIME] {label}: "

        f"{elapsed:.2f}秒 "

        f"(累積 {total:.2f}秒)",

        flush=True

    )

    return elapsed

# ============================================================

# RESULT FILE

# ============================================================

def write_result(text):

    with open(

        RESULT_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        f.write(text)

    print(

        text,

        flush=True

    )

# ============================================================

# PORTFOLIO

# ============================================================

def load_portfolio():

    if not os.path.exists(

        PORTFOLIO_FILE

    ):

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

    data.setdefault(

        "equity",

        INITIAL_CAPITAL

    )

    data.setdefault(

        "positions",

        []

    )

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

# ============================================================

# INDEX

# ============================================================

def normalize_index(df):

    if df is None or df.empty:

        return df

    try:

        if getattr(

            df.index,

            "tz",

            None

        ) is not None:

            df.index = (

                df.index

                .tz_convert(

                    "Asia/Tokyo"

                )

                .tz_localize(None)

            )

    except Exception:

        pass

    return df

# ============================================================

# DAILY DATA

# ============================================================

def download_daily():

    try:

        data = yf.download(

            tickers=TICKERS,

            period="6mo",

            interval="1d",

            auto_adjust=False,

            progress=False,

            threads=True,

            group_by="ticker",

            timeout=15

        )

    except Exception as e:

        print(

            f"[DAILY ERROR] {type(e).__name__}: {e}",

            flush=True

        )

        return {}

    if data is None or data.empty:

        return {}

    data = normalize_index(data)

    result = {}

    if not isinstance(

        data.columns,

        pd.MultiIndex

    ):

        return result

    level0 = set(

        data.columns.get_level_values(0)

    )

    level1 = set(

        data.columns.get_level_values(1)

    )

    required = [

        "Open",

        "High",

        "Low",

        "Close",

        "Volume"

    ]

    # ========================================================

    # ticker = level 0

    # ========================================================

    if any(

        t in level0

        for t in TICKERS

    ):

        for ticker in TICKERS:

            if ticker not in level0:

                continue

            try:

                df = data[

                    ticker

                ].copy()

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=["Close"]

                )

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    # ========================================================

    # ticker = level 1

    # ========================================================

    elif any(

        t in level1

        for t in TICKERS

    ):

        for ticker in TICKERS:

            if ticker not in level1:

                continue

            try:

                df = data.xs(

                    ticker,

                    axis=1,

                    level=1

                ).copy()

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=["Close"]

                )

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    return result

# ============================================================

# DAILY CACHE

# ============================================================

def load_daily_cache():

    if not os.path.exists(

        DAILY_CACHE_FILE

    ):

        return {}

    try:

        return pd.read_pickle(

            DAILY_CACHE_FILE

        )

    except Exception:

        return {}

def get_daily_data():

    cache = load_daily_cache()

    today = pd.Timestamp.now(

        tz="Asia/Tokyo"

    ).date()

    if cache:

        valid = False

        for df in cache.values():

            if df is None or df.empty:

                continue

            try:

                last_date = df.index[-1].date()

                if last_date >= (

                    today -

                    pd.Timedelta(days=5)

                ).date():

                    valid = True

                    break

            except Exception:

                continue

        if valid:

            # ------------------------------------------------

            # 古いキャッシュから除外銘柄を削除

            # ------------------------------------------------

            cache = {

                k: v

                for k, v in cache.items()

                if k in TICKERS

            }

            return cache

    data = download_daily()

    if data:

        # ----------------------------------------------------

        # 実際に取得できた銘柄だけ保存

        # ----------------------------------------------------

        data = {

            k: v

            for k, v in data.items()

            if k in TICKERS

        }

        try:

            pd.to_pickle(

                data,

                DAILY_CACHE_FILE

            )

        except Exception:

            pass

    return data

# ============================================================

# RS

# ============================================================

def calc_rs(

    daily_df,

    target_date

):

    if daily_df is None:

        return np.nan

    if daily_df.empty:

        return np.nan

    past = daily_df[

        daily_df.index.date <

        target_date.date()

    ]

    if len(past) < (

        RS_LOOKBACK + 1

    ):

        return np.nan

    current = float(

        past["Close"].iloc[-1]

    )

    old = float(

        past["Close"].iloc[

            -RS_LOOKBACK - 1

        ]

    )

    if old <= 0:

        return np.nan

    return (

        current / old - 1

    )

# ============================================================

# AFFORDABLE

# ============================================================

def get_affordable_tickers(

    daily,

    equity

):

    max_value = max(

        equity * LONG_LEVERAGE,

        equity * SHORT_LEVERAGE

    )

    result = []

    for ticker in TICKERS:

        df = daily.get(

            ticker

        )

        if df is None or df.empty:

            continue

        try:

            price = float(

                df["Close"].iloc[-1]

            )

        except Exception:

            continue

        if price <= 0:

            continue

        required = (

            price *

            LOT_SIZE

        )

        if required <= max_value:

            result.append(

                ticker

            )

    return result

# ============================================================

# RS RANK

# ============================================================

def make_rs_table(

    daily,

    affordable,

    target_date

):

    rows = []

    for ticker in affordable:

        try:

            rs = calc_rs(

                daily.get(ticker),

                target_date

            )

            if pd.isna(rs):

                continue

            rows.append(

                {

                    "ticker": ticker,

                    "raw_rs": rs

                }

            )

        except Exception:

            continue

    if not rows:

        return pd.DataFrame()

    df = pd.DataFrame(

        rows

    )

    df["RS"] = (

        df["raw_rs"]

        .rank(

            pct=True

        )

        * 100

    )

    return df

# ============================================================

# FAST CANDIDATE FILTER

# ============================================================

def get_intraday_candidates(

    rs_df,

    positions

):

    long_count = sum(

        1

        for p in positions

        if p.get("side") == "LONG"

    )

    short_count = sum(

        1

        for p in positions

        if p.get("side") == "SHORT"

    )

    long_df = rs_df[

        rs_df["RS"] >=

        LONG_RS_THRESHOLD

    ].copy()

    short_df = rs_df[

        rs_df["RS"] <=

        SHORT_RS_THRESHOLD

    ].copy()

    if long_count >= MAX_LONG_POSITIONS:

        long_df = pd.DataFrame()

    if short_count >= MAX_SHORT_POSITIONS:

        short_df = pd.DataFrame()

    if not long_df.empty:

        long_df = long_df.sort_values(

            "RS",

            ascending=False

        ).head(

            MAX_LONG_INTRADAY

        )

    if not short_df.empty:

        short_df = short_df.sort_values(

            "RS",

            ascending=True

        ).head(

            MAX_SHORT_INTRADAY

        )

    long_tickers = (

        long_df["ticker"].tolist()

        if not long_df.empty

        else []

    )

    short_tickers = (

        short_df["ticker"].tolist()

        if not short_df.empty

        else []

    )

    tickers = list(

        dict.fromkeys(

            long_tickers +

            short_tickers

        )

    )

    return (

        tickers,

        set(long_tickers),

        set(short_tickers)

    )

# ============================================================

# 5 MINUTE DATA

# ============================================================

def download_5m(

    tickers

):

    if not tickers:

        return {}

    # --------------------------------------------------------

    # 除外銘柄を念のため再チェック

    # --------------------------------------------------------

    tickers = [

        t

        for t in tickers

        if t not in INVALID_TICKERS

    ]

    if not tickers:

        return {}

    print(

        f"[5M] 取得開始: {len(tickers)}銘柄",

        flush=True

    )

    try:

        data = yf.download(

            tickers=tickers,

            period="1d",

            interval="5m",

            auto_adjust=False,

            progress=False,

            threads=True,

            group_by="ticker",

            timeout=15

        )

    except Exception as e:

        print(

            f"[5M ERROR] {type(e).__name__}: {e}",

            flush=True

        )

        return {}

    if data is None or data.empty:

        return {}

    data = normalize_index(data)

    result = {}

    required = [

        "Open",

        "High",

        "Low",

        "Close",

        "Volume"

    ]

    if not isinstance(

        data.columns,

        pd.MultiIndex

    ):

        return result

    level0 = set(

        data.columns.get_level_values(0)

    )

    level1 = set(

        data.columns.get_level_values(1)

    )

    if any(

        t in level0

        for t in tickers

    ):

        for ticker in tickers:

            if ticker not in level0:

                continue

            try:

                df = data[

                    ticker

                ].copy()

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=["Close"]

                )

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    elif any(

        t in level1

        for t in tickers

    ):

        for ticker in tickers:

            if ticker not in level1:

                continue

            try:

                df = data.xs(

                    ticker,

                    axis=1,

                    level=1

                ).copy()

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=["Close"]

                )

                if not df.empty:

                    result[ticker] = df

            except Exception:

                continue

    print(

        f"[5M] 取得完了: {len(result)}/{len(tickers)}銘柄",

        flush=True

    )

    return result

# ============================================================

# MAKE CANDIDATE

# ============================================================

def make_candidate(

    ticker,

    intraday,

    daily,

    target_date

):

    if intraday is None:

        return None

    if intraday.empty:

        return None

    if daily is None:

        return None

    if daily.empty:

        return None

    target = target_date.date()

    day = intraday[

        intraday.index.date ==

        target

    ]

    if day.empty:

        return None

    decision_ts = pd.Timestamp(

        f"{target_date:%Y-%m-%d} "

        f"{DECISION_TIME}:00"

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

                before["Close"] *

                volume

            ).sum()

            /

            volume.sum()

        )

    else:

        vwap = close_1245

    past = daily[

        daily.index.date <

        target

    ]

    if past.empty:

        return None

    prev_close = float(

        past["Close"].iloc[-1]

    )

    if prev_close <= 0:

        return None

    day_return = (

        close_1245 /

        prev_close

        - 1

    )

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

                afternoon_open

                - 1

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

                first_close

                - 1

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

        "day_return": day_return,

        "afternoon_return":

            afternoon_return,

        "recent_return":

            recent_return,

        "raw_rs": raw_rs

    }

# ============================================================

# SELECT

# ============================================================

def select_candidates(

    intraday,

    daily,

    long_tickers,

    short_tickers

):

    now = pd.Timestamp.now(

        tz="Asia/Tokyo"

    ).tz_localize(None)

    target_date = now.normalize()

    rows = []

    for ticker in intraday:

        try:

            row = make_candidate(

                ticker,

                intraday.get(ticker),

                daily.get(ticker),

                target_date

            )

            if row is None:

                continue

            row["ticker"] = ticker

            rows.append(

                row

            )

        except Exception:

            continue

    if not rows:

        return pd.DataFrame()

    df = pd.DataFrame(

        rows

    )

    if df.empty:

        return df

    df["RS"] = (

        df["raw_rs"]

        .rank(

            pct=True

        )

        * 100

    )

    day_score = (

        df["day_return"]

        .rank(

            pct=True

        )

        * 100

    )

    afternoon_score = (

        df["afternoon_return"]

        .rank(

            pct=True

        )

        * 100

    )

    recent_score = (

        df["recent_return"]

        .rank(

            pct=True

        )

        * 100

    )

    df["score"] = (

        df["RS"] * 0.30

        +

        day_score * 0.30

        +

        afternoon_score * 0.25

        +

        recent_score * 0.15

    )

    selected = []

    # ========================================================

    # LONG

    # ========================================================

    long_df = df[

        df["ticker"].isin(

            long_tickers

        )

    ].copy()

    long_df = long_df[

        long_df["RS"] >=

        LONG_RS_THRESHOLD

    ]

    long_df = long_df[

        long_df["close_1245"] >

        long_df["morning_high"]

    ]

    if not long_df.empty:

        long_df = long_df.sort_values(

            "score",

            ascending=False

        )

        row = long_df.iloc[0].copy()

        row["side"] = "LONG"

        selected.append(

            row

        )

    # ========================================================

    # SHORT

    # ========================================================

    short_df = df[

        df["ticker"].isin(

            short_tickers

        )

    ].copy()

    short_df = short_df[

        short_df["RS"] <=

        SHORT_RS_THRESHOLD

    ]

    short_df = short_df[

        short_df["close_1245"] <

        short_df["morning_low"]

    ]

    if not short_df.empty:

        short_df = short_df.sort_values(

            "score",

            ascending=True

        )

        row = short_df.iloc[0].copy()

        row["side"] = "SHORT"

        selected.append(

            row

        )

    if not selected:

        return pd.DataFrame()

    return pd.DataFrame(

        selected

    )

# ============================================================

# CREATE POSITION

# ============================================================

def create_positions(

    candidates,

    intraday,

    equity

):

    positions = []

    if candidates.empty:

        return positions

    for _, row in candidates.iterrows():

        ticker = row["ticker"]

        side = row["side"]

        df = intraday.get(

            ticker

        )

        if df is None or df.empty:

            continue

        target_date = pd.Timestamp(

            row["date"]

        )

        entry_ts = pd.Timestamp(

            f"{target_date:%Y-%m-%d} "

            f"{ENTRY_TIME}:00"

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

        shares = LOT_SIZE

        required_value = (

            entry_price *

            shares

        )

        max_value = (

            equity *

            (

                LONG_LEVERAGE

                if side == "LONG"

                else SHORT_LEVERAGE

            )

        )

        if required_value > max_value:

            continue

        if side == "LONG":

            tp_price = (

                entry_price *

                (1 + TP)

            )

            sl_price = (

                entry_price *

                (1 - SL)

            )

        else:

            tp_price = (

                entry_price *

                (1 - TP)

            )

            sl_price = (

                entry_price *

                (1 + SL)

            )

        positions.append(

            {

                "ticker": ticker,

                "side": side,

                "shares": shares,

                "entry_price": entry_price,

                "tp_price": tp_price,

                "sl_price": sl_price,

                "entry_time": str(

                    entry_ts

                ),

                "entry_date": str(

                    target_date.date()

                )

            }

        )

    return positions

# ============================================================

# CHECK TP / SL

# ============================================================

def check_position(

    position,

    intraday

):

    ticker = position["ticker"]

    df = intraday.get(

        ticker

    )

    if df is None or df.empty:

        return (

            False,

            None,

            None,

            None

        )

    entry_time = pd.Timestamp(

        position["entry_time"]

    )

    after = df[

        df.index > entry_time

    ]

    if after.empty:

        return (

            False,

            None,

            None,

            None

        )

    side = position["side"]

    tp_price = float(

        position["tp_price"]

    )

    sl_price = float(

        position["sl_price"]

    )

    if side == "LONG":

        for idx, bar in after.iterrows():

            high = float(

                bar["High"]

            )

            low = float(

                bar["Low"]

            )

            if low <= sl_price:

                return (

                    True,

                    sl_price,

                    "SL",

                    idx

                )

            if high >= tp_price:

                return (

                    True,

                    tp_price,

                    "TP",

                    idx

                )

    else:

        for idx, bar in after.iterrows():

            high = float(

                bar["High"]

            )

            low = float(

                bar["Low"]

            )

            if high >= sl_price:

                return (

                    True,

                    sl_price,

                    "SL",

                    idx

                )

            if low <= tp_price:

                return (

                    True,

                    tp_price,

                    "TP",

                    idx

                )

    return (

        False,

        None,

        None,

        None

    )

# ============================================================

# RESULT MODE

# ============================================================

def run_result():

    total_start = time.perf_counter()

    portfolio = load_portfolio()

    old_equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

    if not positions:

        text = (

            "15:45 結果\n\n"

            f"前資産: ¥{old_equity:,.0f}\n"

            "損益: ¥0\n"

            f"現在資産: ¥{old_equity:,.0f}\n"

            "決済: なし\n"

            "持越し: なし"

        )

        write_result(text)

        return

    tickers = list(

        dict.fromkeys(

            p["ticker"]

            for p in positions

        )

    )

    t = time.perf_counter()

    intraday = download_5m(

        tickers

    )

    log_time(

        "結果5分足取得",

        t,

        total_start

    )

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

            remaining.append(

                position

            )

            continue

        entry_price = float(

            position["entry_price"]

        )

        shares = int(

            position["shares"]

        )

        if position["side"] == "LONG":

            ret = (

                exit_price /

                entry_price

                - 1

            )

        else:

            ret = (

                entry_price /

                exit_price

                - 1

            )

        pnl = (

            entry_price *

            shares *

            ret

        )

        total_pnl += pnl

        closed.append(

            {

                "date":

                    str(exit_time.date()),

                "ticker":

                    position["ticker"],

                "side":

                    position["side"],

                "shares":

                    shares,

                "entry":

                    entry_price,

                "exit":

                    exit_price,

                "return":

                    ret,

                "pnl":

                    pnl,

                "reason":

                    reason,

                "entry_time":

                    position["entry_time"],

                "exit_time":

                    str(exit_time)

            }

        )

    new_equity = (

        old_equity +

        total_pnl

    )

    portfolio["equity"] = new_equity

    portfolio["positions"] = remaining

    portfolio["last_update"] = (

        datetime.now().strftime(

            "%Y-%m-%d %H:%M:%S"

        )

    )

    save_portfolio(

        portfolio

    )

    if closed:

        trade_df = pd.DataFrame(

            closed

        )

        if os.path.exists(

            TRADE_FILE

        ):

            try:

                old_df = pd.read_csv(

                    TRADE_FILE

                )

                trade_df = pd.concat(

                    [

                        old_df,

                        trade_df

                    ],

                    ignore_index=True

                )

            except Exception:

                pass

        trade_df.to_csv(

            TRADE_FILE,

            index=False,

            encoding="utf-8-sig"

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

        lines.append(

            "決済:"

        )

        for trade in closed:

            lines.append(

                f"{trade['side']} "

                f"{trade['ticker']} "

                f"{trade['shares']}株 "

                f"{trade['reason']} "

                f"損益 ¥{trade['pnl']:,.0f}"

            )

    else:

        lines.append(

            "決済: なし"

        )

    lines.append("")

    if remaining:

        lines.append(

            "持越し:"

        )

        for p in remaining:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"建値 "

                f"{p['entry_price']:,.1f}円"

            )

    else:

        lines.append(

            "持越し: なし"

        )

    write_result(

        "\n".join(lines)

    )

    log_time(

        "結果処理合計",

        total_start,

        total_start

    )

# ============================================================

# DECISION MODE

# ============================================================

def run_decision():

    total_start = time.perf_counter()

    # ========================================================

    # 初期処理

    # ========================================================

    t = time.perf_counter()

    portfolio = load_portfolio()

    equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

    log_time(

        "初期処理",

        t,

        total_start

    )

    # ========================================================

    # 日付

    # ========================================================

    now = pd.Timestamp.now(

        tz="Asia/Tokyo"

    ).tz_localize(None)

    target_date = now.normalize()

    # ========================================================

    # 日足

    # ========================================================

    t = time.perf_counter()

    daily = get_daily_data()

    log_time(

        "日足取得",

        t,

        total_start

    )

    if not daily:

        write_result(

            "12:45 判定\n\n"

            "日足データを取得できませんでした。"

        )

        return

    # ========================================================

    # 実際に取得できた銘柄だけに限定

    # ========================================================

    daily = {

        k: v

        for k, v in daily.items()

        if k in TICKERS

    }

    # ========================================================

    # 100株購入可能銘柄

    # ========================================================

    t = time.perf_counter()

    affordable = get_affordable_tickers(

        daily,

        equity

    )

    log_time(

        "100株購入可能銘柄抽出",

        t,

        total_start

    )

    # ========================================================

    # RS

    # ========================================================

    t = time.perf_counter()

    rs_df = make_rs_table(

        daily,

        affordable,

        target_date

    )

    log_time(

        "RS計算",

        t,

        total_start

    )

    if rs_df.empty:

        write_result(

            "12:45 判定\n\n"

            f"現在資産: ¥{equity:,.0f}\n"

            "LONG: なし\n"

            "SHORT: なし\n"

            "新規取引: なし"

        )

        return

    # ========================================================

    # 5分足候補抽出

    # ========================================================

    t = time.perf_counter()

    (

        target_tickers,

        long_tickers,

        short_tickers

    ) = get_intraday_candidates(

        rs_df,

        positions

    )

    log_time(

        "候補絞り込み",

        t,

        total_start

    )

    print(

        f"日足対象: {len(affordable)}",

        flush=True

    )

    print(

        f"5分足対象: {len(target_tickers)}",

        flush=True

    )

    print(

        f"LONG候補: {len(long_tickers)}",

        flush=True

    )

    print(

        f"SHORT候補: {len(short_tickers)}",

        flush=True

    )

    # ========================================================

    # 5分足

    # ========================================================

    t = time.perf_counter()

    intraday = download_5m(

        target_tickers

    )

    log_time(

        "5分足取得",

        t,

        total_start

    )

    # ========================================================

    # 最終判定

    # ========================================================

    t = time.perf_counter()

    candidates = select_candidates(

        intraday,

        daily,

        long_tickers,

        short_tickers

    )

    log_time(

        "5分足判定",

        t,

        total_start

    )

    # ========================================================

    # 12:50 OPEN

    # ========================================================

    t = time.perf_counter()

    new_positions = create_positions(

        candidates,

        intraday,

        equity

    )

    log_time(

        "ポジション作成",

        t,

        total_start

    )

    # ========================================================

    # 保存

    # ========================================================

    t = time.perf_counter()

    if new_positions:

        portfolio[

            "positions"

        ].extend(

            new_positions

        )

        portfolio[

            "last_update"

        ] = datetime.now().strftime(

            "%Y-%m-%d %H:%M:%S"

        )

        save_portfolio(

            portfolio

        )

    if not candidates.empty:

        try:

            candidates.to_csv(

                CANDIDATE_FILE,

                index=False,

                encoding="utf-8-sig"

            )

        except Exception:

            pass

    log_time(

        "保存",

        t,

        total_start

    )

    # ========================================================

    # MAIL

    # ========================================================

    t = time.perf_counter()

    lines = [

        "12:45 判定",

        "",

        f"現在資産: ¥{equity:,.0f}",

        "",

        f"LONG上限: ¥"

        f"{equity * LONG_LEVERAGE:,.0f}",

        f"SHORT上限: ¥"

        f"{equity * SHORT_LEVERAGE:,.0f}",

        ""

    ]

    # ========================================================

    # LONG

    # ========================================================

    longs = [

        p

        for p in new_positions

        if p["side"] == "LONG"

    ]

    if longs:

        p = longs[0]

        lines.extend(

            [

                f"LONG: {p['ticker']}",

                f"12:50 OPEN: "

                f"{p['entry_price']:,.1f}円",

                f"株数: {p['shares']}株",

                f"TP: {p['tp_price']:,.1f}円",

                f"SL: {p['sl_price']:,.1f}円",

                ""

            ]

        )

    else:

        lines.extend(

            [

                "LONG: なし",

                ""

            ]

        )

    # ========================================================

    # SHORT

    # ========================================================

    shorts = [

        p

        for p in new_positions

        if p["side"] == "SHORT"

    ]

    if shorts:

        p = shorts[0]

        lines.extend(

            [

                f"SHORT: {p['ticker']}",

                f"12:50 OPEN: "

                f"{p['entry_price']:,.1f}円",

                f"株数: {p['shares']}株",

                f"TP: {p['tp_price']:,.1f}円",

                f"SL: {p['sl_price']:,.1f}円",

                ""

            ]

        )

    else:

        lines.extend(

            [

                "SHORT: なし",

                ""

            ]

        )

    lines.append(

        f"新規取引: "

        f"{len(new_positions)}件"

    )

    write_result(

        "\n".join(lines)

    )

    log_time(

        "メール本文生成",

        t,

        total_start

    )

    # ========================================================

    # TOTAL

    # ========================================================

    total = (

        time.perf_counter()

        -

        total_start

    )

    print(

        "================================",

        flush=True

    )

    print(

        f"[TIME] 合計: {total:.2f}秒",

        flush=True

    )

    print(

        "================================",

        flush=True

    )

# ============================================================

# MODE

# ============================================================

def get_run_mode():

    mode = os.environ.get(

        "RUN_MODE",

        ""

    ).strip().lower()

    if mode in (

        "decision",

        "result"

    ):

        return mode

    now = pd.Timestamp.now(

        tz="Asia/Tokyo"

    )

    if now.hour < 14:

        return "decision"

    return "result"

# ============================================================

# MAIN

# ============================================================

def main():

    main_start = time.perf_counter()

    mode = get_run_mode()

    print(

        "================================",

        flush=True

    )

    print(

        f"{VERSION} START",

        flush=True

    )

    print(

        f"RUN MODE: {mode}",

        flush=True

    )

    print(

        "================================",

        flush=True

    )

    print(

        f"対象銘柄数: {len(TICKERS)}",

        flush=True

    )

    print(

        "除外: 7205.T / 7206.T / 7207.T",

        flush=True

    )

    try:

        if mode == "decision":

            run_decision()

        elif mode == "result":

            run_result()

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

        write_result(

            error_text

        )

        raise

    finally:

        total = (

            time.perf_counter()

            -

            main_start

        )

        print(

            "================================",

            flush=True

        )

        print(

            f"[TIME] Cloud Run実処理合計: "

            f"{total:.2f}秒",

            flush=True

        )

        print(

            f"{VERSION} END",

            flush=True

        )

        print(

            "================================",

            flush=True

        )

# ============================================================

# START

# ============================================================

if __name__ == "__main__":

    main()
