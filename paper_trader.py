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

# 設定

# ============================================================

INITIAL_CAPITAL = 1_000_000

RS_THRESHOLD = 70.0

RS_LOOKBACK = 20

TP = 0.020

SL = 0.015

MORNING_START = "09:00"

MORNING_END = "12:40"

ENTRY_TIME = "12:45"

MAX_POSITIONS = 3

MARKET_TICKER = "1306.T"

TZ = ZoneInfo("Asia/Tokyo")

PORTFOLIO_FILE = "data/portfolio.json"

TRADES_FILE = "data/trades.csv"

# ============================================================

# 銘柄ユニバース

# ============================================================

UNIVERSE = [

    "1301.T","1332.T","1333.T","1605.T",

    "1721.T","1801.T","1802.T","1803.T","1808.T","1812.T",

    "1925.T","1928.T","1963.T",

    "2002.T",

    "2267.T","2269.T","2282.T",

    "2413.T",

    "2501.T","2502.T","2503.T",

    "2768.T",

    "2801.T","2802.T","2871.T",

    "2914.T",

    "3086.T","3092.T","3099.T",

    "3101.T","3103.T",

    "3289.T",

    "3382.T",

    "3401.T","3402.T","3405.T","3407.T",

    "3861.T","3863.T",

    "4004.T","4005.T","4021.T","4042.T","4043.T","4061.T","4062.T",

    "4183.T","4188.T","4202.T","4203.T",

    "4307.T","4324.T",

    "4452.T",

    "4502.T","4503.T","4506.T","4507.T",

    "4519.T","4523.T",

    "4543.T",

    "4568.T",

    "4661.T","4689.T",

    "4704.T","4751.T",

    "4901.T","4902.T",

    "4911.T",

    "5019.T",

    "5020.T","5021.T",

    "5101.T","5108.T",

    "5201.T","5214.T",

    "5401.T","5406.T","5411.T",

    "5711.T","5713.T","5714.T",

    "5801.T","5802.T","5803.T",

    "5831.T","5832.T",

    "6098.T",

    "6103.T","6113.T",

    "6301.T","6302.T","6305.T",

    "6326.T",

    "6361.T","6367.T",

    "6471.T","6472.T","6473.T",

    "6501.T","6503.T","6504.T","6506.T",

    "6526.T",

    "6594.T",

    "6645.T",

    "6701.T","6702.T","6723.T","6724.T",

    "6752.T","6753.T","6758.T",

    "6762.T","6770.T",

    "6841.T",

    "6857.T",

    "6861.T",

    "6902.T","6920.T",

    "6954.T","6963.T",

    "6971.T","6976.T",

    "6981.T",

    "7003.T","7004.T",

    "7011.T","7012.T","7013.T",

    "7201.T","7202.T","7203.T","7205.T",

    "7267.T","7269.T","7270.T",

    "7731.T","7733.T","7735.T",

    "7741.T",

    "7751.T",

    "7832.T",

    "7911.T","7912.T",

    "8001.T","8002.T",

    "8015.T",

    "8031.T","8035.T",

    "8053.T","8058.T",

    "8113.T",

    "8233.T","8252.T","8267.T",

    "8306.T","8308.T","8309.T",

    "8316.T",

    "8411.T",

    "8591.T",

    "8601.T","8604.T",

    "8630.T",

    "8697.T",

    "8725.T","8750.T","8766.T",

    "8801.T","8802.T",

    "8830.T",

    "9001.T","9005.T","9007.T",

    "9020.T","9021.T","9022.T",

    "9064.T",

    "9101.T","9104.T","9107.T",

    "9201.T","9202.T",

    "9432.T","9433.T","9434.T",

    "9501.T","9502.T","9503.T",

    "9531.T","9532.T",

    "9613.T",

    "9983.T","9984.T",

]

# ============================================================

# Portfolio

# ============================================================

