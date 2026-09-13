# ============================================================
# FIX17 OFFICIAL CONTRACT SAFETY GATE
#
# Auto-generated from proven FIX17 audit.
#
# Missing rules must NOT be invented.
# ============================================================

from __future__ import annotations

import hashlib
import json
from pathlib import Path


EXPECTED_FIX17_SHA256 = (
    "9598156080b81445e5754c7b0f561389"
    "00862e8fd7f35ac89960491bec7222c4"
)


LONG_ENTRY_CONTRACT = {
    "RS20_corrected": ">= 80",
    "RVOL20": ">= 2",
    "turnover_median_20d_oku": ">= 3",
    "ORB15_LongSignal": True,
    "CrossPass_EXACT": True,
    "BacktestReady": True,
}


SHORT_ENTRY_CONTRACT = {
    "RS20_corrected":
        "<= 20 EFFECTIVE BOUND",

    "RVOL20":
        ">= 2",

    "turnover_median_20d_oku":
        ">= 3",

    "ORB15_ShortSignal":
        True,

    "is_lending":
        True,

    "_entered":
        True,
}


FIX17_LONG_SIZING_RULE = (
    "target_notional = long_remaining_capacity"
)


class Fix17ContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:

    h = hashlib.sha256()

    with path.open("rb") as f:

        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):

            h.update(chunk)

    return h.hexdigest()


def validate_fix17_contract(
    repo_dir: str | Path | None = None,
) -> dict:

    if repo_dir is None:

        repo = Path(
            __file__
        ).resolve().parent

    else:

        repo = Path(
            repo_dir
        ).resolve()


    official_source = (
        repo
        / "FIX17_OFFICIAL_FULL_SOURCE.py"
    )

    contract_file = (
        repo
        / "FIX17_ENTRY_CONTRACT_PROVEN.json"
    )


    if not official_source.exists():

        raise Fix17ContractError(
            "FIX17_OFFICIAL_FULL_SOURCE.py がありません"
        )


    if not contract_file.exists():

        raise Fix17ContractError(
            "FIX17_ENTRY_CONTRACT_PROVEN.json がありません"
        )


    actual_sha = sha256_file(
        official_source
    )


    if actual_sha != EXPECTED_FIX17_SHA256:

        raise Fix17ContractError(
            "FIX17 official SHA256 mismatch\n"
            f"Expected: {EXPECTED_FIX17_SHA256}\n"
            f"Actual  : {actual_sha}"
        )


    contract = json.loads(
        contract_file.read_text(
            encoding="utf-8"
        )
    )


    if contract.get("version") != "FIX17":

        raise Fix17ContractError(
            "Contract version != FIX17"
        )


    official = contract.get(
        "official_fix17",
        {}
    )


    if (
        official.get("sha256")
        != EXPECTED_FIX17_SHA256
    ):

        raise Fix17ContractError(
            "Contract SHA256 mismatch"
        )


    if (
        official
        .get(
            "fix17_change_only",
            {}
        )
        .get("fix17")
        != FIX17_LONG_SIZING_RULE
    ):

        raise Fix17ContractError(
            "FIX17 LONG sizing rule mismatch"
        )


    long_conditions = (
        contract
        .get(
            "long_entry_candidate_contract",
            {},
        )
        .get(
            "conditions",
            {},
        )
    )


    if (
        long_conditions
        != LONG_ENTRY_CONTRACT
    ):

        raise Fix17ContractError(
            "LONG entry contract mismatch"
        )


    short_block = contract.get(
        "short_entry_candidate_contract",
        {},
    )


    short_conditions = (
        short_block.get(
            "conditions",
            {}
        )
    )


    if (
        short_conditions
        != SHORT_ENTRY_CONTRACT
    ):

        raise Fix17ContractError(
            "SHORT entry contract mismatch"
        )


    short_crosspass = (
        short_block
        .get(
            "crosspass",
            {},
        )
        .get("status")
    )


    if short_crosspass != "NOT_PROVEN":

        raise Fix17ContractError(
            "SHORT CrossPass proof status mismatch"
        )


    return {

        "version":
            "FIX17",

        "official_sha256":
            actual_sha,

        "long_contract":
            "PASS",

        "short_contract":
            "PASS",

        "short_crosspass":
            "NOT_PROVEN",

        "fix17_long_sizing":
            "PASS",

        "safe_to_load_contract":
            True,

        # --------------------------------------------
        # IMPORTANT
        #
        # This does NOT mean the live trading system
        # is production-ready.
        #
        # It only means the recovered FIX17 contract
        # itself has not drifted.
        # --------------------------------------------

        "production_ready":
            False,
    }


if __name__ == "__main__":

    result = validate_fix17_contract()

    print(
        "★★★★★ FIX17 CONTRACT SAFETY GATE PASS ★★★★★"
    )

    print(
        "SHA256:",
        result["official_sha256"],
    )

    print(
        "LONG:",
        result["long_contract"],
    )

    print(
        "SHORT:",
        result["short_contract"],
    )

    print(
        "SHORT CrossPass:",
        result["short_crosspass"],
    )

    print(
        "FIX17 sizing:",
        result["fix17_long_sizing"],
    )
