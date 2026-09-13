# ============================================================

# FIX11 FORWARD PAPER TRADER

#

# 実注文なし

# GitHub / Cloud Run 用

#

# Strategy:

#   FIX11 broker-realistic paper trading

#

# Signal:

#   ORB15 = 09:00-09:14

#   signal = 09:15以降

#

# LONG:

#   RS20 >= 80

#   turnover20 >= 3億円

#   RVOL20 >= 2.0

#   PrevClose <= ORB15 High

#   CurrentClose > ORB15 High

#

# SHORT:

#   RS20 <= 20

#   turnover20 >= 3億円

#   RVOL20 >= 2.0

#   PrevClose >= ORB15 Low

#   CurrentClose < ORB15 Low

#

# Entry:

#   signal後の次の実在1分足 Open

#

# Position:

#   LONG 最大1

#   SHORT 最大1

#

# FIX11:

#   LONG leverage 1.00

#   SHORT leverage 0.50

#   100株単位

#   entry margin >= 30%

#

# Exit:

#   LONG

#     fixed SL -2.5%

#     trail trigger +2.5%

#     trail width 1.0%

#     max 10 TSE trading days

#

#   SHORT

#     fixed SL -1.5%

#     trail trigger +2.0%

#     trail width 2.0%

#     carry

#

# IMPORTANT:

#   ・実注文は一切出さない

#   ・No-Future

#   ・raw Yahoo 1mを保存

#   ・履歴不足は推測せず NOT_READY

# ============================================================

from __future__ import annotations

import os

import json

import math

import time

import traceback

from pathlib import Path

from datetime import datetime, timedelta

import numpy as np

import pandas as pd

import yfinance as yf

# ============================================================

# SETTINGS

# ============================================================

TZ = "Asia/Tokyo"

INITIAL_CAPITAL = 1_117_792.0

LONG_LEVERAGE = 1.00

SHORT_LEVERAGE = 0.50

LOT_SIZE = 100

MIN_MARGIN_RATIO = 0.30

SUBSTITUTE_HAIRCUT = 0.80

# ------------------------------------------------------------

# FIX11 exit rules

# ------------------------------------------------------------

LONG_SL = 0.025

LONG_TRAIL_TRIGGER = 0.025

LONG_TRAIL_WIDTH = 0.010

LONG_MAX_TRADING_DAYS = 10

SHORT_SL = 0.015

SHORT_TRAIL_TRIGGER = 0.020

SHORT_TRAIL_WIDTH = 0.020

# ------------------------------------------------------------

# Signal

# ------------------------------------------------------------

RS_LONG_MIN = 80.0

RS_SHORT_MAX = 20.0

TURNOVER_MIN_OKU = 3.0

RVOL_MIN = 2.0

ORB_START = "09:00"

ORB_END = "09:14"

SIGNAL_START = "09:15"

# ------------------------------------------------------------

# Data

# ------------------------------------------------------------

DATA_DIR = Path(

    os.getenv(

        "FIX11_DATA_DIR",

        "data/fix11"

    )

)

RAW_DIR = DATA_DIR / "yahoo_1m"

STATE_FILE = DATA_DIR / "portfolio.json"

TRADES_FILE = DATA_DIR / "paper_trades.csv"

SCREEN_FILE = DATA_DIR / "screening_history.csv"

LATEST_FILE = Path("latest_fix11_result.txt")

UNIVERSE_FILE = Path("data/universe.csv")

DATA_DIR.mkdir(parents=True, exist_ok=True)

RAW_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================

# HELPERS

# ============================================================

def now_jst():

    return pd.Timestamp.now(tz=TZ)

def normalize_code(x):

    s = str(x).strip()

    if s.endswith(".T"):

        s = s[:-2]

    if s.endswith(".0"):

        s = s[:-2]

    return s.zfill(4)

def ticker_from_code(code):

    return f"{normalize_code(code)}.T"

def safe_float(x, default=np.nan):

    try:

        v = float(x)

        if np.isfinite(v):

            return v

    except Exception:

        pass

    return default

