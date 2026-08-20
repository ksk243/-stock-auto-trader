# ============================================================

# v33.8 Cloud Run Paper Trader

# LONG 1.0倍 + SHORT 1.0倍

#

# 12:45判定

# 12:50 OPEN約定

# TP +2%

# SL -1.5%

# 持越しあり

#

# 完全No-Future

# Cloud Run常駐版

# Gmail通知対応

# ============================================================

import warnings

warnings.filterwarnings("ignore")

import os

import json

import smtplib

from datetime import datetime

from email.mime.text import MIMEText

from email.mime.multipart import MIMEMultipart

import yfinance as yf

import pandas as pd

import numpy as np

# ============================================================

# 設定

# ============================================================

VERSION = "v33.8 Cloud"

INITIAL_CAPITAL = 1117792

DATA_DIR = "data"

PORTFOLIO_FILE = f"{DATA_DIR}/portfolio.json"

TRADE_FILE = f"{DATA_DIR}/paper_trades.csv"

CANDIDATE_FILE = f"{DATA_DIR}/paper_candidates.csv"

os.makedirs(

    DATA_DIR,

    exist_ok=True

)

# ============================================================

# Email

# ============================================================

def send_email(subject, body):

    smtp_user = os.environ.get(

        "MAIL_USER"

    )

    smtp_pass = os.environ.get(

        "MAIL_PASS"

    )

    mail_to = os.environ.get(

        "MAIL_TO"

    )

    if not smtp_user or not smtp_pass or not mail_to:

        raise RuntimeError(

            "メール用GitHub Secretsが未設定です"

        )

    msg = MIMEMultipart()

    msg["From"] = smtp_user

    msg["To"] = mail_to

    msg["Subject"] = subject

    msg.attach(

        MIMEText(

            body,

            "plain",

            "utf-8"

        )

    )

    with smtplib.SMTP_SSL(

        "smtp.gmail.com",

        465

    ) as server:

        server.login(

            smtp_user,

            smtp_pass

        )

        server.send_message(

            msg

        )

    print(

        "メール送信完了"

    )

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

HOLD_OVERNIGHT = True

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

# portfolio読み込み

# ============================================================

def load_portfolio():

    if not os.path.exists(PORTFOLIO_FILE):

        return {

            "equity": INITIAL_CAPITAL,

            "positions": []

        }

    with open(

        PORTFOLIO_FILE,

        "r",

        encoding="utf-8"

    ) as f:

        return json.load(f)

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

# データ取得

# ============================================================

def download_5m(ticker):

    try:

        df = yf.download(

            ticker,

            period="60d",

            interval="5m",

            auto_adjust=False,

            progress=False,

            threads=False

        )

        if df is None or df.empty:

            return None

        if isinstance(

            df.columns,

            pd.MultiIndex

        ):

            df.columns = (

                df.columns

                .get_level_values(0)

            )

        if df.index.tz is not None:

            df.index = (

                df.index

                .tz_convert(

                    "Asia/Tokyo"

                )

                .tz_localize(None)

            )

        df = df.sort_index()

        return df[

            [

                "Open",

                "High",

                "Low",

                "Close",

                "Volume"

            ]

        ].dropna()

    except Exception:

        return None

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

        if df is None or df.empty:

            return None

        if isinstance(

            df.columns,

            pd.MultiIndex

        ):

            df.columns = (

                df.columns

                .get_level_values(0)

            )

        return df[

            [

                "Open",

                "High",

                "Low",

                "Close",

                "Volume"

            ]

        ].dropna()

    except Exception:

        return None

# ============================================================

# RS計算

# 完全No-Future

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

        .iloc[-RS_LOOKBACK-1]

    )

    if old <= 0:

        return np.nan

    return (

        now / old - 1

    )

# ============================================================

# 候補作成

