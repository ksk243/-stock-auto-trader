# -*- coding: utf-8 -*-

import os

import json

import smtplib

from email.mime.text import MIMEText

from email.header import Header

from datetime import datetime

from zoneinfo import ZoneInfo

import numpy as np

import pandas as pd

import yfinance as yf

# ============================================================

# Paper Trader v29.4

# LONG + SHORT 各1倍

# 実約定価格・保守版

# ============================================================

VERSION = "v29.4"

# ============================================================

# 基本設定

# ============================================================

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

TZ = ZoneInfo("Asia/Tokyo")

PORTFOLIO_FILE = "data/portfolio.json"

TRADES_FILE = "data/trades.csv"

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

# Yahoo共通

# ============================================================

def clean_columns(df):

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

    return None if df.empty else df

def normalize_index(df):

    if df is None or df.empty:

        return df

    idx = pd.to_datetime(

        df.index

    )

    if getattr(idx, "tz", None) is not None:

        idx = (

            idx

            .tz_convert("Asia/Tokyo")

            .tz_localize(None)

        )

    df = df.copy()

    df.index = idx

    return df.sort_index()

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

def load_portfolio():

    os.makedirs(

        "data",

        exist_ok=True

    )

    if not os.path.exists(

        PORTFOLIO_FILE

    ):

        portfolio = {

            "version": VERSION,

            "initial_capital": INITIAL_CAPITAL,

            "cash": INITIAL_CAPITAL,

            "realized_pnl": 0.0,

            "positions": [],

            "created_at":

                datetime.now(TZ).isoformat()

        }

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

def save_portfolio(portfolio):

    os.makedirs(

        "data",

        exist_ok=True

    )

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

#

# 12:45に使えるのは前営業日終値まで。

# 当日終値は絶対に使用しない。

# ============================================================