def load_csv_safe(path):

    if not Path(path).exists():

        return pd.DataFrame()

    try:

        return pd.read_csv(path)

    except Exception:

        return pd.DataFrame()

def save_json(obj, path):

    tmp = str(path) + ".tmp"

    with open(

        tmp,

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            obj,

            f,

            ensure_ascii=False,

            indent=2,

            default=str

        )

    os.replace(tmp, path)

# ============================================================

# UNIVERSE

# ============================================================

def load_universe():

    # --------------------------------------------------------

    # 1. data/universe.csv

    #

    # accepted columns:

    #   Code

    #   code

    #   Ticker

    #   ticker

    # --------------------------------------------------------

    if UNIVERSE_FILE.exists():

        df = pd.read_csv(

            UNIVERSE_FILE,

            dtype=str

        )

        for col in [

            "Code",

            "code",

            "Ticker",

            "ticker"

        ]:

            if col in df.columns:

                values = (

                    df[col]

                    .dropna()

                    .astype(str)

                    .tolist()

                )

                codes = []

                for x in values:

                    if ".T" in x:

                        x = x.replace(".T", "")

                    x = x.replace(".0", "")

                    if x.isdigit():

                        codes.append(

                            normalize_code(x)

                        )

                codes = sorted(set(codes))

                if codes:

                    return codes

    # --------------------------------------------------------

    # 2. environment variable fallback

    # --------------------------------------------------------

    env = os.getenv(

        "FIX11_UNIVERSE",

        ""

    ).strip()

    if env:

        codes = []

        for x in env.split(","):

            x = x.strip()

            x = x.replace(".T", "")

            if x:

                codes.append(

                    normalize_code(x)

                )

        codes = sorted(set(codes))

        if codes:

            return codes

    raise RuntimeError(

        "\n"

        "FIX11 universe がありません。\n"

        "\n"

        "data/universe.csv を作成してください。\n"

        "最低限 Code 列があればOKです。\n"

        "\n"

        "例:\n"

        "Code\n"

        "5803\n"

        "6871\n"

        "6723\n"

    )

# ============================================================

# PORTFOLIO STATE

# ============================================================

def initial_state():

    return {

        "version":

            "FIX11_FORWARD_V1",

        "cash":

            INITIAL_CAPITAL,

        "strategy_equity":

            INITIAL_CAPITAL,

        "etf_1557_shares":

            0,

        "positions":

            {

                "LONG": None,

                "SHORT": None,

            },

        "pending_entries":

            {

                "LONG": None,

                "SHORT": None,

            },

        "last_run":

            None,

        "last_processed_bar":

            None,

    }

def load_state():

    if not STATE_FILE.exists():

        state = initial_state()

        save_json(

            state,

            STATE_FILE

        )

        return state

    with open(

        STATE_FILE,

        "r",

        encoding="utf-8"

    ) as f:

        return json.load(f)

# ============================================================

# YAHOO DATA NORMALIZATION

# ============================================================

def normalize_yf_intraday(df):

    if df is None or len(df) == 0:

        return pd.DataFrame()

    x = df.copy()

    if isinstance(

        x.columns,

        pd.MultiIndex

    ):

        x.columns = [

            c[0]

            if isinstance(c, tuple)

            else c

            for c in x.columns

        ]

    x = x.reset_index()

    dt_col = None

    for c in [

        "Datetime",

        "Date"

    ]:

        if c in x.columns:

            dt_col = c

            break

    if dt_col is None:

        return pd.DataFrame()

    x["Datetime"] = pd.to_datetime(

        x[dt_col],

        errors="coerce",

        utc=True

    )

    x["Datetime"] = (

        x["Datetime"]

        .dt.tz_convert(TZ)

        .dt.tz_localize(None)

    )

    ren = {

        "Open": "O",

        "High": "H",

        "Low": "L",

        "Close": "C",

        "Volume": "V",

    }

    x = x.rename(

        columns=ren

    )

    need = [

        "Datetime",

        "O",

        "H",

        "L",

        "C",

        "V",

    ]

    if any(

        c not in x.columns

        for c in need

    ):

        return pd.DataFrame()

    x = x[need].copy()

    for c in [

        "O",

        "H",

        "L",

        "C",

        "V"

    ]:

        x[c] = pd.to_numeric(

            x[c],

            errors="coerce"

        )

    x = x.dropna(

        subset=[

            "Datetime",

            "O",

            "H",

            "L",

            "C"

        ]

    )

    x["Date"] = (

        x["Datetime"]

        .dt.normalize()

    )

    x["Time"] = (

        x["Datetime"]

        .dt.strftime("%H:%M")

    )

    return (

        x

        .sort_values("Datetime")

        .drop_duplicates(

            "Datetime",

            keep="last"

        )

        .reset_index(drop=True)

    )

