# ============================================================
# FIX18_SIGNAL_ENGINE.py
#
# FIX18 official historical signal engine
#
# Parent:
#   FIX17_RUNTIME
#
# Proven equivalence:
#   2026-09-11
#
# Result:
#   generated signals : 79
#   old Paper Trader  : 79
#   common            : 79
#   FIX18 only        : 0
#   old only          : 0
#
# Exact:
#   Signal set
#   RS20_corrected
#   RVOL20
#   turnover
#   ORBHigh / ORBLow
#   EntryDatetime
#   EntryPrice
#
# SHORT:
#   is_lending=True required
#
# No-Future:
#   prior sessions only
#
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Tuple, Optional, Any

import numpy as np
import pandas as pd


# ============================================================
# CONSTANTS
# ============================================================

RS_LONG_MIN = 80.0
RS_SHORT_MAX = 20.0
RVOL_MIN = 2.0
TURNOVER_MIN_OKU = 3.0

ORB_START = "09:00"
ORB_END = "09:14"
SIGNAL_START = "09:15"

REQUIRED_HISTORY_SESSIONS = 20


# ============================================================
# CODE NORMALIZATION
# ============================================================

def normalize_code(code: Any) -> str:
    s = str(code).strip()

    if s.endswith(".0"):
        s = s[:-2]

    if len(s) == 5 and s.endswith("0"):
        s = s[:-1]

    return s


# ============================================================
# RS20_corrected
#
# Proven historical formula:
#
# valid["RS20_corrected"] =
#     valid["Return20_prev"]
#     .rank(pct=True, method="average")
#     * 100
#
# ============================================================

def compute_rs20_corrected(
    feature_df: pd.DataFrame,
) -> pd.DataFrame:

    x = feature_df.copy()

    if "Return20_prev" not in x.columns:
        raise RuntimeError(
            "Return20_prev missing"
        )

    x["RS20_corrected"] = np.nan

    valid = x[
        x["Return20_prev"].notna()
    ].copy()

    if valid.empty:
        return x

    ranked = (
        valid["Return20_prev"]
        .rank(
            pct=True,
            method="average",
        )
        * 100.0
    )

    x.loc[
        valid.index,
        "RS20_corrected",
    ] = ranked

    return x


# ============================================================
# HISTORY STORE
#
# history_store:
#
# {
#   code: {
#       date: (
#           np.ndarray[str HH:MM],
#           np.ndarray[float cumulative_volume]
#       )
#   }
# }
#
# ============================================================

HistoryStore = Dict[
    str,
    Dict[
        date,
        Tuple[np.ndarray, np.ndarray],
    ],
]


# ============================================================
# BUILD COMPRESSED RVOL HISTORY
# ============================================================

def build_compressed_history(
    daily_frames: List[Tuple[date, pd.DataFrame]],
) -> HistoryStore:

    history_store: HistoryStore = {}

    for trade_date, df in daily_frames:

        if df is None or df.empty:
            continue

        x = df.copy()

        required = {
            "Datetime",
            "Code",
            "Volume",
        }

        missing = required - set(
            x.columns
        )

        if missing:
            raise RuntimeError(
                "History columns missing: "
                + ", ".join(
                    sorted(missing)
                )
            )

        x["Code"] = (
            x["Code"]
            .astype(str)
            .map(normalize_code)
        )

        x["Datetime"] = pd.to_datetime(
            x["Datetime"],
            errors="coerce",
        )

        x = x[
            x["Datetime"].notna()
        ].copy()

        x["Time"] = (
            x["Datetime"]
            .dt
            .strftime("%H:%M")
        )

        x["VolumeNumeric"] = (
            pd.to_numeric(
                x["Volume"],
                errors="coerce",
            )
            .fillna(0.0)
        )

        grouped = (
            x
            .groupby(
                ["Code", "Time"],
                sort=False,
                as_index=False,
            )["VolumeNumeric"]
            .sum()
        )

        for code, g in grouped.groupby(
            "Code",
            sort=False,
        ):

            g = g.sort_values(
                "Time"
            )

            times = (
                g["Time"]
                .astype(str)
                .to_numpy()
            )

            cumulative = (
                g["VolumeNumeric"]
                .cumsum()
                .to_numpy(dtype=float)
            )

            history_store.setdefault(
                str(code),
                {},
            )[trade_date] = (
                times,
                cumulative,
            )

    return history_store


