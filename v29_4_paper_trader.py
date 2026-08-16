# -*- coding: utf-8 -*-

"""

v29.4 LONG + SHORT Paper Trader

完全No-Futureルール

LONG:

    RS >= 70

    前場Highブレイク

    建玉上限 = 現在Equity × 1.0

SHORT:

    RS <= 30

    前場Lowブレイク

    建玉上限 = 現在Equity × 1.0

最大合計建玉 = 現在Equity × 2.0

12:45:

    新規Entry判定

    iCloudメール送信

15:45:

    TP/SL確認

    決済

    iCloudメール送信

重要:

    初期資産はキオクシア26株

    1,117,792円

    TEST_MODE=1 の場合、

    売買・portfolio更新は行わず、

    データ取得と判定だけ実行する。

"""

import os

import json

import smtplib

import warnings

from datetime import datetime

from email.mime.text import MIMEText

from email.header import Header

from zoneinfo import ZoneInfo

import numpy as np

import pandas as pd

import yfinance as yf

warnings.filterwarnings("ignore")

# ============================================================

# 基本設定

# ============================================================

TZ = ZoneInfo("Asia/Tokyo")

INITIAL_CAPITAL = 1_117_792.0

LONG_LEVERAGE = 1.0

SHORT_LEVERAGE = 1.0

RS_LOOKBACK = 20

LONG_RS_THRESHOLD = 70.0

SHORT_RS_THRESHOLD = 30.0

TP = 0.020

SL = 0.015

MORNING_START = "09:00"

MORNING_END = "12:40"

ENTRY_TIME = "12:45"

MAX_LONG_POSITIONS = 10

MAX_SHORT_POSITIONS = 10

MARKET_TICKER = "1306.T"

PORTFOLIO_FILE = "data/portfolio.json"

TRADES_FILE = "data/trades.csv"

EQUITY_FILE = "data/equity.csv"

TEST_MODE = os.environ.get(

    "TEST_MODE",

    "0"

) == "1"

# ============================================================

# 銘柄ユニバース

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

# ディレクトリ

# ============================================================

def ensure_data_dir():

    os.makedirs(

        "data",

        exist_ok=True

    )

# ============================================================

# Yahoo共通

# ============================================================

def clean_columns(df):

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

    return None if df.empty else df

def normalize_index(df):

    if df is None or df.empty:

        return df

    idx = pd.to_datetime(

        df.index

    )

    if getattr(

        idx,

        "tz",

        None

    ) is not None:

        idx = (

            idx

            .tz_convert("Asia/Tokyo")

            .tz_localize(None)

        )

    df = df.copy()

    df.index = idx

    return df.sort_index()

# ============================================================

# 日足取得

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

        return normalize_index(

            clean_columns(df)

        )

    except Exception as e:

        print(

            f"{ticker} 日足取得失敗: {e}"

        )

        return None

# ============================================================

# 5分足取得

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

        return normalize_index(

            clean_columns(df)

        )

    except Exception as e:

        print(

            f"{ticker} 5分足取得失敗: {e}"

        )

        return None

# ============================================================

# Portfolio

# ============================================================

def create_empty_portfolio():

    return {

        "cash": INITIAL_CAPITAL,

        "realized_pnl": 0.0,

        "positions": [],

        "started_at": datetime.now(

            TZ

        ).isoformat(),

        "version": "v29.4"

    }

def load_portfolio():

    ensure_data_dir()

    if not os.path.exists(

        PORTFOLIO_FILE

    ):

        portfolio = (

            create_empty_portfolio()

        )

        save_portfolio(

            portfolio

        )

        return portfolio

    with open(

        PORTFOLIO_FILE,

        "r",

        encoding="utf-8"

    ) as f:

        portfolio = json.load(f)

    return portfolio

def save_portfolio(

    portfolio

):

    ensure_data_dir()

    with open(

        PORTFOLIO_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            portfolio,

            f,

            ensure_ascii=False,

            indent=2

        )

# ============================================================

# RS計算

# ============================================================

