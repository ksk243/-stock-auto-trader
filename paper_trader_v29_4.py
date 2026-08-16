# -*- coding: utf-8 -*-

import os

import json

from datetime import datetime

from zoneinfo import ZoneInfo

import numpy as np

import pandas as pd

import yfinance as yf

# ============================================================

# v29.4 Paper Trader

# LONG + SHORT 各1倍

# ============================================================

TZ = ZoneInfo("Asia/Tokyo")

# ----------------------------

# 初期資産

# キオクシア26株 × 金曜日終値

# 1,117,792円

# ----------------------------

INITIAL_CAPITAL = 1_117_792

# ----------------------------

# レバレッジ

# ----------------------------

LONG_LEVERAGE = 1.0

SHORT_LEVERAGE = 1.0

# ----------------------------

# RS

# ----------------------------

RS_LOOKBACK = 20

LONG_RS_THRESHOLD = 70.0

SHORT_RS_THRESHOLD = 30.0

# ----------------------------

# TP / SL

# ----------------------------

TP = 0.020

SL = 0.015

# ----------------------------

# 時刻

# ----------------------------

MORNING_START = "09:00"

MORNING_END = "12:40"

ENTRY_TIME = "12:45"

# ----------------------------

# 最大ポジション数

# ----------------------------

MAX_LONG_POSITIONS = 10

MAX_SHORT_POSITIONS = 10

# ----------------------------

# ETF / 市場RS

# ----------------------------

MARKET_TICKER = "1306.T"

# ----------------------------

# ファイル

# ----------------------------

PORTFOLIO_FILE = "data/v29_4_portfolio.json"

TRADES_FILE = "data/v29_4_trades.csv"

# ============================================================

# ユニバース

# ============================================================

UNIVERSE = [

    "1301.T","1332.T","1333.T","1605.T",

    "1721.T","1801.T","1802.T","1803.T","1808.T",

    "1812.T","1925.T","1928.T","1963.T",

    "2002.T","2267.T","2269.T","2282.T","2413.T",

    "2501.T","2502.T","2503.T","2531.T","2768.T",

    "2801.T","2802.T","2871.T","2914.T","3086.T",

    "3092.T","3099.T","3101.T","3103.T","3105.T",

    "3116.T","3141.T","3382.T","3401.T","3402.T",

    "3405.T","3407.T","3436.T","3659.T","3861.T",

    "3863.T","4004.T","4005.T","4021.T","4042.T",

    "4043.T","4061.T","4062.T","4063.T","4183.T",

    "4188.T","4202.T","4203.T","4502.T","4503.T",

    "4506.T","4507.T","4519.T","4523.T","4543.T",

    "4568.T","4578.T","4661.T","4689.T","4704.T",

    "4751.T","4901.T","4902.T","4911.T","5020.T",

    "5101.T","5108.T","5201.T","5202.T","5232.T",

    "5233.T","5301.T","5332.T","5333.T","5401.T",

    "5406.T","5411.T","5631.T","5706.T","5707.T",

    "5711.T","5713.T","5714.T","5801.T","5802.T",

    "5803.T","5831.T","6098.T","6103.T","6113.T",

    "6301.T","6302.T","6305.T","6326.T","6361.T",

    "6367.T","6471.T","6472.T","6473.T","6479.T",

    "6501.T","6503.T","6504.T","6506.T","6526.T",

    "6532.T","6594.T","6645.T","6674.T","6701.T",

    "6702.T","6723.T","6724.T","6752.T","6753.T",

    "6758.T","6762.T","6770.T","6841.T","6857.T",

    "6861.T","6869.T","6902.T","6920.T","6952.T",

    "6954.T","6971.T","6976.T","6981.T","7003.T",

    "7004.T","7011.T","7012.T","7013.T","7182.T",

    "7201.T","7202.T","7203.T","7205.T","7206.T",

    "7208.T","7211.T","7261.T","7267.T","7269.T",

    "7270.T","7272.T","7276.T","7309.T","7731.T",

    "7733.T","7735.T","7741.T","7751.T","7752.T",

    "7832.T","7911.T","7912.T","7951.T","7974.T",

    "8001.T","8002.T","8015.T","8031.T","8035.T",

    "8053.T","8058.T","8233.T","8252.T","8253.T",

    "8267.T","8303.T","8304.T","8306.T","8308.T",

    "8309.T","8316.T","8331.T","8354.T","8411.T",

    "8591.T","8601.T","8604.T","8630.T","8697.T",

    "8725.T","8750.T","8766.T","8795.T","8801.T",

    "8802.T","8804.T","8830.T","9001.T","9005.T",

    "9007.T","9008.T","9009.T","9020.T","9021.T",

    "9022.T","9064.T","9101.T","9104.T","9107.T",

    "9201.T","9202.T","9301.T","9412.T","9432.T",

    "9433.T","9434.T","9501.T","9502.T","9503.T",

    "9531.T","9532.T","9602.T","9613.T","9684.T",

    "9735.T","9766.T","9983.T","9984.T"

]