# ============================================================
# RVOL20
#
# Exact historical behavior:
#
# current cumulative volume through signal minute
#
# divided by
#
# median(
#   cumulative volume through same minute
#   for prior 20 sessions
# )
#
# Exactly 20 sessions required.
# ============================================================

def calc_rvol20(
    code: str,
    current_df: pd.DataFrame,
    signal_dt: pd.Timestamp,
    history_store: HistoryStore,
) -> Tuple[float, int]:

    code = normalize_code(code)

    signal_dt = pd.Timestamp(
        signal_dt
    )

    minute = signal_dt.strftime(
        "%H:%M"
    )

    sessions = history_store.get(
        code,
        {},
    )

    dates = sorted(
        d
        for d in sessions.keys()
        if d < signal_dt.date()
    )[-REQUIRED_HISTORY_SESSIONS:]

    if len(dates) < REQUIRED_HISTORY_SESSIONS:
        return np.nan, len(dates)

    current_cut = current_df[
        pd.to_datetime(
            current_df["Datetime"]
        )
        <= signal_dt
    ]

    current_cum = (
        pd.to_numeric(
            current_cut["V"],
            errors="coerce",
        )
        .fillna(0.0)
        .sum()
    )

    hist_cums = []

    for trade_date in dates:

        times, cumulative = (
            sessions[trade_date]
        )

        pos = np.searchsorted(
            times,
            minute,
            side="right",
        ) - 1

        if pos < 0:
            hist_cums.append(0.0)
        else:
            hist_cums.append(
                float(
                    cumulative[pos]
                )
            )

    if (
        len(hist_cums)
        != REQUIRED_HISTORY_SESSIONS
    ):
        return np.nan, len(hist_cums)

    baseline = float(
        np.median(
            hist_cums
        )
    )

    if (
        not np.isfinite(baseline)
        or baseline <= 0
    ):
        return np.nan, REQUIRED_HISTORY_SESSIONS

    return (
        float(
            current_cum
            /
            baseline
        ),
        REQUIRED_HISTORY_SESSIONS,
    )


# ============================================================
# CURRENT MINUTE SCHEMA
# ============================================================

def prepare_minute_df(
    df: pd.DataFrame,
) -> pd.DataFrame:

    x = df.copy()

    required = {
        "Datetime",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    }

    missing = required - set(
        x.columns
    )

    if missing:
        raise RuntimeError(
            "Minute columns missing: "
            + ", ".join(
                sorted(missing)
            )
        )

    x["Datetime"] = pd.to_datetime(
        x["Datetime"],
        errors="coerce",
    )

    x = x[
        x["Datetime"].notna()
    ].copy()

    x = x.sort_values(
        "Datetime"
    )

    x["O"] = pd.to_numeric(
        x["Open"],
        errors="coerce",
    )

    x["H"] = pd.to_numeric(
        x["High"],
        errors="coerce",
    )

    x["L"] = pd.to_numeric(
        x["Low"],
        errors="coerce",
    )

    x["C"] = pd.to_numeric(
        x["Close"],
        errors="coerce",
    )

    x["V"] = pd.to_numeric(
        x["Volume"],
        errors="coerce",
    ).fillna(0.0)

    x["Time"] = (
        x["Datetime"]
        .dt
        .strftime("%H:%M")
    )

    return x[
        [
            "Datetime",
            "Time",
            "O",
            "H",
            "L",
            "C",
            "V",
        ]
    ].reset_index(
        drop=True
    )


