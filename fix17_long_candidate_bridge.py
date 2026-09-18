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


def _generate_selected_side(
    minute_by_code,
    feature_by_code,
    side,
):
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
                    "",
                )
            ).upper()
            != side
        ):
            continue

        raw.append(
            signal
        )

    print(
        f"FIX17 bridge {side} signals:",
        len(raw),
    )

    if not raw:
        return []

    selected = choose_candidate(
        raw,
        side,
    )

    if not selected:
        return []

    code = str(
        selected.get(
            "Code",
            "",
        )
    )

    candidate = (
        convert_fix11_signal_to_fix17(
            selected,
            minute_by_code.get(
                code
            ),
        )
    )

    if candidate is None:
        return []

    return [
        candidate
    ]


def generate_fix17_long_candidates(
    minute_by_code,
    feature_by_code,
):
    return _generate_selected_side(
        minute_by_code,
        feature_by_code,
        "LONG",
    )


def generate_fix17_short_candidates(
    minute_by_code,
    feature_by_code,
):
    return _generate_selected_side(
        minute_by_code,
        feature_by_code,
        "SHORT",
    )


def generate_fix17_long_short_candidates(
    minute_by_code,
    feature_by_code,
):
    """
    At most one LONG and one SHORT.
    Both are selected independently using the recovered FIX11
    choose_candidate() ordering.
    """
    long_candidates = (
        generate_fix17_long_candidates(
            minute_by_code,
            feature_by_code,
        )
    )

    short_candidates = (
        generate_fix17_short_candidates(
            minute_by_code,
            feature_by_code,
        )
    )

    return (
        list(
            long_candidates
        )
        +
        list(
            short_candidates
        )
    )


def short_generator_status():
    return {
        "enabled": True,
        "reason":
            "RECOVERED_FIX11_SHORT_SIGNAL_PATH",
    }
