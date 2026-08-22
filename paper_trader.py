# ============================================================

# v33.11 Cloud Paper Trader

# 高速化版

#

# 変更点

# ・日足をキャッシュ

# ・5分足を一括取得

# ・Yahooエラーを画面に大量表示しない

# ・100株単位

# ・LONG最大1銘柄

# ・SHORT最大1銘柄

# ・TP/SL未到達なら持越し

# ・12:45確定足で判定

# ・12:50 OPEN

# ============================================================

import os

import json

import warnings

import traceback

from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

import yfinance as yf

import pandas as pd

import numpy as np

# ============================================================

# 基本設定

# ============================================================

VERSION = "v33.11"

PROJECT_DIR = os.path.dirname(

    os.path.abspath(__file__)

)

DATA_DIR = os.path.join(

    PROJECT_DIR,

    "data"

)

CACHE_DIR = os.path.join(

    DATA_DIR,

    "cache"

)

DAILY_CACHE_FILE = os.path.join(

    CACHE_DIR,

    "daily_cache.pkl"

)

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

os.makedirs(

    DATA_DIR,

    exist_ok=True

)

os.makedirs(

    CACHE_DIR,

    exist_ok=True

)

# ============================================================

# 資金

# ============================================================

INITIAL_CAPITAL = 1_117_792

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

LOT_SIZE = 100

DECISION_TIME = "12:45"

ENTRY_TIME = "12:50"

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

TICKERS = list(

    dict.fromkeys(TICKERS)

)

# ============================================================

# 結果出力

# ============================================================

def write_result(text):

    with open(

        RESULT_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        f.write(text)

    print(text)

# ============================================================

# Portfolio

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

# Index

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

# Yahoo一括取得

# ============================================================

def download_5m():

    print(

        f"5分足取得: {len(TICKERS)}銘柄"

    )

    try:

        data = yf.download(

            tickers=TICKERS,

            period="3d",

            interval="5m",

            auto_adjust=False,

            progress=False,

            threads=True,

            group_by="ticker"

        )

    except Exception:

        return {}

    if data is None or data.empty:

        return {}

    data = normalize_index(

        data

    )

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

    # --------------------------------------------------------

    # tickerがlevel0

    # --------------------------------------------------------

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

                required = [

                    "Open",

                    "High",

                    "Low",

                    "Close",

                    "Volume"

                ]

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=[

                        "Close"

                    ]

                )

                if not df.empty:

                    result[

                        ticker

                    ] = df

            except Exception:

                continue

    # --------------------------------------------------------

    # tickerがlevel1

    # --------------------------------------------------------

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

                required = [

                    "Open",

                    "High",

                    "Low",

                    "Close",

                    "Volume"

                ]

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=[

                        "Close"

                    ]

                )

                if not df.empty:

                    result[

                        ticker

                    ] = df

            except Exception:

                continue

    return result

# ============================================================

# 日足キャッシュ

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

def save_daily_cache(

    data

):

    try:

        pd.to_pickle(

            data,

            DAILY_CACHE_FILE

        )

    except Exception:

        pass