# ============================================================

# FETCH TODAY 1M

# ============================================================

def fetch_today_1m(code):

    ticker = ticker_from_code(

        code

    )

    try:

        raw = yf.download(

            ticker,

            period="1d",

            interval="1m",

            auto_adjust=False,

            prepost=False,

            progress=False,

            threads=False,

        )

        x = normalize_yf_intraday(

            raw

        )

        if x.empty:

            return x

        today = now_jst().tz_localize(None).normalize()

        x = x[

            x["Date"] == today

        ].copy()

        x["Code"] = normalize_code(

            code

        )

        return x

    except Exception:

        return pd.DataFrame()

# ============================================================

# RAW SNAPSHOT SAVE

# ============================================================

def save_raw_snapshot(df):

    if df.empty:

        return

    date = pd.Timestamp(

        df["Date"].iloc[0]

    )

    day_dir = (

        RAW_DIR

        /

        date.strftime("%Y")

        /

        date.strftime("%m")

    )

    day_dir.mkdir(

        parents=True,

        exist_ok=True

    )

    code = str(

        df["Code"].iloc[0]

    )

    path = (

        day_dir

        /

        f"{date:%Y-%m-%d}_{code}.parquet"

    )

    # --------------------------------------------------------

    # Immutable-like merge:

    # existing observations are kept,

    # newly arrived timestamps appended.

    # --------------------------------------------------------

    if path.exists():

        old = pd.read_parquet(

            path

        )

        z = pd.concat(

            [old, df],

            ignore_index=True

        )

        z["Datetime"] = pd.to_datetime(

            z["Datetime"]

        )

        z = (

            z

            .sort_values("Datetime")

            .drop_duplicates(

                "Datetime",

                keep="first"

            )

        )

    else:

        z = df.copy()

    z.to_parquet(

        path,

        index=False

    )

# ============================================================

# DAILY DATA

# ============================================================

def fetch_daily_batch(codes):

    tickers = [

        ticker_from_code(c)

        for c in codes

    ]

    frames = []

    # 50 symbols per batch

    for i in range(

        0,

        len(tickers),

        50

    ):

        batch = tickers[

            i:i + 50

        ]

        try:

            raw = yf.download(

                batch,

                period="3mo",

                interval="1d",

                auto_adjust=False,

                group_by="ticker",

                progress=False,

                threads=True,

            )

        except Exception:

            continue

        for ticker in batch:

            code = ticker.replace(

                ".T",

                ""

            )

            try:

                if len(batch) == 1:

                    d = raw.copy()

                else:

                    if ticker not in raw.columns.levels[0]:

                        continue

                    d = raw[ticker].copy()

                if d.empty:

                    continue

                d = d.reset_index()

                d["Date"] = pd.to_datetime(

                    d["Date"],

                    errors="coerce"

                ).dt.normalize()

                # ------------------------------------------------

                # Backtest used adjusted basis for indicators.

                # Yahoo Adj Close is used here for DAILY indicator

                # calculation only.

                # Broker quantity later uses raw entry Open.

                # ------------------------------------------------

                if "Adj Close" in d.columns:

                    d["AdjC"] = pd.to_numeric(

                        d["Adj Close"],

                        errors="coerce"

                    )

                else:

                    d["AdjC"] = pd.to_numeric(

                        d["Close"],

                        errors="coerce"

                    )

                d["RawC"] = pd.to_numeric(

                    d["Close"],

                    errors="coerce"

                )

                d["Volume"] = pd.to_numeric(

                    d["Volume"],

                    errors="coerce"

                )

                d["Code"] = normalize_code(

                    code

                )

                frames.append(

                    d[

                        [

                            "Date",

                            "Code",

                            "AdjC",

                            "RawC",

                            "Volume",

                        ]

                    ]

                )

            except Exception:

                continue

    if not frames:

        return pd.DataFrame()

    return pd.concat(

        frames,

        ignore_index=True

    )