def load_portfolio():

    os.makedirs("data", exist_ok=True)

    if not os.path.exists(PORTFOLIO_FILE):

        portfolio = {

            "cash": INITIAL_CAPITAL,

            "positions": [],

            "realized_pnl": 0.0

        }

        save_portfolio(portfolio)

        return portfolio

    with open(

        PORTFOLIO_FILE,

        "r",

        encoding="utf-8"

    ) as f:

        return json.load(f)

def save_portfolio(portfolio):

    os.makedirs("data", exist_ok=True)

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

# Yahoo 日足

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

        if df is None or df.empty:

            return None

        if isinstance(

            df.columns,

            pd.MultiIndex

        ):

            df.columns = [

                c[0]

                for c in df.columns

            ]

        df.columns = [

            str(c).lower()

            for c in df.columns

        ]

        return df

    except Exception as e:

        print(

            f"{ticker} 日足取得失敗: {e}"

        )

        return None

# ============================================================

# Yahoo 5分足

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

        if df is None or df.empty:

            return None

        if isinstance(

            df.columns,

            pd.MultiIndex

        ):

            df.columns = [

                c[0]

                for c in df.columns

            ]

        df.columns = [

            str(c).lower()

            for c in df.columns

        ]

        idx = pd.to_datetime(

            df.index

        )

        if idx.tz is not None:

            idx = (

                idx

                .tz_convert("Asia/Tokyo")

                .tz_localize(None)

            )

        df.index = idx

        return df

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

# Morning High

# ============================================================

def get_morning_high(df, date):

    day = df[

        df.index.date == date

    ]

    if day.empty:

        return None

    morning = day.between_time(

        MORNING_START,

        MORNING_END

    )

    if morning.empty:

        return None

    return float(

        morning["high"].max()

    )

# ============================================================

# 12:45候補抽出

# ============================================================

def find_candidates():

    print("RS計算中...")

    rs = calculate_rs()

    if not rs:

        return []

    today = datetime.now(TZ).date()

    candidates = []

    for ticker, rs_value in rs.items():

        if rs_value < RS_THRESHOLD:

            continue

        df = download_5m(ticker)

        if df is None:

            continue

        morning_high = get_morning_high(

            df,

            today

        )

        if morning_high is None:

            continue

        day = df[

            df.index.date == today

        ]

        afternoon = day[

            day.index.strftime("%H:%M")

            >= ENTRY_TIME

        ]

        if afternoon.empty:

            continue

        price = float(

            afternoon.iloc[-1]["close"]

        )

        # Morning High突破

        if price < morning_high:

            continue

        candidates.append({

            "ticker": ticker,

            "rs": float(rs_value),

            "morning_high": morning_high,

            "entry": price,

            "tp": price * (1 + TP),

            "sl": price * (1 - SL)

        })

    candidates.sort(

        key=lambda x: x["rs"],

        reverse=True

    )

    return candidates

# ============================================================

# 仮想エントリー

# ============================================================

def enter_positions(

    portfolio,

    candidates

):

    existing = {

        p["ticker"]

        for p in portfolio["positions"]

    }

    candidates = [

        c for c in candidates

        if c["ticker"] not in existing

    ]

    slots = (

        MAX_POSITIONS

        - len(existing)

    )

    candidates = candidates[:slots]

    executed = []

    capital_per_position = (

        INITIAL_CAPITAL

        / MAX_POSITIONS

    )

    for c in candidates:

        price = c["entry"]

        shares = int(

            capital_per_position

            / price

            / 100

        ) * 100

        if shares <= 0:

            continue

        cost = (

            price * shares

        )

        if cost > portfolio["cash"]:

            continue

        position = {

            "ticker": c["ticker"],

            "entry_date": datetime.now(

                TZ

            ).date().isoformat(),

            "entry_price": price,

            "shares": shares,

            "tp": c["tp"],

            "sl": c["sl"],

            "rs": c["rs"],

            "morning_high": c[

                "morning_high"

            ]

        }

        portfolio["positions"].append(

            position

        )

        portfolio["cash"] -= cost

        executed.append(position)

    return executed

# ============================================================

# TP / SL判定

# ============================================================

