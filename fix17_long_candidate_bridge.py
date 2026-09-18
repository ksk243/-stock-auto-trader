# ============================================================
# FIX17 LONG CANDIDATE BRIDGE
#
# Source:
#   audited FIX11 live entry implementation
#
# LONG only.
# SHORT is intentionally blocked.
#
# ============================================================
#
# PERFORMANCE FIX
#
# FIX11 original calc_rvol20():
#
#   find_first_signal
#       ↓ every 1-minute bar
#   calc_rvol20
#       ↓
#   read 20 parquet files
#
# This causes an enormous number of repeated parquet reads.
#
# This bridge keeps EXACTLY the same:
#
#   - FIX11 find_first_signal()
#   - RS20 >= 80
#   - RVOL20 >= 2
#   - ORB15 cross
#   - turnover >= 3
#   - exact 20 prior sessions
#   - median historical cumulative volume
#
# Only the I/O implementation is accelerated:
#
#   Each historical parquet file is read ONCE per code.
#
# ENTRY / EXIT logic is NOT changed.
# ============================================================

from pathlib import Path
import runpy
import math


ROOT = Path(__file__).resolve().parents[1]

FIX11_RUNTIME_SOURCE = (
    ROOT
    / "FIX11_LIVE_SOURCE_FOR_STEP6.py"
)


# ============================================================
# FINITE
# ============================================================

def _finite(v):

    try:
        return math.isfinite(
            float(v)
        )
    except Exception:
        return False


# ============================================================
# FIX11 ENTRY NAMESPACE
# ============================================================