# ============================================================

# DAILY FEATURES

# ============================================================

def build_daily_features(

    daily,

    today,

):

    if daily.empty:

        return pd.DataFrame()

    d = daily.copy()

    d = d[

        d["Date"] < today

    ].copy()

    d = d.sort_values(

        ["Code", "Date"]

    )

    # --------------------------------------------------------

    # Return20_prev

    # Must use only data known before today.

    # --------------------------------------------------------

    d["Return20"] = (

        d.groupby("Code")["AdjC"]

        .pct_change(20)

    )

    latest_rows = []

    for code, g in d.groupby(

        "Code",

        sort=False

    ):

        g = (

            g

            .sort_values("Date")

            .reset_index(drop=True)

        )

        if len(g) < 21:

            continue

        last = g.iloc[-1]

        # ----------------------------------------------------

        # 20-day median turnover

        # Raw close × volume / 1e8

        # previous 20 trading observations

        # ----------------------------------------------------

        tail20 = g.tail(20).copy()

        turnover = (

            tail20["RawC"]

            *

            tail20["Volume"]

            /

            1e8

        )

        turnover_med = float(

            turnover.median()

        )

        latest_rows.append({

            "Code":

                code,

            "Return20_prev":

                safe_float(

                    last["Return20"]

                ),

            "turnover_median_20d_oku":

                turnover_med,

            "PrevDailyClose":

                safe_float(

                    last["RawC"]

                ),

        })

    f = pd.DataFrame(

        latest_rows

    )

    if f.empty:

        return f

    valid = f[

        f["Return20_prev"].notna()

    ].copy()

    if valid.empty:

        f["RS20"] = np.nan

        return f

    # --------------------------------------------------------

    # Cross-sectional percentile 0-100

    # --------------------------------------------------------

    valid["RS20"] = (

        valid["Return20_prev"]

        .rank(

            pct=True,

            method="average"

        )

        *

        100.0

    )

    f = f.merge(

        valid[

            [

                "Code",

                "RS20",

            ]

        ],

        on="Code",

        how="left"

    )

    return f

# ============================================================

# RVOL20 HISTORY

# ============================================================

def get_history_files_for_code(

    code,

    before_date,

):

    paths = []

    for p in RAW_DIR.rglob(

        f"*_{code}.parquet"

    ):

        try:

            date_str = (

                p.name[:10]

            )

            date = pd.Timestamp(

                date_str

            )

            if date < before_date:

                paths.append(

                    (date, p)

                )

        except Exception:

            continue

    paths.sort(

        key=lambda x: x[0]

    )

    return paths[-20:]

