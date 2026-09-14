# ============================================================
# FIX18 DAILY FEATURE PROVIDER
#
# Purpose
# ------------------------------------------------------------
# Provide reproducible daily features for FIX18.
#
# Priority:
#
#   1. Frozen exact daily_features for target date
#   2. Build from raw Yahoo daily data using No-Future rules
#
# Features:
#
#   Return20_prev
#   turnover_median_20d_oku
#   ATR14_pct_prev
#   RS20_corrected
#
# Important:
#
#   * target date itself is never used.
#   * frozen feature files take precedence.
#   * generated feature files are never silently overwritten.
#   * caller owns raw-daily acquisition.
#   * no yfinance network call exists inside this module.
#
# This keeps historical data acquisition separate from
# deterministic feature calculation.
# ============================================================

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "Code",
    "Return20_prev",
    "turnover_median_20d_oku",
    "ATR14_pct_prev",
    "RS20_corrected",
]


# ============================================================
# CODE NORMALIZATION
# ============================================================

def normalize_code(value) -> str:

    s = str(value).strip()

    if s.endswith(".T"):
        s = s[:-2]

    if (
        s.endswith(".0")
        and
        s[:-2].isdigit()
    ):
        s = s[:-2]

    # FIX18 common normalization:
    #
    #   72030 -> 7203
    #   130A0 -> 130A
    #
    # while codes such as 25935 / 94346 remain unchanged.
    if (
        len(s) == 5
        and
        s.endswith("0")
    ):
        s = s[:-1]

    return s


# ============================================================
# HASH
# ============================================================

def sha256_file(path) -> str:

    p = Path(path)

    h = hashlib.sha256()

    with p.open("rb") as f:

        while True:

            block = f.read(
                1024 * 1024
            )

            if not block:
                break

            h.update(block)

    return h.hexdigest()


# ============================================================
# INPUT NORMALIZATION
# ============================================================

def normalize_raw_daily(
    raw_daily: pd.DataFrame,
) -> pd.DataFrame:
    """
    Normalize raw Yahoo-style daily data.

    Required logical fields:

        Date
        Code
        Open
        High
        Low
        Close
        Adj Close
        Volume

    Accepted aliases include:
        O/H/L/C
        AdjClose
        Vo/V
    """

    if not isinstance(
        raw_daily,
        pd.DataFrame,
    ):
        raise TypeError(
            "raw_daily must be DataFrame"
        )

    if raw_daily.empty:
        raise ValueError(
            "raw_daily is empty"
        )

    df = raw_daily.copy()


    aliases = {

        "Date": [
            "Date",
            "Datetime",
        ],

        "Code": [
            "Code",
            "Ticker",
        ],

        "Open": [
            "Open",
            "O",
        ],

        "High": [
            "High",
            "H",
        ],

        "Low": [
            "Low",
            "L",
        ],

        "Close": [
            "Close",
            "C",
        ],

        "Adj Close": [
            "Adj Close",
            "AdjClose",
        ],

        "Volume": [
            "Volume",
            "Vo",
            "V",
        ],
    }


    resolved = {}

    for logical, candidates in aliases.items():

        found = None

        for c in candidates:

            if c in df.columns:

                found = c
                break

        if found is None:

            raise ValueError(
                f"raw_daily missing field: "
                f"{logical}"
            )

        resolved[
            logical
        ] = found


    out = pd.DataFrame()


    out["Date"] = pd.to_datetime(
        df[
            resolved["Date"]
        ],
        errors="coerce",
    ).dt.normalize()


    out["Code"] = (
        df[
            resolved["Code"]
        ]
        .map(
            normalize_code
        )
    )


    for logical in [
        "Open",
        "High",
        "Low",
        "Close",
        "Adj Close",
        "Volume",
    ]:

        out[
            logical
        ] = pd.to_numeric(
            df[
                resolved[
                    logical
                ]
            ],
            errors="coerce",
        )


    out = out[
        out["Date"].notna()
        &
        out["Code"].notna()
        &
        out["Open"].notna()
        &
        out["High"].notna()
        &
        out["Low"].notna()
        &
        out["Close"].notna()
        &
        out["Adj Close"].notna()
        &
        out["Volume"].notna()
    ].copy()


    out = (
        out
        .drop_duplicates(
            subset=[
                "Date",
                "Code",
            ],
            keep="last",
        )
        .sort_values(
            [
                "Code",
                "Date",
            ]
        )
        .reset_index(
            drop=True
        )
    )


    return out


# ============================================================
# BUILD DAILY FEATURES
# ============================================================

