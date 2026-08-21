# ============================================================

# v33.9 Cloud Paper Trader

#

# 12:45判定

# 12:50 OPEN

# 15:45 結果確認

#

# LONG 1.0倍 + SHORT 1.0倍

# LONG 最大1銘柄

# SHORT 最大1銘柄

#

# 取引単位 100株

#

# TP +2%

# SL -1.5%

#

# 持越しあり

#

# 12:45処理では未来データを使用しない

# ============================================================

import warnings

warnings.filterwarnings("ignore")

import os

import json

from datetime import datetime

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

PENDING_FILE = f"{DATA_DIR}/pending_orders.json"

RESULT_FILE = f"{DATA_DIR}/latest_result.txt"

LOT_SIZE = 100

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

os.makedirs(

    INTRADAY_CACHE,

    exist_ok=True

)

os.makedirs(

    DAILY_CACHE,

    exist_ok=True

)

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

# 時刻

# ============================================================

def now_jst():

    return pd.Timestamp.now(

        tz="Asia/Tokyo"

    ).tz_localize(None)

def get_run_mode():

    env_mode = os.environ.get(

        "RUN_MODE",

        "auto"

    )

    if env_mode != "auto":

        return env_mode

    now = now_jst()

    if now.hour < 14:

        return "decision"

    return "result"

# ============================================================

# Cache

# ============================================================

def save_cache(

    df,

    path

):

    df.to_csv(

        path,

        encoding="utf-8-sig"

    )

def load_cache(

    path

):

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