def calc_rvol20(

    code,

    current_df,

    signal_dt,

):

    date = pd.Timestamp(

        signal_dt

    ).normalize()

    minute = pd.Timestamp(

        signal_dt

    ).strftime("%H:%M")

    hist_files = get_history_files_for_code(

        code,

        date

    )

    # EXACT 20 prior sessions required.

    if len(hist_files) < 20:

        return np.nan, len(hist_files)

    current_cut = current_df[

        current_df["Datetime"]

        <= signal_dt

    ]

    if current_cut.empty:

        return np.nan, 20

    current_cum = float(

        current_cut["V"].fillna(0).sum()

    )

    hist_cums = []

    for hist_date, path in hist_files:

        try:

            h = pd.read_parquet(

                path

            )

            h["Datetime"] = pd.to_datetime(

                h["Datetime"]

            )

            h["Time"] = (

                h["Datetime"]

                .dt.strftime("%H:%M")

            )

            # Missing eligible prior-day bar contributes zero

            cut = h[

                h["Time"] <= minute

            ]

            if cut.empty:

                cum = 0.0

            else:

                cum = float(

                    pd.to_numeric(

                        cut["V"],

                        errors="coerce"

                    )

                    .fillna(0)

                    .sum()

                )

            hist_cums.append(

                cum

            )

        except Exception:

            hist_cums.append(

                0.0

            )

    if len(hist_cums) != 20:

        return np.nan, len(hist_cums)

    baseline = float(

        np.median(

            hist_cums

        )

    )

    if (

        not np.isfinite(baseline)

        or

        baseline <= 0

    ):

        return np.nan, 20

    return (

        current_cum / baseline,

        20

    )

# ============================================================

# SIGNAL FINDER

# ============================================================

def find_first_signal(

    code,

    minute_df,

    feature,

):

    if minute_df.empty:

        return None

    x = minute_df.copy()

    x = x[

        x["Time"] >= ORB_START

    ].copy()

    if x.empty:

        return None

    orb = x[

        (x["Time"] >= ORB_START)

        &

        (x["Time"] <= ORB_END)

    ]

    if orb.empty:

        return None

    orb_high = float(

        orb["H"].max()

    )

    orb_low = float(

        orb["L"].min()

    )

    post = x[

        x["Time"] >= SIGNAL_START

    ].copy()

    if len(post) < 2:

        return None

    rs20 = safe_float(

        feature.get("RS20")

    )

    turnover = safe_float(

        feature.get(

            "turnover_median_20d_oku"

        )

    )

    if not np.isfinite(rs20):

        return None

    if (

        not np.isfinite(turnover)

        or

        turnover < TURNOVER_MIN_OKU

    ):

        return None

    prev_close = None

    for i in range(

        len(post)

    ):

        row = post.iloc[i]

        dt = pd.Timestamp(

            row["Datetime"]

        )

        close = float(

            row["C"]

        )

        if prev_close is None:

            # previous actual bar

            before = x[

                x["Datetime"] < dt

            ]

            if before.empty:

                continue

            prev_close = float(

                before.iloc[-1]["C"]

            )

        rvol, prev_days = calc_rvol20(

            code=code,

            current_df=x,

            signal_dt=dt,

        )

        if not np.isfinite(rvol):

            prev_close = close

            continue

        # ----------------------------------------------------

        # LONG

        # ----------------------------------------------------

        long_break = (

            prev_close

            <=

            orb_high

            and

            close

            >

            orb_high

        )

        if (

            rs20 >= RS_LONG_MIN

            and

            rvol >= RVOL_MIN

            and

            long_break

        ):

            return {

                "Side":

                    "LONG",

                "Code":

                    code,

                "SignalDatetime":

                    dt,

                "SignalPrice":

                    close,

                "ORBHigh":

                    orb_high,

                "ORBLow":

                    orb_low,

                "RS20":

                    rs20,

                "RVOL20":

                    rvol,

                "Turnover20Oku":

                    turnover,

                "PrevDays":

                    prev_days,

            }

        # ----------------------------------------------------

        # SHORT

        # ----------------------------------------------------

        short_break = (

            prev_close

            >=

            orb_low

            and

            close

            <

            orb_low

        )

        if (

            rs20 <= RS_SHORT_MAX

            and

            rvol >= RVOL_MIN

            and

            short_break

        ):

            return {

                "Side":

                    "SHORT",

                "Code":

                    code,

                "SignalDatetime":

                    dt,

                "SignalPrice":

                    close,

                "ORBHigh":

                    orb_high,

                "ORBLow":

                    orb_low,

                "RS20":

                    rs20,

                "RVOL20":

                    rvol,

                "Turnover20Oku":

                    turnover,

                "PrevDays":

                    prev_days,

            }

        prev_close = close

    return None