def calculate_rs():

    print(

        "RS計算開始..."

    )

    all_returns = {}

    for ticker in UNIVERSE:

        df = download_daily(

            ticker

        )

        if df is None:

            continue

        close = (

            df["close"]

            .dropna()

        )

        if len(close) < (

            RS_LOOKBACK + 2

        ):

            continue

        close.index = pd.to_datetime(

            close.index

        ).normalize()

        ret = (

            close.shift(1)

            /

            close.shift(

                RS_LOOKBACK + 1

            )

            - 1.0

        )

        all_returns[ticker] = ret

    if not all_returns:

        return {}

    stocks = pd.DataFrame(

        all_returns

    )

    stocks = stocks.dropna(

        how="all"

    )

    rs = (

        stocks

        .rank(

            axis=1,

            pct=True,

            method="average"

        )

        * 100.0

    )

    today = datetime.now(

        TZ

    ).date()

    valid = rs[

        rs.index.date < today

    ]

    if valid.empty:

        return {}

    latest = valid.iloc[-1]

    return (

        latest

        .dropna()

        .to_dict()

    )

# ============================================================

# Morning High / Low

# ============================================================

def get_morning_levels(

    df,

    date

):

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

    high = float(

        morning["high"].max()

    )

    low = float(

        morning["low"].min()

    )

    return high, low

# ============================================================

# v29.4 Entry候補

# ============================================================

def find_candidates():

    rs = calculate_rs()

    if not rs:

        print(

            "RSデータなし"

        )

        return []

    today = datetime.now(

        TZ

    ).date()

    candidates = []

    print(

        "5分足スキャン開始..."

    )

    for ticker, rs_value in rs.items():

        side = None

        if (

            rs_value

            >=

            LONG_RS_THRESHOLD

        ):

            side = "LONG"

        elif (

            rs_value

            <=

            SHORT_RS_THRESHOLD

        ):

            side = "SHORT"

        else:

            continue

        df = download_5m(

            ticker

        )

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

        afternoon = day[

            day.index.time

            >=

            pd.Timestamp(

                ENTRY_TIME

            ).time()

        ]

        if afternoon.empty:

            continue

        # ----------------------------------------------------

        # LONG

        # ----------------------------------------------------

        if side == "LONG":

            for ts, bar in (

                afternoon.iterrows()

            ):

                high = float(

                    bar["high"]

                )

                if high >= morning_high:

                    candidates.append({

                        "ticker":

                            ticker,

                        "side":

                            "LONG",

                        "rs":

                            float(

                                rs_value

                            ),

                        "time":

                            ts.isoformat(),

                        "entry":

                            high,

                        "morning_high":

                            morning_high,

                        "morning_low":

                            morning_low,

                        "tp":

                            high * (

                                1 + TP

                            ),

                        "sl":

                            high * (

                                1 - SL

                            )

                    })

                    break

        # ----------------------------------------------------

        # SHORT

        # ----------------------------------------------------

        elif side == "SHORT":

            for ts, bar in (

                afternoon.iterrows()

            ):

                low = float(

                    bar["low"]

                )

                if low <= morning_low:

                    candidates.append({

                        "ticker":

                            ticker,

                        "side":

                            "SHORT",

                        "rs":

                            float(

                                rs_value

                            ),

                        "time":

                            ts.isoformat(),

                        "entry":

                            low,

                        "morning_high":

                            morning_high,

                        "morning_low":

                            morning_low,

                        "tp":

                            low * (

                                1 - TP

                            ),

                        "sl":

                            low * (

                                1 + SL

                            )

                    })

                    break

    return candidates

# ============================================================

# 現在Equity

# ============================================================

def calculate_equity(

    portfolio

):

    equity = float(

        portfolio["cash"]

    )

    today = datetime.now(

        TZ

    ).date()

    for p in portfolio[

        "positions"

    ]:

        df = download_5m(

            p["ticker"]

        )

        if df is None:

            continue

        day = df[

            df.index.date == today

        ]

        if day.empty:

            continue

        last_price = float(

            day["close"].iloc[-1]

        )

        if p["side"] == "LONG":

            equity += (

                last_price

                *

                p["shares"]

            )

        else:

            # SHORTでは売却代金をcashに

            # 反映させず、評価損益だけを加える

            equity += (

                (

                    p["entry_price"]

                    -

                    last_price

                )

                *

                p["shares"]

            )

    return equity

# ============================================================

# 現在建玉

# ============================================================

def exposure(

    portfolio,

    side

):

    return sum(

        float(p["entry_price"])

        *

        int(p["shares"])

        for p in portfolio[

            "positions"

        ]

        if p["side"] == side

    )

# ============================================================

# Entry

# ============================================================