def download_daily():

    cache = load_daily_cache()

    # --------------------------------------------------------

    # キャッシュが十分ある場合はYahooへ行かない

    # --------------------------------------------------------

    valid_cache = True

    if not cache:

        valid_cache = False

    else:

        for ticker in TICKERS:

            if ticker not in cache:

                valid_cache = False

                break

            df = cache[ticker]

            if df is None or df.empty:

                valid_cache = False

                break

            if len(df) < (

                RS_LOOKBACK + 5

            ):

                valid_cache = False

                break

    if valid_cache:

        print(

            "日足: キャッシュ使用"

        )

        return cache

    # --------------------------------------------------------

    # 初回だけ取得

    # --------------------------------------------------------

    print(

        "日足: 初回取得"

    )

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

    except Exception:

        return cache

    if data is None or data.empty:

        return cache

    result = {}

    if not isinstance(

        data.columns,

        pd.MultiIndex

    ):

        return cache

    level0 = set(

        data.columns.get_level_values(0)

    )

    level1 = set(

        data.columns.get_level_values(1)

    )

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

                required = [

                    "Open",

                    "High",

                    "Low",

                    "Close",

                    "Volume"

                ]

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=[

                        "Close"

                    ]

                )

                if not df.empty:

                    result[

                        ticker

                    ] = df

            except Exception:

                continue

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

                required = [

                    "Open",

                    "High",

                    "Low",

                    "Close",

                    "Volume"

                ]

                if not all(

                    c in df.columns

                    for c in required

                ):

                    continue

                df = df[

                    required

                ].dropna(

                    subset=[

                        "Close"

                    ]

                )

                if not df.empty:

                    result[

                        ticker

                    ] = df

            except Exception:

                continue

    if result:

        save_daily_cache(

            result

        )

        return result

    return cache

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

    now = float(

        past["Close"].iloc[-1]

    )

    old = float(

        past["Close"]

        .iloc[

            -RS_LOOKBACK - 1

        ]

    )

    if old <= 0:

        return np.nan

    return (

        now / old - 1

    )

# ============================================================

# 候補作成

# ============================================================

def make_candidate(

    ticker,

    intraday,

    daily,

    target_date

):

    if intraday is None:

        return None

    if daily is None:

        return None

    if intraday.empty:

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

    cutoff = pd.Timestamp(

        f"{target_date:%Y-%m-%d} "

        f"{DECISION_TIME}:00"

    )

    before = day[

        day.index <= cutoff

    ]

    if before.empty:

        return None

    # --------------------------------------------------------

    # 12:45確定足

    # --------------------------------------------------------

    exact = before[

        before.index.time ==

        datetime.strptime(

            DECISION_TIME,

            "%H:%M"

        ).time()

    ]

    if exact.empty:

        return None

    close_1245 = float(

        exact["Close"].iloc[-1]

    )

    # --------------------------------------------------------

    # 前場

    # --------------------------------------------------------

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

    # --------------------------------------------------------

    # VWAP

    # --------------------------------------------------------

    volume = (

        before["Volume"]

        .astype(float)

    )

    if volume.sum() > 0:

        vwap = float(

            (

                before["Close"]

                * volume

            ).sum()

            /

            volume.sum()

        )

    else:

        vwap = close_1245

    # --------------------------------------------------------

    # 前日終値

    # --------------------------------------------------------

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

    # --------------------------------------------------------

    # 午後

    # --------------------------------------------------------

    afternoon = before[

        before.index.time >=

        datetime.strptime(

            "12:00",

            "%H:%M"

        ).time()

    ]

    if not afternoon.empty:

        afternoon_return = (

            close_1245 /

            float(

                afternoon["Open"].iloc[0]

            )

            - 1

        )

    else:

        afternoon_return = 0.0

    # --------------------------------------------------------

    # 直近

    # --------------------------------------------------------

    recent = before.tail(3)

    if len(recent) >= 2:

        recent_return = (

            close_1245 /

            float(

                recent["Close"].iloc[0]

            )

            - 1

        )

    else:

        recent_return = 0.0

    return {

        "ticker": ticker,

        "date": str(target),

        "morning_high": morning_high,

        "morning_low": morning_low,

        "close_1245": close_1245,

        "vwap": vwap,

        "day_return": day_return,

        "afternoon_return": afternoon_return,

        "recent_return": recent_return,

        "raw_rs": calc_rs(

            daily,

            target_date

        )

    }

# ============================================================

# 候補選択

# ============================================================

