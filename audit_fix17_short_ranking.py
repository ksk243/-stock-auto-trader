# ============================================================
# FIX17 SHORT RANKING / AFFORDABILITY AUDIT
#
# 目的:
#   現在のFIX17/FIX11ロジックを変更せず、
#   SHORTシグナル全件を取得して順位と発注可能性を確認する。
#
# 確認:
#   - SHORTシグナル全件
#   - 正式候補選択に使われる値
#   - EntryPrice
#   - 100株必要額
#   - SHORT 0.5倍枠
#   - 100株発注可能か
#
# 注文しない
# state変更しない
# メールしない
# ============================================================

from pathlib import Path
import runpy
import math
import pandas as pd


ROOT = Path(__file__).resolve().parent

PAPER = ROOT / "paper_trader.py"
BRIDGE = ROOT / "fix17_long_candidate_bridge.py"


# ============================================================
# CHECK
# ============================================================

for p in [PAPER, BRIDGE]:

    if not p.exists():

        raise RuntimeError(
            f"missing: {p}"
        )


print("=" * 110)
print("FIX17 SHORT RANKING / AFFORDABILITY AUDIT")
print("=" * 110)


# ============================================================
# LOAD CURRENT PAPER
# ============================================================

paper_ns = runpy.run_path(
    str(PAPER),
    run_name="__fix17_short_ranking_paper__",
)


builder = paper_ns.get(
    "build_fix17_long_live_inputs"
)

if builder is None:

    raise RuntimeError(
        "build_fix17_long_live_inputs() missing"
    )


# ============================================================
# BUILD EXACT CURRENT INPUT
# ============================================================

(
    minute_by_code,
    feature_by_code,
) = builder()


print()
print(
    "Bridge input codes:",
    len(minute_by_code),
)


# ============================================================
# LOAD CURRENT FAST BRIDGE / FIX11
# ============================================================

bridge_ns = runpy.run_path(
    str(BRIDGE),
    run_name="__fix17_short_ranking_bridge__",
)


loader = bridge_ns.get(
    "_load_fix11_entry_namespace"
)

if loader is None:

    raise RuntimeError(
        "_load_fix11_entry_namespace() missing"
    )


ns = loader()


find_first_signal = ns.get(
    "find_first_signal"
)

choose_candidate = ns.get(
    "choose_candidate"
)


if find_first_signal is None:

    raise RuntimeError(
        "find_first_signal() missing"
    )


if choose_candidate is None:

    raise RuntimeError(
        "choose_candidate() missing"
    )


# ============================================================
# GET ALL SHORT SIGNALS
# ============================================================

short_signals = []


for code, minute_df in minute_by_code.items():

    code = str(code)

    feature = feature_by_code.get(
        code
    )

    if feature is None:
        continue


    signal = find_first_signal(
        code,
        minute_df,
        feature,
    )


    if not signal:
        continue


    side = str(
        signal.get(
            "Side",
            ""
        )
    ).upper()


    if side == "SHORT":

        short_signals.append(
            signal
        )


print()
print(
    "SHORT signals:",
    len(short_signals),
)


if not short_signals:

    print("SHORT signal NONE")
    raise SystemExit(0)


# ============================================================
# CONFIRM OFFICIAL SELECTED CANDIDATE
# ============================================================

official_selected = choose_candidate(
    short_signals,
    "SHORT",
)


official_code = None

if official_selected:

    official_code = str(
        official_selected.get(
            "Code",
            ""
        )
    )


print(
    "Official selected SHORT:",
    official_code,
)


# ============================================================
# CURRENT CAPITAL / SHORT LEVERAGE
# ============================================================

INITIAL_CASH = float(
    paper_ns.get(
        "INITIAL_CASH",
        1117792.0,
    )
)


SHORT_LEVERAGE = float(
    paper_ns.get(
        "SHORT_LEVERAGE",
        0.5,
    )
)


LOT_SIZE = int(
    paper_ns.get(
        "LOT_SIZE",
        100,
    )
)


short_capacity = (
    INITIAL_CASH
    *
    SHORT_LEVERAGE
)


print()
print(
    "Capital basis   :",
    f"{INITIAL_CASH:,.0f} yen",
)

print(
    "SHORT leverage  :",
    SHORT_LEVERAGE,
)

print(
    "SHORT capacity  :",
    f"{short_capacity:,.0f} yen",
)

print(
    "Lot size        :",
    LOT_SIZE,
)


# ============================================================
# HELPERS
# ============================================================

def finite(v):

    try:

        return math.isfinite(
            float(v)
        )

    except Exception:

        return False


def formal_entry_after_signal(
    minute_df,
    signal_datetime,
):

    if minute_df is None:
        return None, None

    if len(minute_df) == 0:
        return None, None


    x = minute_df.copy()


    if "Datetime" not in x.columns:
        return None, None


    x["Datetime"] = pd.to_datetime(
        x["Datetime"],
        errors="coerce",
    )


    x = x[
        x["Datetime"].notna()
    ].copy()


    if x.empty:
        return None, None


    x = x.sort_values(
        "Datetime",
        kind="stable",
    )


    signal_dt = pd.to_datetime(
        signal_datetime,
        errors="coerce",
    )


    if pd.isna(signal_dt):
        return None, None


    nxt = x[
        x["Datetime"]
        >
        signal_dt
    ]


    if nxt.empty:
        return None, None


    row = nxt.iloc[0]


    if "O" in row.index:

        price = row["O"]

    elif "Open" in row.index:

        price = row["Open"]

    else:

        return None, None


    if not finite(price):
        return None, None


    return (
        float(price),
        row["Datetime"],
    )


