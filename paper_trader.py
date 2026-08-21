# ============================================================

# v33.9 Cloud Paper Trader

#

# LONG 1.0倍 + SHORT 1.0倍

# LONG 最大1銘柄

# SHORT 最大1銘柄

#

# 12:45 判定

# 12:50 OPEN

# 15:45 TP / SL確認

# TP +2%

# SL -1.5%

#

# 100株単位

# 100株買えない銘柄は除外

# 持越しあり

# ============================================================

import warnings

warnings.filterwarnings("ignore")

import os

import json

from datetime import datetime, time

import yfinance as yf

import pandas as pd

import numpy as np

# ============================================================

# 設定

# ============================================================

VERSION = "v33.9"

INITIAL_CAPITAL = 1117792

DATA_DIR = "data"

CACHE_DIR = f"{DATA_DIR}/cache"

INTRADAY_CACHE = f"{CACHE_DIR}/5m"

DAILY_CACHE = f"{CACHE_DIR}/daily"

PORTFOLIO_FILE = f"{DATA_DIR}/portfolio.json"

TRADE_FILE = f"{DATA_DIR}/paper_trades.csv"

CANDIDATE_FILE = f"{DATA_DIR}/paper_candidates.csv"

os.makedirs(INTRADAY_CACHE, exist_ok=True)

os.makedirs(DAILY_CACHE, exist_ok=True)

# ============================================================

# 売買設定

# ============================================================

LONG_LEVERAGE = 1.0

SHORT_LEVERAGE = 1.0

MAX_LONG_POSITIONS = 1

MAX_SHORT_POSITIONS = 1

LONG_RS_THRESHOLD = 70.0

SHORT_RS_THRESHOLD = 30.0

RS_LOOKBACK = 20

TP = 0.020

SL = 0.015

DECISION_TIME = "12:45"

ENTRY_TIME = "12:50"

LOT_SIZE = 100

# ============================================================

# 銘柄

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

    "7205.T","7206.T","7207.T","7261.T","7267.T",

    "7269.T","7270.T","7272.T","7309.T","7731.T",

    "7733.T","7735.T","7741.T","7751.T","7752.T"

]

# ============================================================

# Cache

# ============================================================

def save_cache(df, path):

    df.to_csv(

        path,

        encoding="utf-8-sig"

    )

def load_cache(path):

    if not os.path.exists(path):

        return None

    try:

        return pd.read_csv(

            path,

            index_col=0,

            parse_dates=True

        )

    except Exception:

        return None

# ============================================================

# 5分足取得

# ============================================================

def download_5m(ticker):

    path = f"{INTRADAY_CACHE}/{ticker}.csv"

    old = load_cache(path)

    try:

        new = yf.download(

            ticker,

            period="5d",

            interval="5m",

            auto_adjust=False,

            progress=False,

            threads=False

        )

        if new.empty:

            return old

        if isinstance(new.columns, pd.MultiIndex):

            new.columns = (

                new.columns

                .get_level_values(0)

            )

        if new.index.tz is not None:

            new.index = (

                new.index

                .tz_convert("Asia/Tokyo")

                .tz_localize(None)

            )

        new = new[

            [

                "Open",

                "High",

                "Low",

                "Close",

                "Volume"

            ]

        ].dropna()

        if old is not None:

            df = pd.concat(

                [

                    old,

                    new

                ]

            )

            df = (

                df

                .loc[

                    ~df.index.duplicated()

                ]

                .sort_index()

            )

        else:

            df = new

        save_cache(

            df,

            path

        )

        return df

    except Exception:

        return old

# ============================================================

# Daily取得

# ============================================================

def download_daily(ticker):

    path = f"{DAILY_CACHE}/{ticker}.csv"

    old = load_cache(path)

    try:

        new = yf.download(

            ticker,

            period="1mo",

            interval="1d",

            auto_adjust=False,

            progress=False,

            threads=False

        )

        if new.empty:

            return old

        if isinstance(new.columns, pd.MultiIndex):

            new.columns = (

                new.columns

                .get_level_values(0)

            )

        new = new[

            [

                "Open",

                "High",

                "Low",

                "Close",

                "Volume"

            ]

        ].dropna()

        if old is not None:

            df = pd.concat(

                [

                    old,

                    new

                ]

            )

            df = (

                df

                .loc[

                    ~df.index.duplicated()

                ]

                .sort_index()

            )

        else:

            df = new

        save_cache(

            df,

            path

        )

        return df

    except Exception:

        return old

# ============================================================

# Portfolio

# ============================================================

def load_portfolio():

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

    if "equity" not in data:

        data["equity"] = INITIAL_CAPITAL

    if "positions" not in data:

        data["positions"] = []

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

# 実行モード