def select_candidates(

    intraday,

    daily

):

    now = pd.Timestamp.now(

        tz="Asia/Tokyo"

    ).tz_localize(None)

    target_date = now.normalize()

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

    df = df.dropna(

        subset=[

            "raw_rs"

        ]

    )

    if df.empty:

        return df

    # --------------------------------------------------------

    # RS

    # --------------------------------------------------------

    df["RS"] = (

        df["raw_rs"]

        .rank(

            pct=True

        )

        * 100

    )

    # --------------------------------------------------------

    # 各スコア

    # --------------------------------------------------------

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

        df["RS"] >=

        LONG_RS_THRESHOLD

    ].copy()

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

        df["RS"] <=

        SHORT_RS_THRESHOLD

    ].copy()

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

        entry_time = pd.Timestamp(

            f"{target_date:%Y-%m-%d} "

            f"{ENTRY_TIME}:00"

        )

        entry_rows = df[

            df.index >= entry_time

        ]

        if entry_rows.empty:

            continue

        entry_price = float(

            entry_rows.iloc[0]["Open"]

        )

        # ----------------------------------------------------

        # 必ず100株

        # ----------------------------------------------------

        shares = LOT_SIZE

        required = (

            entry_price *

            shares

        )

        if side == "LONG":

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

        else:

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

                "entry_time": str(

                    entry_time

                ),

                "entry_date": str(

                    target_date.date()

                )

            }

        )

    return positions

# ============================================================

# TP / SL

# ============================================================

def check_position(

    position,

    intraday

):

    ticker = position[

        "ticker"

    ]

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

    start_time = pd.Timestamp(

        position[

            "entry_time"

        ]

    )

    after = df[

        df.index > start_time

    ]

    if after.empty:

        return (

            False,

            None,

            None,

            None

        )

    side = position[

        "side"

    ]

    tp_price = float(

        position[

            "tp_price"

        ]

    )

    sl_price = float(

        position[

            "sl_price"

        ]

    )

    for idx, bar in after.iterrows():

        high = float(

            bar["High"]

        )

        low = float(

            bar["Low"]

        )

        # ----------------------------------------------------

        # LONG

        # ----------------------------------------------------

        if side == "LONG":

            # 同一足でTP/SL両方到達

            # 保守的にSL優先

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

        # ----------------------------------------------------

        # SHORT

        # ----------------------------------------------------

        else:

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

# RESULT

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

    if not positions:

        text = (

            "15:45 結果\n"

            "\n"

            f"前資産: ¥{old_equity:,.0f}\n"

            "損益: ¥0\n"

            f"現在資産: ¥{old_equity:,.0f}\n"

            "\n"

            "決済: なし\n"

            "持越し: なし\n"

        )

        write_result(

            text

        )

        return

    # --------------------------------------------------------

    # 既存ポジションだけ取得

    # --------------------------------------------------------

    intraday = download_5m()

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

            position[

                "entry_price"

            ]

        )

        shares = int(

            position[

                "shares"

            ]

        )

        side = position[

            "side"

        ]

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

            entry_price

            * shares

            * ret

        )

        total_pnl += pnl

        closed.append(

            {

                "date":

                    str(

                        exit_time.date()

                    ),

                "ticker":

                    position[

                        "ticker"

                    ],

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

                    reason,

                "entry_time":

                    position[

                        "entry_time"

                    ],

                "exit_time":

                    str(

                        exit_time

                    )

            }

        )

    new_equity = (

        old_equity +

        total_pnl

    )

    portfolio["equity"] = (

        new_equity

    )

    portfolio["positions"] = (

        remaining

    )

    portfolio["last_update"] = (

        datetime.now().strftime(

            "%Y-%m-%d %H:%M:%S"

        )

    )

    save_portfolio(

        portfolio

    )

    # --------------------------------------------------------

    # Trade保存

    # --------------------------------------------------------

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

    # --------------------------------------------------------

    # メール本文

    # --------------------------------------------------------

    lines = []

    lines.append(

        "15:45 結果"

    )

    lines.append("")

    lines.append(

        f"前資産: ¥{old_equity:,.0f}"

    )

    lines.append(

        f"損益: ¥{total_pnl:,.0f}"

    )

    lines.append(

        f"現在資産: ¥{new_equity:,.0f}"

    )

    lines.append("")

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

        for position in remaining:

            lines.append(

                f"{position['side']} "

                f"{position['ticker']} "

                f"{position['shares']}株 "

                f"建値 "

                f"{position['entry_price']:,.1f}円"

            )

    else:

        lines.append(

            "持越し: なし"

        )

    write_result(

        "\n".join(lines)

    )