# ============================================================

# Yahoo共通

# ============================================================

def clean_yahoo(df):

    if df is None or df.empty:

        return None

    if isinstance(df.columns, pd.MultiIndex):

        df.columns = df.columns.get_level_values(0)

    df.columns = [

        str(c).lower()

        for c in df.columns

    ]

    required = [

        "open",

        "high",

        "low",

        "close"

    ]

    if not all(

        c in df.columns

        for c in required

    ):

        return None

    for c in required:

        df[c] = pd.to_numeric(

            df[c],

            errors="coerce"

        )

    df = df.dropna(

        subset=required

    )

    if df.empty:

        return None

    idx = pd.to_datetime(df.index)

    if getattr(idx, "tz", None) is not None:

        idx = (

            idx

            .tz_convert("Asia/Tokyo")

            .tz_localize(None)

        )

    df.index = idx

    return df.sort_index()

# ============================================================

# 日足

# ============================================================

def download_daily(ticker):

    try:

        df = yf.download(

            ticker,

            period="1y",

            interval="1d",

            auto_adjust=False,

            progress=False,

            threads=False

        )

        return clean_yahoo(df)

    except Exception as e:

        print(

            f"{ticker} 日足取得失敗: {e}"

        )

        return None

# ============================================================

# 5分足

# ============================================================

def download_5m(ticker):

    try:

        df = yf.download(

            ticker,

            period="5d",

            interval="5m",

            auto_adjust=False,

            progress=False,

            threads=False

        )

        return clean_yahoo(df)

    except Exception as e:

        print(

            f"{ticker} 5分足取得失敗: {e}"

        )

        return None
# ============================================================

# RS計算

# ============================================================

def calculate_rs():

    market = download_daily(

        MARKET_TICKER

    )

    if market is None:

        return {}

    market_close = pd.to_numeric(

        market["close"],

        errors="coerce"

    ).dropna()

    market_close.index = pd.to_datetime(

        market_close.index

    ).normalize()

    market_return = (

        market_close.shift(1)

        /

        market_close.shift(

            RS_LOOKBACK + 1

        )

        - 1

    )

    returns = {}

    for ticker in UNIVERSE:

        df = download_daily(

            ticker

        )

        if df is None:

            continue

        close = pd.to_numeric(

            df["close"],

            errors="coerce"

        ).dropna()

        if len(close) < RS_LOOKBACK + 2:

            continue

        close.index = pd.to_datetime(

            close.index

        ).normalize()

        returns[ticker] = (

            close.shift(1)

            /

            close.shift(

                RS_LOOKBACK + 1

            )

            - 1

        )

    if not returns:

        return {}

    stocks = pd.DataFrame(

        returns

    )

    common = stocks.index.intersection(

        market_return.index

    )

    stocks = stocks.loc[common]

    market_return = market_return.loc[common]

    relative = stocks.sub(

        market_return,

        axis=0

    )

    rs = (

        relative

        .rank(

            axis=1,

            pct=True

        )

        * 100

    )

    today = datetime.now(TZ).date()

    valid = rs[

        rs.index.date < today

    ]

    if valid.empty:

        return {}

    return valid.iloc[-1].dropna().to_dict()
    # ============================================================

# Morning High / Low

# ============================================================

def get_morning_levels(df, date):

    day = df[

        df.index.date == date

    ]

    if day.empty:

        return None, None

    morning = day.between_time(

        MORNING_START,

        MORNING_END

    )

    if morning.empty:

        return None, None

    morning_high = float(

        morning["high"].max()

    )

    morning_low = float(

        morning["low"].min()

    )

    return morning_high, morning_low

# ============================================================

# v29.4 12:45候補抽出

# LONG + SHORT

# ============================================================