def _load_fix11_entry_namespace():

    import runpy
    from pathlib import Path
    import numpy as np
    import pandas as pd

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
        "get_history_files_for_code",
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
    # FIX17 RVOL HISTORY DIRECTORY
    # ========================================================

    candidates = [

        repo_dir
        / "runtime"
        / "fix17_rvol_history",

        repo_dir
        / "data"
        / "runtime"
        / "fix17_rvol_history",
    ]

    history_dir = None

    for p in candidates:

        if (
            p.exists()
            and
            p.is_dir()
        ):

            history_dir = p
            break

    if history_dir is None:

        raise RuntimeError(
            "FIX17 RVOL history directory missing"
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

    print(
        "FIX17 bridge RVOL history:",
        str(history_dir)
    )

    print(
        "FIX17 bridge RVOL files:",
        len(history_files)
    )

    # ========================================================
    # CONNECT ORIGINAL FIX11 FUNCTIONS TO FIX17 HISTORY
    # ========================================================

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

    # ========================================================
    # RVOL20 HISTORY CACHE
    #
    # IMPORTANT:
    #
    # Original FIX11:
    #
    #   for every signal minute:
    #       read 20 parquet files
    #
    # New implementation:
    #
    #   first signal minute for a code:
    #       read 20 parquet files once
    #
    #   subsequent signal minutes:
    #       use cached cumulative-volume arrays
    #
    # Mathematical definition is unchanged.
    # ========================================================

    history_cache = {}

    original_get_history_files = ns[
        "get_history_files_for_code"
    ]

    original_calc_rvol20 = ns[
        "calc_rvol20"
    ]

    # --------------------------------------------------------
    # Convert HH:MM to integer minute-of-day
    # --------------------------------------------------------

    def _minute_number(value):

        ts = pd.Timestamp(
            value
        )

        return (
            int(ts.hour) * 60
            +
            int(ts.minute)
        )

    # --------------------------------------------------------
    # Load one code's 20 historical sessions ONCE
    # --------------------------------------------------------

    def _load_code_history(
        code,
        before_date,
    ):

        normalized_date = pd.Timestamp(
            before_date
        ).normalize()

        cache_key = (
            str(code),
            normalized_date.date().isoformat(),
        )

        if cache_key in history_cache:

            return history_cache[
                cache_key
            ]

        hist_files_for_code = (
            original_get_history_files(
                code,
                normalized_date,
            )
        )

        # EXACT FIX11 contract:
        # 20 prior sessions required.
        if len(
            hist_files_for_code
        ) < 20:

            result = {
                "prev_days":
                    len(
                        hist_files_for_code
                    ),

                "sessions":
                    [],
            }

            history_cache[
                cache_key
            ] = result

            return result

        sessions = []

        for hist_date, path in (
            hist_files_for_code
        ):

            try:

                h = pd.read_parquet(
                    path
                )

                h["Datetime"] = (
                    pd.to_datetime(
                        h["Datetime"]
                    )
                )

                volume = (
                    pd.to_numeric(
                        h["V"],
                        errors="coerce",
                    )
                    .fillna(0.0)
                    .astype(float)
                )

                minute_numbers = (
                    h["Datetime"].dt.hour
                    * 60
                    +
                    h["Datetime"].dt.minute
                ).to_numpy(
                    dtype=np.int32
                )

                volume_values = (
                    volume.to_numpy(
                        dtype=float
                    )
                )

                # ------------------------------------------------
                # Original FIX11 definition:
                #
                #   h[h["Time"] <= minute]["V"].sum()
                #
                # We reproduce exactly the same <= minute result,
                # but prepare cumulative arrays once.
                # ------------------------------------------------

                order = np.argsort(
                    minute_numbers,
                    kind="stable",
                )

                minute_numbers = (
                    minute_numbers[
                        order
                    ]
                )

                volume_values = (
                    volume_values[
                        order
                    ]
                )

                cumulative = np.cumsum(
                    volume_values,
                    dtype=float,
                )

                sessions.append(
                    (
                        minute_numbers,
                        cumulative,
                    )
                )

            except Exception:

                # Exact original behavior:
                # failed historical read contributes zero.
                sessions.append(
                    (
                        np.empty(
                            0,
                            dtype=np.int32,
                        ),
                        np.empty(
                            0,
                            dtype=float,
                        ),
                    )
                )

        result = {
            "prev_days":
                len(
                    hist_files_for_code
                ),

            "sessions":
                sessions,
        }

        history_cache[
            cache_key
        ] = result

        return result

    # ========================================================
    # FAST RVOL20
    #
    # SAME CONTRACT AS FIX11 calc_rvol20()
    # ========================================================

    def cached_calc_rvol20(
        code,
        current_df,
        signal_dt,
    ):

        date = pd.Timestamp(
            signal_dt
        ).normalize()

        signal_minute = (
            _minute_number(
                signal_dt
            )
        )

        history = (
            _load_code_history(
                code,
                date,
            )
        )

        prev_days = int(
            history[
                "prev_days"
            ]
        )

        # EXACT FIX11 requirement.
        if prev_days < 20:

            return (
                np.nan,
                prev_days,
            )

        # ----------------------------------------------------
        # Current cumulative volume
        #
        # Exact original definition:
        #
        # current_df[
        #     current_df["Datetime"] <= signal_dt
        # ]["V"].sum()
        # ----------------------------------------------------

        current_cut = current_df[
            current_df[
                "Datetime"
            ]
            <=
            signal_dt
        ]

        if current_cut.empty:

            return (
                np.nan,
                20,
            )

        current_cum = float(
            current_cut[
                "V"
            ]
            .fillna(0)
            .sum()
        )

        hist_cums = []

        # ----------------------------------------------------
        # Historical cumulative volumes
        # ----------------------------------------------------

        for (
            minute_numbers,
            cumulative,
        ) in history["sessions"]:

            if (
                len(
                    minute_numbers
                )
                == 0
            ):

                # Exact original behavior:
                # missing/failed day contributes zero.
                hist_cums.append(
                    0.0
                )

                continue

            # Last historical bar whose time <= signal minute.
            pos = np.searchsorted(
                minute_numbers,
                signal_minute,
                side="right",
            ) - 1

            if pos < 0:

                # Exact original behavior:
                # no eligible bar -> zero.
                cum = 0.0

            else:

                cum = float(
                    cumulative[
                        pos
                    ]
                )

            hist_cums.append(
                cum
            )

        if len(
            hist_cums
        ) != 20:

            return (
                np.nan,
                len(
                    hist_cums
                ),
            )

        baseline = float(
            np.median(
                hist_cums
            )
        )

        if (
            not np.isfinite(
                baseline
            )
            or
            baseline <= 0
        ):

            return (
                np.nan,
                20,
            )

        return (
            current_cum
            /
            baseline,

            20,
        )

    # ========================================================
    # IMPORTANT
    #
    # find_first_signal() was loaded with runpy.
    #
    # Its global calc_rvol20 reference must point to the cached
    # implementation.
    #
    # The signal function itself is NOT changed.
    # ========================================================

    ns[
        "find_first_signal"
    ].__globals__[
        "calc_rvol20"
    ] = cached_calc_rvol20

    # Also expose it through namespace for audit.
    ns[
        "calc_rvol20"
    ] = cached_calc_rvol20

    print(
        "FIX17 bridge RVOL cache: ENABLED"
    )

    return ns


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

    if len(
        minute_df
    ) == 0:
        return None, None

    x = minute_df.copy()

    if "Datetime" not in x.columns:
        return None, None

    x["Datetime"] = (
        pd.to_datetime(
            x["Datetime"],
            errors="coerce",
        )
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

        signal_dt = (
            pd.Timestamp(
                signal_datetime
            )
        )

    except Exception:

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

        price = row[
            "O"
        ]

    elif "Open" in row.index:

        price = row[
            "Open"
        ]

    else:

        return None, None

    try:

        price = float(
            price
        )

    except Exception:

        return None, None

    if (
        not math.isfinite(
            price
        )
        or
        price <= 0
    ):

        return None, None

    return (
        price,
        row[
            "Datetime"
        ],
    )


# ============================================================
# FIX11 SIGNAL -> FIX17 CANDIDATE
# ============================================================

def convert_fix11_long_signal_to_fix17(
    signal,
    minute_df,
):

    """
    Convert audited FIX11 LONG signal
    into FIX17 candidate interface.

    Sizing remains in FIX17 execution layer.
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
        _finite(
            rs
        ),
        _finite(
            rvol
        ),
        _finite(
            turnover
        ),
        _finite(
            signal_price
        ),
    ]):

        return None

    # ========================================================
    # PROVEN FIX17/FIX11 LONG FILTERS
    # UNCHANGED
    # ========================================================

    if float(
        rs
    ) < 80:

        return None

    if float(
        rvol
    ) < 2:

        return None

    if float(
        turnover
    ) < 3:

        return None

    # find_first_signal() returns LONG only after
    # the exact ORB cross has already passed.

    orb_long = True
    cross_exact = True

    prev_days = signal.get(
        "PrevDays"
    )

    backtest_ready = (
        prev_days is not None
        and
        int(
            prev_days
        ) == 20
    )

    if not backtest_ready:

        return None

    (
        formal_entry_price,
        formal_entry_datetime,
    ) = (
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

        "ORB15_LongSignal":
            bool(
                orb_long
            ),

        "CrossPass_EXACT":
            bool(
                cross_exact
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


# ============================================================
# LONG GENERATOR
# ============================================================

def generate_fix17_long_candidates(
    minute_by_code,
    feature_by_code,
):

    """
    FIX17 LONG candidate generator.

    Existing audited FIX11 find_first_signal() is used unchanged.

    Only historical RVOL parquet I/O is cached.
    """

    ns = (
        _load_fix11_entry_namespace()
    )

    find_first_signal = ns[
        "find_first_signal"
    ]

    choose_candidate = ns[
        "choose_candidate"
    ]

    raw = []

    scanned = 0
    long_signals = 0

    # ========================================================
    # EXACT EXISTING SIGNAL PASS
    # ========================================================

    for code, minute_df in (
        minute_by_code.items()
    ):

        feature = (
            feature_by_code.get(
                code
            )
        )

        if feature is None:

            continue

        scanned += 1

        signal = (
            find_first_signal(
                code,
                minute_df,
                feature,
            )
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

    # ========================================================
    # EXISTING FIX11 CANDIDATE SELECTION
    # ========================================================

    selected = (
        choose_candidate(
            raw,
            "LONG",
        )
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
# SHORT
# ============================================================

def short_generator_status():

    return {

        "enabled":
            False,

        "reason":
            "SHORT_ENTRY_CONTRACT_NOT_FULLY_PROVEN",
    }