def download_5m(

    ticker

):

    path = (

        f"{INTRADAY_CACHE}/{ticker}.csv"

    )

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

        if isinstance(

            new.columns,

            pd.MultiIndex

        ):

            new.columns = (

                new.columns

                .get_level_values(0)

            )

        if new.index.tz is not None:

            new.index = (

                new.index

                .tz_convert(

                    "Asia/Tokyo"

                )

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

# Daily Cache

# ============================================================

def download_daily(

    ticker

):

    path = (

        f"{DAILY_CACHE}/{ticker}.csv"

    )

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

        if isinstance(

            new.columns,

            pd.MultiIndex

        ):

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

    if not os.path.exists(

        PORTFOLIO_FILE

    ):

        return {

            "equity": INITIAL_CAPITAL,

            "positions": [],

            "last_update": None

        }

    with open(

        PORTFOLIO_FILE,

        "r",

        encoding="utf-8"

    ) as f:

        data = json.load(f)

    if "positions" not in data:

        data["positions"] = []

    return data

def save_portfolio(

    data

):

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

# Pending Orders

# ============================================================

def load_pending():

    if not os.path.exists(

        PENDING_FILE

    ):

        return []

    try:

        with open(

            PENDING_FILE,

            "r",

            encoding="utf-8"

        ) as f:

            return json.load(f)

    except Exception:

        return []

def save_pending(

    data

):

    with open(

        PENDING_FILE,

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

# Result

# ============================================================

def save_result_text(

    text

):

    with open(

        RESULT_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        f.write(text)

# ============================================================

# 購入可能株数

# ============================================================

def calc_order_quantity(

    equity,

    price,

    leverage

):

    if price <= 0:

        return 0

    max_value = (

        equity *

        leverage

    )

    lots = int(

        max_value

        /

        (price * LOT_SIZE)

    )

    return lots * LOT_SIZE

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

    return (

        now / old - 1

    )

# ============================================================

# Candidate

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

        f"{date.strftime('%Y-%m-%d')} "

        f"{DECISION_TIME}:00"

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

    volume = (

        before["Volume"]

        .astype(float)

    )

    if volume.sum() > 0:

        vwap = (

            before["Close"] * volume

        ).sum() / volume.sum()

    else:

        vwap = close_1245

    if ticker not in daily:

        return None

    past = daily[ticker][

        daily[ticker].index.date

        <

        date.date()

    ]

    if past.empty:

        return None

    prev_close = float(

        past["Close"].iloc[-1]

    )

    day_return = (

        close_1245 /

        prev_close -

        1

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

            afternoon["Close"].iloc[-1]

            /

            afternoon["Open"].iloc[0]

            - 1

        )

    else:

        afternoon_return = 0

    recent = before.tail(3)

    if len(recent) >= 2:

        recent_return = (

            recent["Close"].iloc[-1]

            /

            recent["Close"].iloc[0]

            - 1

        )

    else:

        recent_return = 0

    return {

        "ticker": ticker,

        "date": str(date.date()),

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

# Candidate Selection

# ============================================================

def select_candidates(

    intraday,

    daily,

    equity,

    positions

):

    today = now_jst()

    date = today.normalize()

    rows = []

    for ticker in TICKERS:

        c = make_candidate(

            ticker,

            intraday,

            daily,

            date

        )

        if c is not None:

            rows.append(c)

    if not rows:

        return pd.DataFrame()

    df = pd.DataFrame(

        rows

    )

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

    long_count = sum(

        1

        for p in positions

        if p["side"] == "LONG"

    )

    short_count = sum(

        1

        for p in positions

        if p["side"] == "SHORT"

    )

    # ========================================================

    # LONG

    # ========================================================

    long = df[

        df["RS"] >=

        LONG_RS_THRESHOLD

    ]

    long = long[

        long["close_1245"]

        >=

        long["morning_high"]

    ]

    # 12:45時点で100株買えるものだけ

    long = long[

        long["close_1245"].apply(

            lambda x:

            calc_order_quantity(

                equity,

                float(x),

                LONG_LEVERAGE

            ) >= LOT_SIZE

        )

    ]

    if (

        not long.empty

        and

        long_count < MAX_LONG_POSITIONS

    ):

        x = (

            long

            .sort_values(

                "score",

                ascending=False

            )

            .iloc[0]

            .to_dict()

        )

        x["side"] = "LONG"

        x["quantity"] = calc_order_quantity(

            equity,

            float(x["close_1245"]),

            LONG_LEVERAGE

        )

        result.append(x)

    # ========================================================

    # SHORT

    # ========================================================

    short = df[

        df["RS"] <=

        SHORT_RS_THRESHOLD

    ]

    short = short[

        short["close_1245"]

        <=

        short["morning_low"]

    ]

    # 12:45時点で100株単位の建玉が可能なものだけ

    short = short[

        short["close_1245"].apply(

            lambda x:

            calc_order_quantity(

                equity,

                float(x),

                SHORT_LEVERAGE

            ) >= LOT_SIZE

        )

    ]

    if (

        not short.empty

        and

        short_count < MAX_SHORT_POSITIONS

    ):

        x = (

            short

            .sort_values(

                "score",

                ascending=False

            )

            .iloc[0]

            .to_dict()

        )

        x["side"] = "SHORT"

        x["quantity"] = calc_order_quantity(

            equity,

            float(x["close_1245"]),

            SHORT_LEVERAGE

        )

        result.append(x)

    return pd.DataFrame(

        result

    )

# ============================================================

# 12:45 Decision

# ============================================================

def run_decision(

    intraday,

    daily,

    portfolio

):

    date = now_jst().normalize()

    equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

    candidates = select_candidates(

        intraday,

        daily,

        equity,

        positions

    )

    if candidates.empty:

        result_text = (

            f"{VERSION}\n\n"

            f"12:45判定\n\n"

            f"候補なし\n"

        )

        save_result_text(

            result_text

        )

        return

    pending = []

    for _, row in candidates.iterrows():

        quantity = int(

            row["quantity"]

        )

        if quantity < LOT_SIZE:

            continue

        pending.append({

            "date":

                str(date.date()),

            "ticker":

                row["ticker"],

            "side":

                row["side"],

            "quantity":

                quantity,

            "planned_entry_time":

                ENTRY_TIME,

            "close_1245":

                float(row["close_1245"]),

            "morning_high":

                float(row["morning_high"]),

            "morning_low":

                float(row["morning_low"]),

            "RS":

                float(row["RS"]),

            "score":

                float(row["score"])

        })

    save_pending(

        pending

    )

    candidates.to_csv(

        CANDIDATE_FILE,

        index=False,

        encoding="utf-8-sig"

    )

    lines = []

    lines.append(

        f"{VERSION}"

    )

    lines.append("")

    lines.append(

        "12:45確定足で判定"

    )

    lines.append("")

    lines.append(

        "12:50 OPEN予定"

    )

    lines.append("")

    if not pending:

        lines.append(

            "注文なし"

        )

    for p in pending:

        lines.append(

            f'{p["side"]} '

            f'{p["ticker"]} '

            f'{p["quantity"]}株'

        )

        lines.append(

            f'12:45価格: '

            f'{p["close_1245"]:,.1f}'

        )

        lines.append(

            f'想定金額: '

            f'¥{p["close_1245"] * p["quantity"]:,.0f}'

        )

        lines.append(

            f'RS: '

            f'{p["RS"]:.1f}'

        )

        lines.append(

            f'Score: '

            f'{p["score"]:.1f}'

        )

        lines.append("")

    result_text = "\n".join(

        lines

    )

    print(result_text)

    save_result_text(

        result_text

    )

# ============================================================

# 12:50 Entry Price

# ============================================================

def get_entry_price(

    ticker,

    date,

    intraday

):

    if ticker not in intraday:

        return None

    df = intraday[ticker]

    day = df[

        df.index.date ==

        date.date()

    ]

    if day.empty:

        return None

    entry_time = pd.Timestamp(

        f"{date.strftime('%Y-%m-%d')} "

        f"{ENTRY_TIME}:00"

    )

    entry_df = day[

        day.index >= entry_time

    ]

    if entry_df.empty:

        return None

    return float(

        entry_df.iloc[0]["Open"]

    )

# ============================================================

# Position Check

# ============================================================

def check_position(

    position,

    intraday,

    date

):

    ticker = position["ticker"]

    side = position["side"]

    entry_price = float(

        position["entry_price"]

    )

    entry_date = pd.Timestamp(

        position["entry_date"]

    )

    if ticker not in intraday:

        return None

    if entry_date.date() == date.date():

        start_time = pd.Timestamp(

            f"{date.strftime('%Y-%m-%d')} "

            f"{ENTRY_TIME}:00"

        )

    else:

        start_time = pd.Timestamp(

            f"{date.strftime('%Y-%m-%d')} "

            f"09:00:00"

        )

    df = intraday[ticker]

    day = df[

        df.index.date ==

        date.date()

    ]

    after = day[

        day.index >= start_time

    ]

    if after.empty:

        return None

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

    for idx, bar in after.iterrows():

        high = float(

            bar["High"]

        )

        low = float(

            bar["Low"]

        )

        if side == "LONG":

            if low <= sl_price:

                return {

                    "exit_price":

                        sl_price,

                    "exit_time":

                        str(idx),

                    "reason":

                        "SL"

                }

            if high >= tp_price:

                return {

                    "exit_price":

                        tp_price,

                    "exit_time":

                        str(idx),

                    "reason":

                        "TP"

                }

        else:

            if high >= sl_price:

                return {

                    "exit_price":

                        sl_price,

                    "exit_time":

                        str(idx),

                    "reason":

                        "SL"

                }

            if low <= tp_price:

                return {

                    "exit_price":

                        tp_price,

                    "exit_time":

                        str(idx),

                    "reason":

                        "TP"

                }

    return None

# ============================================================

# 15:45 Result

# ============================================================

def run_result(

    intraday,

    daily,

    portfolio

):

    today = now_jst()

    date = today.normalize()

    equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

    pending = load_pending()

    trades = []

    total_pnl = 0

    # ========================================================

    # 12:50 OPEN

    # ========================================================

    for order in pending:

        ticker = order["ticker"]

        side = order["side"]

        quantity = int(

            order["quantity"]

        )

        entry_price = get_entry_price(

            ticker,

            date,

            intraday

        )

        if entry_price is None:

            continue

        # ----------------------------------------------------

        # 12:50実価格でも100株購入可能か確認

        # ----------------------------------------------------

        leverage = (

            LONG_LEVERAGE

            if side == "LONG"

            else SHORT_LEVERAGE

        )

        max_quantity = calc_order_quantity(

            equity,

            entry_price,

            leverage

        )

        if max_quantity < LOT_SIZE:

            print(

                f"{ticker}: "

                f"12:50価格では資金不足"

            )

            continue

        quantity = min(

            quantity,

            max_quantity

        )

        quantity = (

            quantity // LOT_SIZE

        ) * LOT_SIZE

        if quantity < LOT_SIZE:

            continue

        position = {

            "ticker":

                ticker,

            "side":

                side,

            "entry_date":

                str(date.date()),

            "entry_price":

                entry_price,

            "quantity":

                quantity,

            "leverage":

                leverage

        }

        positions.append(

            position

        )

    save_pending([])

    # ========================================================

    # TP / SL確認

    # ========================================================

    remaining = []

    for position in positions:

        result = check_position(

            position,

            intraday,

            date

        )

        if result is None:

            remaining.append(

                position

            )

            continue

        entry_price = float(

            position["entry_price"]

        )

        exit_price = float(

            result["exit_price"]

        )

        quantity = int(

            position["quantity"]

        )

        side = position["side"]

        if side == "LONG":

            ret = (

                exit_price /

                entry_price -

                1

            )

            pnl = (

                exit_price -

                entry_price

            ) * quantity

        else:

            ret = (

                entry_price /

                exit_price -

                1

            )

            pnl = (

                entry_price -

                exit_price

            ) * quantity

        total_pnl += pnl

        trades.append({

            "date":

                str(date.date()),

            "ticker":

                position["ticker"],

            "side":

                side,

            "quantity":

                quantity,

            "entry":

                entry_price,

            "exit":

                exit_price,

            "return":

                ret,

            "pnl":

                pnl,

            "reason":

                result["reason"],

            "entry_date":

                position["entry_date"],

            "exit_time":

                result["exit_time"]

        })

    # ========================================================

    # 資産更新

    # ========================================================

    new_equity = (

        equity +

        total_pnl

    )

    portfolio["equity"] = (

        new_equity

    )

    portfolio["positions"] = (

        remaining

    )

    portfolio["last_update"] = (

        datetime.now()

        .strftime(

            "%Y-%m-%d %H:%M:%S"

        )

    )

    save_portfolio(

        portfolio

    )

    save_csv(

        TRADE_FILE,

        trades

    )

    # ========================================================

    # 結果

    # ========================================================

    lines = []

    lines.append(

        f"{VERSION}"

    )

    lines.append("")

    lines.append(

        "15:45 結果"

    )

    lines.append("")

    lines.append(

        f"前資産: "

        f"¥{equity:,.0f}"

    )

    lines.append(

        f"損益: "

        f"¥{total_pnl:,.0f}"

    )

    lines.append(

        f"現在資産: "

        f"¥{new_equity:,.0f}"

    )

    lines.append("")

    if trades:

        lines.append(

            "決済:"

        )

        for t in trades:

            lines.append(

                f'{t["side"]} '

                f'{t["ticker"]} '

                f'{t["quantity"]}株 '

                f'{t["reason"]} '

                f'{t["pnl"]:+,.0f}円'

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

                f'{p["side"]} '

                f'{p["ticker"]} '

                f'{p["quantity"]}株 '

                f'建値 '

                f'{float(p["entry_price"]):,.1f}'

            )

    else:

        lines.append(

            "持越し: なし"

        )

    result_text = "\n".join(

        lines

    )

    print(result_text)

    save_result_text(

        result_text

    )

# ============================================================

# CSV保存

# ============================================================

def save_csv(

    filename,

    rows

):

    if not rows:

        return

    new = pd.DataFrame(

        rows

    )

    if os.path.exists(

        filename

    ):

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

# Data Load

# ============================================================

def load_all_data():

    intraday = {}

    daily = {}

    success_5m = 0

    success_daily = 0

    print(

        "データ更新開始"

    )

    for ticker in TICKERS:

        df5 = download_5m(

            ticker

        )

        if df5 is not None:

            intraday[ticker] = df5

            success_5m += 1

        dd = download_daily(

            ticker

        )

        if dd is not None:

            daily[ticker] = dd

            success_daily += 1

    print(

        f"5分足: "

        f"{success_5m}銘柄"

    )

    print(

        f"日足: "

        f"{success_daily}銘柄"

    )

    return (

        intraday,

        daily

    )

# ============================================================

# MAIN

# ============================================================

def main():

    print("=" * 80)

    print(

        f"{VERSION} START"

    )

    print("=" * 80)

    mode = get_run_mode()

    print(

        f"RUN MODE: {mode}"

    )

    portfolio = load_portfolio()

    print(

        f"現在資産: "

        f"¥{float(portfolio['equity']):,.0f}"

    )

    intraday, daily = (

        load_all_data()

    )

    if mode == "decision":

        run_decision(

            intraday,

            daily,

            portfolio

        )

    else:

        run_result(

            intraday,

            daily,

            portfolio

        )

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
