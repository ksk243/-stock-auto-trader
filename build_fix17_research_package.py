# ============================================================
# FIX17 RESEARCH PACKAGE BUILDER
#
# PURPOSE
#   Build ONE permanent local-PC research package so future
#   FIX17 experiments do not need repeated GitHub / GCS /
#   Drive source searches.
#
# SOURCE
#   - Current GitHub repository
#   - Current authenticated GCS
#
# DOES NOT
#   - trade
#   - modify paper state
#   - modify FIX17
#   - download Yahoo Finance data
#   - reconstruct ENTRY / EXIT logic
#
# OUTPUT
#   FIX17_RESEARCH.zip
# ============================================================

from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import ast


# ============================================================
# SETTINGS
# ============================================================

ROOT = Path(__file__).resolve().parent

BUILD_ROOT = ROOT / "_fix17_research_build"

PACKAGE_ROOT = BUILD_ROOT / "FIX17_RESEARCH"

ZIP_BASE = ROOT / "FIX17_RESEARCH"

OFFICIAL_NAME = "FIX17_OFFICIAL_FULL_SOURCE.py"

EXPECTED_OFFICIAL_SHA256 = (
    "9598156080b81445e5754c7b0f561389"
    "00862e8fd7f35ac89960491bec7222c4"
)

BUCKET = os.environ.get(
    "GCS_BUCKET",
    "stock-auto-trader-506100-paper",
).strip()


# Known current research contract.
CONTRACT = {
    "official_sha256":
        EXPECTED_OFFICIAL_SHA256,

    "base_reference": {
        "mtm":
            6136042.33,

        "return_pct":
            448.94,

        "max_dd_pct":
            -17.11,

        "trades":
            663,

        "long_trades":
            430,
    },

    "current_leverage": {
        "LONG":
            1.0,

        "SHORT":
            0.5,
    },

    "lot_size":
        100,

    "rules": {
        "official_fix17_read_only":
            True,

        "do_not_reconstruct_fix17":
            True,

        "no_future_required":
            True,

        "experiment_changes_must_be_explicit":
            True,
    },
}


# ============================================================
# HELPERS
# ============================================================

def sha256_file(path):

    h = hashlib.sha256()

    with open(path, "rb") as f:

        while True:

            chunk = f.read(
                1024 * 1024
            )

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def size_mb(path):

    return (
        path.stat().st_size
        /
        1024
        /
        1024
    )


def run_command(
    args,
    check=True,
):

    result = subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if (
        check
        and
        result.returncode != 0
    ):

        raise RuntimeError(
            "\nCOMMAND FAILED\n"
            + " ".join(args)
            + "\n\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )

    return result


def copy_file(
    src,
    dst,
):

    src = Path(src)
    dst = Path(dst)

    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        src,
        dst,
    )


def relative_or_name(path):

    try:

        return str(
            path.relative_to(ROOT)
        )

    except Exception:

        return path.name


# ============================================================
# CLEAN BUILD
# ============================================================

if BUILD_ROOT.exists():

    shutil.rmtree(
        BUILD_ROOT
    )


old_zip = Path(
    str(ZIP_BASE) + ".zip"
)

if old_zip.exists():

    old_zip.unlink()


# ============================================================
# CREATE STRUCTURE
# ============================================================

dirs = [
    PACKAGE_ROOT / "official",
    PACKAGE_ROOT / "runtime_source",
    PACKAGE_ROOT / "master",
    PACKAGE_ROOT / "data" / "gcs",
    PACKAGE_ROOT / "data" / "local",
    PACKAGE_ROOT / "experiments" / "fallback",
    PACKAGE_ROOT / "experiments" / "leverage",
    PACKAGE_ROOT / "experiments" / "entry",
    PACKAGE_ROOT / "experiments" / "exit",
    PACKAGE_ROOT / "results",
    PACKAGE_ROOT / "manifest",
]


for d in dirs:

    d.mkdir(
        parents=True,
        exist_ok=True,
    )


print("=" * 100)
print("FIX17 RESEARCH PACKAGE BUILDER")
print("=" * 100)