# ============================================================

def get_run_mode():

    env_mode = os.environ.get("RUN_MODE", "").lower().strip()

    if env_mode in ["decision", "result"]:

        return env_mode

    now = datetime.now()

    if now.time() < time(14, 0):

        return "decision"

    return "result"

# ============================================================

# RS

# ============================================================

def calc_rs(

    ticker,

    daily,

    date

):

    if ticker not in daily:

        return np.nan

    d = daily[ticker]

    past = d[

        d.index.date < date.date()

    ]

    if len(past) < RS_LOOKBACK + 1:

        return np.nan

    now = float(

        past["Close"].iloc[-1]

    )

    old = float(

        past["Close"]

        .iloc[-RS_LOOKBACK - 1]

    )

    if old <= 0:

        return np.nan

    return now / old - 1

# ============================================================

# 候補作成

# ============================================================

def make_candidate(

    ticker,

    intraday,

    daily,

    date

):

    if ticker not in intraday:

        return None

    df = intraday[ticker]

    day = df[

        df.index.date == date.date()

    ]

    if day.empty:

        return None

    cutoff = pd.Timestamp(

        f"{date.strftime('%Y-%m-%d')} {DECISION_TIME}:00"

    )

    before = day[

        day.index <= cutoff

    ]

    if len(before) < 10:

        return None

    morning = before[

        before.index.time <

        datetime.strptime(

            "12:00",

            "%H:%M"

        ).time()

    ]

    if morning.empty:

        return None

    morning_high = float(

        morning["High"].max()

    )

    morning_low = float(

        morning["Low"].min()

    )

    close_1245 = float(

        before["Close"].iloc[-1]

    )

    volume = before["Volume"].astype(float)

    if volume.sum() > 0:

        vwap = (

            before["Close"] * volume

        ).sum() / volume.sum()

    else:

        vwap = close_1245

    if ticker not in daily:

        return None

    past = daily[ticker][

        daily[ticker].index.date <

        date.date()

    ]

    if past.empty:

        return None

    prev_close = float(

        past["Close"].iloc[-1]

    )

    day_return = (

        close_1245 /

        prev_close

        - 1

    )

    afternoon = before[

        before.index.time >=

        datetime.strptime(

            "12:00",

            "%H:%M"

        ).time()

    ]

    if len(afternoon) >= 2:

        afternoon_return = (

            afternoon["Close"].iloc[-1] /

            afternoon["Open"].iloc[0]

            - 1

        )

    else:

        afternoon_return = 0

    recent = before.tail(3)

    if len(recent) >= 2:

        recent_return = (

            recent["Close"].iloc[-1] /

            recent["Close"].iloc[0]

            - 1

        )

    else:

        recent_return = 0

    return {

        "ticker": ticker,

        "date": date,

        "morning_high": morning_high,

        "morning_low": morning_low,

        "close_1245": close_1245,

        "vwap": vwap,

        "day_return": day_return,

        "afternoon_return": afternoon_return,

        "recent_return": recent_return,

        "raw_rs": calc_rs(

            ticker,

            daily,

            date

        )

    }

# ============================================================

# 候補選定

# ============================================================

def select_candidates(

    intraday,

    daily

):

    today = (

        pd.Timestamp.now(

            tz="Asia/Tokyo"

        )

        .tz_localize(None)

    )

    date = today.normalize()

    rows = []

    for ticker in intraday:

        c = make_candidate(

            ticker,

            intraday,

            daily,

            date

        )

        if c:

            rows.append(c)

    if not rows:

        return pd.DataFrame()

    df = pd.DataFrame(rows)

    df = df.dropna(

        subset=["raw_rs"]

    )

    if df.empty:

        return df

    df["RS"] = (

        df["raw_rs"]

        .rank(pct=True)

        * 100

    )

    df["score"] = (

        df["RS"] * 0.30

        +

        df["day_return"]

        .rank(pct=True)

        * 100

        * 0.30

        +

        df["afternoon_return"]

        .rank(pct=True)

        * 100

        * 0.25

        +

        df["recent_return"]

        .rank(pct=True)

        * 100

        * 0.15

    )

    result = []

    # ========================================================

    # LONG

    # ========================================================

    long = df[

        df["RS"] >= LONG_RS_THRESHOLD

    ]

    long = long[

        long["close_1245"] >=

        long["morning_high"]

    ]

    if not long.empty:

        long = long.sort_values(

            "score",

            ascending=False

        )

        for _, row in long.iterrows():

            price = float(

                row["close_1245"]

            )

            # 100株買える銘柄だけ

            if price * LOT_SIZE <= 0:

                continue

            x = row.to_dict()

            x["side"] = "LONG"

            result.append(x)

            break

    # ========================================================

    # SHORT

    # ========================================================

    short = df[

        df["RS"] <= SHORT_RS_THRESHOLD

    ]

    short = short[

        short["close_1245"] <=

        short["morning_low"]

    ]

    if not short.empty:

        short = short.sort_values(

            "score",

            ascending=True

        )

        for _, row in short.iterrows():

            x = row.to_dict()

            x["side"] = "SHORT"

            result.append(x)

            break

    return pd.DataFrame(result)

