# ============================================================
# FIX17 INPUT UNIVERSE AUDIT
#
# 目的:
#   build_fix17_long_live_inputs() に入る前段で、
#   LONG / SHORT のどちらの銘柄が残っているか確認する。
#
# 重要:
#   ・注文しない
#   ・約定しない
#   ・paper stateを変更しない
#   ・メールしない
#   ・FIX17ロジックを変更しない
#   ・paper_trader.pyを変更しない
#
# 確認内容:
#   1. 日足feature全体のRS20分布
#   2. LONG側 RS20 >= 80 の銘柄数
#   3. SHORT側 RS20 <= 20 の銘柄数
#   4. build_fix17_long_live_inputs() 後の銘柄数
#   5. その入力集合のRS20分布
#   6. 入力集合にSHORT対象が何銘柄存在するか
# ============================================================

from pathlib import Path
import runpy
import math

import pandas as pd
import numpy as np


# ============================================================
# PATH
# ============================================================

ROOT = Path(__file__).resolve().parent

PAPER_PATH = (
    ROOT
    / "paper_trader.py"
)


if not PAPER_PATH.exists():

    raise RuntimeError(
        "paper_trader.py がありません: "
        + str(PAPER_PATH)
    )


# ============================================================
# LOAD PAPER TRADER
#
# __main__ ではロードしないため、
# daily paper tradingは実行されない。
# ============================================================

print(
    "=" * 100
)

print(
    "FIX17 INPUT UNIVERSE AUDIT"
)

print(
    "=" * 100
)


paper_ns = runpy.run_path(
    str(
        PAPER_PATH
    ),
    run_name="__fix17_input_universe_audit__",
)


# ============================================================
# FIND INPUT BUILDER
# ============================================================

builder = paper_ns.get(
    "build_fix17_long_live_inputs"
)


if builder is None:

    raise RuntimeError(
        "build_fix17_long_live_inputs() がありません"
    )


# ============================================================
# BUILD CURRENT INPUT
#
# 現在Paper Traderが実際にBridgeへ渡しているもの。
# ============================================================

print()

print(
    "Building current FIX17 inputs..."
)


(
    minute_by_code,
    feature_by_code,
) = builder()


print()

print(
    "Current minute codes :",
    len(
        minute_by_code
    ),
)