# ============================================================

# NEXT ACTUAL BAR ENTRY

# ============================================================

def attach_next_open(

    signal,

    minute_df,

):

    dt = pd.Timestamp(

        signal["SignalDatetime"]

    )

    after = minute_df[

        minute_df["Datetime"] > dt

    ]

    if after.empty:

        return None

    nxt = after.iloc[0]

    result = dict(signal)

    result[

        "EntryDatetime"

    ] = pd.Timestamp(

        nxt["Datetime"]

    )

    # IMPORTANT:

    # Broker position sizing uses RAW Yahoo Open.

    result[

        "EntryPriceRaw"

    ] = float(

        nxt["O"]

    )

    return result

# ============================================================

# RANKING

# ============================================================

def choose_candidate(

    candidates,

    side

):

    x = [

        c

        for c in candidates

        if c["Side"] == side

    ]

    if not x:

        return None

    df = pd.DataFrame(

        x

    )

    # earliest signal first

    earliest = df[

        "SignalDatetime"

    ].min()

    df = df[

        df["SignalDatetime"]

        ==

        earliest

    ].copy()

    if side == "LONG":

        df = df.sort_values(

            [

                "RS20",

                "RVOL20",

                "Turnover20Oku",

                "Code",

            ],

            ascending=[

                False,

                False,

                False,

                True,

            ],

            kind="stable",

        )

    else:

        df = df.sort_values(

            [

                "RS20",

                "RVOL20",

                "Turnover20Oku",

                "Code",

            ],

            ascending=[

                True,

                False,

                False,

                True,

            ],

            kind="stable",

        )

    return df.iloc[0].to_dict()

# ============================================================

# 100 SHARE POSITION SIZE

# ============================================================

def calc_qty(

    strategy_equity,

    leverage,

    entry_price,

):

    target = (

        float(strategy_equity)

        *

        float(leverage)

    )

    one_lot = (

        float(entry_price)

        *

        LOT_SIZE

    )

    if one_lot <= 0:

        return 0, target

    lots = int(

        math.floor(

            target

            /

            one_lot

        )

    )

    qty = max(

        0,

        lots * LOT_SIZE

    )

    return qty, target

# ============================================================

# MARGIN CHECK

# ============================================================

def estimate_margin_ratio_after_entry(

    state,

    qty,

    entry_price,

):

    positions = state[

        "positions"

    ]

    existing = 0.0

    for side in [

        "LONG",

        "SHORT"

    ]:

        p = positions.get(

            side

        )

        if p:

            existing += safe_float(

                p.get(

                    "ActualNotional"

                ),

                0.0

            )

    new_notional = (

        qty

        *

        entry_price

    )

    gross = (

        existing

        +

        new_notional

    )

    if gross <= 0:

        return np.inf

    # Forward paper version:

    # cash is used as collateral.

    #

    # 1557 collateral valuation can be added when

    # live 1557 holding management is enabled.

    effective_collateral = safe_float(

        state.get(

            "cash"

        ),

        0.0

    )

    return (

        effective_collateral

        /

        gross

    )

# ============================================================

# ENTRY

# ============================================================

