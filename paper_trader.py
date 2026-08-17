# -*- coding: utf-8 -*-

import os

import json

import smtplib

from email.mime.text import MIMEText

from email.header import Header

from datetime import datetime

from zoneinfo import ZoneInfo

import pandas as pd

import yfinance as yf

# ============================================================

# v29.5 Paper Trader

#

# LONG  1倍

# SHORT 1倍

#

# 12:45

#   1. 持越しポジションの午前中TP/SL確認

#   2. 決済済みポジションの枠を開放

#   3. 空いたLONG/SHORT枠だけ新規選定

#

# 15:45

#   1. 当日のTP/SL確認

#   2. 未決済なら持越し

#

# ============================================================

TZ = ZoneInfo("Asia/Tokyo")

# ============================================================

# 基本設定

# ============================================================

INITIAL_CAPITAL = 1_117_792

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

MAX_LONG_POSITIONS = 1

MAX_SHORT_POSITIONS = 1

MARKET_TICKER = "1306.T"

INTEREST_RATE = 0.028

BORROW_RATE = 0.028

PORTFOLIO_FILE = "data/v29_4_portfolio.json"

TRADES_FILE = "data/v29_4_trades.csv"

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

    "4188.T","4202.T","4203.T",

    "4307.T","4324.T","4452.T",

    "4502.T","4503.T","4506.T","4507.T",

    "4519.T","4523.T","4543.T","4568.T","4578.T",

    "4661.T","4689.T","4704.T","4751.T",

    "4901.T","4902.T","4911.T",

    "5019.T","5020.T","5021.T",

    "5101.T","5108.T","5201.T","5202.T",

    "5232.T","5233.T","5301.T","5332.T","5333.T",

    "5401.T","5406.T","5411.T",

    "5631.T","5706.T","5707.T","5711.T","5713.T","5714.T",

    "5801.T","5802.T","5803.T",

    "5831.T","5832.T","6098.T",

    "6103.T","6113.T",

    "6301.T","6302.T","6305.T","6326.T",

    "6361.T","6367.T",

    "6471.T","6472.T","6473.T","6479.T",

    "6501.T","6503.T","6504.T","6506.T","6526.T",

    "6532.T","6594.T","6645.T","6674.T",

    "6701.T","6702.T","6723.T","6724.T",

    "6752.T","6753.T","6758.T","6762.T","6770.T",

    "6841.T","6857.T","6861.T","6869.T",

    "6902.T","6920.T","6952.T","6954.T",

    "6971.T","6976.T","6981.T",

    "7003.T","7004.T","7011.T","7012.T","7013.T",

    "7182.T",

    "7201.T","7202.T","7203.T","7205.T","7206.T",

    "7208.T","7211.T",

    "7261.T","7267.T","7269.T","7270.T","7272.T","7276.T",

    "7309.T",

    "7731.T","7733.T","7735.T","7741.T",

    "7751.T","7752.T",

    "7832.T","7911.T","7912.T","7951.T","7974.T",

    "8001.T","8002.T","8015.T","8031.T","8035.T",

    "8053.T","8058.T",

    "8233.T","8252.T","8253.T","8267.T",

    "8303.T","8304.T","8306.T","8308.T","8309.T",

    "8316.T","8331.T","8354.T","8411.T",

    "8591.T","8601.T","8604.T","8630.T","8697.T",

    "8725.T","8750.T","8766.T","8795.T",

    "8801.T","8802.T","8804.T","8830.T",

    "9001.T","9005.T","9007.T","9008.T","9009.T",

    "9020.T","9021.T","9022.T","9064.T",

    "9101.T","9104.T","9107.T",

    "9201.T","9202.T","9301.T",

    "9412.T","9432.T","9433.T","9434.T",

    "9501.T","9502.T","9503.T",

    "9531.T","9532.T","9602.T","9613.T",

    "9684.T","9735.T","9766.T",

    "9983.T","9984.T"

]

# ============================================================

# Yahooデータ整形

# ============================================================

