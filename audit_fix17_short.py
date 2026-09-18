# ============================================================
# FIX17 SHORT AUDIT
#
# PURPOSE
#   Audit SHORT signal flow using the CURRENT repository code.
#
# IMPORTANT
#   - NO order
#   - NO fill
#   - NO paper-state modification
#   - NO mail
#   - NO FIX17 logic modification
#   - Uses existing paper_trader.py input builder
#   - Uses existing FAST FIX17 bridge
#   - Uses existing FIX11 find_first_signal()
#
# OUTPUT
#   Number of:
#     scanned codes
#     RS20 <= SHORT threshold
#     RVOL20 >= threshold
#     ORB15 low crosses
#     RS + RVOL + cross
#     official FIX11 SHORT signals
# ============================================================

from pathlib import Path
import runpy
import math

import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parent

PAPER_PATH = (
    ROOT
    / "paper_trader.py"
)

BRIDGE_PATH = (
    ROOT
    / "fix17_long_candidate_bridge.py"
)

FIX11_PATH = (
    ROOT
    / ".github"
    / "workflows"
    / "fix11_paper_trader.py"
)


# ============================================================
# FILE CHECK
# ============================================================

required = [
    PAPER_PATH,
    BRIDGE_PATH,
    FIX11_PATH,
]

missing = [
    str(p)
    for p in required
    if not p.exists()
]

if missing:

    print(
        "Required files missing:"
    )

    for p in missing:
        print(
            " ",
            p,
        )

    raise RuntimeError(
        "FIX17 SHORT AUDIT required source missing"
    )


print(
    "=" * 100
)

print(
    "FIX17 SHORT SIGNAL AUDIT"
)

print(
    "=" * 100
)

print(
    "Paper :",
    PAPER_PATH,
)

print(
    "Bridge:",
    BRIDGE_PATH,
)

print(
    "FIX11 :",
    FIX11_PATH,
)


# ============================================================
# LOAD PAPER TRADER
#
# run_name is NOT __main__, so daily trading execution
# must not start.
# ============================================================

paper_ns = runpy.run_path(
    str(
        PAPER_PATH
    ),
    run_name="__fix17_short_audit_paper__",
)


builder = paper_ns.get(
    "build_fix17_long_live_inputs"
)

if builder is None:

    raise RuntimeError(
        "build_fix17_long_live_inputs() missing"
    )


# ============================================================
# BUILD SAME FIX17 LIVE INPUT
# ============================================================

print()

print(
    "Building FIX17 live inputs..."
)

(
    minute_by_code,
    feature_by_code,
) = builder()


print(
    "minute codes :",
    len(
        minute_by_code
    ),
)

print(
    "feature codes:",
    len(
        feature_by_code
    ),
)


if not minute_by_code:

    raise RuntimeError(
        "minute_by_code is empty"
    )


# ============================================================
# LOAD CURRENT FAST BRIDGE
# ============================================================

bridge_ns = runpy.run_path(
    str(
        BRIDGE_PATH
    ),
    run_name="__fix17_short_audit_bridge__",
)


loader = bridge_ns.get(
    "_load_fix11_entry_namespace"
)

if loader is None:

    raise RuntimeError(
        "_load_fix11_entry_namespace() missing"
    )


# This gives us the SAME FIX11 namespace
# with the SAME fast RVOL implementation
# currently used by the paper trader.

fix11_ns = loader()


find_first_signal = (
    fix11_ns.get(
        "find_first_signal"
    )
)

calc_rvol20 = (
    fix11_ns.get(
        "calc_rvol20"
    )
)


if find_first_signal is None:

    raise RuntimeError(
        "find_first_signal() missing"
    )


if calc_rvol20 is None:

    raise RuntimeError(
        "calc_rvol20() missing"
    )


# ============================================================
# READ CURRENT FIX11 THRESHOLDS
# ============================================================

RS_SHORT_MAX = (
    fix11_ns.get(
        "RS_SHORT_MAX",
        20.0,
    )
)