def calculate_rs():

    records = []

    today = datetime.now(TZ).date()

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

        close.index = (

            pd.to_datetime(

                close.index

            ).normalize()

        )

        # 前営業日まででRSを計算

        valid = close[

            close.index.date < today

        ]

        if len(valid) < RS_LOOKBACK + 1:

            continue

        current = valid.iloc[-1]

        past = valid.iloc[

            -1 - RS_LOOKBACK

        ]

        if past <= 0:

            continue

        ret = (

            current / past

            - 1.0

        )

        records.append({

            "ticker": ticker,

            "return": ret

        })

    if not records:

        return {}

    rs_df = pd.DataFrame(

        records

    )

    rs_df["RS"] = (

        rs_df["return"]

        .rank(

            pct=True,

            method="average"

        )

        * 100

    )

    return dict(

        zip(

            rs_df["ticker"],

            rs_df["RS"]

        )

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

# 12:45 Entry候補

#

# v29.4:

# LONG  = Morning Highを5分足Highが突破

# SHORT = Morning Lowを5分足Lowが突破

#

# 実約定価格：

# LONG  = ブレイク足High

# SHORT = ブレイク足Low

# ============================================================

def find_candidates():

    print("RS計算中...")

    rs = calculate_rs()

    if not rs:

        return []

    today = datetime.now(

        TZ

    ).date()

    candidates = []

    for ticker, rs_value in rs.items():

        side = None

        if rs_value >= LONG_RS_THRESHOLD:

            side = "LONG"

        elif rs_value <= SHORT_RS_THRESHOLD:

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

            for ts, row in afternoon.iterrows():

                high = float(

                    row["high"]

                )

                if high >= morning_high:

                    entry = high

                    candidates.append({

                        "ticker": ticker,

                        "side": "LONG",

                        "rs": float(rs_value),

                        "time": ts.isoformat(),

                        "entry": entry,

                        "tp":

                            entry * (1 + TP),

                        "sl":

                            entry * (1 - SL),

                        "morning_high":

                            morning_high,

                        "morning_low":

                            morning_low

                    })

                    break

        # ----------------------------------------------------

        # SHORT

        # ----------------------------------------------------

        else:

            for ts, row in afternoon.iterrows():

                low = float(

                    row["low"]

                )

                if low <= morning_low:

                    entry = low

                    candidates.append({

                        "ticker": ticker,

                        "side": "SHORT",

                        "rs": float(rs_value),

                        "time": ts.isoformat(),

                        "entry": entry,

                        "tp":

                            entry * (1 - TP),

                        "sl":

                            entry * (1 + SL),

                        "morning_high":

                            morning_high,

                        "morning_low":

                            morning_low

                    })

                    break

    candidates.sort(

        key=lambda x:

            x["rs"],

        reverse=False

    )

    # LONGはRS高い順、

    # SHORTはRS低い順

    longs = sorted(

        [

            c for c in candidates

            if c["side"] == "LONG"

        ],

        key=lambda x:

            x["rs"],

        reverse=True

    )

    shorts = sorted(

        [

            c for c in candidates

            if c["side"] == "SHORT"

        ],

        key=lambda x:

            x["rs"]

    )

    return longs + shorts

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

    for p in portfolio["positions"]:

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

        price = float(

            day["close"].iloc[-1]

        )

        if p["side"] == "LONG":

            equity += (

                price

                -

                p["entry_price"]

            ) * p["shares"]

        else:

            # SHORTは売却代金を

            # cashに入れていないため、

            # entry→currentの含み損益を加算

            equity += (

                p["entry_price"]

                -

                price

            ) * p["shares"]

    return equity

# ============================================================

# 仮想Entry

# ============================================================

def enter_positions(

    portfolio,

    candidates

):

    existing_long = {

        p["ticker"]

        for p in portfolio["positions"]

        if p["side"] == "LONG"

    }

    existing_short = {

        p["ticker"]

        for p in portfolio["positions"]

        if p["side"] == "SHORT"

    }

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

    current_long = sum(

        p["entry_price"] * p["shares"]

        for p in portfolio["positions"]

        if p["side"] == "LONG"

    )

    current_short = sum(

        p["entry_price"] * p["shares"]

        for p in portfolio["positions"]

        if p["side"] == "SHORT"

    )

    executed = []

    for c in candidates:

        ticker = c["ticker"]

        side = c["side"]

        if side == "LONG":

            if ticker in existing_long:

                continue

            if sum(

                p["side"] == "LONG"

                for p in portfolio["positions"]

            ) >= MAX_LONG_POSITIONS:

                continue

            available = (

                long_limit

                -

                current_long

            )

        else:

            if ticker in existing_short:

                continue

            if sum(

                p["side"] == "SHORT"

                for p in portfolio["positions"]

            ) >= MAX_SHORT_POSITIONS:

                continue

            available = (

                short_limit

                -

                current_short

            )

        if available <= 0:

            continue

        price = float(

            c["entry"]

        )

        shares = int(

            available / price

        )

        # 日本株単元株

        shares = (

            shares // 100

        ) * 100

        if shares <= 0:

            continue

        value = (

            price * shares

        )

        # LONG

        if side == "LONG":

            if value > portfolio["cash"]:

                # 現物cashではなく信用取引を想定。

                # ここでは信用建玉として許可する。

                pass

            position = {

                "version": VERSION,

                "ticker": ticker,

                "side": side,

                "entry_date":

                    datetime.now(

                        TZ

                    ).date().isoformat(),

                "entry_time":

                    c["time"],

                "entry_price": price,

                "shares": shares,

                "tp": c["tp"],

                "sl": c["sl"],

                "rs": c["rs"],

                "morning_high":

                    c["morning_high"],

                "morning_low":

                    c["morning_low"]

            }

            portfolio["positions"].append(

                position

            )

            current_long += value

        # SHORT

        else:

            position = {

                "version": VERSION,

                "ticker": ticker,

                "side": side,

                "entry_date":

                    datetime.now(

                        TZ

                    ).date().isoformat(),

                "entry_time":

                    c["time"],

                "entry_price": price,

                "shares": shares,

                "tp": c["tp"],

                "sl": c["sl"],

                "rs": c["rs"],

                "morning_high":

                    c["morning_high"],

                "morning_low":

                    c["morning_low"]

            }

            portfolio["positions"].append(

                position

            )

            current_short += value

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

    for p in portfolio["positions"]:

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

        for _, row in day.iterrows():

            high = float(

                row["high"]

            )

            low = float(

                row["low"]

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

            # 同一5分足で両方

            # → 保守的にSL

            if hit_tp and hit_sl:

                exit_price = sl

                reason = "SL"

                break

            if hit_sl:

                exit_price = sl

                reason = "SL"

                break

            if hit_tp:

                exit_price = tp

                reason = "TP"

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

        else:

            pnl = (

                p["entry_price"]

                -

                exit_price

            ) * p["shares"]

        portfolio["realized_pnl"] += pnl

        closed.append({

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

            "entry_time":

                p["entry_time"],

            "exit_date":

                today.isoformat()

        })

    portfolio["positions"] = holding

    return closed

# ============================================================

# CSV

# ============================================================

def save_trades(

    trades

):

    if not trades:

        return

    os.makedirs(

        "data",

        exist_ok=True

    )

    rows = []

    now = datetime.now(

        TZ

    ).isoformat()

    for t in trades:

        rows.append({

            "datetime": now,

            "ticker":

                t["ticker"],

            "side":

                t["side"],

            "entry":

                t["entry"],

            "exit":

                t["exit"],

            "shares":

                t["shares"],

            "pnl":

                t["pnl"],

            "reason":

                t["reason"],

            "entry_date":

                t["entry_date"],

            "entry_time":

                t["entry_time"],

            "exit_date":

                t["exit_date"]

        })

    new = pd.DataFrame(

        rows

    )

    if os.path.exists(

        TRADES_FILE

    ):

        old = pd.read_csv(

            TRADES_FILE

        )

        new = pd.concat(

            [old, new],

            ignore_index=True

        )

    new.to_csv(

        TRADES_FILE,

        index=False,

        encoding="utf-8-sig"

    )

# ============================================================

# Email

# ============================================================

def send_email(

    subject,

    body

):

    host = os.environ.get(

        "SMTP_HOST"

    )

    port = int(

        os.environ.get(

            "SMTP_PORT",

            "587"

        )

    )

    user = os.environ.get(

        "SMTP_USER"

    )

    password = os.environ.get(

        "SMTP_PASSWORD"

    )

    recipient = os.environ.get(

        "MAIL_TO"

    )

    if not all([

        host,

        user,

        password,

        recipient

    ]):

        raise RuntimeError(

            "メール用GitHub Secretsが未設定です"

        )

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

        "===== v29.4 12:45 ====="

    )

    portfolio = load_portfolio()

    candidates = find_candidates()

    print(

        f"候補数: {len(candidates)}"

    )

    executed = enter_positions(

        portfolio,

        candidates

    )

    save_portfolio(

        portfolio

    )

    equity = calculate_equity(

        portfolio

    )

    lines = []

    lines.append(

        "【仮想取引 v29.4】12:45"

    )

    lines.append("")

    lines.append(

        f"現在Equity: ¥{equity:,.0f}"

    )

    lines.append(

        f"LONG上限: ¥{equity * LONG_LEVERAGE:,.0f}"

    )

    lines.append(

        f"SHORT上限: ¥{equity * SHORT_LEVERAGE:,.0f}"

    )

    lines.append("")

    if executed:

        lines.append(

            "【新規エントリー】"

        )

        for p in executed:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f} "

                f"TP ¥{p['tp']:,.1f} "

                f"SL ¥{p['sl']:,.1f} "

                f"RS {p['rs']:.1f}"

            )

    else:

        lines.append(

            "【新規エントリーなし】"

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

                    f"RS {c['rs']:.1f} "

                    f"Entry ¥{c['entry']:,.1f}"

                )

        else:

            lines.append(

                "RS条件 + Morning "

                "High/Low Breakoutなし"

            )

    lines.append("")

    lines.append(

        "【現在の持越し】"

    )

    if portfolio["positions"]:

        for p in portfolio["positions"]:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f}"

            )

    else:

        lines.append("なし")

    send_email(

        "【仮想取引 v29.4】12:45 売買指示",

        "\n".join(lines)

    )