def clean_yahoo(df):

    if df is None or df.empty:

        return None

    if isinstance(df.columns, pd.MultiIndex):

        df.columns = df.columns.get_level_values(0)

    df.columns = [str(c).lower() for c in df.columns]

    required = ["open", "high", "low", "close"]

    if not all(c in df.columns for c in required):

        return None

    for c in required:

        df[c] = pd.to_numeric(

            df[c],

            errors="coerce"

        )

    df = df.dropna(subset=required)

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

        print(f"{ticker} 日足取得失敗: {e}")

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

        print(f"{ticker} 5分足取得失敗: {e}")

        return None

# ============================================================

# Portfolio

# ============================================================

def default_portfolio():

    return {

        "cash": float(INITIAL_CAPITAL),

        "positions": [],

        "realized_pnl": 0.0

    }

def load_portfolio():

    os.makedirs("data", exist_ok=True)

    if not os.path.exists(PORTFOLIO_FILE):

        portfolio = default_portfolio()

        save_portfolio(portfolio)

        return portfolio

    try:

        with open(

            PORTFOLIO_FILE,

            "r",

            encoding="utf-8"

        ) as f:

            return json.load(f)

    except Exception:

        print("Portfolio読み込み失敗。初期資産から開始します。")

        portfolio = default_portfolio()

        save_portfolio(portfolio)

        return portfolio

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

# Equity

# ============================================================

def calculate_equity(portfolio):

    equity = float(portfolio["cash"])

    for p in portfolio["positions"]:

        df = download_5m(p["ticker"])

        if df is None or df.empty:

            continue

        close = float(df.iloc[-1]["close"])

        shares = int(p["shares"])

        if p["side"] == "LONG":

            equity += close * shares

        else:

            equity -= close * shares

    return float(equity)

# ============================================================

# 建玉

# ============================================================

def get_exposure(portfolio):

    long_exposure = 0.0

    short_exposure = 0.0

    for p in portfolio["positions"]:

        value = (

            float(p["entry_price"])

            *

            int(p["shares"])

        )

        if p["side"] == "LONG":

            long_exposure += value

        else:

            short_exposure += value

    return long_exposure, short_exposure

def count_positions(portfolio, side):

    return sum(

        p["side"] == side

        for p in portfolio["positions"]

    )

# ============================================================

# RS

# ============================================================

def calculate_rs():

    market = download_daily(MARKET_TICKER)

    if market is None:

        return {}

    market_close = pd.to_numeric(

        market["close"],

        errors="coerce"

    ).dropna()

    market_close.index = (

        pd.to_datetime(

            market_close.index

        ).normalize()

    )

    market_return = (

        market_close.shift(1)

        /

        market_close.shift(RS_LOOKBACK + 1)

        - 1

    )

    returns = {}

    for ticker in UNIVERSE:

        df = download_daily(ticker)

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

        returns[ticker] = (

            close.shift(1)

            /

            close.shift(RS_LOOKBACK + 1)

            - 1

        )

    if not returns:

        return {}

    stocks = pd.DataFrame(returns)

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

            pct=True,

            method="average"

        )

        * 100

    )

    today = datetime.now(TZ).date()

    valid = rs[

        rs.index.date < today

    ]

    if valid.empty:

        return {}

    return (

        valid

        .iloc[-1]

        .dropna()

        .to_dict()

    )

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

# 午前中のTP/SL判定

#

# end_time:

#   12:40 → 12:45時点の確認

#   15:30 → 15:45時点の確認

# ============================================================