def enter_positions(

    portfolio,

    candidates

):

    if TEST_MODE:

        print(

            "TEST_MODE=1 "

            "新規Entryは実行しません"

        )

        return []

    equity = calculate_equity(

        portfolio

    )

    long_limit = (

        equity

        *

        LONG_LEVERAGE

    )

    short_limit = (

        equity

        *

        SHORT_LEVERAGE

    )

    long_exposure = exposure(

        portfolio,

        "LONG"

    )

    short_exposure = exposure(

        portfolio,

        "SHORT"

    )

    executed = []

    existing = {

        p["ticker"]

        for p in portfolio[

            "positions"

        ]

    }

    # --------------------------------------------------------

    # LONG

    # --------------------------------------------------------

    longs = sorted(

        [

            c for c in candidates

            if c["side"] == "LONG"

        ],

        key=lambda x: x["rs"],

        reverse=True

    )

    for c in longs:

        if sum(

            p["side"] == "LONG"

            for p in portfolio[

                "positions"

            ]

        ) >= MAX_LONG_POSITIONS:

            break

        if c["ticker"] in existing:

            continue

        available = (

            long_limit

            -

            long_exposure

        )

        if available <= 0:

            break

        price = float(

            c["entry"]

        )

        shares = int(

            available

            /

            price

            /

            100

        ) * 100

        if shares <= 0:

            continue

        value = (

            price

            *

            shares

        )

        position = {

            "ticker":

                c["ticker"],

            "side":

                "LONG",

            "entry_date":

                datetime.now(

                    TZ

                ).date().isoformat(),

            "entry_time":

                c["time"],

            "entry_price":

                price,

            "shares":

                shares,

            "tp":

                c["tp"],

            "sl":

                c["sl"],

            "rs":

                c["rs"],

            "morning_high":

                c["morning_high"],

            "morning_low":

                c["morning_low"]

        }

        portfolio[

            "positions"

        ].append(position)

        long_exposure += value

        existing.add(

            c["ticker"]

        )

        executed.append(

            position

        )

    # --------------------------------------------------------

    # SHORT

    # --------------------------------------------------------

    shorts = sorted(

        [

            c for c in candidates

            if c["side"] == "SHORT"

        ],

        key=lambda x: x["rs"]

    )

    for c in shorts:

        if sum(

            p["side"] == "SHORT"

            for p in portfolio[

                "positions"

            ]

        ) >= MAX_SHORT_POSITIONS:

            break

        if c["ticker"] in existing:

            continue

        available = (

            short_limit

            -

            short_exposure

        )

        if available <= 0:

            break

        price = float(

            c["entry"]

        )

        shares = int(

            available

            /

            price

            /

            100

        ) * 100

        if shares <= 0:

            continue

        value = (

            price

            *

            shares

        )

        position = {

            "ticker":

                c["ticker"],

            "side":

                "SHORT",

            "entry_date":

                datetime.now(

                    TZ

                ).date().isoformat(),

            "entry_time":

                c["time"],

            "entry_price":

                price,

            "shares":

                shares,

            "tp":

                c["tp"],

            "sl":

                c["sl"],

            "rs":

                c["rs"],

            "morning_high":

                c["morning_high"],

            "morning_low":

                c["morning_low"]

        }

        portfolio[

            "positions"

        ].append(position)

        short_exposure += value

        existing.add(

            c["ticker"]

        )

        executed.append(

            position

        )

    return executed

# ============================================================

# TP / SL

# ============================================================

