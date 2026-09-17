# ============================================================
# FIX17 LONG CANDIDATE BRIDGE
#
# Source:
#   audited FIX11 live entry implementation
#
# LONG only.
# SHORT is intentionally blocked.
#
# IMPORTANT:
#   FIX11 ENTRY logic is NOT modified.
#   FIX17 ENTRY logic is NOT modified.
#
# FIX:
#   Connect the freshly loaded FIX11 namespace to the
#   FIX17 temporary RVOL20 history directory created by
#   paper_trader.py.
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
    """
    Load the FIX11 entry implementation stored permanently
    inside this GitHub repository.

    IMPORTANT:
    paper_trader.py creates the temporary FIX17 RVOL20 history:

        data/runtime/fix17_rvol_history

    The FIX11 namespace loaded here is a NEW runpy namespace.
    Therefore its RAW_DIR must explicitly be connected to the
    same temporary history directory.

    No FIX11 trading rule is changed.
    """

    import runpy
    from pathlib import Path

    repo_dir = Path(__file__).resolve().parent

    fix11_path = (
        repo_dir
        / ".github"
        / "workflows"
        / "fix11_paper_trader.py"
    )

    if not fix11_path.exists():
        raise RuntimeError(
            "FIX11 GitHub entry source missing: "
            + str(fix11_path)
        )

    ns = runpy.run_path(
        str(fix11_path),
        run_name="__fix17_fix11_entry_namespace__",
    )

    required = [
        "fetch_today_1m",
        "calc_rvol20",
        "find_first_signal",
        "choose_candidate",
    ]

    missing = [
        name
        for name in required
        if name not in ns
    ]

    if missing:
        raise RuntimeError(
            "FIX11 required entry functions missing: "
            + ", ".join(missing)
        )

    # ========================================================
    # FIX17 RVOL HISTORY CONNECTION
    #
    # paper_trader.py creates:
    #
    #   repo/data/runtime/fix17_rvol_history
    #
    # The functions loaded above have their own globals dict
    # because runpy.run_path() created a new namespace.
    #
    # Bind ONLY RAW_DIR.
    # Trading logic is unchanged.
    # ========================================================

    history_dir = (
        repo_dir
        / "data"
        / "runtime"
        / "fix17_rvol_history"
    )

    # Fallback:
    # use the same runtime location used by paper_trader.py
    # if the repository layout differs.
    if not history_dir.exists():

        candidates = [
            repo_dir
            / "runtime"
            / "fix17_rvol_history",

            repo_dir
            / "data"
            / "runtime"
            / "fix17_rvol_history",
        ]

        found = [
            p
            for p in candidates
            if p.exists()
            and p.is_dir()
        ]

        if found:
            history_dir = found[0]

    if not history_dir.exists():
        raise RuntimeError(
            "FIX17 RVOL history directory missing: "
            + str(history_dir)
        )

    history_files = list(
        history_dir.glob(
            "*.parquet"
        )
    )

    if not history_files:
        raise RuntimeError(
            "FIX17 RVOL history directory is empty: "
            + str(history_dir)
        )

    # runpy functions retain their own globals dictionary.
    # Bind the existing audited FIX11 functions to the
    # FIX17-prepared history directory.
    for fn_name in [
        "get_history_files_for_code",
        "calc_rvol20",
        "find_first_signal",
    ]:

        fn = ns.get(
            fn_name
        )

        if fn is None:
            raise RuntimeError(
                "FIX11 required RVOL function missing: "
                + fn_name
            )

        fn.__globals__[
            "RAW_DIR"
        ] = history_dir

    print(
        "FIX17 bridge RVOL history:",
        str(history_dir)
    )

    print(
        "FIX17 bridge RVOL files:",
        len(history_files)
    )

    return ns


def _finite(v):

    try:
        return math.isfinite(
            float(v)
        )
    except Exception:
        return False


# ============================================================
# FIX17 STEP9B FORMAL ENTRY PRICE
# ============================================================

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


# ============================================================
# SIGNAL -> FIX17 CANDIDATE
# ============================================================

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


# ============================================================
# LONG GENERATOR
# ============================================================

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

    scanned = 0
    long_signals = 0

    for code, minute_df in (
        minute_by_code.items()
    ):

        feature = feature_by_code.get(
            code
        )

        if feature is None:
            continue

        scanned += 1

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

        long_signals += 1

        raw.append(
            signal
        )

    # Diagnostic only.
    # Does not change candidate selection.
    print(
        "FIX17 bridge scanned:",
        scanned
    )

    print(
        "FIX17 bridge LONG signals:",
        long_signals
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


# ============================================================
# SHORT STATUS
# ============================================================

def short_generator_status():

    return {
        "enabled": False,
        "reason":
            "SHORT_ENTRY_CONTRACT_NOT_FULLY_PROVEN",
    }