def check_positions_until(

    portfolio,

    end_time

):

    today = datetime.now(TZ).date()

    closed = []

    holding = []

    for p in portfolio["positions"]:

        df = download_5m(p["ticker"])

        if df is None or df.empty:

            holding.append(p)

            continue

        day = df[

            df.index.date == today

        ]

        if day.empty:

            holding.append(p)

            continue

        day = day[

            day.index.strftime("%H:%M") <= end_time

        ]

        if day.empty:

            holding.append(p)

            continue

        tp = float(p["tp"])

        sl = float(p["sl"])

        exit_price = None

        reason = None

        exit_time = None

        for timestamp, row in day.iterrows():

            high = float(row["high"])

            low = float(row["low"])

            if p["side"] == "LONG":

                hit_tp = high >= tp

                hit_sl = low <= sl

            else:

                hit_tp = low <= tp

                hit_sl = high >= sl

            # 同一5分足で両方到達

            # 保守的にSL

            if hit_tp and hit_sl:

                exit_price = sl

                reason = "SL"

                exit_time = timestamp

                break

            if hit_sl:

                exit_price = sl

                reason = "SL"

                exit_time = timestamp

                break

            if hit_tp:

                exit_price = tp

                reason = "TP"

                exit_time = timestamp

                break

        if exit_price is None:

            holding.append(p)

            continue

        entry_price = float(

            p["entry_price"]

        )

        shares = int(

            p["shares"]

        )

        entry_date = datetime.fromisoformat(

            p["entry_date"]

        ).date()

        holding_days = max(

            1,

            (today - entry_date).days

        )

        if p["side"] == "LONG":

            gross_pnl = (

                exit_price - entry_price

            ) * shares

            interest = (

                entry_price

                * shares

                * INTEREST_RATE

                * holding_days

                / 365

            )

            pnl = gross_pnl - interest

            portfolio["cash"] += (

                exit_price * shares

            )

        else:

            gross_pnl = (

                entry_price - exit_price

            ) * shares

            borrow = (

                entry_price

                * shares

                * BORROW_RATE

                * holding_days

                / 365

            )

            pnl = gross_pnl - borrow

            portfolio["cash"] -= (

                exit_price * shares

            )

        portfolio["realized_pnl"] += pnl

        closed.append({

            "ticker": p["ticker"],

            "side": p["side"],

            "entry": entry_price,

            "exit": exit_price,

            "shares": shares,

            "pnl": pnl,

            "reason": reason,

            "holding_days": holding_days,

            "exit_time": str(exit_time)

        })

    portfolio["positions"] = holding

    return closed

# ============================================================

# 新規候補

# ============================================================

def find_candidates():

    print("RS計算中...")

    rs = calculate_rs()

    if not rs:

        return []

    today = datetime.now(TZ).date()

    candidates = []

    for ticker, rs_value in rs.items():

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

        available = day[

            day.index.strftime("%H:%M")

            <= ENTRY_TIME

        ]

        if available.empty:

            continue

        latest = available.iloc[-1]

        price = float(

            latest["close"]

        )

        # LONG

        if side == "LONG":

            if price < morning_high:

                continue

            candidates.append({

                "ticker": ticker,

                "side": "LONG",

                "rs": float(rs_value),

                "morning_high": morning_high,

                "morning_low": morning_low,

                "entry": price,

                "tp": price * (1 + TP),

                "sl": price * (1 - SL)

            })

        # SHORT

        else:

            if price > morning_low:

                continue

            candidates.append({

                "ticker": ticker,

                "side": "SHORT",

                "rs": float(rs_value),

                "morning_high": morning_high,

                "morning_low": morning_low,

                "entry": price,

                "tp": price * (1 - TP),

                "sl": price * (1 + SL)

            })

    candidates.sort(

        key=lambda x: (

            0 if x["side"] == "LONG" else 1,

            -x["rs"]

            if x["side"] == "LONG"

            else x["rs"]

        )

    )

    print(

        f"候補数: {len(candidates)}"

    )

    return candidates

# ============================================================

# 新規Entry

#

# 空いている方向だけEntry

#

# LONG最大1倍

# SHORT最大1倍

# ============================================================

