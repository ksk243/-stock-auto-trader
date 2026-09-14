# ============================================================
# FIX18 -> FIX17 FROZEN RUNTIME ADAPTER
#
# FIX17 source of truth:
#   tag    : FIX17_RUNTIME
#   commit : dfba056f1e8a86d7f6ee7b9507f16830d9dfaeda
#   runtime: FIX17_FROZEN/paper_trader.py
#
# This adapter DOES NOT rewrite FIX17 trading logic.
#
# It only replaces the candidate provider temporarily so that
# FIX18 candidates flow through the exact frozen FIX17:
#
#   calculate_fix17_order()
#       ->
#   apply_paper_fill()
#
# ============================================================

from __future__ import annotations

import sys
import json
import importlib.util
from pathlib import Path
from typing import Any, Dict, List


HERE = Path(__file__).resolve().parent

RUNTIME_FILE = (
    HERE
    / 'FIX17_FROZEN/paper_trader.py'
)

BRIDGE_MANIFEST = (
    HERE
    / "FIX18_FIX17_FROZEN_BRIDGE.json"
)


_runtime_module = None


# ============================================================
# IMPORT EXACT FROZEN RUNTIME
# ============================================================

def load_frozen_runtime():

    global _runtime_module

    if _runtime_module is not None:
        return _runtime_module


    if not RUNTIME_FILE.exists():

        raise RuntimeError(
            f"Frozen FIX17 runtime missing: "
            f"{RUNTIME_FILE}"
        )


    module_name = (
        "fix18_frozen_fix17_runtime"
    )


    if module_name in sys.modules:

        mod = sys.modules[
            module_name
        ]

        _runtime_module = mod

        return mod


    spec = importlib.util.spec_from_file_location(
        module_name,
        RUNTIME_FILE,
    )


    if (
        spec is None
        or
        spec.loader is None
    ):

        raise RuntimeError(
            "Cannot create FIX17 runtime import spec"
        )


    mod = importlib.util.module_from_spec(
        spec
    )

    sys.modules[
        module_name
    ] = mod


    spec.loader.exec_module(
        mod
    )


    required = [
        "execute_fix17_candidate_batch",
        "calculate_fix17_order",
        "apply_paper_fill",
        "get_fix17_position_state",
    ]


    missing = [
        name
        for name in required
        if not hasattr(
            mod,
            name,
        )
    ]


    if missing:

        raise RuntimeError(
            "Frozen FIX17 runtime missing: "
            +
            ", ".join(
                missing
            )
        )


    _runtime_module = mod

    return mod


# ============================================================
# CANDIDATE PAYLOAD
# ============================================================

def build_candidate_payload(
    candidates: List[Dict[str, Any]],
    *,
    market_date=None,
):

    clean = []


    for candidate in candidates:

        if not isinstance(
            candidate,
            dict,
        ):

            raise TypeError(
                "FIX18 candidate must be dict"
            )


        x = dict(
            candidate
        )


        # FIX17 runtime側へ渡す際にも
        # candidate内容は変更しない。
        clean.append(
            x
        )


    return {
        "status":
            (
                "OK"
                if clean
                else
                "NO_CANDIDATES"
            ),

        "market_date":
            (
                str(market_date)
                if market_date is not None
                else None
            ),

        "candidate_count":
            len(clean),

        "candidates":
            clean,
    }


# ============================================================
# RUN EXACT FIX17 ENTRY PIPELINE
#
# execute_fix17_candidate_batch() は
# generate_fix17_live_candidates() を内部で呼ぶ。
#
# そのproviderだけ一時的にFIX18 payloadへ差し替える。
#
# calculate_fix17_order / sizing / apply_paper_fill は
# 凍結FIX17そのものを使う。
# ============================================================

def execute_fix18_candidates(
    candidates: List[Dict[str, Any]],
    *,
    market_date=None,
):

    runtime = load_frozen_runtime()


    payload = build_candidate_payload(
        candidates,
        market_date=market_date,
    )


    if not hasattr(
        runtime,
        "generate_fix17_live_candidates",
    ):

        raise RuntimeError(
            "Frozen runtime has no "
            "generate_fix17_live_candidates"
        )


    original_provider = (
        runtime.generate_fix17_live_candidates
    )


    def _fix18_provider():

        return payload


    runtime.generate_fix17_live_candidates = (
        _fix18_provider
    )


    try:

        result = (
            runtime
            .execute_fix17_candidate_batch()
        )

    finally:

        runtime.generate_fix17_live_candidates = (
            original_provider
        )


    return result


# ============================================================
# DIRECT FORMAL ORDER CHECK
#
# Stateを直接渡してorderだけ計算したい回帰テスト用。
# ============================================================

def calculate_order_exact(
    candidate,
    state,
):

    runtime = load_frozen_runtime()

    return runtime.calculate_fix17_order(
        candidate,
        state,
    )


# ============================================================
# APPLY FILL EXACT
# ============================================================

def apply_fill_exact(
    state,
    order,
    market_date,
):

    runtime = load_frozen_runtime()

    return runtime.apply_paper_fill(
        state,
        order,
        market_date,
    )


# ============================================================
# POSITION STATE EXACT
# ============================================================

def get_position_state_exact(
    runtime_state,
    state,
    market_date,
):

    runtime = load_frozen_runtime()

    return runtime.get_fix17_position_state(
        runtime_state,
        state,
        market_date,
    )


# ============================================================
# IDENTITY
# ============================================================

def identity():

    manifest = json.loads(
        BRIDGE_MANIFEST.read_text(
            encoding="utf-8"
        )
    )


    return {
        "runtime_tag":
            manifest[
                "runtime_tag"
            ],

        "runtime_commit":
            manifest[
                "runtime_commit"
            ],

        "runtime_file":
            str(
                RUNTIME_FILE.relative_to(
                    HERE
                )
            ),

        "candidate_injection":
            "generate_fix17_live_candidates",

        "order_engine":
            "calculate_fix17_order",

        "fill_engine":
            "apply_paper_fill",
    }


if __name__ == "__main__":

    x = identity()

    print(
        "Runtime tag      :",
        x["runtime_tag"],
    )

    print(
        "Runtime commit   :",
        x["runtime_commit"][:12],
    )

    print(
        "Runtime file     :",
        x["runtime_file"],
    )

    print(
        "Candidate bridge :",
        x["candidate_injection"],
    )

    print(
        "Order engine     :",
        x["order_engine"],
    )

    print(
        "Fill engine      :",
        x["fill_engine"],
    )