# ============================================================

# 12:50 OPEN

# ============================================================

def create_positions(

    candidates,

    intraday,

    equity

):

    positions = []

    if candidates.empty:

        return positions

    for _, candidate in candidates.iterrows():

        ticker = candidate["ticker"]

        side = candidate["side"]

        date = pd.Timestamp(

            candidate["date"]

        )

        if ticker not in intraday:

            continue

        df = intraday[ticker]

        day = df[

            df.index.date ==

            date.date()

        ]

        if day.empty:

            continue

        entry_time = pd.Timestamp(

            f"{date.strftime('%Y-%m-%d')} {ENTRY_TIME}:00"

        )

        entry_df = day[

            day.index >= entry_time

        ]

        if entry_df.empty:

            continue

        entry_price = float(

            entry_df.iloc[0]["Open"]

        )

        shares = LOT_SIZE

        # ====================================================

        # LONG

        # ====================================================

        if side == "LONG":

            required = (

                entry_price *

                shares

            )

            max_value = (

                equity *

                LONG_LEVERAGE

            )

            if required > max_value:

                continue

            tp_price = (

                entry_price *

                (1 + TP)

            )

            sl_price = (

                entry_price *

                (1 - SL)

            )

        # ====================================================

        # SHORT

        # ====================================================

        else:

            required = (

                entry_price *

                shares

            )

            max_value = (

                equity *

                SHORT_LEVERAGE

            )

            if required > max_value:

                continue

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

                "entry_time": str(entry_time),

                "entry_date": str(date.date())

            }

        )

    return positions

# ============================================================

# 15:45 ポジション確認

# ============================================================

def check_positions(

    positions,

    intraday,

    equity

):

    total_pnl = 0

    closed = []

    remaining = []

    for position in positions:

        ticker = position["ticker"]

        side = position["side"]

        shares = int(

            position["shares"]

        )

        entry_price = float(

            position["entry_price"]

        )

        tp_price = float(

            position["tp_price"]

        )

        sl_price = float(

            position["sl_price"]

        )

        if ticker not in intraday:

            remaining.append(position)

            continue

        df = intraday[ticker]

        date = pd.Timestamp(

            position["entry_date"]

        )

        day = df[

            df.index.date ==

            date.date()

        ]

        if day.empty:

            remaining.append(position)

            continue

        # 12:50以降の5分足

        after = day[

            day.index >

            pd.Timestamp(

                position["entry_time"]

            )

        ]

        hit = False

        exit_price = None

        exit_reason = None

        exit_time = None

        for idx, bar in after.iterrows():

            high = float(

                bar["High"]

            )

            low = float(

                bar["Low"]

            )

            # =================================================

            # LONG

            # =================================================

            if side == "LONG":

                if low <= sl_price:

                    exit_price = sl_price

                    exit_reason = "SL"

                    exit_time = idx

                    hit = True

                    break

                if high >= tp_price:

                    exit_price = tp_price

                    exit_reason = "TP"

                    exit_time = idx

                    hit = True

                    break

            # =================================================

            # SHORT

            # =================================================

            else:

                if high >= sl_price:

                    exit_price = sl_price

                    exit_reason = "SL"

                    exit_time = idx

                    hit = True

                    break

                if low <= tp_price:

                    exit_price = tp_price

                    exit_reason = "TP"

                    exit_time = idx

                    hit = True

                    break

        # =====================================================

        # TP / SL未到達 → 持越し

        # =====================================================

        if not hit:

            remaining.append(position)

            continue

        # =====================================================

        # PNL

        # =====================================================

        if side == "LONG":

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

                    str(date.date()),

                "ticker":

                    ticker,

                "side":

                    side,

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

                    exit_reason,

                "entry_time":

                    position["entry_time"],

                "exit_time":

                    str(exit_time)

            }

        )

    return (

        remaining,

        closed,

        total_pnl

    )

# ============================================================

# CSV

# ============================================================

def save_csv(

    filename,

    rows

):

    if not rows:

        return

    new = pd.DataFrame(rows)

    if os.path.exists(filename):

        old = pd.read_csv(

            filename

        )

        new = pd.concat(

            [

                old,

                new

            ],

            ignore_index=True

        )

    new.to_csv(

        filename,

        index=False,

        encoding="utf-8-sig"

    )