def execute_paper_entry(

    state,

    candidate,

):

    side = candidate[

        "Side"

    ]

    if state[

        "positions"

    ].get(side):

        return state, None

    price = float(

        candidate[

            "EntryPriceRaw"

        ]

    )

    leverage = (

        LONG_LEVERAGE

        if side == "LONG"

        else

        SHORT_LEVERAGE

    )

    qty, target = calc_qty(

        strategy_equity=

            state[

                "strategy_equity"

            ],

        leverage=leverage,

        entry_price=price,

    )

    if qty <= 0:

        return state, {

            "Status":

                "SKIP_LOT_TOO_LARGE",

            **candidate,

            "Quantity":

                0,

            "TargetNotional":

                target,

        }

    margin = (

        estimate_margin_ratio_after_entry(

            state,

            qty,

            price

        )

    )

    if margin < MIN_MARGIN_RATIO:

        return state, {

            "Status":

                "SKIP_MARGIN",

            **candidate,

            "Quantity":

                0,

            "TargetNotional":

                target,

            "PostMarginPct":

                margin * 100.0,

        }

    position = {

        "Side":

            side,

        "Code":

            candidate["Code"],

        "EntryDatetime":

            str(

                candidate[

                    "EntryDatetime"

                ]

            ),

        "EntryPrice":

            price,

        "Quantity":

            qty,

        "TargetNotional":

            target,

        "ActualNotional":

            qty * price,

        "RS20":

            candidate["RS20"],

        "RVOL20":

            candidate["RVOL20"],

        "Turnover20Oku":

            candidate[

                "Turnover20Oku"

            ],

        "SignalDatetime":

            str(

                candidate[

                    "SignalDatetime"

                ]

            ),

        "TrailActive":

            False,

        "BestPrice":

            price,

        "PendingTrailStop":

            None,

        "TradingDaysHeld":

            1,

    }

    state[

        "positions"

    ][side] = position

    return state, {

        "Status":

            "PAPER_ENTRY",

        **candidate,

        "Quantity":

            qty,

        "TargetNotional":

            target,

        "ActualNotional":

            qty * price,

        "PostMarginPct":

            margin * 100.0,

    }

# ============================================================

# SCREEN HISTORY SAVE

# ============================================================

def append_screen_rows(

    rows

):

    if not rows:

        return

    df = pd.DataFrame(

        rows

    )

    exists = SCREEN_FILE.exists()

    df.to_csv(

        SCREEN_FILE,

        mode="a",

        header=not exists,

        index=False

    )

# ============================================================

# TRADE LOG SAVE

# ============================================================

def append_trade_row(

    row

):

    df = pd.DataFrame(

        [row]

    )

    exists = TRADES_FILE.exists()

    df.to_csv(

        TRADES_FILE,

        mode="a",

        header=not exists,

        index=False

    )

# ============================================================

# RESULT TEXT

# ============================================================

def write_result(

    lines

):

    text = "\n".join(

        str(x)

        for x in lines

    )

    print(text)

    with open(

        LATEST_FILE,

        "w",

        encoding="utf-8"

    ) as f:

        f.write(

            text

            +

            "\n"

        )

# ============================================================

# MAIN

# ============================================================