# ============================================================

# 15:45

# ============================================================

def run_1545():

    print(

        "===== v29.4 15:45 ====="

    )

    portfolio = load_portfolio()

    closed = check_positions(

        portfolio

    )

    save_trades(

        closed

    )

    save_portfolio(

        portfolio

    )

    equity = calculate_equity(

        portfolio

    )

    lines = []

    lines.append(

        "【仮想取引 v29.4】15:45"

    )

    lines.append("")

    lines.append(

        f"現在Equity: ¥{equity:,.0f}"

    )

    lines.append(

        f"累計確定損益: "

        f"¥{portfolio['realized_pnl']:,.0f}"

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

                f"{sign}¥{t['pnl']:,.0f}"

            )

    else:

        lines.append(

            "決済なし"

        )

    lines.append("")

    lines.append(

        "【持越し】"

    )

    if portfolio["positions"]:

        for p in portfolio["positions"]:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f}"

            )

    else:

        lines.append("なし")

    send_email(

        "【仮想取引 v29.4】15:45 結果・持越し",

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

        f"現在時刻: "

        f"{now:%Y-%m-%d %H:%M:%S}"

    )

    force_1245 = (

        os.environ.get(

            "FORCE_1245"

        ) == "1"

    )

    force_1545 = (

        os.environ.get(

            "FORCE_1545"

        ) == "1"

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