def enter_positions(

    portfolio,

    candidates,

    closed_today

):

    if not candidates:

        return []

    equity = calculate_equity(

        portfolio

    )

    if equity <= 0:

        return []

    long_limit = (

        equity * LONG_LEVERAGE

    )

    short_limit = (

        equity * SHORT_LEVERAGE

    )

    long_exposure, short_exposure = (

        get_exposure(portfolio)

    )

    existing_tickers = {

        p["ticker"]

        for p in portfolio["positions"]

    }

    # 決済済み銘柄は同日再Entryしない

    for c in closed_today:

        existing_tickers.add(

            c["ticker"]

        )

    long_count = count_positions(

        portfolio,

        "LONG"

    )

    short_count = count_positions(

        portfolio,

        "SHORT"

    )

    executed = []

    for c in candidates:

        ticker = c["ticker"]

        if ticker in existing_tickers:

            continue

        price = float(

            c["entry"]

        )

        if price <= 0:

            continue

        # ==========================

        # LONG

        # ==========================

        if c["side"] == "LONG":

            if long_count >= MAX_LONG_POSITIONS:

                continue

            available = (

                long_limit

                - long_exposure

            )

            if available <= 0:

                continue

            shares = (

                int(

                    available / price / 100

                ) * 100

            )

            if shares <= 0:

                continue

            value = price * shares

            portfolio["cash"] -= value

            long_exposure += value

            long_count += 1

        # ==========================

        # SHORT

        # ==========================

        else:

            if short_count >= MAX_SHORT_POSITIONS:

                continue

            available = (

                short_limit

                - short_exposure

            )

            if available <= 0:

                continue

            shares = (

                int(

                    available / price / 100

                ) * 100

            )

            if shares <= 0:

                continue

            value = price * shares

            portfolio["cash"] += value

            short_exposure += value

            short_count += 1

        position = {

            "ticker": ticker,

            "side": c["side"],

            "entry_date": datetime.now(

                TZ

            ).date().isoformat(),

            "entry_price": price,

            "shares": int(shares),

            "tp": float(c["tp"]),

            "sl": float(c["sl"]),

            "rs": float(c["rs"]),

            "morning_high": float(

                c["morning_high"]

            ),

            "morning_low": float(

                c["morning_low"]

            )

        }

        portfolio["positions"].append(

            position

        )

        existing_tickers.add(

            ticker

        )

        executed.append(position)

    return executed

# ============================================================

# CSV

# ============================================================

def save_trades(trades):

    if not trades:

        return

    os.makedirs(

        "data",

        exist_ok=True

    )

    now = datetime.now(TZ).isoformat()

    rows = []

    for t in trades:

        rows.append({

            "datetime": now,

            "ticker": t["ticker"],

            "side": t["side"],

            "entry": t["entry"],

            "exit": t["exit"],

            "shares": t["shares"],

            "pnl": t["pnl"],

            "reason": t["reason"],

            "holding_days": t["holding_days"],

            "exit_time": t["exit_time"]

        })

    new = pd.DataFrame(rows)

    if os.path.exists(TRADES_FILE):

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

        server.send_message(msg)

# ============================================================

# 12:45処理

# ============================================================

def run_1245():

    portfolio = load_portfolio()

    # --------------------------------------------------------

    # STEP 1

    # 持越しポジションの午前中TP/SL確認

    # --------------------------------------------------------

    before_count = len(

        portfolio["positions"]

    )

    closed_morning = check_positions_until(

        portfolio,

        "12:40"

    )

    after_count = len(

        portfolio["positions"]

    )

    print(

        f"午前中決済: {len(closed_morning)}件"

    )

    # --------------------------------------------------------

    # STEP 2

    # 新規候補を取得

    # --------------------------------------------------------

    candidates = find_candidates()

    # --------------------------------------------------------

    # STEP 3

    # 空いたLONG/SHORT枠へ新規Entry

    # --------------------------------------------------------

    executed = enter_positions(

        portfolio,

        candidates,

        closed_morning

    )

    save_trades(

        closed_morning

    )

    save_portfolio(

        portfolio

    )

    # --------------------------------------------------------

    # STEP 4

    # 現在状況

    # --------------------------------------------------------

    equity = calculate_equity(

        portfolio

    )

    long_exposure, short_exposure = (

        get_exposure(portfolio)

    )

    lines = []

    lines.append(

        "【v29.5 仮想取引】12:45"

    )

    lines.append("")

    lines.append(

        f"初期資産 : ¥{INITIAL_CAPITAL:,.0f}"

    )

    lines.append(

        f"現在Equity : ¥{equity:,.0f}"

    )

    lines.append(

        f"LONG上限 : ¥{equity * LONG_LEVERAGE:,.0f}"

    )

    lines.append(

        f"SHORT上限 : ¥{equity * SHORT_LEVERAGE:,.0f}"

    )

    lines.append(

        f"LONG建玉 : ¥{long_exposure:,.0f}"

    )

    lines.append(

        f"SHORT建玉 : ¥{short_exposure:,.0f}"

    )

    lines.append(

        f"合計建玉 : ¥{long_exposure + short_exposure:,.0f}"

    )

    lines.append("")

    # --------------------------------------------------------

    # 午前中決済

    # --------------------------------------------------------

    lines.append(

        "【午前中の決済】"

    )

    if closed_morning:

        for t in closed_morning:

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

            "なし"

        )

    lines.append("")

    # --------------------------------------------------------

    # 新規Entry

    # --------------------------------------------------------

    lines.append(

        "【新規エントリー】"

    )

    if executed:

        for p in executed:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"成行 "

                f"Entry ¥{p['entry_price']:,.1f} "

                f"TP ¥{p['tp']:,.1f} "

                f"SL ¥{p['sl']:,.1f} "

                f"RS {p['rs']:.1f}"

            )

    else:

        lines.append(

            "なし"

        )

    lines.append("")

    # --------------------------------------------------------

    # 保有中

    # --------------------------------------------------------

    lines.append(

        "【持越し・保有中】"

    )

    if portfolio["positions"]:

        for p in portfolio["positions"]:

            lines.append(

                f"{p['side']} "

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f} "

                f"TP ¥{p['tp']:,.1f} "

                f"SL ¥{p['sl']:,.1f}"

            )

    else:

        lines.append(

            "なし"

        )

    lines.append("")

    lines.append(

        f"累計確定損益 : "

        f"¥{portfolio['realized_pnl']:+,.0f}"

    )

    send_email(

        "【v29.5】12:45 仮想取引指示",

        "\n".join(lines)

    )