def main():

    run_time = now_jst()

    run_naive = (

        run_time

        .tz_localize(None)

    )

    today = run_naive.normalize()

    print("=" * 100)

    print("FIX11 FORWARD PAPER TRADER")

    print("=" * 100)

    print("Run:", run_time)

    print()

    state = load_state()

    universe = load_universe()

    print(

        "Universe:",

        len(universe)

    )

    # ========================================================

    # Daily features

    # ========================================================

    print(

        "Daily data..."

    )

    daily = fetch_daily_batch(

        universe

    )

    features = build_daily_features(

        daily=daily,

        today=today,

    )

    if features.empty:

        raise RuntimeError(

            "Daily features empty"

        )

    feature_map = (

        features

        .set_index("Code")

        .to_dict(

            orient="index"

        )

    )

    # ========================================================

    # Scan intraday

    # ========================================================

    candidates = []

    screen_rows = []

    success = 0

    failed = 0

    history_not_ready = 0

    for i, code in enumerate(

        universe,

        1

    ):

        minute = fetch_today_1m(

            code

        )

        if minute.empty:

            failed += 1

            continue

        success += 1

        save_raw_snapshot(

            minute

        )

        feature = feature_map.get(

            normalize_code(code)

        )

        if not feature:

            continue

        hist_n = len(

            get_history_files_for_code(

                normalize_code(code),

                today

            )

        )

        if hist_n < 20:

            history_not_ready += 1

            screen_rows.append({

                "RunDatetime":

                    run_naive,

                "Date":

                    today,

                "Code":

                    normalize_code(code),

                "Status":

                    "NOT_READY_RVOL20",

                "HistoryDays":

                    hist_n,

                "RS20":

                    feature.get(

                        "RS20"

                    ),

                "Turnover20Oku":

                    feature.get(

                        "turnover_median_20d_oku"

                    ),

            })

            continue

        sig = find_first_signal(

            code=normalize_code(code),

            minute_df=minute,

            feature=feature,

        )

        if sig is None:

            continue

        sig = attach_next_open(

            sig,

            minute

        )

        if sig is None:

            screen_rows.append({

                "RunDatetime":

                    run_naive,

                "Date":

                    today,

                "Code":

                    normalize_code(code),

                "Status":

                    "SIGNAL_WAIT_NEXT_BAR",

            })

            continue

        candidates.append(

            sig

        )

        screen_rows.append({

            "RunDatetime":

                run_naive,

            "Date":

                today,

            "Code":

                sig["Code"],

            "Status":

                "SIGNAL",

            "Side":

                sig["Side"],

            "SignalDatetime":

                sig[

                    "SignalDatetime"

                ],

            "EntryDatetime":

                sig[

                    "EntryDatetime"

                ],

            "EntryPriceRaw":

                sig[

                    "EntryPriceRaw"

                ],

            "RS20":

                sig[

                    "RS20"

                ],

            "RVOL20":

                sig[

                    "RVOL20"

                ],

            "Turnover20Oku":

                sig[

                    "Turnover20Oku"

                ],

        })

        if i % 50 == 0:

            print(

                f"{i}/{len(universe)} "

                f"success={success} "

                f"failed={failed}"

            )

    append_screen_rows(

        screen_rows

    )

    # ========================================================

    # Select candidate

    # ========================================================

    chosen = []

    for side in [

        "LONG",

        "SHORT"

    ]:

        if state[

            "positions"

        ].get(side):

            continue

        c = choose_candidate(

            candidates,

            side

        )

        if c is not None:

            chosen.append(

                c

            )

    # ========================================================

    # Paper entry

    # ========================================================

    entry_results = []

    for c in chosen:

        state, result = (

            execute_paper_entry(

                state,

                c

            )

        )

        if result:

            result[

                "RunDatetime"

            ] = run_naive

            append_trade_row(

                result

            )

            entry_results.append(

                result

            )

    state[

        "last_run"

    ] = str(

        run_naive

    )

    save_json(

        state,

        STATE_FILE

    )

    # ========================================================

    # Result

    # ========================================================

    lines = []

    lines.append(

        "FIX11 FORWARD PAPER TRADER"

    )

    lines.append(

        f"Run: {run_naive}"

    )

    lines.append(

        f"Universe: {len(universe)}"

    )

    lines.append(

        f"1m success: {success}"

    )

    lines.append(

        f"1m failed: {failed}"

    )

    lines.append(

        f"RVOL20 not ready: "

        f"{history_not_ready}"

    )

    lines.append(

        f"Signals: "

        f"{len(candidates)}"

    )

    lines.append("")

    for side in [

        "LONG",

        "SHORT"

    ]:

        p = state[

            "positions"

        ].get(side)

        if p:

            lines.append(

                f"{side}: "

                f"{p['Code']} "

                f"{p['Quantity']}株 "

                f"@ {p['EntryPrice']:,.2f}"

            )

        else:

            lines.append(

                f"{side}: FLAT"

            )

    if entry_results:

        lines.append("")

        lines.append(

            "NEW PAPER ENTRY"

        )

        for r in entry_results:

            lines.append(

                f"{r['Side']} "

                f"{r['Code']} "

                f"{r['Status']} "

                f"{int(r['Quantity'])}株 "

                f"@ {r['EntryPriceRaw']:,.2f}"

            )

    write_result(

        lines

    )

# ============================================================

# ENTRYPOINT

# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        msg = [

            "FIX11 FORWARD PAPER TRADER ERROR",

            "",

            str(e),

            "",

            traceback.format_exc(),

        ]

        write_result(

            msg

        )

        raise
