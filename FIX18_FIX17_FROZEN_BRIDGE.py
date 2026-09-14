# ============================================================
# FIX18 -> FIX17 FROZEN BRIDGE
#
# Source of truth:
#   GitHub FIX17_FROZEN
#   GitHub FIX17_RECOVERY
#   tag FIX17_RUNTIME
#
# No FIX17 trading logic is reimplemented here.
# ============================================================

from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent

FROZEN_ROOT = (
    HERE
    / "FIX17_FROZEN"
)

RECOVERY_ROOT = (
    HERE
    / "FIX17_RECOVERY"
)

MANIFEST_FILE = (
    HERE
    / "FIX18_FIX17_FROZEN_BRIDGE.json"
)


def load_bridge_manifest():

    if not MANIFEST_FILE.exists():

        raise RuntimeError(
            f"Missing bridge manifest: {MANIFEST_FILE}"
        )

    return json.loads(
        MANIFEST_FILE.read_text(
            encoding="utf-8"
        )
    )


def frozen_path(relative_path: str):

    p = (
        HERE
        / relative_path
    ).resolve()

    root = (
        FROZEN_ROOT.resolve()
    )

    if (
        p != root
        and
        root not in p.parents
    ):

        raise RuntimeError(
            "Path is outside FIX17_FROZEN"
        )

    if not p.exists():

        raise RuntimeError(
            f"Frozen file missing: {p}"
        )

    return p


def symbol_locations(symbol_name: str):

    manifest = load_bridge_manifest()

    return (
        manifest
        .get(
            "known_symbols",
            {}
        )
        .get(
            symbol_name,
            []
        )
    )


def require_unique_symbol(
    symbol_name: str,
):

    hits = symbol_locations(
        symbol_name
    )

    if len(hits) != 1:

        raise RuntimeError(
            f"{symbol_name}: expected exactly 1 frozen location, "
            f"found {len(hits)}"
        )

    return hits[0]


def runtime_identity():

    manifest = load_bridge_manifest()

    return {
        "runtime_tag":
            manifest[
                "runtime_tag"
            ],

        "runtime_commit":
            manifest[
                "runtime_commit"
            ],

        "frozen_file_count":
            manifest[
                "frozen_file_count"
            ],

        "source":
            manifest[
                "source"
            ],
    }


if __name__ == "__main__":

    x = runtime_identity()

    print(
        "FIX17 runtime tag    :",
        x["runtime_tag"],
    )

    print(
        "FIX17 runtime commit :",
        x["runtime_commit"][:12],
    )

    print(
        "Frozen files         :",
        x["frozen_file_count"],
    )

    print(
        "Source               :",
        x["source"],
    )
