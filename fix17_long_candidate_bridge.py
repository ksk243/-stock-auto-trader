# ============================================================
# FIX17 LONG + SHORT CANDIDATE BRIDGE
#
# Source:
#   audited FIX11 live entry implementation
#
# Signal rules are NOT reconstructed here.
# Both sides use FIX11 find_first_signal() and choose_candidate().
# ============================================================

from pathlib import Path
import runpy
import math
import numpy as np
import pandas as pd


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

    # IMPORTANT:
    # build_fix17_long_live_inputs() has already created the exact
    # 20-session per-code RVOL history here. runpy.run_path() above
    # creates a NEW FIX11 namespace, so its functions must be pointed
    # to the same prepared history directory too.
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

    print(
        "FIX17 bridge RVOL history:",
        history_dir,
    )

    # ========================================================
    # FAST RVOL20 CACHE
    #
    # FIX11 calc_rvol20() has exact semantics:
    #   current cumulative volume through signal minute
    #   ------------------------------------------------
    #   median of 20 prior-session cumulative volumes
    #   through the same minute
    #
    # The original implementation re-reads 20 parquet files
    # for every signal minute.  Here those SAME historical
    # values are loaded once per code and cached in memory.
    #
    # Trading thresholds / ORB / RS / candidate ordering are
    # not changed.
    # ========================================================

    history_files_by_code = {}

    for p in history_dir.glob("*.parquet"):
        name = p.name
        if len(name) < 12:
            continue

        try:
            hist_date = pd.Timestamp(
                name[:10]
            )
        except Exception:
            continue

        # filename:
        # YYYY-MM-DD_<code>.parquet
        stem = p.stem
        if "_" not in stem:
            continue

        code = stem.split(
            "_",
            1,
        )[1]

        history_files_by_code.setdefault(
            code,
            [],
        ).append(
            (
                hist_date,
                p,
            )
        )

    for code in history_files_by_code:
        history_files_by_code[
            code
        ].sort(
            key=lambda x: x[0]
        )

    history_curve_cache = {}
    current_curve_cache = {}

    def _load_history_curves(
        code,
        before_date,
    ):
        """
        Return the exact latest 20 prior-session cumulative-volume
        curves used by FIX11, but read each parquet only once.
        """

        key = (
            str(code),
            pd.Timestamp(
                before_date
            ).normalize(),
        )

        if key in history_curve_cache:
            return history_curve_cache[
                key
            ]

        files = [
            item
            for item in history_files_by_code.get(
                str(code),
                [],
            )
            if item[0] < key[1]
        ][-20:]

        if len(files) < 20:
            result = (
                [],
                len(files),
            )
            history_curve_cache[
                key
            ] = result
            return result

        curves = []

        for hist_date, path in files:
            try:
                h = pd.read_parquet(
                    path
                )

                h["Datetime"] = pd.to_datetime(
                    h["Datetime"],
                    errors="coerce",
                )

                h = h[
                    h["Datetime"].notna()
                ].copy()

                if h.empty:
                    curves.append({})
                    continue

                h["Time"] = (
                    h["Datetime"]
                    .dt.strftime("%H:%M")
                )

                h["_V"] = pd.to_numeric(
                    h["V"],
                    errors="coerce",
                ).fillna(0.0)

                # FIX11 semantics are:
                # sum(V) where Time <= requested minute.
                # Store cumulative value at each existing minute.
                by_time = (
                    h.groupby(
                        "Time",
                        sort=True,
                    )["_V"]
                    .sum()
                    .cumsum()
                )

                curves.append(
                    by_time.to_dict()
                )

            except Exception:
                # Original FIX11 appends 0.0 on read failure.
                curves.append({})

        result = (
            curves,
            20,
        )

        history_curve_cache[
            key
        ] = result

        return result

    def _cum_at_minute(
        curve,
        minute,
    ):
        """
        Exact equivalent of:
            h[h["Time"] <= minute]["V"].sum()

        Missing eligible prior-day bar contributes zero.
        """
        if not curve:
            return 0.0

        # HH:MM strings are lexicographically ordered.
        value = 0.0
        for t, cum in curve.items():
            if t > minute:
                break
            value = float(cum)

        return value

    def _current_cumulative(
        code,
        current_df,
        signal_dt,
    ):
        minute = pd.Timestamp(
            signal_dt
        ).strftime("%H:%M")

        # One current intraday curve per code/DataFrame.
        key = (
            str(code),
            id(current_df),
        )

        curve = current_curve_cache.get(
            key
        )

        if curve is None:
            x = current_df[
                ["Datetime", "V"]
            ].copy()

            x["Datetime"] = pd.to_datetime(
                x["Datetime"],
                errors="coerce",
            )

            x = x[
                x["Datetime"].notna()
            ].copy()

            x["Time"] = (
                x["Datetime"]
                .dt.strftime("%H:%M")
            )

            x["_V"] = pd.to_numeric(
                x["V"],
                errors="coerce",
            ).fillna(0.0)

            curve = (
                x.groupby(
                    "Time",
                    sort=True,
                )["_V"]
                .sum()
                .cumsum()
                .to_dict()
            )

            current_curve_cache[
                key
            ] = curve

        return _cum_at_minute(
            curve,
            minute,
        )

    def fast_calc_rvol20(
        code,
        current_df,
        signal_dt,
    ):
        """
        Numerically equivalent to the recovered FIX11 calc_rvol20(),
        with historical parquet I/O cached.
        """

        date = pd.Timestamp(
            signal_dt
        ).normalize()

        minute = pd.Timestamp(
            signal_dt
        ).strftime("%H:%M")

        curves, prev_days = (
            _load_history_curves(
                code,
                date,
            )
        )

        if prev_days < 20:
            return (
                np.nan,
                prev_days,
            )

        if (
            current_df is None
            or current_df.empty
        ):
            return (
                np.nan,
                20,
            )

        current_cum = (
            _current_cumulative(
                code,
                current_df,
                signal_dt,
            )
        )

        hist_cums = [
            _cum_at_minute(
                curve,
                minute,
            )
            for curve in curves
        ]

        if len(hist_cums) != 20:
            return (
                np.nan,
                len(hist_cums),
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
            or baseline <= 0
        ):
            return (
                np.nan,
                20,
            )

        return (
            current_cum
            / baseline,
            20,
        )

    # find_first_signal() resolves calc_rvol20 from its own
    # runpy globals dictionary. Replace only that data-access
    # implementation with the numerically equivalent cached one.
    ns["calc_rvol20"] = (
        fast_calc_rvol20
    )

    ns[
        "find_first_signal"
    ].__globals__[
        "calc_rvol20"
    ] = fast_calc_rvol20

    print(
        "FIX17 bridge RVOL files:",
        sum(
            len(v)
            for v
            in history_files_by_code.values()
        ),
    )

    print(
        "FIX17 bridge RVOL cache: ENABLED"
    )

    return ns