def build_daily_features(
    raw_daily: pd.DataFrame,
    target_date,
    *,
    lending_map: Optional[
        Mapping[str, bool]
    ] = None,
) -> pd.DataFrame:
    """
    Reconstruct FIX11/FIX17-style daily features.

    Strict No-Future:
        only Date < target_date is used.

    Formula:
        Return20_prev
            = AdjClose.pct_change(20) * 100

        turnover_median_20d_oku
            = median(last20 raw Close * raw Volume / 1e8)

        adjusted OHLC
            = raw OHLC * (AdjClose / raw Close)

        TR
            = max(
                AdjHigh - AdjLow,
                abs(AdjHigh - PrevAdjClose),
                abs(AdjLow - PrevAdjClose),
              )

        ATR14
            = rolling mean(TR, 14)

        ATR14_pct_prev
            = ATR14 / AdjClose * 100

        RS20_corrected
            = cross-sectional percentile rank
              of Return20_prev
              using method="average"
              multiplied by 100.
    """

    target = pd.Timestamp(
        target_date
    ).normalize()


    df = normalize_raw_daily(
        raw_daily
    )


    # --------------------------------------------------------
    # NO FUTURE
    # --------------------------------------------------------

    df = df[
        df["Date"]
        <
        target
    ].copy()


    if df.empty:

        raise ValueError(
            "No rows before target_date"
        )


    # --------------------------------------------------------
    # Adjusted OHLC
    # --------------------------------------------------------

    safe_close = (
        df["Close"]
        .replace(
            0,
            np.nan,
        )
    )


    df[
        "_AdjFactor"
    ] = (
        df["Adj Close"]
        /
        safe_close
    )


    df[
        "_AdjOpen"
    ] = (
        df["Open"]
        *
        df["_AdjFactor"]
    )


    df[
        "_AdjHigh"
    ] = (
        df["High"]
        *
        df["_AdjFactor"]
    )


    df[
        "_AdjLow"
    ] = (
        df["Low"]
        *
        df["_AdjFactor"]
    )


    df[
        "_AdjClose"
    ] = (
        df["Adj Close"]
    )


    # --------------------------------------------------------
    # PER CODE
    # --------------------------------------------------------

    pieces = []


    for code, g in df.groupby(
        "Code",
        sort=False,
    ):

        g = g.sort_values(
            "Date"
        ).copy()


        # Return20 is percentage-point representation.
        g[
            "_Return20"
        ] = (
            g[
                "_AdjClose"
            ]
            .pct_change(
                periods=20
            )
            *
            100.0
        )


        g[
            "_PrevAdjClose"
        ] = (
            g[
                "_AdjClose"
            ]
            .shift(1)
        )


        tr1 = (
            g["_AdjHigh"]
            -
            g["_AdjLow"]
        ).abs()


        tr2 = (
            g["_AdjHigh"]
            -
            g["_PrevAdjClose"]
        ).abs()


        tr3 = (
            g["_AdjLow"]
            -
            g["_PrevAdjClose"]
        ).abs()


        g[
            "_TR"
        ] = pd.concat(
            [
                tr1,
                tr2,
                tr3,
            ],
            axis=1,
        ).max(
            axis=1
        )


        g[
            "_ATR14"
        ] = (
            g["_TR"]
            .rolling(
                window=14,
                min_periods=14,
            )
            .mean()
        )


        g[
            "_ATR14_pct"
        ] = (
            g["_ATR14"]
            /
            g["_AdjClose"]
            *
            100.0
        )


        g[
            "_TurnoverOku"
        ] = (
            g["Close"]
            *
            g["Volume"]
            /
            1e8
        )


        latest = g.iloc[-1]


        # Historical producer needs at least 21 observations
        # for Return20 and at least 20 for turnover median.
        if len(g) < 21:
            continue


        return20 = latest[
            "_Return20"
        ]


        atr_pct = latest[
            "_ATR14_pct"
        ]


        if (
            pd.isna(return20)
            or
            pd.isna(atr_pct)
        ):
            continue


        turnover20 = (
            g[
                "_TurnoverOku"
            ]
            .tail(20)
        )


        if len(
            turnover20
        ) != 20:
            continue


        pieces.append(
            {
                "Code":
                    code,

                "Return20_prev":
                    float(
                        return20
                    ),

                "turnover_median_20d_oku":
                    float(
                        turnover20.median()
                    ),

                "ATR14_pct_prev":
                    float(
                        atr_pct
                    ),
            }
        )


    features = pd.DataFrame(
        pieces
    )


    if features.empty:

        return pd.DataFrame(
            columns=(
                FEATURE_COLUMNS
                +
                (
                    ["is_lending"]
                    if lending_map is not None
                    else []
                )
            )
        )


    # --------------------------------------------------------
    # RS20
    # --------------------------------------------------------

    features[
        "RS20_corrected"
    ] = (
        features[
            "Return20_prev"
        ]
        .rank(
            pct=True,
            method="average",
        )
        *
        100.0
    )


    # --------------------------------------------------------
    # Lending
    #
    # Never invent lending eligibility.
    # --------------------------------------------------------

    if lending_map is not None:

        normalized_lending = {
            normalize_code(k):
                bool(v)
            for k, v
            in lending_map.items()
        }


        features[
            "is_lending"
        ] = (
            features["Code"]
            .map(
                normalized_lending
            )
        )


    features = (
        features
        .sort_values(
            "Code"
        )
        .reset_index(
            drop=True
        )
    )


    return features