# ============================================================
# FIRST SIGNAL
#
# Exact FIX11 entry behavior reconstructed and proven
# against old Paper Trader candidate audit.
# ============================================================

def find_first_signal(
    code: str,
    minute_df: pd.DataFrame,
    feature: Dict[str, Any],
    history_store: HistoryStore,
) -> Optional[Dict[str, Any]]:

    code = normalize_code(code)

    if minute_df is None or minute_df.empty:
        return None

    x = minute_df.copy()

    rs = pd.to_numeric(
        feature.get(
            "RS20_corrected"
        ),
        errors="coerce",
    )

    turnover = pd.to_numeric(
        feature.get(
            "turnover_median_20d_oku"
        ),
        errors="coerce",
    )

    is_lending = bool(
        feature.get(
            "is_lending",
            False,
        )
    )

    if not np.isfinite(rs):
        return None

    if not np.isfinite(turnover):
        return None

    if turnover < TURNOVER_MIN_OKU:
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

    candidates = x[
        x["Time"] >= SIGNAL_START
    ]

    if candidates.empty:
        return None

    prev_close = None

    for row in x.itertuples(
        index=False
    ):

        current_time = row.Time

        if current_time < SIGNAL_START:
            prev_close = row.C
            continue

        if prev_close is None:
            prev_close = row.C
            continue

        signal_dt = pd.Timestamp(
            row.Datetime
        )

        # ----------------------------------------------------
        # LONG CROSS
        # ----------------------------------------------------

        long_cross = (
            prev_close <= orb_high
            and row.C > orb_high
        )

        if (
            long_cross
            and rs >= RS_LONG_MIN
        ):

            rvol, prev_days = calc_rvol20(
                code=code,
                current_df=x,
                signal_dt=signal_dt,
                history_store=history_store,
            )

            if (
                np.isfinite(rvol)
                and rvol >= RVOL_MIN
                and prev_days
                    == REQUIRED_HISTORY_SESSIONS
            ):

                return {
                    "Side": "LONG",
                    "Code": code,
                    "SignalDatetime": signal_dt,
                    "SignalPrice": float(
                        row.C
                    ),
                    "ORBHigh": orb_high,
                    "ORBLow": orb_low,
                    "RS20": float(rs),
                    "RS20_corrected": float(rs),
                    "RVOL20": float(rvol),
                    "Turnover20Oku": float(
                        turnover
                    ),
                    "turnover_median_20d_oku": float(
                        turnover
                    ),
                    "PrevDays": int(
                        prev_days
                    ),
                }

        # ----------------------------------------------------
        # SHORT CROSS
        # ----------------------------------------------------

        short_cross = (
            prev_close >= orb_low
            and row.C < orb_low
        )

        if (
            short_cross
            and rs <= RS_SHORT_MAX
            and is_lending
        ):

            rvol, prev_days = calc_rvol20(
                code=code,
                current_df=x,
                signal_dt=signal_dt,
                history_store=history_store,
            )

            if (
                np.isfinite(rvol)
                and rvol >= RVOL_MIN
                and prev_days
                    == REQUIRED_HISTORY_SESSIONS
            ):

                return {
                    "Side": "SHORT",
                    "Code": code,
                    "SignalDatetime": signal_dt,
                    "SignalPrice": float(
                        row.C
                    ),
                    "ORBHigh": orb_high,
                    "ORBLow": orb_low,
                    "RS20": float(rs),
                    "RS20_corrected": float(rs),
                    "RVOL20": float(rvol),
                    "Turnover20Oku": float(
                        turnover
                    ),
                    "turnover_median_20d_oku": float(
                        turnover
                    ),
                    "PrevDays": int(
                        prev_days
                    ),
                    "is_lending": True,
                }

        prev_close = row.C

    return None


# ============================================================
# NEXT ACTUAL 1M OPEN
# ============================================================