# 12:45まで確定データのみ

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

    ].copy()

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

            (

                before["Close"]

                *

                volume

            ).sum()

            /

            volume.sum()

        )

    else:

        vwap = close_1245

    if ticker not in daily:

        return None

    past = daily[ticker][

        daily[ticker].index.date < date.date()

    ]

    if past.empty:

        return None

    prev_close = float(

        past["Close"].iloc[-1]

    )

    day_return = (

        close_1245

        /

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

            float(

                afternoon["Close"].iloc[-1]

            )

            /

            float(

                afternoon["Open"].iloc[0]

            )

            - 1

        )

    else:

        afternoon_return = 0

    recent = before.tail(3)

    if len(recent) >= 2:

        recent_return = (

            float(

                recent["Close"].iloc[-1]

            )

            /

            float(

                recent["Close"].iloc[0]

            )

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

# 今日候補選定

# ============================================================

def select_candidates(

    intraday,

    daily

):

    today = pd.Timestamp.now(

        tz="Asia/Tokyo"

    ).tz_localize(None)

    date = today.normalize()

    rows = []

    for ticker in intraday:

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

    df = pd.DataFrame(rows)

    df = df.dropna(

        subset=[

            "raw_rs"

        ]

    )

    if df.empty:

        return df

    # ------------------------------------------------

    # 横断RS

    # ------------------------------------------------

    df["RS"] = (

        df["raw_rs"]

        .rank(

            pct=True

        )

        *

        100

    )

    # ------------------------------------------------

    # SCORE

    # ------------------------------------------------

    df["score"] = (

        df["RS"]

        *

        0.30

        +

        df["day_return"]

        .rank(

            pct=True

        )

        *

        100

        *

        0.30

        +

        df["afternoon_return"]

        .rank(

            pct=True

        )

        *

        100

        *

        0.25

        +

        df["recent_return"]

        .rank(

            pct=True

        )

        *

        100

        *

        0.15

    )

    result = []

    # ------------------------------------------------

    # LONG

    # ------------------------------------------------

    long = df[

        df["RS"]

        >=

        LONG_RS_THRESHOLD

    ].copy()

    long = long[

        long["close_1245"]

        >=

        long["morning_high"]

    ]

    long = long.sort_values(

        [

            "score",

            "RS"

        ],

        ascending=False

    )

    if not long.empty:

        x = long.iloc[0].to_dict()

        x["side"] = "LONG"

        result.append(x)

    # ------------------------------------------------

    # SHORT

    # ------------------------------------------------

    short = df[

        df["RS"]

        <=

        SHORT_RS_THRESHOLD

    ].copy()

    short = short[

        short["close_1245"]

        <=

        short["morning_low"]

    ]

    short = short.sort_values(

        [

            "score",

            "RS"

        ],

        ascending=True

    )

    if not short.empty:

        x = short.iloc[0].to_dict()

        x["side"] = "SHORT"

        result.append(x)

    return pd.DataFrame(result)

# ============================================================

# トレード実行

# 12:50 OPEN

# ============================================================

def execute_trade(

    candidate,

    intraday,

    equity

):

    ticker = candidate["ticker"]

    side = candidate["side"]

    date = candidate["date"]

    if ticker not in intraday:

        return None

    df = intraday[ticker]

    day = df[

        df.index.date == date.date()

    ]

    if day.empty:

        return None

    entry_time = pd.Timestamp(

        f"{date.strftime('%Y-%m-%d')} {ENTRY_TIME}:00"

    )

    entry_df = day[

        day.index >= entry_time

    ]

    if entry_df.empty:

        return None

    entry_price = float(

        entry_df.iloc[0]["Open"]

    )

    if side == "LONG":

        tp_price = entry_price * (

            1 + TP

        )

        sl_price = entry_price * (

            1 - SL

        )

    else:

        tp_price = entry_price * (

            1 - TP

        )

        sl_price = entry_price * (

            1 + SL

        )

    exit_price = None

    exit_reason = None

    exit_time = None

    after = day[

        day.index > entry_time

    ]

    for idx, bar in after.iterrows():

        high = float(bar["High"])

        low = float(bar["Low"])

        if side == "LONG":

            if low <= sl_price:

                exit_price = sl_price

                exit_reason = "SL"

                exit_time = idx

                break

            if high >= tp_price:

                exit_price = tp_price

                exit_reason = "TP"

                exit_time = idx

                break

        else:

            if high >= sl_price:

                exit_price = sl_price

                exit_reason = "SL"

                exit_time = idx

                break

            if low <= tp_price:

                exit_price = tp_price

                exit_reason = "TP"

                exit_time = idx

                break

              # ========================================================

    # 決済なし

    # ========================================================

    if exit_price is None:

        exit_price = float(

            day["Close"].iloc[-1]

        )

        exit_time = day.index[-1]

        exit_reason = "HOLD"

    # ========================================================

    # リターン計算

    # ========================================================

    if side == "LONG":

        ret = (

            exit_price

            /

            entry_price

            -

            1

        )

    else:

        ret = (

            entry_price

            /

            exit_price

            -

            1

        )

    # ========================================================

    # 損益

    # ========================================================

    if side == "LONG":

        pnl = (

            equity

            *

            LONG_LEVERAGE

            *

            ret

        )

    else:

        pnl = (

            equity

            *

            SHORT_LEVERAGE

            *

            ret

        )

    return {

        "date":

            str(date.date()),

        "ticker":

            ticker,

        "side":

            side,

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

            str(entry_time),

        "exit_time":

            str(exit_time)

    }

# ============================================================

# CSV保存

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

# MAIN

# ============================================================

def main():

    print("="*80)

    print(

        f"{VERSION} LONG + SHORT"

    )

    print("="*80)

    portfolio = load_portfolio()

    equity = portfolio["equity"]

    print(

        f"現在資産: ¥{equity:,.0f}"

    )

    print(

        "5分足取得中..."

    )

    intraday = {}

    daily = {}

    for ticker in TICKERS:

        df = download_5m(

            ticker

        )

        if df is not None:

            intraday[ticker] = df

        dd = download_daily(

            ticker

        )

        if dd is not None:

            daily[ticker] = dd

    print(

        f"取得完了 "

        f"{len(intraday)}銘柄"

    )

    candidates = select_candidates(

        intraday,

        daily

    )

    if candidates.empty:

        print(

            "候補なし"

        )

        send_email(

            f"{VERSION} 候補なし",

            "本日は候補なし"

        )

        return

    print()

    print("="*80)

    print("12:45候補")

    print("="*80)

    print(

        candidates.to_string(

            index=False

        )

    )

    candidates.to_csv(

        CANDIDATE_FILE,

        index=False,

        encoding="utf-8-sig"

    )

    trades = []

    # --------------------------------------------------------

    # LONG

    # --------------------------------------------------------

    long_candidates = candidates[

        candidates["side"]

        ==

        "LONG"

    ]

    if not long_candidates.empty:

        trade = execute_trade(

            long_candidates.iloc[0],

            intraday,

            equity

        )

        if trade:

            trades.append(trade)

    # --------------------------------------------------------

    # SHORT

    # --------------------------------------------------------

    short_candidates = candidates[

        candidates["side"]

        ==

        "SHORT"

    ]

    if not short_candidates.empty:

        trade = execute_trade(

            short_candidates.iloc[0],

            intraday,

            equity

        )

        if trade:

            trades.append(trade)

          # ========================================================

    # 資産更新

    # ========================================================

    total_pnl = 0

    for t in trades:

        total_pnl += t["pnl"]

    new_equity = (

        equity

        +

        total_pnl

    )

    portfolio["equity"] = new_equity

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

    print()

    print("="*80)

    print("結果")

    print("="*80)

    print(

        f"前資産 : ¥{equity:,.0f}"

    )

    print(

        f"損益   : ¥{total_pnl:,.0f}"

    )

    print(

        f"現在資産: ¥{new_equity:,.0f}"

    )

    # ========================================================

    # メール本文

    # ========================================================

    if trades:

        trade_text = pd.DataFrame(

            trades

        ).to_string(

            index=False

        )

    else:

        trade_text = "取引なし"

    mail_body = f"""

{VERSION}

Paper Trader 結果

日時:

{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

前資産:

¥{equity:,.0f}

損益:

¥{total_pnl:,.0f}

現在資産:

¥{new_equity:,.0f}

候補:

{candidates.to_string(index=False)}

取引:

{trade_text}

"""

    send_email(

        subject=f"{VERSION} Paper Trader",

        body=mail_body

    )

    print(

        "メール送信完了"

    )

    print()

    print("="*80)

    print(

        f"{VERSION} 完了"

    )

    print("="*80)

# ============================================================

# START

# ============================================================

if __name__ == "__main__":

    main()