print(
    "Repository:",
    ROOT,
)

print(
    "GCS bucket:",
    BUCKET,
)


# ============================================================
# 1. LOCATE OFFICIAL FIX17 IN CURRENT REPOSITORY
# ============================================================

print()
print("=" * 100)
print("1. OFFICIAL FIX17")
print("=" * 100)


official_hits = []


for p in ROOT.rglob(
    OFFICIAL_NAME
):

    if not p.is_file():
        continue

    if BUILD_ROOT in p.parents:
        continue

    official_hits.append(
        p
    )


official_source = None

official_candidates = []


for p in official_hits:

    try:

        sha = sha256_file(
            p
        )

    except Exception:

        continue


    official_candidates.append(
        {
            "path":
                relative_or_name(p),

            "sha256":
                sha,

            "size_mb":
                round(
                    size_mb(p),
                    3,
                ),
        }
    )


    print(
        relative_or_name(p),
        sha,
    )


    if (
        sha
        ==
        EXPECTED_OFFICIAL_SHA256
    ):

        official_source = p


if official_source is None:

    raise RuntimeError(
        "\nOFFICIAL FIX17 NOT FOUND IN REPOSITORY.\n"
        "Expected SHA256:\n"
        + EXPECTED_OFFICIAL_SHA256
        + "\n\n"
        "No replacement was invented."
    )


official_dest = (
    PACKAGE_ROOT
    / "official"
    / OFFICIAL_NAME
)


copy_file(
    official_source,
    official_dest,
)


if (
    sha256_file(
        official_dest
    )
    !=
    EXPECTED_OFFICIAL_SHA256
):

    raise RuntimeError(
        "Copied official FIX17 SHA mismatch"
    )


# Syntax check only.
ast.parse(
    official_dest.read_text(
        encoding="utf-8"
    )
)


print()
print("OFFICIAL FIX17: PASS")
print("Python parse   : PASS")


# ============================================================
# 2. SAVE CURRENT RUNTIME SOURCE
#
# These are useful for understanding the current paper/live
# environment, but they do NOT replace the frozen official.
# ============================================================

print()
print("=" * 100)
print("2. CURRENT RUNTIME SOURCE")
print("=" * 100)


runtime_candidates = [
    ROOT / "paper_trader.py",
    ROOT / "paper_state_store.py",
    ROOT / "fix17_long_candidate_bridge.py",
    ROOT / ".github" / "workflows" / "fix11_paper_trader.py",
]


runtime_manifest = []


for src in runtime_candidates:

    if not src.exists():

        print(
            "MISSING:",
            relative_or_name(src),
        )

        continue


    if src == (
        ROOT
        / ".github"
        / "workflows"
        / "fix11_paper_trader.py"
    ):

        dst = (
            PACKAGE_ROOT
            / "runtime_source"
            / "github_workflows"
            / src.name
        )

    else:

        dst = (
            PACKAGE_ROOT
            / "runtime_source"
            / src.name
        )


    copy_file(
        src,
        dst,
    )


    item = {
        "source_path":
            relative_or_name(src),

        "package_path":
            str(
                dst.relative_to(
                    PACKAGE_ROOT
                )
            ),

        "sha256":
            sha256_file(src),

        "size_mb":
            round(
                size_mb(src),
                3,
            ),
    }


    runtime_manifest.append(
        item
    )


    print(
        "COPIED:",
        item[
            "source_path"
        ],
    )


# ============================================================
# 3. INVENTORY REPOSITORY DATA
# ============================================================

print()
print("=" * 100)
print("3. REPOSITORY DATA INVENTORY")
print("=" * 100)


DATA_EXTENSIONS = {
    ".parquet",
    ".csv",
    ".pkl",
    ".pickle",
    ".feather",
    ".json",
}


local_data_inventory = []


for p in ROOT.rglob("*"):

    if not p.is_file():
        continue

    if BUILD_ROOT in p.parents:
        continue

    if p.suffix.lower() not in DATA_EXTENSIONS:
        continue


    item = {
        "path":
            relative_or_name(p),

        "size_bytes":
            p.stat().st_size,

        "size_mb":
            round(
                size_mb(p),
                3,
            ),
    }


    local_data_inventory.append(
        item
    )