def find_candidates():

    print("RS計算中...")

    rs = calculate_rs()

    if not rs:

        print("RSデータなし")

        return []

    today = datetime.now(TZ).date()

    candidates = []

    for ticker, rs_value in rs.items():

        side = None

        if rs_value >= LONG_RS_THRESHOLD:

            side = "LONG"

        elif rs_value <= SHORT_RS_THRESHOLD:

            side = "SHORT"

        else:

            continue

        df = download_5m(ticker)

        if df is None:

            continue

        morning_high, morning_low = (

            get_morning_levels(

                df,

                today

            )

        )

        if (

            morning_high is None

            or

            morning_low is None

        ):

            continue

        day = df[

            df.index.date == today

        ]

        if day.empty:

            continue

        # 12:45以降

        afternoon = day[

            day.index.strftime("%H:%M")

            >= ENTRY_TIME

        ]

        if afternoon.empty:

            continue

        # ----------------------------------------------------

        # v29.4

        # 実約定価格 = ブレイクした5分足のHigh / Low

        # ----------------------------------------------------

        if side == "LONG":

            for ts, row in afternoon.iterrows():

                high = float(row["high"])

                if high >= morning_high:

                    entry_price = high

                    candidates.append({

                        "ticker": ticker,

                        "side": "LONG",

                        "rs": float(rs_value),

                        "morning_high":

                            morning_high,

                        "morning_low":

                            morning_low,

                        "entry":

                            entry_price,

                        "tp":

                            entry_price * (1 + TP),

                        "sl":

                            entry_price * (1 - SL),

                        "time":

                            ts.isoformat()

                    })

                    break

        # ----------------------------------------------------

        # SHORT

        # ----------------------------------------------------

        elif side == "SHORT":

            for ts, row in afternoon.iterrows():

                low = float(row["low"])

                if low <= morning_low:

                    entry_price = low

                    candidates.append({

                        "ticker": ticker,

                        "side": "SHORT",

                        "rs": float(rs_value),

                        "morning_high":

                            morning_high,

                        "morning_low":

                            morning_low,

                        "entry":

                            entry_price,

                        "tp":

                            entry_price * (1 - TP),

                        "sl":

                            entry_price * (1 + SL),

                        "time":

                            ts.isoformat()

                    })

                    break

    # --------------------------------------------------------

    # LONGはRSが高い順

    # SHORTはRSが低い順

    # --------------------------------------------------------

    candidates.sort(

        key=lambda x: (

            0 if x["side"] == "LONG" else 1,

            -x["rs"]

            if x["side"] == "LONG"

            else x["rs"]

        )

    )

    print(

        f"Entry候補 : "

        f"{len(candidates)}件"

    )

    long_count = sum(

        c["side"] == "LONG"

        for c in candidates

    )

    short_count = sum(

        c["side"] == "SHORT"

        for c in candidates

    )

    print(

        f"LONG候補 : "

        f"{long_count}件"

    )

    print(

        f"SHORT候補 : "

        f"{short_count}件"

    )

    return candidates
# ============================================================

# 起動テスト

# ============================================================

def main():

    now = datetime.now(TZ)

    print("=" * 70)

    print("v29.4 Paper Trader")

    print("=" * 70)

    print(

        f"現在時刻 : "

        f"{now:%Y-%m-%d %H:%M:%S}"

    )

    print(

        f"初期資産 : "

        f"¥{INITIAL_CAPITAL:,.0f}"

    )

    print(

        f"LONG     : "

        f"{LONG_LEVERAGE:.1f}倍"

    )

    print(

        f"SHORT    : "

        f"{SHORT_LEVERAGE:.1f}倍"

    )

    print(

        f"RS       : "

        f"LONG >= {LONG_RS_THRESHOLD:.0f} / "

        f"SHORT <= {SHORT_RS_THRESHOLD:.0f}"

    )

    print(

        f"TP / SL  : "

        f"+{TP * 100:.1f}% / "

        f"-{SL * 100:.1f}%"

    )

    print()

    print("Yahoo Finance 接続テスト...")

    df = download_daily(MARKET_TICKER)

    if df is None:

        raise RuntimeError(

            "1306.T 日足取得失敗"

        )

    print(

        f"1306.T 日足取得OK : "

        f"{len(df)}本"

    )

    df5 = download_5m(MARKET_TICKER)

    if df5 is None:

        raise RuntimeError(

            "1306.T 5分足取得失敗"

        )

    print(

        f"1306.T 5分足取得OK : "

        f"{len(df5)}本"

    )

    print()

    print("v29.4 基礎動作確認 OK")

    print("=" * 70)

if __name__ == "__main__":

    main()