RVOL_MIN = (
    fix11_ns.get(
        "RVOL_MIN",
        2.0,
    )
)


RS_SHORT_MAX = float(
    RS_SHORT_MAX
)

RVOL_MIN = float(
    RVOL_MIN
)


print()

print(
    "RS_SHORT_MAX:",
    RS_SHORT_MAX,
)

print(
    "RVOL_MIN    :",
    RVOL_MIN,
)


# ============================================================
# HELPERS
# ============================================================

def finite(v):

    try:

        return math.isfinite(
            float(
                v
            )
        )

    except Exception:

        return False


def get_feature(
    feature,
    *names,
):

    if not isinstance(
        feature,
        dict,
    ):

        return None

    for name in names:

        if name in feature:

            value = feature.get(
                name
            )

            if value is not None:

                return value

    return None


def normalize_minute(
    minute_df,
):

    if minute_df is None:

        return None

    if len(
        minute_df
    ) == 0:

        return None

    x = minute_df.copy()

    if "Datetime" not in x.columns:

        return None

    x[
        "Datetime"
    ] = pd.to_datetime(
        x[
            "Datetime"
        ],
        errors="coerce",
    )

    x = x[
        x[
            "Datetime"
        ].notna()
    ].copy()

    if x.empty:

        return None

    x = x.sort_values(
        "Datetime",
        kind="stable",
    )

    return x


def get_close_column(
    x,
):

    if "C" in x.columns:

        return "C"

    if "Close" in x.columns:

        return "Close"

    return None


def get_low_column(
    x,
):

    if "L" in x.columns:

        return "L"

    if "Low" in x.columns:

        return "Low"

    return None


# ============================================================
# ORB15 LOW
# ============================================================

def calculate_orb15_low(
    minute_df,
):

    x = normalize_minute(
        minute_df
    )

    if x is None:

        return None

    low_col = get_low_column(
        x
    )

    if low_col is None:

        return None

    times = (
        x[
            "Datetime"
        ]
        .dt.strftime(
            "%H:%M"
        )
    )

    # Opening 15 minutes:
    # 09:00 through 09:14.

    orb = x[
        (times >= "09:00")
        &
        (times <= "09:14")
    ]

    if orb.empty:

        return None

    low = pd.to_numeric(
        orb[
            low_col
        ],
        errors="coerce",
    ).min()

    if not finite(
        low
    ):

        return None

    return float(
        low
    )


# ============================================================
# AUDIT
# ============================================================

rows = []

official_short_signals = []