print(
    "Repository data files:",
    len(
        local_data_inventory
    ),
)


# ============================================================
# 4. GCS INVENTORY
#
# This records the complete current object inventory first.
# No assumptions about the correct historical dataset.
# ============================================================

print()
print("=" * 100)
print("4. GCS INVENTORY")
print("=" * 100)


gcs_uri = (
    "gs://"
    + BUCKET
)


result = run_command(
    [
        "gcloud",
        "storage",
        "ls",
        "--recursive",
        gcs_uri,
    ],
    check=False,
)


if result.returncode != 0:

    raise RuntimeError(
        "\nGCS LIST FAILED\n"
        + result.stderr
    )


gcs_objects = []


for raw in result.stdout.splitlines():

    line = raw.strip()

    if not line:
        continue

    if not line.startswith(
        "gs://"
    ):
        continue

    gcs_objects.append(
        line
    )


print(
    "GCS objects:",
    len(
        gcs_objects
    ),
)


# ============================================================
# 5. CLASSIFY GCS OBJECTS
#
# We preserve inventory even for objects not copied.
# Known FIX11/FIX17 1m data are selected conservatively.
# ============================================================

one_minute_objects = []

daily_objects = []

state_objects = []

other_objects = []


for uri in gcs_objects:

    lower = uri.lower()


    if any(
        marker in lower
        for marker in [
            "fix11_forward/snapshots/",
            "fix17/test/",
            "1m",
            "minute",
        ]
    ):

        one_minute_objects.append(
            uri
        )


    elif any(
        marker in lower
        for marker in [
            "daily",
            "feature",
            "atr",
        ]
    ):

        daily_objects.append(
            uri
        )


    elif any(
        marker in lower
        for marker in [
            "portfolio",
            "paper_trades",
            "latest_result",
            "screening_history",
        ]
    ):

        state_objects.append(
            uri
        )


    else:

        other_objects.append(
            uri
        )


print(
    "1m candidates   :",
    len(
        one_minute_objects
    ),
)

print(
    "Daily candidates:",
    len(
        daily_objects
    ),
)

print(
    "State objects   :",
    len(
        state_objects
    ),
)

print(
    "Other objects   :",
    len(
        other_objects
    ),
)


# ============================================================
# 6. SAVE COMPLETE INVENTORY BEFORE COPY
# ============================================================

inventory = {
    "repository_data":
        local_data_inventory,

    "gcs": {
        "bucket":
            BUCKET,

        "all_objects":
            gcs_objects,

        "one_minute_candidates":
            one_minute_objects,

        "daily_candidates":
            daily_objects,

        "state_objects":
            state_objects,

        "other_objects":
            other_objects,
    },
}


inventory_path = (
    PACKAGE_ROOT
    / "manifest"
    / "SOURCE_INVENTORY.json"
)