# ============================================================

# Result

# ============================================================

def save_result_text(text):

    with open(

        f"{DATA_DIR}/latest_result.txt",

        "w",

        encoding="utf-8"

    ) as f:

        f.write(text)

# ============================================================

# DATA

# ============================================================

def load_market_data():

    intraday = {}

    daily = {}

    for ticker in TICKERS:

        df5 = download_5m(ticker)

        if df5 is not None:

            intraday[ticker] = df5

        dd = download_daily(ticker)

        if dd is not None:

            daily[ticker] = dd

    return intraday, daily

# ============================================================

# DECISION

# ============================================================

def run_decision():

    portfolio = load_portfolio()

    equity = float(

        portfolio["equity"]

    )

    existing = portfolio.get(

        "positions",

        []

    )

    # 既に保有がある場合は新規追加しない

    long_exists = any(

        p["side"] == "LONG"

        for p in existing

    )

    short_exists = any(

        p["side"] == "SHORT"

        for p in existing

    )

    intraday, daily = load_market_data()

    candidates = select_candidates(

        intraday,

        daily

    )

    if candidates.empty:

        text = (

            "12:45 判定\n\n"

            f"前資産: ¥{equity:,.0f}\n"

            "LONG: なし\n"

            "SHORT: なし\n"

        )

        save_result_text(text)

        return

    selected = []

    for _, row in candidates.iterrows():

        if (

            row["side"] == "LONG"

            and long_exists

        ):

            continue

        if (

            row["side"] == "SHORT"

            and short_exists

        ):

            continue

        selected.append(row)

    if selected:

        selected_df = pd.DataFrame(

            selected

        )

    else:

        selected_df = pd.DataFrame()

    new_positions = create_positions(

        selected_df,

        intraday,

        equity

    )

    portfolio["positions"].extend(

        new_positions

    )

    portfolio["last_update"] = (

        datetime.now().strftime(

            "%Y-%m-%d %H:%M:%S"

        )

    )

    save_portfolio(

        portfolio

    )

    selected_df.to_csv(

        CANDIDATE_FILE,

        index=False,

        encoding="utf-8-sig"

    )

    lines = []

    lines.append(

        "12:45 判定"

    )

    lines.append("")

    lines.append(

        f"現在資産: ¥{equity:,.0f}"

    )

    lines.append("")

    for p in new_positions:

        lines.append(

            f"{p['side']} {p['ticker']}"

        )

        lines.append(

            f"12:50 OPEN予定: "

            f"{p['entry_price']:,.1f}円"

        )

        lines.append(

            f"株数: {p['shares']}株"

        )

        lines.append(

            f"TP: {p['tp_price']:,.1f}円"

        )

        lines.append(

            f"SL: {p['sl_price']:,.1f}円"

        )

        lines.append("")

    if not new_positions:

        lines.append(

            "新規取引: なし"

        )

    save_result_text(

        "\n".join(lines)

    )

# ============================================================

# RESULT

# ============================================================

def run_result():

    portfolio = load_portfolio()

    equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

    intraday, daily = load_market_data()

    remaining, closed, total_pnl = check_positions(

        positions,

        intraday,

        equity

    )

    new_equity = (

        equity +

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

    save_csv(

        TRADE_FILE,

        closed

    )

    lines = []

    lines.append(

        "15:45 結果"

    )

    lines.append("")

    lines.append(

        f"前資産: ¥{equity:,.0f}"

    )

    lines.append(

        f"損益: ¥{total_pnl:,.0f}"

    )

    lines.append(

        f"現在資産: ¥{new_equity:,.0f}"

    )

    lines.append("")

    if closed:

        lines.append("決済:")

        for t in closed:

            lines.append(

                f"{t['side']} "

                f"{t['ticker']} "

                f"{t['shares']}株 "

                f"{t['reason']} "

                f"損益 ¥{t['pnl']:,.0f}"

            )

    else:

        lines.append(

            "決済: なし"

        )

    lines.append("")

    if remaining:

        lines.append("持越し:")

        for p in remaining:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"建値 {p['entry_price']:,.1f}円"

            )

    else:

        lines.append(

            "持越し: なし"

        )

    save_result_text(

        "\n".join(lines)

    )

# ============================================================

# MAIN

# ============================================================

def main():

    mode = get_run_mode()

    print("=" * 80)

    print(

        f"{VERSION} START"

    )

    print(

        f"RUN MODE: {mode}"

    )

    print("=" * 80)

    if mode == "decision":

        run_decision()

    else:

        run_result()

    print("=" * 80)

    print(

        f"{VERSION} END"

    )

    print("=" * 80)

# ============================================================

# START

# ============================================================

if __name__ == "__main__":

    main()
