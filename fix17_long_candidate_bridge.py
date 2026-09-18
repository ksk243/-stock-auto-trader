# ============================================================
# FIX17 LONG + SHORT CANDIDATE BRIDGE
#
# RVOL CACHE RESTORED VERSION
#
# Source:
#   audited FIX11 live entry implementation
#
# IMPORTANT
#   - FIX11 ENTRY logic is NOT reconstructed.
#   - find_first_signal() is used unchanged.
#   - choose_candidate() is used unchanged.
#   - LONG / SHORT are scanned in ONE PASS.
#   - RVOL20 calculation result is cached in memory.
#   - FormalEntryPrice is the next actual 1-minute OPEN
#     after SignalDatetime.
#
# This file replaces:
#   fix17_long_candidate_bridge.py
# ============================================================

from pathlib import Path
import runpy
import math
from functools import wraps


# ============================================================
# FIX11 ENTRY NAMESPACE
# ============================================================

def _load_fix11_entry_namespace():

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
    # RVOL HISTORY DIRECTORY
    #
    # build_fix17_long_live_inputs() creates the exact
    # 20-session per-code history here.
    # ========================================================

    history_dir = (
        repo_dir
        / "runtime"
        / "fix17_rvol_history"
    )

    if not history_dir.exists():

        raise RuntimeError(
            "FIX17 bridge RVOL history missing: "
            + str(history_dir)
        )

    # ========================================================
    # IMPORTANT
    #
    # runpy.run_path() creates a new FIX11 namespace.
    # Therefore the FIX11 functions must be pointed to the
    # prepared FIX17 RVOL history directory.
    # ========================================================

    for fn_name in (
        "get_history_files_for_code",
        "calc_rvol20",
        "find_first_signal",
    ):

        fn = ns.get(fn_name)

        if fn is None:

            raise RuntimeError(
                f"FIX11 {fn_name} missing"
            )

        fn.__globals__["RAW_DIR"] = history_dir

    # ========================================================
    # RVOL20 MEMORY CACHE
    #
    # DO NOT change the official calc_rvol20 calculation.
    #
    # We only cache its RETURN VALUE.
    #
    # The original function is still responsible for the
    # actual RVOL calculation.
    # ========================================================

    original_calc_rvol20 = ns[
        "calc_rvol20"
    ]

    rvol_cache = {}

    @wraps(original_calc_rvol20)
    def cached_calc_rvol20(*args, **kwargs):

        # ----------------------------------------------------
        # Build a safe cache key from the exact call.
        #
        # FIX11 normally calls calc_rvol20 repeatedly while
        # scanning the intraday bars of one code.
        #
        # Arguments can contain pandas Timestamp etc.
        # repr() gives us a stable hashable representation
        # without changing the arguments passed to FIX11.
        # ----------------------------------------------------

        try:

            key = (
                tuple(
                    repr(x)
                    for x in args
                ),
                tuple(
                    sorted(
                        (
                            str(k),
                            repr(v),
                        )
                        for k, v
                        in kwargs.items()
                    )
                ),
            )

        except Exception:

            # Extremely defensive fallback.
            # If a cache key cannot be constructed,
            # execute the original FIX11 function unchanged.

            return original_calc_rvol20(
                *args,
                **kwargs,
            )

        if key in rvol_cache:

            return rvol_cache[
                key
            ]

        result = original_calc_rvol20(
            *args,
            **kwargs,
        )

        rvol_cache[
            key
        ] = result

        return result

    # ========================================================
    # Replace calc_rvol20 reference inside the exact
    # find_first_signal global namespace.
    #
    # This does NOT replace find_first_signal itself.
    # It only prevents repeated identical RVOL calculations.
    # ========================================================

    ns[
        "calc_rvol20"
    ] = cached_calc_rvol20

    find_first_signal = ns[
        "find_first_signal"
    ]

    find_first_signal.__globals__[
        "calc_rvol20"
    ] = cached_calc_rvol20

    # ========================================================
    # Diagnostics
    # ========================================================

    try:

        rvol_files = len(
            list(
                history_dir.glob(
                    "*.parquet"
                )
            )
        )

    except Exception:

        rvol_files = -1

    print(
        "FIX17 bridge RVOL history:",
        history_dir,
    )

    print(
        "FIX17 bridge RVOL files:",
        rvol_files,
    )

    print(
        "FIX17 bridge RVOL cache: ENABLED"
    )

    # Keep cache reachable for diagnostics if required.

    ns[
        "__fix17_rvol_cache__"
    ] = rvol_cache

    return ns