def check_positions(portfolio):

    today = datetime.now(TZ).date()

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

        tp = float(p["tp"])

        sl = float(p["sl"])

        exit_price = None

        reason = None

        for _, row in day.iterrows():

            high = float(row["high"])

            low = float(row["low"])

            # 同一5分足でTP/SL両方に到達した場合

            # 保守的にSLを優先

            if low <= sl:

                exit_price = sl

                reason = "SL"

                break

            if high >= tp:

                exit_price = tp

                reason = "TP"

                break

        if exit_price is None:

            holding.append(p)

            continue

        pnl = (

            exit_price

            - p["entry_price"]

        ) * p["shares"]

        portfolio["cash"] += (

            exit_price

            * p["shares"]

        )

        portfolio["realized_pnl"] += pnl

        closed.append({

            "ticker": p["ticker"],

            "entry": p["entry_price"],

            "exit": exit_price,

            "shares": p["shares"],

            "pnl": pnl,

            "reason": reason

        })

    portfolio["positions"] = holding

    return closed

# ============================================================

# CSV記録

# ============================================================

def save_trades(trades):

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

            "ticker": t["ticker"],

            "entry": t["entry"],

            "exit": t["exit"],

            "shares": t["shares"],

            "pnl": t["pnl"],

            "reason": t["reason"]

        })

    new = pd.DataFrame(rows)

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

# メール

# ============================================================

def send_email(subject, body):

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

    portfolio = load_portfolio()

    candidates = find_candidates()

    executed = enter_positions(

        portfolio,

        candidates

    )

    save_portfolio(

        portfolio

    )

    lines = []

    lines.append(

        "【仮想取引】12:45 売買指示"

    )

    lines.append("")

    if executed:

        lines.append(

            "【仮想エントリー】"

        )

        for p in executed:

            lines.append(

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

            lines.append("候補:") l

            for c in candidates[:10]:

                lines.append(

                    f"{c['ticker']} "

                    f"RS {c['rs']:.1f} "

                    f"Entry ¥{c['entry']:,.1f}"

                )

        else:

            lines.append(

                "RS70 + Morning High Breakout"

            )

            lines.append(

                "条件を満たす銘柄なし"

            )

    lines.append("")

    lines.append("【持越し】")

    if portfolio["positions"]:

        for p in portfolio["positions"]:

            lines.append(

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f}"

            )

    else:

        lines.append("なし")

    send_email(

        "【仮想取引】12:45 売買指示",

        "\n".join(lines)

    )

# ============================================================

# 15:45

# ============================================================

def run_1545():

    portfolio = load_portfolio()

    closed = check_positions(

        portfolio

    )

    save_trades(closed)

    save_portfolio(

        portfolio

    )

    lines = []

    lines.append(

        "【仮想取引】15:45 結果報告"

    )

    lines.append("")

    lines.append(

        f"仮想現金: ¥{portfolio['cash']:,.0f}"

    )

    lines.append(

        f"累計確定損益: "

        f"¥{portfolio['realized_pnl']:,.0f}"

    )

    lines.append("")

    lines.append("【本日の決済】")

    if closed:

        for t in closed:

            sign = "+" if t["pnl"] >= 0 else ""

            lines.append(

                f"{t['ticker']} "

                f"{t['reason']} "

                f"{sign}¥{t['pnl']:,.0f}"

            )

    else:

        lines.append(

            "決済なし"

        )

    lines.append("")

    lines.append("【持越し】")

    if portfolio["positions"]:

        for p in portfolio["positions"]:

            lines.append(

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f}"

            )

    else:

        lines.append("なし")

    send_email(

        "【仮想取引】15:45 結果・持越し報告",

        "\n".join(lines)

    )

# ============================================================

# MAIN

# ============================================================

def main():

    now = datetime.now(TZ)

    print(

        f"現在時刻: {now:%Y-%m-%d %H:%M:%S}"

    )

    if (

        now.hour == 12

        and 40 <= now.minute <= 55

    ):

        run_1245()

    elif (

        now.hour == 15

        and 40 <= now.minute <= 55

    ):

        run_1545()

    else:

        print(

            "実行時間外"

        )

if __name__ == "__main__":

    main()