# ============================================================
# FROZEN FEATURE STORE
# ============================================================

@dataclass(
    frozen=True
)
class FeatureLoadResult:

    target_date: str

    source: str

    path: Optional[str]

    sha256: Optional[str]

    rows: int

    dataframe: pd.DataFrame


def frozen_feature_path(
    frozen_root,
    target_date,
) -> Path:

    target = pd.Timestamp(
        target_date
    ).normalize()

    root = Path(
        frozen_root
    )

    return (
        root
        /
        f"{target.date()}.parquet"
    )


def load_frozen_features(
    frozen_root,
    target_date,
) -> Optional[
    FeatureLoadResult
]:

    path = frozen_feature_path(
        frozen_root,
        target_date,
    )


    if not path.exists():

        return None


    df = pd.read_parquet(
        path
    )


    required = set(
        FEATURE_COLUMNS
    )


    missing = (
        required
        -
        set(df.columns)
    )


    if missing:

        raise RuntimeError(
            f"Frozen feature file missing columns: "
            f"{sorted(missing)}"
        )


    df = df.copy()

    df[
        "Code"
    ] = (
        df["Code"]
        .map(
            normalize_code
        )
    )


    return FeatureLoadResult(
        target_date=str(
            pd.Timestamp(
                target_date
            ).date()
        ),
        source="FROZEN",
        path=str(path),
        sha256=sha256_file(
            path
        ),
        rows=len(df),
        dataframe=df,
    )


def freeze_features(
    features: pd.DataFrame,
    frozen_root,
    target_date,
    *,
    overwrite: bool = False,
) -> FeatureLoadResult:

    target = pd.Timestamp(
        target_date
    ).normalize()


    path = frozen_feature_path(
        frozen_root,
        target,
    )


    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    if (
        path.exists()
        and
        not overwrite
    ):

        raise FileExistsError(
            f"Frozen feature already exists: "
            f"{path}"
        )


    df = features.copy()


    required = set(
        FEATURE_COLUMNS
    )


    missing = (
        required
        -
        set(df.columns)
    )


    if missing:

        raise ValueError(
            f"features missing columns: "
            f"{sorted(missing)}"
        )


    df[
        "Code"
    ] = (
        df["Code"]
        .map(
            normalize_code
        )
    )


    df = (
        df
        .sort_values(
            "Code"
        )
        .reset_index(
            drop=True
        )
    )


    tmp = path.with_suffix(
        ".tmp.parquet"
    )


    df.to_parquet(
        tmp,
        index=False,
    )


    if path.exists():

        path.unlink()


    tmp.replace(
        path
    )


    digest = sha256_file(
        path
    )


    manifest = {

        "target_date":
            str(
                target.date()
            ),

        "rows":
            int(
                len(df)
            ),

        "sha256":
            digest,

        "file":
            path.name,

        "columns":
            list(
                df.columns
            ),
    }


    manifest_path = (
        path.with_suffix(
            ".manifest.json"
        )
    )


    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


    return FeatureLoadResult(
        target_date=str(
            target.date()
        ),
        source="GENERATED_FROZEN",
        path=str(path),
        sha256=digest,
        rows=len(df),
        dataframe=df,
    )


# ============================================================
# PROVIDER
# ============================================================

def get_daily_features(
    target_date,
    *,
    frozen_root,
    raw_daily: Optional[
        pd.DataFrame
    ] = None,
    lending_map: Optional[
        Mapping[str, bool]
    ] = None,
    freeze_generated: bool = True,
) -> FeatureLoadResult:
    """
    Main FIX18 feature-provider interface.

    Priority:
        1. exact frozen target-date features
        2. deterministic generation from supplied raw_daily

    No network request is performed here.
    """

    existing = load_frozen_features(
        frozen_root,
        target_date,
    )


    if existing is not None:

        return existing


    if raw_daily is None:

        raise FileNotFoundError(
            "No frozen feature for target_date and "
            "raw_daily was not supplied."
        )


    features = build_daily_features(
        raw_daily,
        target_date,
        lending_map=lending_map,
    )


    if freeze_generated:

        return freeze_features(
            features,
            frozen_root,
            target_date,
            overwrite=False,
        )


    return FeatureLoadResult(
        target_date=str(
            pd.Timestamp(
                target_date
            ).date()
        ),
        source="GENERATED_MEMORY",
        path=None,
        sha256=None,
        rows=len(features),
        dataframe=features,
    )