# ============================================================
# FINITE NUMBER CHECK
# ============================================================

def _finite(v):

    try:

        return math.isfinite(
            float(v)
        )

    except Exception:

        return False


# ============================================================
# FORMAL ENTRY PRICE
# ============================================================

def resolve_fix17_formal_entry_price(
    minute_df,
    signal_datetime,
):

    """
    FIX17 FormalEntryPrice

    SignalDatetime より後の
    最初の実在1分足 Open。

    Signal bar itself is NOT used.
    """

    import pandas as pd

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

        price = float(
            price
        )

    except Exception:

        return None, None

    if (
        not math.isfinite(price)
        or
        price <= 0
    ):

        return None, None

    return (
        price,
        row["Datetime"],
    )


# ============================================================
# FIX11 SIGNAL -> FIX17 CANDIDATE
# ============================================================

def convert_fix11_signal_to_fix17(
    signal,
    minute_df,
):

    if not signal:

        return None

    side = str(
        signal.get(
            "Side",
            "",
        )
    ).upper()

    if side not in {
        "LONG",
        "SHORT",
    }:

        return None

    code = str(
        signal.get(
            "Code",
            "",
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

    # ========================================================
    # EXACT RECOVERED FIX11 BOUNDS
    # ========================================================

    if side == "LONG":

        if float(rs) < 80:

            return None

    else:

        if float(rs) > 20:

            return None

    if float(rvol) < 2:

        return None

    if float(turnover) < 3:

        return None

    prev_days = signal.get(
        "PrevDays"
    )

    backtest_ready = (
        prev_days is not None
        and
        int(prev_days) == 20
    )

    if not backtest_ready:

        return None

    # ========================================================
    # NEXT ACTUAL 1-MINUTE OPEN
    # ========================================================

    (
        formal_entry_price,
        formal_entry_datetime,
    ) = resolve_fix17_formal_entry_price(
        minute_df,
        signal.get(
            "SignalDatetime"
        ),
    )

    if formal_entry_price is None:

        return None

    candidate = {

        "code":
            code,

        "side":
            side,

        "entry_price":
            float(
                formal_entry_price
            ),

        "FormalEntryPrice":
            float(
                formal_entry_price
            ),

        "EntryDatetime":
            formal_entry_datetime,

        "RS20_corrected":
            float(
                rs
            ),

        "RVOL20":
            float(
                rvol
            ),

        "turnover_median_20d_oku":
            float(
                turnover
            ),

        "BacktestReady":
            bool(
                backtest_ready
            ),

        "SignalDatetime":
            signal.get(
                "SignalDatetime"
            ),

        "SignalPrice":
            float(
                signal_price
            ),

        "ORBHigh":
            signal.get(
                "ORBHigh"
            ),

        "ORBLow":
            signal.get(
                "ORBLow"
            ),

        "PrevDays":
            int(
                prev_days
            ),
    }

    if side == "LONG":

        candidate[
            "ORB15_LongSignal"
        ] = True

        candidate[
            "CrossPass_EXACT"
        ] = True

    else:

        candidate[
            "ORB15_ShortSignal"
        ] = True

    return candidate


# ============================================================
# FIX17 LONG + SHORT
#
# SINGLE PASS
# ============================================================

def generate_fix17_long_short_candidates(
    minute_by_code,
    feature_by_code,
):

    """
    FIX17 LONG + SHORT candidate generator.

    IMPORTANT:

      1. Each code is scanned exactly ONCE.

      2. Signal generation is the recovered FIX11
         find_first_signal().

      3. LONG / SHORT separation occurs only AFTER
         find_first_signal() returns.

      4. Candidate selection is the recovered FIX11
         choose_candidate().

      5. Maximum output:
            LONG  : 1
            SHORT : 1
    """

    ns = _load_fix11_entry_namespace()

    find_first_signal = ns[
        "find_first_signal"
    ]

    choose_candidate = ns[
        "choose_candidate"
    ]

    raw_long = []

    raw_short = []

    scanned = 0

    # ========================================================
    # ONE PASS ONLY
    # ========================================================

    for code, minute_df in (
        minute_by_code.items()
    ):

        feature = feature_by_code.get(
            code
        )

        if feature is None:

            continue

        scanned += 1

        # ----------------------------------------------------
        # EXACT FIX11 SIGNAL ENGINE
        # ----------------------------------------------------

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
                "",
            )
        ).upper()

        if side == "LONG":

            raw_long.append(
                signal
            )

        elif side == "SHORT":

            raw_short.append(
                signal
            )

    # ========================================================
    # DIAGNOSTICS
    # ========================================================

    print(
        "FIX17 bridge scanned:",
        scanned,
    )

    print(
        "FIX17 bridge LONG signals:",
        len(
            raw_long
        ),
    )

    print(
        "FIX17 bridge SHORT signals:",
        len(
            raw_short
        ),
    )

    try:

        print(
            "FIX17 bridge RVOL cache entries:",
            len(
                ns.get(
                    "__fix17_rvol_cache__",
                    {},
                )
            ),
        )

    except Exception:

        pass

    # ========================================================
    # FINAL SELECTION
    # ========================================================

    result = []

    # --------------------------------------------------------
    # LONG
    # --------------------------------------------------------

    if raw_long:

        selected_long = (
            choose_candidate(
                raw_long,
                "LONG",
            )
        )

        if selected_long:

            code = str(
                selected_long.get(
                    "Code",
                    "",
                )
            )

            candidate = (
                convert_fix11_signal_to_fix17(
                    selected_long,
                    minute_by_code.get(
                        code
                    ),
                )
            )

            if candidate is not None:

                result.append(
                    candidate
                )

    # --------------------------------------------------------
    # SHORT
    # --------------------------------------------------------

    if raw_short:

        selected_short = (
            choose_candidate(
                raw_short,
                "SHORT",
            )
        )

        if selected_short:

            code = str(
                selected_short.get(
                    "Code",
                    "",
                )
            )

            candidate = (
                convert_fix11_signal_to_fix17(
                    selected_short,
                    minute_by_code.get(
                        code
                    ),
                )
            )

            if candidate is not None:

                result.append(
                    candidate
                )

    return result