inventory_path.write_text(
    json.dumps(
        inventory,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)


# ============================================================
# 7. COPY CURRENT REPOSITORY DATA
#
# Small/local data files are preserved exactly.
# ============================================================

print()
print("=" * 100)
print("5. COPY REPOSITORY DATA")
print("=" * 100)


local_copied = []


for item in local_data_inventory:

    src = (
        ROOT
        / item[
            "path"
        ]
    )


    if not src.exists():
        continue


    # Do not duplicate manifests/results generated by this build.
    if BUILD_ROOT in src.parents:
        continue


    dst = (
        PACKAGE_ROOT
        / "data"
        / "local"
        / item[
            "path"
        ]
    )


    copy_file(
        src,
        dst,
    )


    local_copied.append(
        {
            "source":
                item[
                    "path"
                ],

            "package_path":
                str(
                    dst.relative_to(
                        PACKAGE_ROOT
                    )
                ),

            "sha256":
                sha256_file(dst),

            "size_mb":
                item[
                    "size_mb"
                ],
        }
    )


print(
    "Local data copied:",
    len(
        local_copied
    ),
)


# ============================================================
# 8. COPY GCS 1-MINUTE CANDIDATES
#
# The package keeps the original GCS directory structure.
#
# This can be large and may take time.
# ============================================================

print()
print("=" * 100)
print("6. COPY GCS 1-MINUTE DATA")
print("=" * 100)


gcs_data_root = (
    PACKAGE_ROOT
    / "data"
    / "gcs"
)


gcs_data_root.mkdir(
    parents=True,
    exist_ok=True,
)


copied_gcs = []

failed_gcs = []


for idx, uri in enumerate(
    one_minute_objects,
    start=1,
):

    # Remove gs://bucket/
    prefix = (
        "gs://"
        + BUCKET
        + "/"
    )


    if uri.startswith(
        prefix
    ):

        relative = uri[
            len(prefix):
        ]

    else:

        # Safety fallback.
        relative = (
            uri
            .replace(
                "gs://",
                "",
                1,
            )
            .replace(
                "/",
                "_",
            )
        )


    dst = (
        gcs_data_root
        / relative
    )


    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    result = run_command(
        [
            "gcloud",
            "storage",
            "cp",
            uri,
            str(dst),
        ],
        check=False,
    )


    if (
        result.returncode == 0
        and
        dst.exists()
    ):

        copied_gcs.append(
            {
                "source":
                    uri,

                "package_path":
                    str(
                        dst.relative_to(
                            PACKAGE_ROOT
                        )
                    ),

                "sha256":
                    sha256_file(
                        dst
                    ),

                "size_mb":
                    round(
                        size_mb(
                            dst
                        ),
                        3,
                    ),
            }
        )

    else:

        failed_gcs.append(
            {
                "source":
                    uri,

                "stderr":
                    result.stderr[-1000:],
            }
        )


    if (
        idx % 10 == 0
        or
        idx == len(
            one_minute_objects
        )
    ):

        print(
            f"{idx}/{len(one_minute_objects)} "
            f"copied={len(copied_gcs)} "
            f"failed={len(failed_gcs)}"
        )


# ============================================================
# 9. COPY GCS DAILY CANDIDATES
# ============================================================

print()
print("=" * 100)
print("7. COPY GCS DAILY / FEATURE DATA")
print("=" * 100)


copied_daily = []


for idx, uri in enumerate(
    daily_objects,
    start=1,
):

    prefix = (
        "gs://"
        + BUCKET
        + "/"
    )


    if uri.startswith(
        prefix
    ):

        relative = uri[
            len(prefix):
        ]

    else:

        relative = (
            "daily_"
            + str(idx)
        )


    dst = (
        gcs_data_root
        / relative
    )


    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    result = run_command(
        [
            "gcloud",
            "storage",
            "cp",
            uri,
            str(dst),
        ],
        check=False,
    )


    if (
        result.returncode == 0
        and
        dst.exists()
    ):

        copied_daily.append(
            {
                "source":
                    uri,

                "package_path":
                    str(
                        dst.relative_to(
                            PACKAGE_ROOT
                        )
                    ),

                "sha256":
                    sha256_file(
                        dst
                    ),

                "size_mb":
                    round(
                        size_mb(
                            dst
                        ),
                        3,
                    ),
            }
        )


print(
    "Daily/feature copied:",
    len(
        copied_daily
    ),
)


# ============================================================
# 10. CONTRACT
# ============================================================

print()
print("=" * 100)
print("8. CREATE RESEARCH CONTRACT")
print("=" * 100)


contract_path = (
    PACKAGE_ROOT
    / "master"
    / "FIX17_CONTRACT.json"
)


contract_path.write_text(
    json.dumps(
        CONTRACT,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)


# ============================================================
# 11. PERMANENT RESEARCH MASTER
#
# Does NOT reimplement FIX17.
# It verifies the frozen source and provides stable local paths.
# ============================================================

master_source = r'''# ============================================================
# FIX17 RESEARCH MASTER
#
# Permanent local entry point for FIX17 research.
#
# This does NOT reconstruct FIX17.
# ============================================================

from pathlib import Path
import hashlib
import json
import runpy


ROOT = Path(__file__).resolve().parents[1]

OFFICIAL = (
    ROOT
    / "official"
    / "FIX17_OFFICIAL_FULL_SOURCE.py"
)

CONTRACT_FILE = (
    ROOT
    / "master"
    / "FIX17_CONTRACT.json"
)

DATA_ROOT = (
    ROOT
    / "data"
)

RESULTS_ROOT = (
    ROOT
    / "results"
)

EXPERIMENTS_ROOT = (
    ROOT
    / "experiments"
)


def sha256_file(path):

    h = hashlib.sha256()

    with open(path, "rb") as f:

        while True:

            chunk = f.read(
                1024 * 1024
            )

            if not chunk:
                break

            h.update(chunk)

    return h.hexdigest()


def load_contract():

    return json.loads(
        CONTRACT_FILE.read_text(
            encoding="utf-8"
        )
    )


def verify_official():

    contract = load_contract()

    expected = contract[
        "official_sha256"
    ]

    if not OFFICIAL.exists():

        raise RuntimeError(
            "Official FIX17 missing: "
            + str(OFFICIAL)
        )

    actual = sha256_file(
        OFFICIAL
    )

    if actual != expected:

        raise RuntimeError(
            "\nFIX17 OFFICIAL SHA256 MISMATCH\n"
            f"Expected: {expected}\n"
            f"Actual  : {actual}\n"
            "Research stopped."
        )

    return actual


def load_fix17():

    verify_official()

    return runpy.run_path(
        str(OFFICIAL),
        run_name="__fix17_research__",
    )


def paths():

    return {
        "root":
            ROOT,

        "official":
            OFFICIAL,

        "data":
            DATA_ROOT,

        "results":
            RESULTS_ROOT,

        "experiments":
            EXPERIMENTS_ROOT,
    }


def status():

    contract = load_contract()

    return {
        "status":
            "READY",

        "official_sha256":
            verify_official(),

        "base_reference":
            contract[
                "base_reference"
            ],

        "long_leverage":
            contract[
                "current_leverage"
            ][
                "LONG"
            ],

        "short_leverage":
            contract[
                "current_leverage"
            ][
                "SHORT"
            ],

        "lot_size":
            contract[
                "lot_size"
            ],
    }


if __name__ == "__main__":

    print("=" * 80)
    print("FIX17 RESEARCH MASTER")
    print("=" * 80)

    for key, value in status().items():

        print(
            f"{key}: {value}"
        )

    print()
    print("Paths:")

    for key, value in paths().items():

        print(
            f"{key}: {value}"
        )
'''


master_path = (
    PACKAGE_ROOT
    / "master"
    / "FIX17_RESEARCH_MASTER.py"
)


master_path.write_text(
    master_source,
    encoding="utf-8",
)


ast.parse(
    master_source
)


# ============================================================
# 12. README
# ============================================================

readme = """FIX17 RESEARCH

このフォルダを今後のFIX17研究の固定起点として使用する。

============================================================
絶対ルール
============================================================

1. official/FIX17_OFFICIAL_FULL_SOURCE.py は変更しない。

2. 正式FIX17 SHA256:
   9598156080b81445e5754c7b0f56138900862e8fd7f35ac89960491bec7222c4

3. FIX17を検証のたびに再構築しない。

4. ENTRY / EXITを変更する実験では、
   変更点をexperimentsへ明示的に保存する。

5. No-Futureを維持する。

6. results/ に各比較結果を保存する。

============================================================
現在の基準
============================================================

LONG leverage : 1.0
SHORT leverage: 0.5
LOT           : 100

参考BASE:
MTM      6,136,042.33
Return   +448.94%
MaxDD    -17.11%
Trades   663
LONG     430

============================================================
最初の実験
============================================================

fallback/

BASE:
1位候補が100株建てられなければ、そのSideは取引なし。

TEST:
1位候補が100株建てられない場合、
正式順位を維持したまま2位、3位...と確認し、
最初に100株以上建てられる候補を採用する。

============================================================
今後
============================================================

このローカルパッケージを起点にする。
GitHub / Drive / GCSからFIX17を毎回探し直さない。
"""


(
    PACKAGE_ROOT
    / "README.txt"
).write_text(
    readme,
    encoding="utf-8",
)


# ============================================================
# 13. FINAL MANIFEST
# ============================================================

manifest = {
    "created_at":
        datetime.now().isoformat(),

    "official": {
        "source":
            relative_or_name(
                official_source
            ),

        "sha256":
            EXPECTED_OFFICIAL_SHA256,

        "size_mb":
            round(
                size_mb(
                    official_dest
                ),
                3,
            ),
    },

    "official_candidates":
        official_candidates,

    "runtime_source":
        runtime_manifest,

    "repository_data_copied":
        local_copied,

    "gcs": {
        "bucket":
            BUCKET,

        "objects_total":
            len(
                gcs_objects
            ),

        "one_minute_candidates":
            len(
                one_minute_objects
            ),

        "one_minute_copied":
            len(
                copied_gcs
            ),

        "one_minute_failed":
            failed_gcs,

        "daily_candidates":
            len(
                daily_objects
            ),

        "daily_copied":
            len(
                copied_daily
            ),
    },

    "contract":
        CONTRACT,

    "status":
        (
            "PASS"
            if not failed_gcs
            else "PASS_WITH_GCS_COPY_FAILURES"
        ),
}


manifest_path = (
    PACKAGE_ROOT
    / "manifest"
    / "FIX17_RESEARCH_MANIFEST.json"
)


manifest_path.write_text(
    json.dumps(
        manifest,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)


# ============================================================
# 14. PACKAGE SELF-CHECK
# ============================================================

print()
print("=" * 100)
print("9. PACKAGE SELF-CHECK")
print("=" * 100)


if (
    sha256_file(
        official_dest
    )
    !=
    EXPECTED_OFFICIAL_SHA256
):

    raise RuntimeError(
        "FINAL official SHA check failed"
    )


if not master_path.exists():

    raise RuntimeError(
        "Research master missing"
    )


if not contract_path.exists():

    raise RuntimeError(
        "Contract missing"
    )


if not manifest_path.exists():

    raise RuntimeError(
        "Manifest missing"
    )


print("Official SHA : PASS")
print("Master       : PASS")
print("Contract     : PASS")
print("Manifest     : PASS")


# ============================================================
# 15. ZIP
# ============================================================

print()
print("=" * 100)
print("10. CREATE FIX17_RESEARCH.zip")
print("=" * 100)


zip_path = Path(
    shutil.make_archive(
        str(
            ZIP_BASE
        ),
        "zip",
        root_dir=str(
            BUILD_ROOT
        ),
        base_dir="FIX17_RESEARCH",
    )
)


zip_sha = sha256_file(
    zip_path
)


print()
print(
    "ZIP:",
    zip_path
)

print(
    "ZIP size:",
    f"{size_mb(zip_path):,.2f} MB",
)

print(
    "ZIP SHA256:",
    zip_sha,
)


# ============================================================
# FINAL
# ============================================================

print()
print("=" * 100)
print("FIX17 RESEARCH PACKAGE COMPLETE")
print("=" * 100)

print(
    "Official FIX17      : PASS"
)

print(
    "Official SHA256     :",
    EXPECTED_OFFICIAL_SHA256,
)

print(
    "Runtime source files:",
    len(
        runtime_manifest
    ),
)

print(
    "GCS objects         :",
    len(
        gcs_objects
    ),
)

print(
    "1m objects copied   :",
    len(
        copied_gcs
    ),
    "/",
    len(
        one_minute_objects
    ),
)

print(
    "Daily objects copied:",
    len(
        copied_daily
    ),
    "/",
    len(
        daily_objects
    ),
)

print(
    "GCS copy failures   :",
    len(
        failed_gcs
    ),
)

print()
print(
    "PC保存用:"
)

print(
    zip_path
)

print()
print(
    "今後の固定起点:"
)

print(
    "FIX17_RESEARCH/master/FIX17_RESEARCH_MASTER.py"
)
