# ============================================================
# FIX17 LONG CANDIDATE BRIDGE
#
# Source:
#   audited FIX11 live entry implementation
#
# LONG only.
# SHORT is intentionally blocked.
# ============================================================

from pathlib import Path
import runpy
import math


ROOT = Path(__file__).resolve().parents[1]

FIX11_RUNTIME_SOURCE = (
    ROOT
    / "FIX11_LIVE_SOURCE_FOR_STEP6.py"
)


def _load_fix11_entry_namespace():

    if not FIX11_RUNTIME_SOURCE.exists():

        raise RuntimeError(
            "FIX11 audited entry source missing: "
            + str(FIX11_RUNTIME_SOURCE)
        )

    ns = runpy.run_path(
        str(FIX11_RUNTIME_SOURCE),
        run_name="__fix17_long_entry_runtime__",
    )

    required = [
        "calc_rvol20",
        "find_first_signal",
        "choose_candidate",
    ]

    missing = [
        name
        for name in required
        if not callable(
            ns.get(name)
        )
    ]

    if missing:

        raise RuntimeError(
            "Missing audited FIX11 functions: "
            + ", ".join(missing)
        )

    return ns


def _finite(v):

    try:
        return math.isfinite(
            float(v)
        )
    except Exception:
        return False



# === FIX17 STEP9B FORMAL ENTRY PRICE ===

def resolve_fix17_formal_entry_price(
    minute_df,
    signal_datetime,
):
    """
    FormalEntryPrice:
    SignalDatetime より後の最初の実在1分足 Open。
    """

    import pandas as pd
    import math

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

    try:
        signal_dt = pd.Timestamp(
            signal_datetime
        )
    except Exception:
        return None, None

    nxt = x[
        x["Datetime"] > signal_dt
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

    try:
        price = float(price)
    except Exception:
        return None, None

    if (
        not math.isfinite(price)
        or price <= 0
    ):
        return None, None

    return (
        price,
        row["Datetime"],
    )

# === END FIX17 STEP9B FORMAL ENTRY PRICE ===


def convert_fix11_long_signal_to_fix17(
    signal,
    minute_df,
):

    """
    Convert an audited FIX11 LONG signal
    into the proven FIX17 candidate interface.

    Sizing is intentionally NOT decided here.
    FIX17 execution layer must derive:
        target_notional = long_remaining_capacity
    """

    if not signal:

        return None

    side = str(
        signal.get(
            "Side",
            ""
        )
    ).upper()

    if side != "LONG":
        return None

    code = str(
        signal.get(
            "Code",
            ""
        )
    ).strip()

    if not code:
        return None

    rs = signal.get(
        "RS20"
    )

    rvol = signal.get(
        "RVOL20"
    )

    turnover = signal.get(
        "Turnover20Oku"
    )

    signal_price = signal.get(
        "SignalPrice"
    )

    if not all([
        _finite(rs),
        _finite(rvol),
        _finite(turnover),
        _finite(signal_price),
    ]):
        return None

    # Proven LONG filters
    if float(rs) < 80:
        return None

    if float(rvol) < 2:
        return None

    if float(turnover) < 3:
        return None

    # find_first_signal() only returns LONG after
    # exact ORB cross condition is satisfied.
    orb_long = True
    cross_exact = True

    # Exact 20-prior-session readiness
    prev_days = signal.get(
        "PrevDays"
    )

    backtest_ready = (
        prev_days is not None
        and int(prev_days) == 20
    )

    if not backtest_ready:
        return None

    formal_entry_price, formal_entry_datetime = (
        resolve_fix17_formal_entry_price(
            minute_df,
            signal.get(
                "SignalDatetime"
            ),
        )
    )

    if formal_entry_price is None:
        return None

    return {
        "code":
            code,

        "side":
            "LONG",

        # Formal execution price is populated
        # only when the formal entry bar is known.
        # Signal close is NOT silently substituted.
        "entry_price":
            float(formal_entry_price),

        "FormalEntryPrice":
            float(formal_entry_price),

        "EntryDatetime":
            formal_entry_datetime,


        "RS20_corrected":
            float(rs),

        "RVOL20":
            float(rvol),

        "turnover_median_20d_oku":
            float(turnover),

        "ORB15_LongSignal":
            bool(orb_long),

        "CrossPass_EXACT":
            bool(cross_exact),

        "BacktestReady":
            bool(backtest_ready),

        "SignalDatetime":
            signal.get(
                "SignalDatetime"
            ),

        "SignalPrice":
            float(signal_price),

        "ORBHigh":
            signal.get(
                "ORBHigh"
            ),

        "ORBLow":
            signal.get(
                "ORBLow"
            ),

        "PrevDays":
            int(prev_days),

        # IMPORTANT:
        # target_notional is intentionally absent.
        # FIX17 sizing belongs to execution/state layer.
    }


def generate_fix17_long_candidates(
    minute_by_code,
    feature_by_code,
):

    """
    Inputs
    ------
    minute_by_code:
        dict[code] -> current 1m DataFrame

    feature_by_code:
        dict[code] -> daily feature dict

    Returns
    -------
    list of FIX17 LONG candidate dictionaries.

    No SHORT candidate is emitted.
    """

    ns = _load_fix11_entry_namespace()

    find_first_signal = ns[
        "find_first_signal"
    ]

    choose_candidate = ns[
        "choose_candidate"
    ]

    raw = []

    for code, minute_df in (
        minute_by_code.items()
    ):

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

        if (
            str(
                signal.get(
                    "Side",
                    ""
                )
            ).upper()
            !=
            "LONG"
        ):
            continue

        raw.append(
            signal
        )

    if not raw:
        return []

    selected = choose_candidate(
        raw,
        "LONG",
    )

    if not selected:
        return []

    candidate = (
        convert_fix11_long_signal_to_fix17(
            selected,
            minute_by_code.get(
                str(
                    selected.get(
                        "Code",
                        ""
                    )
                )
            ),
        )
    )

    if candidate is None:
        return []

    return [
        candidate
    ]


def short_generator_status():

    return {
        "enabled": False,
        "reason":
            "SHORT_ENTRY_CONTRACT_NOT_FULLY_PROVEN",
    }