# ============================================================
# BUILD AUDIT ROWS
# ============================================================

rows = []


for signal in short_signals:

    code = str(
        signal.get(
            "Code",
            ""
        )
    )


    signal_dt = signal.get(
        "SignalDatetime"
    )


    signal_price = signal.get(
        "SignalPrice"
    )


    rs20 = signal.get(
        "RS20"
    )


    rvol20 = signal.get(
        "RVOL20"
    )


    turnover = signal.get(
        "Turnover20Oku"
    )


    minute_df = minute_by_code.get(
        code
    )


    (
        entry_price,
        entry_dt,
    ) = formal_entry_after_signal(
        minute_df,
        signal_dt,
    )


    if (
        entry_price is not None
        and
        entry_price > 0
    ):

        one_lot_notional = (
            entry_price
            *
            LOT_SIZE
        )


        max_qty = (
            math.floor(
                short_capacity
                /
                entry_price
                /
                LOT_SIZE
            )
            *
            LOT_SIZE
        )

    else:

        one_lot_notional = None

        max_qty = 0


    affordable = (
        max_qty
        >=
        LOT_SIZE
    )


    rows.append(
        {
            "Code":
                code,

            "OfficialSelected":
                (
                    code
                    ==
                    official_code
                ),

            "SignalDatetime":
                signal_dt,

            "SignalPrice":
                signal_price,

            "EntryDatetime":
                entry_dt,

            "EntryPrice":
                entry_price,

            "RS20":
                rs20,

            "RVOL20":
                rvol20,

            "Turnover20Oku":
                turnover,

            "OneLotNotional":
                one_lot_notional,

            "ShortCapacity":
                short_capacity,

            "MaxQty":
                max_qty,

            "CanTrade100":
                affordable,
        }
    )


df = pd.DataFrame(
    rows
)


# ============================================================
# FIND OFFICIAL RANKING
#
# choose_candidate() only exposes the winner.
#
# Therefore determine each rank by repeatedly asking the
# SAME official selector, then removing only that selected
# signal from the remaining list.
#
# This avoids recreating the ranking formula.
# ============================================================

remaining = list(
    short_signals
)

ranking = []


while remaining:

    selected = choose_candidate(
        remaining,
        "SHORT",
    )


    if not selected:
        break


    selected_code = str(
        selected.get(
            "Code",
            ""
        )
    )


    ranking.append(
        selected_code
    )


    removed = False

    next_remaining = []


    for sig in remaining:

        sig_code = str(
            sig.get(
                "Code",
                ""
            )
        )


        if (
            not removed
            and
            sig_code
            ==
            selected_code
        ):

            removed = True
            continue


        next_remaining.append(
            sig
        )


    if not removed:

        raise RuntimeError(
            "Could not remove selected signal "
            + selected_code
        )


    remaining = next_remaining


rank_map = {
    code: rank
    for rank, code
    in enumerate(
        ranking,
        start=1,
    )
}


df["OfficialRank"] = (
    df["Code"]
    .map(
        rank_map
    )
)


df = df.sort_values(
    "OfficialRank",
    ascending=True,
    kind="stable",
)


# ============================================================
# RESULT
# ============================================================

print()
print("=" * 110)
print("SHORT OFFICIAL RANKING")
print("=" * 110)


display_cols = [
    "OfficialRank",
    "Code",
    "OfficialSelected",
    "RS20",
    "RVOL20",
    "SignalDatetime",
    "SignalPrice",
    "EntryDatetime",
    "EntryPrice",
    "OneLotNotional",
    "ShortCapacity",
    "MaxQty",
    "CanTrade100",
]


print(
    df[
        display_cols
    ].to_string(
        index=False
    )
)


# ============================================================
# AFFORDABLE NEXT CANDIDATE
# ============================================================

affordable_df = df[
    df[
        "CanTrade100"
    ]
].copy()


print()
print("=" * 110)
print("AFFORDABILITY RESULT")
print("=" * 110)


first = df.iloc[0]


print(
    "Rank #1:",
    first[
        "Code"
    ],
)

print(
    "Rank #1 entry:",
    (
        f'{first["EntryPrice"]:,.2f}'
        if pd.notna(
            first["EntryPrice"]
        )
        else "N/A"
    ),
)

print(
    "Rank #1 100-share notional:",
    (
        f'{first["OneLotNotional"]:,.0f}'
        if pd.notna(
            first["OneLotNotional"]
        )
        else "N/A"
    ),
)

print(
    "Rank #1 tradable:",
    bool(
        first[
            "CanTrade100"
        ]
    ),
)


if affordable_df.empty:

    print()
    print(
        "No SHORT signal can trade even one lot "
        "within the current 0.5x capacity."
    )

else:

    next_row = (
        affordable_df
        .iloc[0]
    )


    print()
    print(
        "Highest-ranked tradable SHORT:"
    )

    print(
        "Rank :",
        int(
            next_row[
                "OfficialRank"
            ]
        ),
    )

    print(
        "Code :",
        next_row[
            "Code"
        ],
    )

    print(
        "Entry:",
        f'{next_row["EntryPrice"]:,.2f}',
    )

    print(
        "100 shares:",
        f'{next_row["OneLotNotional"]:,.0f}',
    )

    print(
        "MaxQty:",
        int(
            next_row[
                "MaxQty"
            ]
        ),
    )


# ============================================================
# SAVE
# ============================================================

output = (
    ROOT
    / "fix17_short_ranking_audit.csv"
)


df.to_csv(
    output,
    index=False,
)


print()
print(
    "CSV:",
    output
)

print("=" * 110)
print("AUDIT COMPLETE")
print("=" * 110)