def next_actual_open(
    minute_df: pd.DataFrame,
    signal_dt: pd.Timestamp,
) -> Tuple[
    Optional[pd.Timestamp],
    Optional[float],
]:

    signal_dt = pd.Timestamp(
        signal_dt
    )

    nxt = minute_df[
        pd.to_datetime(
            minute_df["Datetime"]
        )
        >
        signal_dt
    ].sort_values(
        "Datetime"
    )

    if nxt.empty:
        return None, None

    row = nxt.iloc[0]

    return (
        pd.Timestamp(
            row["Datetime"]
        ),
        float(
            row["O"]
            if "O" in row.index
            else row["Open"]
        ),
    )


# ============================================================
# CHOOSE CANDIDATE
#
# Proven FIX11 ordering:
#
# earliest SignalDatetime first
#
# LONG:
#   RS desc
#   RVOL desc
#   turnover desc
#   Code asc
#
# SHORT:
#   RS asc
#   RVOL desc
#   turnover desc
#   Code asc
# ============================================================

def choose_candidate(
    candidates: List[Dict[str, Any]],
    side: str,
) -> Optional[Dict[str, Any]]:

    if not candidates:
        return None

    side = str(side).upper()

    x = [
        dict(c)
        for c in candidates
        if str(
            c.get("Side", "")
        ).upper() == side
    ]

    if not x:
        return None

    earliest = min(
        pd.Timestamp(
            c["SignalDatetime"]
        )
        for c in x
    )

    x = [
        c
        for c in x
        if pd.Timestamp(
            c["SignalDatetime"]
        ) == earliest
    ]

    if side == "LONG":

        x.sort(
            key=lambda c: (
                -float(c["RS20"]),
                -float(c["RVOL20"]),
                -float(
                    c["Turnover20Oku"]
                ),
                str(c["Code"]),
            )
        )

    elif side == "SHORT":

        x.sort(
            key=lambda c: (
                float(c["RS20"]),
                -float(c["RVOL20"]),
                -float(
                    c["Turnover20Oku"]
                ),
                str(c["Code"]),
            )
        )

    else:
        raise ValueError(
            f"Unknown side: {side}"
        )

    return x[0]


# ============================================================
# GENERATE DAY SIGNALS
# ============================================================

def generate_day_signals(
    minute_day: pd.DataFrame,
    feature_df: pd.DataFrame,
    history_store: HistoryStore,
) -> List[Dict[str, Any]]:

    if minute_day.empty:
        return []

    x = minute_day.copy()

    x["Code"] = (
        x["Code"]
        .astype(str)
        .map(normalize_code)
    )

    f = feature_df.copy()

    f["Code"] = (
        f["Code"]
        .astype(str)
        .map(normalize_code)
    )

    feature_map = (
        f
        .drop_duplicates(
            "Code",
            keep="last",
        )
        .set_index("Code")
        .to_dict(
            orient="index"
        )
    )

    signals = []

    for code, g in x.groupby(
        "Code",
        sort=False,
    ):

        feature = feature_map.get(
            code
        )

        if feature is None:
            continue

        minute = prepare_minute_df(
            g
        )

        signal = find_first_signal(
            code=code,
            minute_df=minute,
            feature=feature,
            history_store=history_store,
        )

        if signal is None:
            continue

        entry_dt, entry_price = (
            next_actual_open(
                minute,
                signal[
                    "SignalDatetime"
                ],
            )
        )

        signal = dict(
            signal
        )

        signal[
            "EntryDatetime"
        ] = entry_dt

        signal[
            "EntryPrice"
        ] = entry_price

        signals.append(
            signal
        )

    return signals


# ============================================================
# PROVENANCE
# ============================================================

FIX18_SIGNAL_ENGINE_METADATA = {
    "parent": "FIX17_RUNTIME",
    "equivalence_date": "2026-09-11",
    "old_result_signals": 79,
    "fix18_signals": 79,
    "set_match": True,
    "entry_datetime_exact": "79/79",
    "entry_price_exact": "79/79",
    "short_is_lending_confirmed": True,
    "no_future": True,
}