def check_positions(

    portfolio

):

    today = datetime.now(

        TZ

    ).date()

    closed = []

    holding = []

    for p in portfolio[

        "positions"

    ]:

        df = download_5m(

            p["ticker"]

        )

        if df is None:

            holding.append(p)

            continue

        day = df[

            df.index.date == today

        ]

        if day.empty:

            holding.append(p)

            continue

        tp = float(

            p["tp"]

        )

        sl = float(

            p["sl"]

        )

        exit_price = None

        reason = None

        for ts, bar in (

            day.iterrows()

        ):

            high = float(

                bar["high"]

            )

            low = float(

                bar["low"]

            )

            if p["side"] == "LONG":

                hit_tp = (

                    high >= tp

                )

                hit_sl = (

                    low <= sl

                )

            else:

                hit_tp = (

                    low <= tp

                )

                hit_sl = (

                    high >= sl

                )

            # 同一5分足

            # 保守的にSL

            if hit_tp and hit_sl:

                exit_price = sl

                reason = "SL"

                exit_time = ts

                break

            if hit_sl:

                exit_price = sl

                reason = "SL"

                exit_time = ts

                break

            if hit_tp:

                exit_price = tp

                reason = "TP"

                exit_time = ts

                break

        if exit_price is None:

            holding.append(p)

            continue

        if p["side"] == "LONG":

            pnl = (

                exit_price

                -

                p["entry_price"]

            ) * p["shares"]

            portfolio["cash"] += (

                exit_price

                *

                p["shares"]

            )

        else:

            pnl = (

                p["entry_price"]

                -

                exit_price

            ) * p["shares"]

            # SHORTの担保資金はcashに

            # 追加・減少させず、損益だけ反映

            portfolio["cash"] += pnl

        portfolio[

            "realized_pnl"

        ] += pnl

        closed.append({

            "datetime":

                datetime.now(

                    TZ

                ).isoformat(),

            "ticker":

                p["ticker"],

            "side":

                p["side"],

            "entry":

                p["entry_price"],

            "exit":

                exit_price,

            "shares":

                p["shares"],

            "pnl":

                pnl,

            "reason":

                reason,

            "entry_date":

                p["entry_date"],

            "exit_time":

                exit_time.isoformat()

        })

    portfolio[

        "positions"

    ] = holding

    return closed

# ============================================================

# CSV

# ============================================================

def append_csv(

    filename,

    rows

):

    if not rows:

        return

    ensure_data_dir()

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

            [old, new],

            ignore_index=True

        )

    new.to_csv(

        filename,

        index=False,

        encoding="utf-8-sig"

    )

# ============================================================

# メール

# ============================================================

def send_email(

    subject,

    body

):

    host = os.environ.get(

        "ICLOUD_SMTP_HOST",

        "smtp.mail.me.com"

    )

    port = int(

        os.environ.get(

            "ICLOUD_SMTP_PORT",

            "587"

        )

    )

    user = os.environ.get(

        "ICLOUD_EMAIL"

    )

    password = os.environ.get(

        "ICLOUD_APP_PASSWORD"

    )

    recipient = os.environ.get(

        "MAIL_TO"

    )

    if not all([

        user,

        password,

        recipient

    ]):

        print(

            "メール設定なし"

        )

        print(

            "ICLOUD_EMAIL / "

            "ICLOUD_APP_PASSWORD / "

            "MAIL_TO "

            "をGitHub Secretsに設定してください"

        )

        return

    msg = MIMEText(

        body,

        "plain",

        "utf-8"

    )

    msg["Subject"] = Header(

        subject,

        "utf-8"

    )

    msg["From"] = user

    msg["To"] = recipient

    with smtplib.SMTP(

        host,

        port,

        timeout=30

    ) as server:

        server.starttls()

        server.login(

            user,

            password

        )

        server.send_message(

            msg

        )

# ============================================================

# 12:45

# ============================================================

def run_1245():

    print(

        "=" * 70

    )

    print(

        "v29.4 12:45 ENTRY"

    )

    print(

        "=" * 70

    )

    portfolio = load_portfolio()

    candidates = (

        find_candidates()

    )

    print(

        f"Entry候補: "

        f"{len(candidates)}件"

    )

    executed = (

        enter_positions(

            portfolio,

            candidates

        )

    )

    if not TEST_MODE:

        save_portfolio(

            portfolio

        )

    equity = calculate_equity(

        portfolio

    )

    lines = []

    lines.append(

        "【v29.4 Paper Trader】"

    )

    lines.append(

        "12:45 ENTRY"

    )

    lines.append("")

    lines.append(

        f"Equity: "

        f"¥{equity:,.0f}"

    )

    lines.append(

        f"LONG枠: "

        f"¥{equity * LONG_LEVERAGE:,.0f}"

    )

    lines.append(

        f"SHORT枠: "

        f"¥{equity * SHORT_LEVERAGE:,.0f}"

    )

    lines.append("")

    if TEST_MODE:

        lines.append(

            "【TEST MODE】"

        )

        lines.append(

            "新規Entryなし"

        )

        lines.append("")

    if executed:

        lines.append(

            "【新規Entry】"

        )

        for p in executed:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥"

                f"{p['entry_price']:,.1f} "

                f"TP ¥"

                f"{p['tp']:,.1f} "

                f"SL ¥"

                f"{p['sl']:,.1f} "

                f"RS "

                f"{p['rs']:.1f}"

            )

    else:

        lines.append(

            "【新規Entryなし】"

        )

        if candidates:

            lines.append("")

            lines.append(

                "候補:"

            )

            for c in candidates[:10]:

                lines.append(

                    f"{c['side']} "

                    f"{c['ticker']} "

                    f"RS "

                    f"{c['rs']:.1f} "

                    f"Entry ¥"

                    f"{c['entry']:,.1f}"

                )

    lines.append("")

    lines.append(

        "【現在ポジション】"

    )

    if portfolio[

        "positions"

    ]:

        for p in portfolio[

            "positions"

        ]:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥"

                f"{p['entry_price']:,.1f}"

            )

    else:

        lines.append(

            "なし"

        )

    send_email(

        "【v29.4】12:45 売買指示",

        "\n".join(lines)

    )