for code, minute_df in (
    minute_by_code.items()
):

    code = str(
        code
    )

    feature = (
        feature_by_code.get(
            code
        )
    )

    if feature is None:

        continue


    # ========================================================
    # RS20
    # ========================================================

    rs20 = get_feature(
        feature,
        "RS20",
        "RS20_corrected",
        "rs20",
    )


    rs_pass = (
        finite(
            rs20
        )
        and
        float(
            rs20
        )
        <=
        RS_SHORT_MAX
    )


    # ========================================================
    # ORB15
    # ========================================================

    orb_low = (
        calculate_orb15_low(
            minute_df
        )
    )


    x = normalize_minute(
        minute_df
    )


    max_rvol = np.nan

    rvol_pass = False

    short_cross = False

    rs_rvol_cross = False

    first_cross_datetime = None

    first_cross_close = None

    first_ready_datetime = None


    # ========================================================
    # DIAGNOSTIC INTRADAY SCAN
    # ========================================================

    if (
        x is not None
        and
        orb_low is not None
    ):

        close_col = (
            get_close_column(
                x
            )
        )

        if close_col is not None:

            prev_close = None

            for _, bar in (
                x.iterrows()
            ):

                dt = bar[
                    "Datetime"
                ]

                time_text = (
                    dt.strftime(
                        "%H:%M"
                    )
                )

                # ORB must already be complete.

                if time_text < "09:15":

                    continue


                try:

                    close = float(
                        bar[
                            close_col
                        ]
                    )

                except Exception:

                    continue


                if not finite(
                    close
                ):

                    continue


                # ============================================
                # SAME FAST RVOL20 USED BY CURRENT BRIDGE
                # ============================================

                try:

                    result = (
                        calc_rvol20(
                            code,
                            minute_df,
                            dt,
                        )
                    )

                    if isinstance(
                        result,
                        tuple,
                    ):

                        rvol = (
                            result[
                                0
                            ]
                        )

                        prev_days = (
                            result[
                                1
                            ]
                            if len(
                                result
                            ) > 1
                            else None
                        )

                    else:

                        rvol = result

                        prev_days = None

                except Exception:

                    rvol = np.nan

                    prev_days = None


                if finite(
                    rvol
                ):

                    if (
                        not finite(
                            max_rvol
                        )
                        or
                        float(
                            rvol
                        )
                        >
                        float(
                            max_rvol
                        )
                    ):

                        max_rvol = float(
                            rvol
                        )


                    if (
                        float(
                            rvol
                        )
                        >=
                        RVOL_MIN
                    ):

                        rvol_pass = True


                # ============================================
                # SHORT ORB CROSS
                #
                # Previous close >= ORB low
                # Current close  < ORB low
                # ============================================

                cross_now = False


                if (
                    prev_close is not None
                    and
                    finite(
                        prev_close
                    )
                ):

                    cross_now = (
                        float(
                            prev_close
                        )
                        >=
                        float(
                            orb_low
                        )
                        and
                        float(
                            close
                        )
                        <
                        float(
                            orb_low
                        )
                    )


                if cross_now:

                    short_cross = True


                    if (
                        first_cross_datetime
                        is None
                    ):

                        first_cross_datetime = (
                            dt
                        )

                        first_cross_close = (
                            close
                        )


                    if (
                        rs_pass
                        and
                        finite(
                            rvol
                        )
                        and
                        float(
                            rvol
                        )
                        >=
                        RVOL_MIN
                    ):

                        rs_rvol_cross = True


                        if (
                            first_ready_datetime
                            is None
                        ):

                            first_ready_datetime = (
                                dt
                            )


                prev_close = close


    # ========================================================
    # OFFICIAL FIX11 RESULT
    #
    # This is the authoritative final signal result.
    # ========================================================

    official_signal = None


    try:

        official_signal = (
            find_first_signal(
                code,
                minute_df,
                feature,
            )
        )

    except TypeError:

        # Compatibility only.
        try:

            official_signal = (
                find_first_signal(
                    code,
                    minute_df,
                )
            )

        except Exception:

            official_signal = None

    except Exception:

        official_signal = None


    official_side = ""


    if isinstance(
        official_signal,
        dict,
    ):

        official_side = str(
            official_signal.get(
                "Side",
                official_signal.get(
                    "side",
                    "",
                ),
            )
        ).upper()


    official_short = (
        official_side
        ==
        "SHORT"
    )


    if official_short:

        official_short_signals.append(
            official_signal
        )


    rows.append(
        {
            "Code":
                code,

            "RS20":
                (
                    float(
                        rs20
                    )
                    if finite(
                        rs20
                    )
                    else np.nan
                ),

            "RS_PASS":
                bool(
                    rs_pass
                ),

            "ORBLow":
                orb_low,

            "MaxRVOL20":
                max_rvol,

            "RVOL_PASS":
                bool(
                    rvol_pass
                ),

            "SHORT_CROSS":
                bool(
                    short_cross
                ),

            "RS_RVOL_CROSS":
                bool(
                    rs_rvol_cross
                ),

            "FirstCrossDatetime":
                first_cross_datetime,

            "FirstCrossClose":
                first_cross_close,

            "FirstReadyDatetime":
                first_ready_datetime,

            "OfficialSide":
                official_side,

            "OFFICIAL_SHORT":
                bool(
                    official_short
                ),
        }
    )


# ============================================================
# DATAFRAME
# ============================================================