# ============================================================

# DECISION

# ============================================================

def run_decision():

    portfolio = load_portfolio()

    equity = float(

        portfolio["equity"]

    )

    positions = portfolio.get(

        "positions",

        []

    )

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

    # --------------------------------------------------------

    # 5分足

    # --------------------------------------------------------

    intraday = download_5m()

    # --------------------------------------------------------

    # 日足

    # 初回だけYahoo

    # 2回目以降キャッシュ

    # --------------------------------------------------------

    daily = download_daily()

    # --------------------------------------------------------

    # 候補

    # --------------------------------------------------------

    candidates = select_candidates(

        intraday,

        daily

    )

    selected = []

    if not candidates.empty:

        for _, row in candidates.iterrows():

            side = row[

                "side"

            ]

            if (

                side == "LONG"

                and

                long_count <

                MAX_LONG_POSITIONS

            ):

                selected.append(

                    row

                )

                long_count += 1

            elif (

                side == "SHORT"

                and

                short_count <

                MAX_SHORT_POSITIONS

            ):

                selected.append(

                    row

                )

                short_count += 1

    if selected:

        selected_df = pd.DataFrame(

            selected

        )

    else:

        selected_df = pd.DataFrame()

    # --------------------------------------------------------

    # 12:50 OPEN

    # --------------------------------------------------------

    new_positions = create_positions(

        selected_df,

        intraday,

        equity

    )

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

    # --------------------------------------------------------

    # Candidate保存

    # --------------------------------------------------------

    if not selected_df.empty:

        selected_df.to_csv(

            CANDIDATE_FILE,

            index=False,

            encoding="utf-8-sig"

        )

    # --------------------------------------------------------

    # メール

    # --------------------------------------------------------

    lines = []

    lines.append(

        "12:45 判定"

    )

    lines.append("")

    lines.append(

        f"現在資産: ¥{equity:,.0f}"

    )

    lines.append("")

    long_positions = [

        p

        for p in new_positions

        if p["side"] == "LONG"

    ]

    short_positions = [

        p

        for p in new_positions

        if p["side"] == "SHORT"

    ]

    # --------------------------------------------------------

    # LONG

    # --------------------------------------------------------

    if long_positions:

        p = long_positions[0]

        lines.append(

            f"LONG: {p['ticker']}"

        )

        lines.append(

            f"12:50 OPEN: "

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

    else:

        lines.append(

            "LONG: なし"

        )

    lines.append("")

    # --------------------------------------------------------

    # SHORT

    # --------------------------------------------------------

    if short_positions:

        p = short_positions[0]

        lines.append(

            f"SHORT: {p['ticker']}"

        )

        lines.append(

            f"12:50 OPEN: "

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

    else:

        lines.append(

            "SHORT: なし"

        )

    lines.append("")

    lines.append(

        f"新規取引: "

        f"{len(new_positions)}件"

    )

    write_result(

        "\n".join(lines)

    )

# ============================================================

# RUN MODE

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

    mode = get_run_mode()

    print("=" * 80)

    print(

        f"{VERSION} START"

    )

    print(

        f"RUN MODE: {mode}"

    )

    print("=" * 80)

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

            f"{VERSION} ERROR\n"

            "\n"

            f"RUN MODE: {mode}\n"

            "\n"

            f"{type(e).__name__}: {e}\n"

            "\n"

            f"{traceback.format_exc()}"

        )

        write_result(

            error_text

        )

        raise

    finally:

        print("=" * 80)

        print(

            f"{VERSION} END"

        )

        print("=" * 80)

if __name__ == "__main__":

    main()