# ============================================================
# LONG COMPATIBILITY WRAPPER
# ============================================================

def generate_fix17_long_candidates(
    minute_by_code,
    feature_by_code,
):

    """
    Compatibility wrapper.

    Uses the same single-pass combined generator
    and returns LONG only.
    """

    return [

        candidate

        for candidate
        in generate_fix17_long_short_candidates(
            minute_by_code,
            feature_by_code,
        )

        if str(
            candidate.get(
                "side",
                "",
            )
        ).upper() == "LONG"
    ]


# ============================================================
# SHORT COMPATIBILITY WRAPPER
# ============================================================

def generate_fix17_short_candidates(
    minute_by_code,
    feature_by_code,
):

    """
    Compatibility wrapper.

    Uses the same single-pass combined generator
    and returns SHORT only.
    """

    return [

        candidate

        for candidate
        in generate_fix17_long_short_candidates(
            minute_by_code,
            feature_by_code,
        )

        if str(
            candidate.get(
                "side",
                "",
            )
        ).upper() == "SHORT"
    ]


# ============================================================
# SHORT GENERATOR STATUS
# ============================================================

def short_generator_status():

    return {

        "enabled":
            True,

        "reason":
            "RECOVERED_FIX11_SHORT_SIGNAL_PATH",
    }


# ============================================================
# END
# ============================================================