# ============================================================

# 15:45処理

# ============================================================

def run_1545():

    portfolio = load_portfolio()

    # 当日の15:30までの5分足で

    # TP/SLを確認

    closed = check_positions_until(

        portfolio,

        "15:30"

    )

    save_trades(closed)

    save_portfolio(portfolio)

    equity = calculate_equity(

        portfolio

    )

    long_exposure, short_exposure = (

        get_exposure(portfolio)

    )

    lines = []

    lines.append(

        "【v29.5 仮想取引】15:45"

    )

    lines.append("")

    lines.append(

        f"現在Equity : ¥{equity:,.0f}"

    )

    lines.append(

        f"累計確定損益 : "

        f"¥{portfolio['realized_pnl']:+,.0f}"

    )

    lines.append(

        f"LONG建玉 : ¥{long_exposure:,.0f}"

    )

    lines.append(

        f"SHORT建玉 : ¥{short_exposure:,.0f}"

    )

    lines.append("")

    # --------------------------------------------------------

    # 決済

    # --------------------------------------------------------

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

                f"{sign}¥{t['pnl']:,.0f} "

                f"({t['exit_time']})"

            )

    else:

        lines.append(

            "なし"

        )

    lines.append("")

    # --------------------------------------------------------

    # 持越し

    # --------------------------------------------------------

    lines.append(

        "【翌日へ持越し】"

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

        lines.append(

            "なし"

        )

    send_email(

        "【v29.5】15:45 結果・持越し",

        "\n".join(lines)

    )

# ============================================================

# MAIN

# ============================================================

def main():

    now = datetime.now(TZ)

    print("=" * 70)

    print(

        "v29.5 LONG + SHORT 各1倍"

    )

    print(

        "Paper Trader"

    )

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

        f"LONG枠 : Equity × "

        f"{LONG_LEVERAGE:.1f}"

    )

    print(

        f"SHORT枠 : Equity × "

        f"{SHORT_LEVERAGE:.1f}"

    )

    print()

    # ========================================================

    # 12:45

    # ========================================================

    if (

        now.hour == 12

        and 40 <= now.minute <= 55

    ):

        print(

            "12:45処理開始"

        )

        run_1245()

        return

    # ========================================================

    # 15:45

    # ========================================================

    if (

        now.hour == 15

        and 40 <= now.minute <= 55

    ):

        print(

            "15:45処理開始"

        )

        run_1545()

        return

    # ========================================================

    # 手動テスト

    # ========================================================

    if os.environ.get(

        "FORCE_1245"

    ) == "1":

        print(

            "FORCE_1245=1"

        )

        run_1245()

        return

    if os.environ.get(

        "FORCE_1545"

    ) == "1":

        print(

            "FORCE_1545=1"

        )

        run_1545()

        return

    print(

        "実行時間外"

    )

if __name__ == "__main__":

    main()