print(
    "Current feature codes:",
    len(
        feature_by_code
    ),
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


def get_rs20(
    feature
):

    if not isinstance(
        feature,
        dict,
    ):

        return None


    for key in (
        "RS20",
        "RS20_corrected",
        "rs20",
    ):

        if key in feature:

            value = feature.get(
                key
            )

            if finite(
                value
            ):

                return float(
                    value
                )

    return None


def get_turnover(
    feature
):

    if not isinstance(
        feature,
        dict,
    ):

        return None


    for key in (
        "Turnover20Oku",
        "turnover_median_20d_oku",
        "turnover",
    ):

        if key in feature:

            value = feature.get(
                key
            )

            if finite(
                value
            ):

                return float(
                    value
                )

    return None


# ============================================================
# CURRENT BRIDGE INPUT ANALYSIS
# ============================================================

rows = []


for code, feature in (
    feature_by_code.items()
):

    code = str(
        code
    )

    rs20 = get_rs20(
        feature
    )

    turnover = get_turnover(
        feature
    )


    rows.append(
        {
            "Code":
                code,

            "RS20":
                (
                    rs20
                    if rs20 is not None
                    else np.nan
                ),

            "Turnover20Oku":
                (
                    turnover
                    if turnover is not None
                    else np.nan
                ),

            "HasMinuteData":
                (
                    code
                    in
                    minute_by_code
                ),

            "LONG_RS_PASS":
                (
                    rs20 is not None
                    and
                    rs20 >= 80.0
                ),

            "SHORT_RS_PASS":
                (
                    rs20 is not None
                    and
                    rs20 <= 20.0
                ),
        }
    )


audit = pd.DataFrame(
    rows
)


# ============================================================
# BASIC COUNTS
# ============================================================

print()

print(
    "=" * 100
)

print(
    "CURRENT BRIDGE INPUT"
)

print(
    "=" * 100
)


print(
    "Feature codes:",
    len(
        audit
    ),
)


print(
    "Minute codes :",
    len(
        minute_by_code
    ),
)


if audit.empty:

    raise RuntimeError(
        "feature_by_code is empty"
    )


valid_rs = audit[
    audit[
        "RS20"
    ].notna()
]


print(
    "Valid RS20   :",
    len(
        valid_rs
    ),
)


print(
    "RS20 >= 80   :",
    int(
        audit[
            "LONG_RS_PASS"
        ].sum()
    ),
)


print(
    "RS20 <= 20   :",
    int(
        audit[
            "SHORT_RS_PASS"
        ].sum()
    ),
)


# ============================================================
# RS DISTRIBUTION
# ============================================================

print()

print(
    "-" * 100
)

print(
    "RS20 DISTRIBUTION"
)

print(
    "-" * 100
)


if not valid_rs.empty:

    print(
        "MIN   :",
        float(
            valid_rs[
                "RS20"
            ].min()
        )
    )

    print(
        "P01   :",
        float(
            valid_rs[
                "RS20"
            ].quantile(
                0.01
            )
        )
    )

    print(
        "P05   :",
        float(
            valid_rs[
                "RS20"
            ].quantile(
                0.05
            )
        )
    )

    print(
        "P10   :",
        float(
            valid_rs[
                "RS20"
            ].quantile(
                0.10
            )
        )
    )

    print(
        "P20   :",
        float(
            valid_rs[
                "RS20"
            ].quantile(
                0.20
            )
        )
    )

    print(
        "MEDIAN:",
        float(
            valid_rs[
                "RS20"
            ].median()
        )
    )

    print(
        "P80   :",
        float(
            valid_rs[
                "RS20"
            ].quantile(
                0.80
            )
        )
    )

    print(
        "P90   :",
        float(
            valid_rs[
                "RS20"
            ].quantile(
                0.90
            )
        )
    )

    print(
        "MAX   :",
        float(
            valid_rs[
                "RS20"
            ].max()
        )
    )


# ============================================================
# RS BUCKETS
# ============================================================

print()

print(
    "-" * 100
)

print(
    "RS20 BUCKETS"
)

print(
    "-" * 100
)


buckets = [
    (
        "RS <= 20",
        lambda x:
            x <= 20,
    ),

    (
        "20 < RS < 80",
        lambda x:
            (x > 20)
            &
            (x < 80),
    ),

    (
        "RS >= 80",
        lambda x:
            x >= 80,
    ),
]


for label, condition in buckets:

    if valid_rs.empty:

        count = 0

    else:

        count = int(
            condition(
                valid_rs[
                    "RS20"
                ]
            ).sum()
        )


    print(
        f"{label:<15}:",
        count,
    )


# ============================================================
# LOWEST RS20 CODES
# ============================================================

print()

print(
    "-" * 100
)

print(
    "LOWEST RS20 IN CURRENT BRIDGE INPUT"
)

print(
    "-" * 100
)


lowest = (
    audit[
        audit[
            "RS20"
        ].notna()
    ]
    .sort_values(
        "RS20",
        ascending=True,
        kind="stable",
    )
    .head(
        30
    )
)


print(
    lowest[
        [
            "Code",
            "RS20",
            "Turnover20Oku",
            "HasMinuteData",
            "SHORT_RS_PASS",
        ]
    ]
    .to_string(
        index=False
    )
)


# ============================================================
# HIGHEST RS20 CODES
# ============================================================

print()

print(
    "-" * 100
)

print(
    "HIGHEST RS20 IN CURRENT BRIDGE INPUT"
)

print(
    "-" * 100
)


highest = (
    audit[
        audit[
            "RS20"
        ].notna()
    ]
    .sort_values(
        "RS20",
        ascending=False,
        kind="stable",
    )
    .head(
        20
    )
)


print(
    highest[
        [
            "Code",
            "RS20",
            "Turnover20Oku",
            "HasMinuteData",
            "LONG_RS_PASS",
        ]
    ]
    .to_string(
        index=False
    )
)


# ============================================================
# SOURCE INSPECTION
#
# builder自体のソースを表示。
# ここでRS>=80等の事前filterが存在するかを
# 実コードから確認する。
# ============================================================

print()

print(
    "=" * 100
)

print(
    "BUILD FUNCTION SOURCE"
)

print(
    "=" * 100
)


try:

    import inspect

    source = inspect.getsource(
        builder
    )

    print(
        source
    )

except Exception as e:

    print(
        "SOURCE INSPECTION FAILED:",
        repr(
            e
        ),
    )


# ============================================================
# VERDICT
# ============================================================

short_count = int(
    audit[
        "SHORT_RS_PASS"
    ].sum()
)


long_count = int(
    audit[
        "LONG_RS_PASS"
    ].sum()
)


print()

print(
    "=" * 100
)

print(
    "AUDIT VERDICT"
)

print(
    "=" * 100
)


if (
    short_count == 0
    and
    long_count > 0
):

    print(
        "SHORT RS candidates in bridge input: ZERO"
    )

    print(
        "LONG RS candidates in bridge input :",
        long_count,
    )

    print()

    print(
        "VERDICT:"
    )

    print(
        "Current Bridge input is excluding "
        "all RS20 <= 20 SHORT candidates "
        "before SHORT signal evaluation."
    )

else:

    print(
        "SHORT RS candidates in bridge input:",
        short_count,
    )

    print(
        "LONG RS candidates in bridge input :",
        long_count,
    )

    print()

    print(
        "VERDICT:"
    )

    print(
        "SHORT-capable RS20 codes exist in "
        "the current Bridge input."
    )


# ============================================================
# SAVE
# ============================================================

output = (
    ROOT
    / "fix17_input_universe_audit.csv"
)


audit.to_csv(
    output,
    index=False,
)


print()

print(
    "CSV:",
    output
)

print(
    "=" * 100
)