audit = pd.DataFrame(
    rows
)


# ============================================================
# RESULT
# ============================================================

print()

print(
    "=" * 100
)

print(
    "FIX17 SHORT AUDIT RESULT"
)

print(
    "=" * 100
)


print(
    "Audited codes      :",
    len(
        audit
    ),
)


print(
    f"RS20 <= {RS_SHORT_MAX:g}      :",
    int(
        audit[
            "RS_PASS"
        ].sum()
    ),
)


print(
    f"RVOL20 >= {RVOL_MIN:g}     :",
    int(
        audit[
            "RVOL_PASS"
        ].sum()
    ),
)


print(
    "ORB15 Low cross    :",
    int(
        audit[
            "SHORT_CROSS"
        ].sum()
    ),
)


print(
    "RS + RVOL + cross  :",
    int(
        audit[
            "RS_RVOL_CROSS"
        ].sum()
    ),
)


print(
    "OFFICIAL SHORT     :",
    int(
        audit[
            "OFFICIAL_SHORT"
        ].sum()
    ),
)


# ============================================================
# FUNNEL
# ============================================================

rs_df = audit[
    audit[
        "RS_PASS"
    ]
]


rs_rvol_df = rs_df[
    rs_df[
        "RVOL_PASS"
    ]
]


rs_rvol_cross_df = (
    rs_rvol_df[
        rs_rvol_df[
            "SHORT_CROSS"
        ]
    ]
)


print()

print(
    "-" * 100
)

print(
    "SHORT FUNNEL"
)

print(
    "-" * 100
)


print(
    "ALL               :",
    len(
        audit
    ),
)


print(
    "RS PASS           :",
    len(
        rs_df
    ),
)


print(
    "RS + RVOL PASS    :",
    len(
        rs_rvol_df
    ),
)


print(
    "RS + RVOL + CROSS :",
    len(
        rs_rvol_cross_df
    ),
)


print(
    "OFFICIAL SHORT    :",
    len(
        official_short_signals
    ),
)


# ============================================================
# NEAR MISSES
# ============================================================

print()

print(
    "-" * 100
)

print(
    "SHORT NEAR MISSES"
)

print(
    "-" * 100
)


if not audit.empty:

    near = audit.copy()


    near[
        "AuditScore"
    ] = (
        near[
            "RS_PASS"
        ].astype(
            int
        )
        +
        near[
            "RVOL_PASS"
        ].astype(
            int
        )
        +
        near[
            "SHORT_CROSS"
        ].astype(
            int
        )
    )


    near = near.sort_values(
        [
            "AuditScore",
            "RS20",
            "MaxRVOL20",
        ],
        ascending=[
            False,
            True,
            False,
        ],
        kind="stable",
    )


    display_columns = [
        "Code",
        "RS20",
        "RS_PASS",
        "MaxRVOL20",
        "RVOL_PASS",
        "ORBLow",
        "SHORT_CROSS",
        "FirstCrossDatetime",
        "FirstCrossClose",
        "OfficialSide",
    ]


    print(
        near[
            display_columns
        ]
        .head(
            30
        )
        .to_string(
            index=False
        )
    )


# ============================================================
# OFFICIAL SHORT SIGNALS
# ============================================================

print()

print(
    "-" * 100
)

print(
    "OFFICIAL SHORT SIGNALS"
)

print(
    "-" * 100
)


if not official_short_signals:

    print(
        "NONE"
    )

else:

    official_df = (
        pd.DataFrame(
            official_short_signals
        )
    )

    print(
        official_df.to_string(
            index=False
        )
    )


# ============================================================
# SAVE CSV AS ACTION ARTIFACT SOURCE
# ============================================================

output_path = (
    ROOT
    / "fix17_short_audit.csv"
)


audit.to_csv(
    output_path,
    index=False,
)


print()

print(
    "=" * 100
)

print(
    "AUDIT COMPLETE"
)

print(
    "=" * 100
)

print(
    "CSV:",
    output_path,
)