def _finite(v):
    try:
        return math.isfinite(
            float(v)
        )
    except Exception:
        return False


def resolve_fix17_formal_entry_price(
    minute_df,
    signal_datetime,
):
    """
    FormalEntryPrice:
    SignalDatetime より後の最初の実在1分足 Open。
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

    # These bounds match the recovered FIX11 entry source.
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
            float(rs),

        "RVOL20":
            float(rvol),

        "turnover_median_20d_oku":
            float(turnover),

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


def generate_fix17_long_short_candidates(
    minute_by_code,
    feature_by_code,
):
    """
    Single-pass FIX17 LONG + SHORT bridge.

    IMPORTANT:
      - Each code is scanned exactly ONCE.
      - Signal generation remains the recovered FIX11
        find_first_signal() implementation.
      - LONG/SHORT are only separated AFTER the signal is returned.
      - Candidate ordering remains FIX11 choose_candidate().
      - At most one LONG and one SHORT are returned.
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

    print(
        "FIX17 bridge scanned:",
        scanned,
    )
    print(
        "FIX17 bridge LONG signals:",
        len(raw_long),
    )
    print(
        "FIX17 bridge SHORT signals:",
        len(raw_short),
    )

    result = []

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


def generate_fix17_long_candidates(
    minute_by_code,
    feature_by_code,
):
    """
    Compatibility wrapper.
    Uses the same single-pass combined generator and returns LONG only.
    """
    return [
        c
        for c in generate_fix17_long_short_candidates(
            minute_by_code,
            feature_by_code,
        )
        if str(
            c.get(
                "side",
                "",
            )
        ).upper() == "LONG"
    ]


def generate_fix17_short_candidates(
    minute_by_code,
    feature_by_code,
):
    """
    Compatibility wrapper.
    Uses the same single-pass combined generator and returns SHORT only.
    """
    return [
        c
        for c in generate_fix17_long_short_candidates(
            minute_by_code,
            feature_by_code,
        )
        if str(
            c.get(
                "side",
                "",
            )
        ).upper() == "SHORT"
    ]


def short_generator_status():
    return {
        "enabled": True,
        "reason":
            "RECOVERED_FIX11_SHORT_SIGNAL_PATH",
    }