# ============================================================

# 15:45

# ============================================================

def run_1545():

    print(

        "=" * 70

    )

    print(

        "v29.4 15:45 EXIT"

    )

    print(

        "=" * 70

    )

    portfolio = load_portfolio()

    closed = check_positions(

        portfolio

    )

    if not TEST_MODE:

        save_portfolio(

            portfolio

        )

        append_csv(

            TRADES_FILE,

            closed

        )

    equity = calculate_equity(

        portfolio

    )

    append_csv(

        EQUITY_FILE,

        [{

            "datetime":

                datetime.now(

                    TZ

                ).isoformat(),

            "equity":

                equity,

            "cash":

                portfolio[

                    "cash"

                ],

            "realized_pnl":

                portfolio[

                    "realized_pnl"

                ],

            "long_exposure":

                exposure(

                    portfolio,

                    "LONG"

                ),

            "short_exposure":

                exposure(

                    portfolio,

                    "SHORT"

                )

        }]

        if not TEST_MODE

        else []

    )

    lines = []

    lines.append(

        "【v29.4 Paper Trader】"

    )

    lines.append(

        "15:45 RESULT"

    )

    lines.append("")

    lines.append(

        f"Equity: "

        f"¥{equity:,.0f}"

    )

    lines.append(

        f"確定損益: "

        f"¥"

        f"{portfolio['realized_pnl']:,.0f}"

    )

    lines.append("")

    lines.append(

        "【本日の決済】"

    )

    if closed:

        for t in closed:

            sign = (

                "+"

                if t["pnl"] >= 0

                else ""

            )

            lines.append(

                f"{t['side']} "

                f"{t['ticker']} "

                f"{t['reason']} "

                f"{sign}"

                f"¥{t['pnl']:,.0f}"

            )

    else:

        lines.append(

            "決済なし"

        )

    lines.append("")

    lines.append(

        "【持越し】"

    )

    if portfolio[

        "positions"

    ]:

        for p in portfolio[

            "positions"

        ]:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥"

                f"{p['entry_price']:,.1f}"

            )

    else:

        lines.append(

            "なし"

        )

    send_email(

        "【v29.4】15:45 結果・持越し",

        "\n".join(lines)

    )

# ============================================================

# MAIN

# ============================================================

def main():

    now = datetime.now(

        TZ

    )

    print(

        "=" * 70

    )

    print(

        "v29.4 LONG + SHORT "

        "Paper Trader"

    )

    print(

        "=" * 70

    )

    print(

        f"現在時刻: "

        f"{now:%Y-%m-%d %H:%M:%S}"

    )

    print(

        f"TEST_MODE: "

        f"{TEST_MODE}"

    )

    print(

        f"初期資産: "

        f"¥{INITIAL_CAPITAL:,.0f}"

    )

    print()

    force_1245 = (

        os.environ.get(

            "FORCE_1245"

        )

        == "1"

    )

    force_1545 = (

        os.environ.get(

            "FORCE_1545"

        )

        == "1"

    )

    if force_1245:

        run_1245()

    elif force_1545:

        run_1545()

    elif (

        now.hour == 12

        and

        40 <= now.minute <= 55

    ):

        run_1245()

    elif (

        now.hour == 15

        and

        40 <= now.minute <= 55

    ):

        run_1545()

    else:

        print(

            "実行時間外"

        )

if __name__ == "__main__":

    main()
