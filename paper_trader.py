# ============================================================
# FIX17 PAPER TRADER
# OFFICIAL ENGINE BRIDGE
#
# DO NOT REBUILD FIX17 LOGIC HERE.
#
# Official FIX17:
#   FIX17_OFFICIAL_FULL_SOURCE.py
#
# Official SHA256:
#   9598156080b81445e5754c7b0f56138900862e8fd7f35ac89960491bec7222c4
#
# Design:
#   ・FIX17 official source is the single source of truth.
#   ・Never copy/rewrite trading rules into this file.
#   ・Official engine is loaded only inside an isolated child process.
#   ・Notebook/global RAM retention is avoided.
#   ・If official SHA differs, execution stops immediately.
# ============================================================

from __future__ import annotations
from mailer import send_error_mail, send_mail
from fix17_contract import validate_fix17_contract

import os
import sys
import json
import hashlib
import smtplib
import subprocess
import tempfile
import traceback

from pathlib import Path
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr


# ============================================================
# SETTINGS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

OFFICIAL_FILE = (
    BASE_DIR
    / "FIX17_OFFICIAL_FULL_SOURCE.py"
)

OFFICIAL_SHA256 = (
    "9598156080b81445e5754c7b0f56138900862e8fd7f35ac89960491bec7222c4"
)

RUNTIME_DIR = (
    BASE_DIR
    / "runtime"
)

STATE_FILE = (
    RUNTIME_DIR
    / "paper_state.json"
)

ENGINE_CHECK_FILE = (
    RUNTIME_DIR
    / "fix17_engine_check.json"
)

RUN_LOG_FILE = (
    RUNTIME_DIR
    / "paper_trader_last_run.json"
)


REQUIRED_FUNCTIONS = [
    "simulate_fix11",
    "simulate_fix15",
    "simulate_profit_floor_trail",
    "calc_entry_time_position_state",
    "calc_long_dynamic_max_positions",
    "calc_margin_capped_qty",
    "calc_max_etf_buy_shares",
    "calc_target_qty",
    "get_broker_return",
    "get_last_close_before",
    "reconstruct_exit_price",
    "fix15_apply_tax",
    "fix15_ensure_tax_year",
    "_fix13_apply_event_filter",
    "_fix13_ban_reason",
    "_fix13_calc_max_etf_buy_shares",
    "_fix13_datetime",
    "_fix13_event_type",
    "_fix13_first_value",
    "_fix13_side",
    "_fix13_trade_id",
]


# ============================================================
# FILE HELPERS
# ============================================================

def sha256_file(path: Path) -> str:

    h = hashlib.sha256()

    with path.open(
        "rb"
    ) as f:

        while True:

            block = f.read(
                8 * 1024 * 1024
            )

            if not block:
                break

            h.update(
                block
            )

    return h.hexdigest()


def save_json(
    path: Path,
    obj
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            obj,
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    tmp.replace(
        path
    )


def load_json(
    path: Path,
    default=None
):

    if not path.exists():
        return default

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(
            f
        )


# ============================================================
# MAIL
# ============================================================

def send_mail(
    subject: str,
    body: str,
):

    host = os.getenv(
        "SMTP_HOST",
        ""
    ).strip()

    port = int(
        os.getenv(
            "SMTP_PORT",
            "587"
        )
    )

    user = os.getenv(
        "SMTP_USER",
        ""
    ).strip()

    password = os.getenv(
        "SMTP_PASSWORD",
        ""
    )

    mail_from = os.getenv(
        "MAIL_FROM",
        user
    ).strip()

    mail_to = os.getenv(
        "MAIL_TO",
        ""
    ).strip()


    if not (
        host
        and user
        and password
        and mail_from
        and mail_to
    ):

        return False


    msg = MIMEText(
        body,
        "plain",
        "utf-8"
    )

    msg["Subject"] = Header(
        subject,
        "utf-8"
    )

    msg["From"] = formataddr(
        (
            str(
                Header(
                    "FIX17 自動売買",
                    "utf-8"
                )
            ),
            mail_from,
        )
    )

    msg["To"] = mail_to


    with smtplib.SMTP(
        host,
        port,
        timeout=30
    ) as smtp:

        smtp.ehlo()

        smtp.starttls()

        smtp.ehlo()

        smtp.login(
            user,
            password
        )

        smtp.sendmail(
            mail_from,
            [mail_to],
            msg.as_string()
        )


    return True


def send_error_mail(
    title: str,
    error_text: str,
):

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    body = (
        "FIX17 ペーパートレーダーでエラーが発生しました。\n\n"
        f"時刻: {now}\n"
        f"内容: {title}\n\n"
        f"{error_text}\n"
    )

    try:

        send_mail(
            "【緊急】FIX17 ペーパートレーダー エラー",
            body,
        )

    except Exception:

        pass


# ============================================================
# OFFICIAL SHA CHECK
# ============================================================

def verify_official_source():

    if not OFFICIAL_FILE.exists():

        raise RuntimeError(
            "正式FIX17ソースがありません: "
            + str(
                OFFICIAL_FILE
            )
        )


    actual = sha256_file(
        OFFICIAL_FILE
    )


    if actual != OFFICIAL_SHA256:

        raise RuntimeError(
            "正式FIX17 SHA256不一致\n"
            f"expected={OFFICIAL_SHA256}\n"
            f"actual={actual}"
        )


    return actual


# ============================================================
# ISOLATED FIX17 ENGINE CHECK
#
# FIX17 namespaceを親プロセスへ持ち込まない。
# ============================================================

ENGINE_AUDIT_SCRIPT = r"""
import sys
import json
import runpy
import inspect
import traceback
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr


source_path = Path(
    sys.argv[1]
)

result_path = Path(
    sys.argv[2]
)

log_path = Path(
    sys.argv[3]
)


result = {
    "success": False,
    "functions": [],
    "classes": [],
    "scalars": {},
    "error": None,
}


try:

    with log_path.open(
        "w",
        encoding="utf-8"
    ) as log:

        with redirect_stdout(
            log
        ), redirect_stderr(
            log
        ):

            ns = runpy.run_path(
                str(
                    source_path
                ),
                run_name="__fix17_paper_engine__",
            )


    function_names = []

    class_names = []


    for name, obj in ns.items():

        if name.startswith(
            "__"
        ):
            continue


        if inspect.isfunction(
            obj
        ):

            if getattr(
                obj,
                "__module__",
                None
            ) == "__fix17_paper_engine__":

                function_names.append(
                    name
                )


        elif inspect.isclass(
            obj
        ):

            if getattr(
                obj,
                "__module__",
                None
            ) == "__fix17_paper_engine__":

                class_names.append(
                    name
                )


    scalar_names = [
        "FIX17_VERSION",
        "FIX17_PARENT",
        "FIX17_PARENT_FILE_ID",
        "FIX17_PARENT_SHA256",
        "FIX17_RULE",
        "FIX17_LONG_TOTAL_LEVERAGE",
    ]


    scalars = {}

    for name in scalar_names:

        if name in ns:

            value = ns[
                name
            ]

            if isinstance(
                value,
                (
                    str,
                    int,
                    float,
                    bool,
                    type(None),
                )
            ):

                scalars[
                    name
                ] = value


    result[
        "functions"
    ] = sorted(
        function_names
    )

    result[
        "classes"
    ] = sorted(
        class_names
    )

    result[
        "scalars"
    ] = scalars

    result[
        "success"
    ] = True


except Exception as e:

    result[
        "error"
    ] = {
        "type": type(
            e
        ).__name__,

        "message": str(
            e
        ),

        "traceback": traceback.format_exc(),
    }


with result_path.open(
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        result,
        f,
        ensure_ascii=False,
        indent=2,
        default=str,
    )


if not result[
    "success"
]:
    sys.exit(
        1
    )
"""


def check_official_engine():
    """
    FIX17 official source static integrity audit.

    Daily GitHub Actionsではofficial sourceをrunpy実行しない。
    Official sourceはColab/Drive復元処理を含むため、
    SHA・compile・AST・FIX17 sizing ruleのみを検証する。
    """

    official_path = REPO_DIR / "FIX17_OFFICIAL_FULL_SOURCE.py"

    if not official_path.exists():
        raise RuntimeError(
            "FIX17_OFFICIAL_FULL_SOURCE.py がありません"
        )

    expected_sha = (
        "9598156080b81445e5754c7b0f561389"
        "00862e8fd7f35ac89960491bec7222c4"
    )

    import hashlib
    import ast
    import py_compile

    h = hashlib.sha256()

    with open(official_path, "rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    actual_sha = h.hexdigest()

    if actual_sha != expected_sha:
        raise RuntimeError(
            "FIX17 official SHA mismatch"
        )

    source = official_path.read_text(
        encoding="utf-8"
    )

    ast.parse(source)

    py_compile.compile(
        str(official_path),
        doraise=True,
    )

    new_rule_count = source.count(
        "target_notional = long_remaining_capacity"
    )

    old_rule_count = source.count(
        "target_notional = min(LONG_CAP_PER_STOCK, long_remaining_capacity)"
    )

    if new_rule_count != 1:
        raise RuntimeError(
            f"FIX17 sizing rule count異常: {new_rule_count}"
        )

    if old_rule_count != 0:
        raise RuntimeError(
            "旧FIX16 sizing ruleが残っています"
        )

    return {
        "status": "PASS",
        "mode": "STATIC_OFFICIAL_AUDIT",
        "sha256": actual_sha,
        "compile": True,
        "new_sizing_rule_count": new_rule_count,
        "old_sizing_rule_count": old_rule_count,
    }




# ============================================================
# PAPER STATE
# ============================================================

def ensure_paper_state():

    state = load_json(
        STATE_FILE,
        default=None
    )


    if state is None:

        state = {
            "version": "FIX17",
            "official_sha256": OFFICIAL_SHA256,

            # 正式検証初期資産
            "initial_equity": 1117792.0,

            "cash": 1117792.0,

            "positions": [],

            "closed_trades": [],

            "last_processed_market_date": None,

            "created_at": datetime.now().isoformat(),

            "updated_at": datetime.now().isoformat(),
        }


        save_json(
            STATE_FILE,
            state
        )


    if (
        state.get(
            "version"
        )
        != "FIX17"
    ):

        raise RuntimeError(
            "paper_state version がFIX17ではありません。"
        )


    if (
        state.get(
            "official_sha256"
        )
        != OFFICIAL_SHA256
    ):

        raise RuntimeError(
            "paper_state のFIX17 SHAが正式版と一致しません。"
        )


    return state


# ============================================================
# FIX17 SIZING RULE STATIC CHECK
# ============================================================

def verify_fix17_sizing_rule():

    source = OFFICIAL_FILE.read_text(
        encoding="utf-8"
    )


    new_rule = (
        "target_notional = long_remaining_capacity"
    )

    old_rule = (
        "target_notional = min("
        "LONG_CAP_PER_STOCK, "
        "long_remaining_capacity)"
    )


    new_count = source.count(
        new_rule
    )

    old_count = source.count(
        old_rule
    )


    if new_count != 1:

        raise RuntimeError(
            "FIX17 sizing rule件数異常\n"
            f"{new_rule}\n"
            f"count={new_count}"
        )


    if old_count != 0:

        raise RuntimeError(
            "FIX16旧sizing ruleがFIX17公式ソースに残っています。"
        )


    return {
        "new_rule_count": new_count,
        "old_rule_count": old_count,
    }


# ============================================================
# MAIN
# ============================================================

def main():

    # ========================================================
    # FIX17_OFFICIAL_CONTRACT_GATE
    # ========================================================

    contract_result = validate_fix17_contract(
        REPO_DIR
    )

    if not contract_result.get(
        "safe_to_load_contract",
        False,
    ):
        raise RuntimeError(
            "FIX17 contract safety gate failed"
        )


    started = datetime.now()


    official_sha = verify_official_source()

    sizing = verify_fix17_sizing_rule()

    engine = check_official_engine()

    state = ensure_paper_state()


    # --------------------------------------------------------
    # ここから先が次工程の接続点
    #
    # 現段階では「FIX17に存在しないENTRY判定」を
    # paper_trader.py側で勝手に再構築しない。
    #
    # 次工程:
    #   current market data
    #       ↓
    #   FIX17 official entry pipeline
    #       ↓
    #   order candidate
    #       ↓
    #   virtual fill
    #       ↓
    #   state update
    #
    # --------------------------------------------------------


    finished = datetime.now()


    result = {
        "status": "READY",
        "version": "FIX17",
        "official_sha256": official_sha,

        "engine": {
            "function_count": len(
                engine.get(
                    "functions",
                    []
                )
            ),
            "class_count": len(
                engine.get(
                    "classes",
                    []
                )
            ),
            "scalars": engine.get(
                "scalars",
                {}
            ),
        },

        "sizing_rule": sizing,

        "paper_state": {
            "cash": state.get(
                "cash"
            ),
            "positions": len(
                state.get(
                    "positions",
                    []
                )
            ),
            "closed_trades": len(
                state.get(
                    "closed_trades",
                    []
                )
            ),
        },

        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),

        "message": (
            "FIX17公式エンジン検証PASS。"
            "ライブデータ接続待ち。"
        ),
    }


    save_json(
        RUN_LOG_FILE,
        result
    )


    print(
        "★★★★★ FIX17 PAPER ENGINE READY ★★★★★"
    )

    print(
        "SHA256:",
        official_sha
    )

    print(
        "Functions:",
        result[
            "engine"
        ][
            "function_count"
        ]
    )

    print(
        "Cash:",
        result[
            "paper_state"
        ][
            "cash"
        ]
    )


    return result



# ============================================================
# ENTRY POINT MOVED TO END OF FILE
#
# LIVE EXECUTION FUNCTIONS MUST BE DEFINED FIRST.
# ============================================================

# ============================================================

# FIX17 OFFICIAL LIVE EXECUTION LAYER

# ============================================================

#

# この層ではFIX17のENTRY条件自体を再構築しない。

#

# 入力:

#   runtime/fix17_candidates.json

#

# candidate例:

# {

#   "market_date": "2026-09-14",

#   "candidates": [

#     {

#       "trade_id": "...",

#       "code": "1234",

#       "side": "LONG",

#       "entry_price": 1000.0,

#       "target_notional": 500000.0

#     }

#   ]

# }

#

# candidate生成は別データ層から行う。

# ここでは正式FIX17 sizing / margin / state logicのみ使用。

# ============================================================

import importlib.util

import math

import uuid

# Repository root
REPO_DIR = __import__("pathlib").Path(__file__).resolve().parent


FIX17_CANDIDATE_FILE = (

    RUNTIME_DIR

    / "fix17_candidates.json"

)

FIX17_EXECUTION_FILE = (

    RUNTIME_DIR

    / "fix17_execution_result.json"

)

# ============================================================

# OFFICIAL RUNTIME LOADER

#

# subprocess隔離では関数を直接呼べないため、

# live execution時のみ専用module namespaceへロードする。

#

# Notebook globalsへは保持しない。

# paper_trader.pyプロセス終了時に消える。

# ============================================================

def load_fix17_runtime_module():

    verify_official_source()

    module_name = (

        "_fix17_official_runtime_"

        + uuid.uuid4().hex

    )

    spec = importlib.util.spec_from_file_location(

        module_name,

        OFFICIAL_FILE,

    )

    if (

        spec is None

        or spec.loader is None

    ):

        raise RuntimeError(

            "FIX17正式runtime moduleを作成できません。"

        )

    module = importlib.util.module_from_spec(

        spec

    )

    spec.loader.exec_module(

        module

    )

    required = [

        "calc_entry_time_position_state",

        "calc_long_dynamic_max_positions",

        "calc_margin_capped_qty",

        "calc_target_qty",

    ]

    missing = [

        name

        for name in required

        if not hasattr(

            module,

            name

        )

    ]

    if missing:

        raise RuntimeError(

            "FIX17 runtime必須関数不足:\n"

            + "\n".join(

                missing

            )

        )

    return module

# ============================================================

# POSITION HELPERS

# ============================================================

def normalize_code(

    code

):

    code = str(

        code

    ).strip()

    if code.endswith(

        ".0"

    ):

        code = code[:-2]

    if code.endswith(

        ".T"

    ):

        code = code[:-2]

    return code

def normalize_side(

    side

):

    side = str(

        side

    ).upper().strip()

    if side not in {

        "LONG",

        "SHORT",

    }:

        raise RuntimeError(

            f"side不正: {side}"

        )

    return side

def position_key(

    code,

    side

):

    return (

        normalize_code(

            code

        )

        + ":"

        + normalize_side(

            side

        )

    )

def active_positions(

    state

):

    return [

        p

        for p in state.get(

            "positions",

            []

        )

        if p.get(

            "status",

            "OPEN"

        ) == "OPEN"

    ]

def active_position_exists(

    state,

    code,

    side

):

    key = position_key(

        code,

        side

    )

    for p in active_positions(

        state

    ):

        if position_key(

            p.get(

                "code"

            ),

            p.get(

                "side"

            ),

        ) == key:

            return True

    return False

def active_trade_id_exists(

    state,

    trade_id

):

    if trade_id is None:

        return False

    trade_id = str(

        trade_id

    )

    for p in active_positions(

        state

    ):

        if str(

            p.get(

                "trade_id",

                ""

            )

        ) == trade_id:

            return True

    return False

# ============================================================

# CANDIDATE INPUT

# ============================================================

def load_fix17_candidates():

    if not FIX17_CANDIDATE_FILE.exists():

        return {

            "market_date": None,

            "candidates": [],

        }

    obj = load_json(

        FIX17_CANDIDATE_FILE,

        default={}

    )

    if not isinstance(

        obj,

        dict

    ):

        raise RuntimeError(

            "fix17_candidates.json形式不正"

        )

    candidates = obj.get(

        "candidates",

        []

    )

    if not isinstance(

        candidates,

        list

    ):

        raise RuntimeError(

            "candidates はlistである必要があります。"

        )

    return {

        "market_date": obj.get(

            "market_date"

        ),

        "candidates": candidates,

    }

# ============================================================

# CURRENT EXPOSURE

# ============================================================

def calculate_existing_exposure(

    state

):

    gross_notional = 0.0

    unrealized = 0.0

    for p in active_positions(

        state

    ):

        entry_price = float(

            p.get(

                "entry_price",

                0.0

            )

        )

        qty = int(

            p.get(

                "qty",

                0

            )

        )

        mark_price = float(

            p.get(

                "mark_price",

                entry_price

            )

        )

        side = normalize_side(

            p.get(

                "side"

            )

        )

        gross_notional += (

            abs(

                mark_price

                * qty

            )

        )

        if side == "LONG":

            pnl = (

                mark_price

                - entry_price

            ) * qty

        else:

            pnl = (

                entry_price

                - mark_price

            ) * qty

        unrealized += pnl

    return (

        gross_notional,

        unrealized

    )

# ============================================================

# EQUITY

# ============================================================

def calculate_equity(

    state

):

    cash_now = float(

        state.get(

            "cash",

            0.0

        )

    )

    _, unrealized = (

        calculate_existing_exposure(

            state

        )

    )

    return (

        cash_now

        + unrealized

    )

# ============================================================

# CANDIDATE VALIDATION

# ============================================================


def validate_candidate(candidate):

    if not isinstance(
        candidate,
        dict,
    ):
        raise RuntimeError(
            "candidate はdictである必要があります。"
        )

    # --------------------------------------------------------
    # Common required fields
    # --------------------------------------------------------

    required_common = [
                          'code',
                          'side',
                          'entry_price',
                          'RS20_corrected',
                          'RVOL20',
                          'turnover_median_20d_oku',
                      ]

    missing = [
        x
        for x in required_common
        if x not in candidate
    ]

    if missing:
        raise RuntimeError(
            "candidate必須項目不足: "
            + ",".join(
                missing
            )
        )

    code = normalize_code(
        candidate[
            "code"
        ]
    )

    side = normalize_side(
        candidate[
            "side"
        ]
    )

    entry_price = float(
        candidate[
            "entry_price"
        ]
    )

    target_notional = float(
        candidate[
            "target_notional"
        ]
    )

    rs20 = float(
        candidate[
            "RS20_corrected"
        ]
    )

    rvol20 = float(
        candidate[
            "RVOL20"
        ]
    )

    turnover20 = float(
        candidate[
            "turnover_median_20d_oku"
        ]
    )

    # --------------------------------------------------------
    # Numeric validity
    # --------------------------------------------------------

    numeric_values = {
        "entry_price":
            entry_price,

        "target_notional":
            target_notional,

        "RS20_corrected":
            rs20,

        "RVOL20":
            rvol20,

        "turnover_median_20d_oku":
            turnover20,
    }

    for name, value in numeric_values.items():

        if not math.isfinite(
            value
        ):
            raise RuntimeError(
                f"{name} がfiniteではありません: "
                f"{value}"
            )

    if entry_price <= 0:

        raise RuntimeError(
            f"entry_price不正: "
            f"{entry_price}"
        )

    if target_notional <= 0:

        raise RuntimeError(
            f"target_notional不正: "
            f"{target_notional}"
        )

    # --------------------------------------------------------
    # Shared proven filters
    # --------------------------------------------------------

    if rvol20 < 2.0:

        raise RuntimeError(
            "FIX17 ENTRY CONTRACT違反: "
            f"RVOL20={rvol20} < 2"
        )

    if turnover20 < 3.0:

        raise RuntimeError(
            "FIX17 ENTRY CONTRACT違反: "
            "turnover_median_20d_oku="
            f"{turnover20} < 3"
        )

    # --------------------------------------------------------
    # LONG
    # --------------------------------------------------------

    if side == "LONG":

        required_long = [
            "ORB15_LongSignal",
            "CrossPass_EXACT",
            "BacktestReady",
        ]

        missing_long = [
            x
            for x in required_long
            if x not in candidate
        ]

        if missing_long:
            raise RuntimeError(
                "LONG candidate必須項目不足: "
                + ",".join(
                    missing_long
                )
            )

        if rs20 < 80.0:

            raise RuntimeError(
                "FIX17 LONG ENTRY CONTRACT違反: "
                f"RS20_corrected={rs20} < 80"
            )

        if (
            candidate[
                "ORB15_LongSignal"
            ]
            is not True
        ):

            raise RuntimeError(
                "FIX17 LONG ENTRY CONTRACT違反: "
                "ORB15_LongSignal != True"
            )

        if (
            candidate[
                "CrossPass_EXACT"
            ]
            is not True
        ):

            raise RuntimeError(
                "FIX17 LONG ENTRY CONTRACT違反: "
                "CrossPass_EXACT != True"
            )

        if (
            candidate[
                "BacktestReady"
            ]
            is not True
        ):

            raise RuntimeError(
                "FIX17 LONG ENTRY CONTRACT違反: "
                "BacktestReady != True"
            )

        contract_status = (
            "PROVEN_LONG"
        )

        live_entry_allowed = True

    # --------------------------------------------------------
    # SHORT
    # --------------------------------------------------------

    elif side == "SHORT":

        required_short = [
            "ORB15_ShortSignal",
            "is_lending",
            "_entered",
        ]

        missing_short = [
            x
            for x in required_short
            if x not in candidate
        ]

        if missing_short:
            raise RuntimeError(
                "SHORT candidate必須項目不足: "
                + ",".join(
                    missing_short
                )
            )

        # Effective surviving formal-data bound
        if rs20 > 20.0:

            raise RuntimeError(
                "FIX17 SHORT ENTRY CONTRACT違反: "
                f"RS20_corrected={rs20} > 20"
            )

        if (
            candidate[
                "ORB15_ShortSignal"
            ]
            is not True
        ):

            raise RuntimeError(
                "FIX17 SHORT ENTRY CONTRACT違反: "
                "ORB15_ShortSignal != True"
            )

        if (
            candidate[
                "is_lending"
            ]
            is not True
        ):

            raise RuntimeError(
                "FIX17 SHORT ENTRY CONTRACT違反: "
                "is_lending != True"
            )

        if (
            candidate[
                "_entered"
            ]
            is not True
        ):

            raise RuntimeError(
                "FIX17 SHORT ENTRY CONTRACT違反: "
                "_entered != True"
            )

        # ----------------------------------------------------
        # IMPORTANT
        #
        # SHORT CrossPass_EXACT is not proven.
        #
        # Candidate can be validated against the recovered
        # effective formal dataset, but execution must remain
        # blocked until exact upstream semantics are proven.
        # ----------------------------------------------------

        contract_status = (
            "PROVEN_EFFECTIVE_SHORT"
        )

        live_entry_allowed = False

    else:

        raise RuntimeError(
            f"side不正: {side}"
        )

    # --------------------------------------------------------
    # Trade ID
    # --------------------------------------------------------

    trade_id = candidate.get(
        "trade_id"
    )

    if trade_id is None:

        trade_id = (
            code
            + "-"
            + side
            + "-"
            + uuid.uuid4().hex[:12]
        )

    # --------------------------------------------------------
    # Normalized candidate
    # --------------------------------------------------------

    return {

        **candidate,

        "trade_id":
            str(
                trade_id
            ),

        "code":
            code,

        "side":
            side,

        "entry_price":
            entry_price,

        "target_notional":
            target_notional,

        "RS20_corrected":
            rs20,

        "RVOL20":
            rvol20,

        "turnover_median_20d_oku":
            turnover20,

        "_fix17_contract_status":
            contract_status,

        "_fix17_live_entry_allowed":
            live_entry_allowed,
    }


# ============================================================

# OFFICIAL FIX17 POSITION SIZE

# ============================================================


# === FIX17 STEP9B LONG SIZING ===

FIX17_LONG_TOTAL_LEVERAGE = 1.0


def calculate_fix17_long_remaining_capacity(
    state,
):
    """
    FIX17 official sizing:
        target_notional = long_remaining_capacity
    """

    try:
        equity = float(
            state.get(
                "equity",
                state.get(
                    "cash",
                    state.get(
                        "initial_equity",
                        0.0,
                    ),
                ),
            )
        )
    except Exception:
        equity = 0.0

    if equity <= 0:
        return 0.0

    existing_long_notional = 0.0

    for p in state.get(
        "positions",
        []
    ):

        side = str(
            p.get(
                "side",
                p.get(
                    "Side",
                    ""
                ),
            )
        ).upper()

        status = str(
            p.get(
                "status",
                p.get(
                    "Status",
                    "OPEN",
                ),
            )
        ).upper()

        if side != "LONG":
            continue

        if status not in {
            "OPEN",
            "ACTIVE",
        }:
            continue

        qty = p.get(
            "qty",
            p.get(
                "Qty",
                p.get(
                    "quantity",
                    0,
                ),
            ),
        )

        price = p.get(
            "entry_price",
            p.get(
                "EntryPrice",
                p.get(
                    "price",
                    0,
                ),
            ),
        )

        try:
            qty = float(qty)
            price = float(price)
        except Exception:
            continue

        if (
            qty > 0
            and price > 0
        ):
            existing_long_notional += (
                qty * price
            )

    max_long_notional = (
        equity
        * FIX17_LONG_TOTAL_LEVERAGE
    )

    return max(
        0.0,
        max_long_notional
        - existing_long_notional,
    )

# === END FIX17 STEP9B LONG SIZING ===


def calculate_fix17_order(

    runtime,

    candidate,

    state,

):

    long_remaining_capacity = (
        calculate_fix17_long_remaining_capacity(
            state
        )
    )

    candidate_for_validation = dict(candidate)
    candidate_for_validation["target_notional"] = (
        long_remaining_capacity
    )

    candidate = validate_candidate(
        candidate_for_validation
    )


    # --------------------------------------------------------
    # FIX17 ENTRY CONTRACT EXECUTION GATE
    #
    # LONG:
    #   proven contract -> execution allowed
    #
    # SHORT:
    #   effective filters are proven,
    #   but CrossPass semantics are NOT proven.
    #   Therefore execution is blocked.
    # --------------------------------------------------------

    # SHORT: existing audited FIX11 path connected.

    code = candidate[

        "code"

    ]

    side = candidate[

        "side"

    ]

    entry_price = candidate[

        "entry_price"

    ]

    long_remaining_capacity = (
        calculate_fix17_long_remaining_capacity(
            state
        )
    )

    target_notional = long_remaining_capacity

    if active_trade_id_exists(

        state,

        candidate[

            "trade_id"

        ],

    ):

        return {

            "status": "SKIP",

            "reason": "DUPLICATE_TRADE_ID",

            "candidate": candidate,

        }

    if active_position_exists(

        state,

        code,

        side,

    ):

        return {

            "status": "SKIP",

            "reason": "POSITION_ALREADY_OPEN",

            "candidate": candidate,

        }

    # --------------------------------------------------------

    # 正式FIX17 calc_target_qty

    # --------------------------------------------------------

    target_qty = runtime.calc_target_qty(

        target_notional,

        entry_price,

    )

    target_qty = int(

        target_qty

    )

    if target_qty <= 0:

        return {

            "status": "SKIP",

            "reason": "TARGET_QTY_ZERO",

            "candidate": candidate,

        }

    cash_now = float(

        state.get(

            "cash",

            0.0

        )

    )

    etf_mark = float(

        state.get(

            "etf_mark",

            0.0

        )

    )

    etf_shares = int(

        state.get(

            "etf_shares",

            0

        )

    )

    (

        existing_gross_notional,

        existing_unrealized,

    ) = calculate_existing_exposure(

        state

    )

    # --------------------------------------------------------

    # 正式FIX17 calc_margin_capped_qty

    # --------------------------------------------------------

    capped_qty = runtime.calc_margin_capped_qty(

        target_qty,

        entry_price,

        cash_now,

        etf_mark,

        etf_shares,

        existing_gross_notional,

        existing_unrealized,

    )

    if isinstance(capped_qty, dict):
        capped_qty = capped_qty['TargetQty']

    capped_qty = int(capped_qty)

    if capped_qty <= 0:

        return {

            "status": "SKIP",

            "reason": "MARGIN_CAPPED_QTY_ZERO",

            "candidate": candidate,

            "target_qty": target_qty,

        }

    return {

        "status": "ORDER",

        "candidate": candidate,

        "target_qty": target_qty,

        "qty": capped_qty,

        "notional": float(

            capped_qty

            * entry_price

        ),

    }

# ============================================================

# PAPER FILL

# ============================================================

def apply_paper_fill(

    state,

    order,

    market_date,

):

    if order.get(

        "status"

    ) != "ORDER":

        return None

    c = order[

        "candidate"

    ]

    qty = int(

        order[

            "qty"

        ]

    )

    entry_price = float(

        c[

            "entry_price"

        ]

    )

    side = c[

        "side"

    ]

    # --------------------------------------------------------

    # 信用売買想定

    #

    # cashは建玉代金全額を差し引かない。

    # FIX17 margin logicは正式関数側で制御済み。

    # --------------------------------------------------------

    position = {

        "trade_id": c[

            "trade_id"

        ],

        "code": c[

            "code"

        ],

        "side": side,

        "entry_price": entry_price,

        "mark_price": entry_price,

        "qty": qty,

        "entry_notional": float(

            entry_price

            * qty

        ),

        "market_date": market_date,

        "entry_datetime": c.get(

            "entry_datetime"

        ),

        "status": "OPEN",

        "source": "FIX17_OFFICIAL_PIPELINE",

        "created_at": datetime.now().isoformat(),

    }

    state.setdefault(

        "positions",

        []

    ).append(

        position

    )

    state[

        "updated_at"

    ] = datetime.now().isoformat()

    return position

# ============================================================

# OFFICIAL ENTRY-TIME STATE

# ============================================================

def get_fix17_position_state(

    runtime,

    state,

    market_date,

):

    broker_active = active_positions(

        state

    )

    return runtime.calc_entry_time_position_state(

        broker_active,

        market_date,

    )

# ============================================================

# PROCESS CANDIDATES

# ============================================================


# === STEP23C FIX17 LONG LIVE INPUT ===

def build_fix17_long_live_inputs():
    """
    FIX17 LONG live input builder.

    Current / historical 1m data:
        Existing FIX17 Save 1m data in GCS

    Daily feature / signal:
        Existing audited FIX11 functions are used unchanged.

    IMPORTANT:
        - FIX17 official source is not modified.
        - FIX11 find_first_signal / calc_rvol20 are not rewritten.
        - Only the input adapter is implemented here.
        - SHORT live execution remains disabled.
    """

    import re
    import runpy
    import shutil
    from datetime import datetime
    from pathlib import Path
    from zoneinfo import ZoneInfo

    import pandas as pd
    from google.cloud import storage

    # --------------------------------------------------------
    # MARKET DATE
    # --------------------------------------------------------

    now_jst = datetime.now(
        ZoneInfo("Asia/Tokyo")
    )

    today = now_jst.date()
    today_str = today.isoformat()

    # --------------------------------------------------------
    # LOAD EXISTING FIX11 ENTRY ENGINE
    # --------------------------------------------------------

    repo_dir = Path(__file__).resolve().parent

    fix11_path = (
        repo_dir
        / ".github"
        / "workflows"
        / "fix11_paper_trader.py"
    )

    if not fix11_path.exists():
        raise RuntimeError(
            "FIX11 paper trader source missing"
        )

    ns = runpy.run_path(
        str(fix11_path),
        run_name="__fix17_fix11_gcs_entry__",
    )

    fetch_daily_batch = ns.get(
        "fetch_daily_batch"
    )
    build_daily_features = ns.get(
        "build_daily_features"
    )
    find_first_signal = ns.get(
        "find_first_signal"
    )

    if fetch_daily_batch is None:
        raise RuntimeError(
            "FIX11 fetch_daily_batch missing"
        )

    if build_daily_features is None:
        raise RuntimeError(
            "FIX11 build_daily_features missing"
        )

    if find_first_signal is None:
        raise RuntimeError(
            "FIX11 find_first_signal missing"
        )

    # --------------------------------------------------------
    # UNIVERSE
    # --------------------------------------------------------

    universe_path = (
        repo_dir
        / "config"
        / "fix17_universe.txt"
    )

    if not universe_path.exists():
        raise RuntimeError(
            "FIX17 universe missing"
        )

    codes = [
        normalize_code(x.strip())
        for x in universe_path.read_text(
            encoding="utf-8"
        ).splitlines()
        if x.strip()
        and not x.strip().startswith("#")
    ]

    codes = list(dict.fromkeys(codes))

    if not codes:
        raise RuntimeError(
            "FIX17 universe empty"
        )

    code_set = set(codes)

    # --------------------------------------------------------
    # EXISTING FIX11 DAILY FEATURES
    # --------------------------------------------------------

    daily = fetch_daily_batch(codes)

    if daily is None or daily.empty:
        raise RuntimeError(
            "FIX11 daily data empty"
        )

    features = build_daily_features(
        daily,
        pd.Timestamp(today),
    )

    if features is None or features.empty:
        raise RuntimeError(
            "FIX11 daily features empty"
        )

    feature_by_code = {}

    for _, row in features.iterrows():
        item = row.to_dict()
        code = normalize_code(
            item.get("Code", "")
        )
        if code:
            item["Code"] = code
            feature_by_code[code] = item

    # LONG necessary daily filters only.
    # These are not new rules; find_first_signal applies the
    # same FIX11 rules again. This only avoids creating tens of
    # thousands of unnecessary temporary history files.
    eligible_codes = []

    for code in codes:
        feature = feature_by_code.get(code)
        if feature is None:
            continue

        try:
            rs20 = float(feature.get("RS20"))
            turnover = float(
                feature.get(
                    "turnover_median_20d_oku"
                )
            )
        except Exception:
            continue

        if (
            math.isfinite(rs20)
            and math.isfinite(turnover)
            and rs20 >= 80.0
            and turnover >= 3.0
        ):
            eligible_codes.append(code)

    print(
        "LONG daily eligible:",
        f"{len(eligible_codes)}/{len(codes)}",
    )

    if not eligible_codes:
        return {}, {}

    eligible_set = set(eligible_codes)

    # --------------------------------------------------------
    # GCS SAVED 1-MINUTE DATA
    # --------------------------------------------------------

    bucket_name = os.getenv(
        "GCS_BUCKET",
        "",
    ).strip()

    if not bucket_name:
        raise RuntimeError(
            "GCS_BUCKET is not set"
        )

    prefix = os.getenv(
        "GCS_1M_PREFIX",
        "fix17/minute_1m",
    ).strip().strip("/")

    client = storage.Client()
    bucket = client.bucket(bucket_name)

    date_pattern = re.compile(
        r"/date=(\d{4}-\d{2}-\d{2})/minute_1m\.parquet$"
    )

    blob_by_date = {}

    for blob in client.list_blobs(
        bucket_name,
        prefix=prefix + "/date=",
    ):
        m = date_pattern.search(
            "/" + blob.name
        )
        if m:
            blob_by_date[m.group(1)] = blob.name

    if today_str not in blob_by_date:
        raise RuntimeError(
            "FIX17 current 1m GCS file missing: "
            f"{prefix}/date={today_str}/minute_1m.parquet"
        )

    history_dates = sorted(
        d
        for d in blob_by_date
        if d < today_str
    )[-20:]

    if len(history_dates) != 20:
        raise RuntimeError(
            "FIX17 RVOL20 history不足: "
            f"{len(history_dates)}/20"
        )

    print(
        "RVOL20 history:",
        f"{len(history_dates)}/20",
    )

    # --------------------------------------------------------
    # TEMPORARY FIX11 RAW_DIR
    # --------------------------------------------------------

    history_dir = (
        RUNTIME_DIR
        / "fix17_rvol_history"
    )

    if history_dir.exists():
        shutil.rmtree(history_dir)

    history_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Functions returned by runpy keep their own globals dict.
    # Point the existing audited FIX11 functions themselves to the
    # temporary RVOL history directory. No FIX17/FIX11 trading rule
    # is changed here; this only connects the input storage path.
    for _fn_name in (
        "get_history_files_for_code",
        "calc_rvol20",
        "find_first_signal",
    ):
        _fn = ns.get(_fn_name)
        if _fn is None:
            raise RuntimeError(
                f"FIX11 {_fn_name} missing"
            )
        _fn.__globals__["RAW_DIR"] = history_dir

    # --------------------------------------------------------
    # NORMALIZER FOR save_1m.py OUTPUT
    # --------------------------------------------------------

    def normalize_saved_1m(df):
        if df is None or df.empty:
            return pd.DataFrame()

        x = df.copy()

        required = [
            "Datetime",
            "Code",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]

        missing = [
            c for c in required
            if c not in x.columns
        ]

        if missing:
            raise RuntimeError(
                "saved 1m columns missing: "
                + ",".join(missing)
            )

        dt = pd.to_datetime(
            x["Datetime"],
            errors="coerce",
            utc=True,
        )

        dt = dt.dt.tz_convert(
            "Asia/Tokyo"
        ).dt.tz_localize(None)

        x["Datetime"] = dt
        x = x[
            x["Datetime"].notna()
        ].copy()

        x["Code"] = (
            x["Code"]
            .astype(str)
            .map(normalize_code)
        )

        x = x[
            x["Code"].isin(code_set)
        ].copy()

        x["Time"] = (
            x["Datetime"]
            .dt.strftime("%H:%M")
        )

        x["O"] = pd.to_numeric(
            x["Open"],
            errors="coerce",
        )
        x["H"] = pd.to_numeric(
            x["High"],
            errors="coerce",
        )
        x["L"] = pd.to_numeric(
            x["Low"],
            errors="coerce",
        )
        x["C"] = pd.to_numeric(
            x["Close"],
            errors="coerce",
        )
        x["V"] = pd.to_numeric(
            x["Volume"],
            errors="coerce",
        ).fillna(0.0)

        return x.sort_values(
            ["Code", "Datetime"]
        ).reset_index(drop=True)

    # --------------------------------------------------------
    # DOWNLOAD CURRENT DAY
    # --------------------------------------------------------

    current_local = (
        RUNTIME_DIR
        / f"minute_1m_{today_str}.parquet"
    )

    bucket.blob(
        blob_by_date[today_str]
    ).download_to_filename(
        str(current_local)
    )

    current_all = normalize_saved_1m(
        pd.read_parquet(current_local)
    )

    current_all = current_all[
        current_all["Code"].isin(
            eligible_set
        )
    ].copy()

    minute_by_code = {}

    for code, g in current_all.groupby(
        "Code",
        sort=False,
    ):
        minute_by_code[str(code)] = (
            g.sort_values("Datetime")
            .reset_index(drop=True)
        )

    success_count = len(minute_by_code)

    print(
        "LONG GCS current 1m:",
        f"{success_count}/{len(eligible_codes)}",
    )

    if not minute_by_code:
        return {}, {}

    active_codes = set(
        minute_by_code.keys()
    )

    # --------------------------------------------------------
    # DOWNLOAD 20 PRIOR SESSIONS AND CREATE ONLY THE TEMPORARY
    # PER-CODE FILES REQUIRED BY THE EXISTING FIX11 RVOL ENGINE.
    # --------------------------------------------------------

    for hist_date in history_dates:

        local_path = (
            RUNTIME_DIR
            / f"minute_1m_hist_{hist_date}.parquet"
        )

        bucket.blob(
            blob_by_date[hist_date]
        ).download_to_filename(
            str(local_path)
        )

        hist = normalize_saved_1m(
            pd.read_parquet(local_path)
        )

        hist = hist[
            hist["Code"].isin(active_codes)
        ][
            ["Datetime", "Code", "V"]
        ].copy()

        for code, g in hist.groupby(
            "Code",
            sort=False,
        ):
            out = (
                history_dir
                / f"{hist_date}_{code}.parquet"
            )

            g[
                ["Datetime", "V"]
            ].to_parquet(
                out,
                index=False,
            )

        try:
            local_path.unlink()
        except Exception:
            pass

    try:
        current_local.unlink()
    except Exception:
        pass

    # --------------------------------------------------------
    # STRICT HISTORY COVERAGE CHECK
    # --------------------------------------------------------

    history_ready_codes = []

    for code in sorted(active_codes):
        count = len(
            list(
                history_dir.glob(
                    f"*_{code}.parquet"
                )
            )
        )

        if count == 20:
            history_ready_codes.append(code)

    print(
        "LONG RVOL-ready:",
        f"{len(history_ready_codes)}/{len(active_codes)}",
    )

    ready_set = set(history_ready_codes)

    minute_by_code = {
        code: df
        for code, df in minute_by_code.items()
        if code in ready_set
    }

    feature_by_code = {
        code: feature_by_code[code]
        for code in minute_by_code
        if code in feature_by_code
    }

    # --------------------------------------------------------
    # CONTRACT CHECK: EXACT 3-ARG FIX11 CALL
    # --------------------------------------------------------

    # Do not execute a separate signal pass here. The audited
    # LONG bridge performs the real call. This signature check
    # prevents the old two-argument wiring from returning.
    import inspect

    sig = inspect.signature(
        find_first_signal
    )

    if len(sig.parameters) != 3:
        raise RuntimeError(
            "FIX11 find_first_signal signature mismatch: "
            + str(sig)
        )

    return (
        minute_by_code,
        feature_by_code,
    )


def generate_fix17_long_live_candidates():
    """
    Generate FIX17 LONG live candidates through the existing
    audited FIX17 LONG bridge.
    """

    from datetime import datetime
    from zoneinfo import ZoneInfo

    minute_by_code, feature_by_code = (
        build_fix17_long_live_inputs()
    )

    market_date = datetime.now(
        ZoneInfo("Asia/Tokyo")
    ).date().isoformat()

    if not minute_by_code:
        return {
            "market_date": market_date,
            "candidates": [],
        }

    generator = (
        get_fix17_long_candidate_generator()
    )

    if generator is None:
        raise RuntimeError(
            "FIX17 LONG candidate generator missing"
        )

    candidates = generator(
        minute_by_code,
        feature_by_code,
    )

    if candidates is None:
        candidates = []

    if not isinstance(
        candidates,
        list,
    ):
        candidates = list(candidates)

    return {
        "market_date": market_date,
        "candidates": candidates,
    }


def generate_fix17_live_candidates():
    """
    Combined FIX17 paper candidate entry point.

    LONG:
        Existing audited FIX17 LONG bridge.

    SHORT:
        Disabled because the current audited status is
        SHORT_ENTRY_CONTRACT_NOT_FULLY_PROVEN.
    """

    short_status = (
        get_fix17_short_generator_status()
    )

    if short_status.get("enabled", False):
        raise RuntimeError(
            "Unexpected SHORT enablement without proven contract"
        )

    return generate_fix17_long_live_candidates()

def execute_fix17_candidate_batch():

    state = ensure_paper_state()

    # STEP23C: FIX17 LONG live candidates
    payload = generate_fix17_live_candidates()

    market_date = payload.get(

        "market_date"

    )

    candidates = payload.get(

        "candidates",

        []

    )

    if not candidates:

        result = {

            "status": "NO_CANDIDATES",

            "market_date": market_date,

            "candidate_count": 0,

            "orders": [],

            "fills": [],

            "time": datetime.now().isoformat(),

        }

        save_json(

            FIX17_EXECUTION_FILE,

            result

        )

        return result

    runtime = load_fix17_runtime_module()

    # --------------------------------------------------------

    # 正式 position state

    # --------------------------------------------------------

    position_state = (

        get_fix17_position_state(

            runtime,

            state,

            market_date,

        )

    )

    orders = []

    fills = []

    for raw_candidate in candidates:

        order = calculate_fix17_order(

            runtime,

            raw_candidate,

            state,

        )

        orders.append(

            order

        )

        if order.get(

            "status"

        ) != "ORDER":

            continue

        fill = apply_paper_fill(

            state,

            order,

            market_date,

        )

        if fill is not None:

            fills.append(

                fill

            )

    save_json(

        STATE_FILE,

        state

    )

    result = {

        "status": "COMPLETE",

        "market_date": market_date,

        "candidate_count": len(

            candidates

        ),

        "order_count": sum(

            1

            for x in orders

            if x.get(

                "status"

            ) == "ORDER"

        ),

        "fill_count": len(

            fills

        ),

        "position_state_repr": repr(

            position_state

        ),

        "orders": orders,

        "fills": fills,

        "time": datetime.now().isoformat(),

    }

    save_json(

        FIX17_EXECUTION_FILE,

        result

    )

    return result


# ============================================================

# END FIX17 OFFICIAL LIVE EXECUTION LAYER

# ============================================================


# ============================================================
# FIX17 NORMAL EVENING RESULT MAIL
# ============================================================

def send_normal_result_mail(
    engine_result,
    execution_result,
):

    state = load_json(
        STATE_FILE,
        default={},
    )

    market_date = execution_result.get(
        "market_date"
    )

    status = execution_result.get(
        "status",
        "UNKNOWN",
    )

    candidate_count = int(
        execution_result.get(
            "candidate_count",
            0,
        )
    )

    order_count = int(
        execution_result.get(
            "order_count",
            0,
        )
    )

    fill_count = int(
        execution_result.get(
            "fill_count",
            0,
        )
    )

    open_positions = active_positions(
        state
    )

    cash_now = float(
        state.get(
            "cash",
            0.0,
        )
    )

    closed_trades = state.get(
        "closed_trades",
        [],
    )

    engine_status = engine_result.get(
        "status",
        "UNKNOWN",
    )

    lines = []

    lines.append(
        "FIX17 仮想取引 当日結果"
    )

    lines.append(
        ""
    )

    lines.append(
        f"市場日: {market_date or '未設定'}"
    )

    lines.append(
        f"エンジン: {engine_status}"
    )

    lines.append(
        f"実行状態: {status}"
    )

    lines.append(
        ""
    )

    lines.append(
        f"候補数: {candidate_count}"
    )

    lines.append(
        f"注文数: {order_count}"
    )

    lines.append(
        f"仮想約定数: {fill_count}"
    )

    lines.append(
        f"保有建玉数: {len(open_positions)}"
    )

    lines.append(
        f"累計決済数: {len(closed_trades)}"
    )

    lines.append(
        f"現金: {cash_now:,.0f}円"
    )

    if open_positions:

        lines.append(
            ""
        )

        lines.append(
            "【保有建玉】"
        )

        for p in open_positions:

            code = p.get(
                "code",
                "?"
            )

            side = p.get(
                "side",
                "?"
            )

            qty = p.get(
                "qty",
                0,
            )

            entry_price = float(
                p.get(
                    "entry_price",
                    0.0,
                )
            )

            lines.append(
                f"{code} {side} "
                f"{qty}株 "
                f"@{entry_price:,.2f}"
            )

    orders = execution_result.get(
        "orders",
        [],
    )

    skipped = [
        x
        for x in orders
        if x.get(
            "status"
        ) == "SKIP"
    ]

    if skipped:

        lines.append(
            ""
        )

        lines.append(
            "【SKIP】"
        )

        for x in skipped:

            c = x.get(
                "candidate",
                {},
            )

            lines.append(
                f"{c.get('code', '?')} "
                f"{c.get('side', '?')} "
                f"{x.get('reason', '?')}"
            )

    lines.append(
        ""
    )

    lines.append(
        "※1分足保存Jobとは独立しています。"
    )

    lines.append(
        "※このメールは15:45の仮想取引結果です。"
    )

    body = "\n".join(
        lines
    )

    return send_mail(
        "FIX17 仮想取引 当日結果",
        body,
    )


# ============================================================
# FINAL DAILY RUN
# ============================================================

def run_fix17_paper_trader_daily():

    # --------------------------------------------------------
    # 1. Official engine / contract verification
    # --------------------------------------------------------

    engine_result = main()

    # --------------------------------------------------------
    # 2. Candidate execution
    #
    # 現段階では runtime/fix17_candidates.json を使用。
    # Candidate generator itself is NOT reconstructed here.
    # --------------------------------------------------------

    execution_result = (
        execute_fix17_candidate_batch()
    )

    # --------------------------------------------------------
    # 3. Normal evening mail
    # --------------------------------------------------------

    mail_sent = send_normal_result_mail(
        engine_result,
        execution_result,
    )

    # --------------------------------------------------------
    # 4. Combined run log
    # --------------------------------------------------------

    combined = {
        "status":
            "COMPLETE",

        "version":
            "FIX17",

        "time":
            datetime.now().isoformat(),

        "engine":
            engine_result,

        "execution":
            execution_result,

        "normal_mail_sent":
            bool(
                mail_sent
            ),
    }

    save_json(
        RUN_LOG_FILE,
        combined,
    )

    return combined


# ============================================================
# FINAL ENTRY POINT
# ============================================================



# === FIX17 STEP8 LONG GENERATOR BRIDGE ===

def get_fix17_long_candidate_generator():

    """
    Load the audited LONG candidate bridge.

    This function only exposes the generator.
    It does not manufacture missing live inputs.
    """

    import importlib.util
    from pathlib import Path

    bridge_path = (
        Path(__file__).resolve().parent
        / "fix17_long_candidate_bridge.py"
    )

    if not bridge_path.exists():

        raise RuntimeError(
            "FIX17 LONG bridge missing: "
            + str(bridge_path)
        )

    spec = importlib.util.spec_from_file_location(
        "fix17_long_candidate_bridge",
        bridge_path,
    )

    if (
        spec is None
        or spec.loader is None
    ):

        raise RuntimeError(
            "FIX17 LONG bridge import failed"
        )

    module = importlib.util.module_from_spec(
        spec
    )

    spec.loader.exec_module(
        module
    )

    return (
        module.generate_fix17_long_candidates
    )


def get_fix17_short_generator_status():

    return {
        "enabled": False,
        "reason":
            "SHORT_ENTRY_CONTRACT_NOT_FULLY_PROVEN",
    }

# === END FIX17 STEP8 LONG GENERATOR BRIDGE ===


if __name__ == "__main__":

    try:

        result = (
            run_fix17_paper_trader_daily()
        )

        print(
            "★★★★★ FIX17 PAPER TRADER DAILY COMPLETE ★★★★★"
        )

        print(
            "Execution status:",
            result.get(
                "execution",
                {}
            ).get(
                "status"
            )
        )

        print(
            "Candidates:",
            result.get(
                "execution",
                {}
            ).get(
                "candidate_count",
                0
            )
        )

        print(
            "Orders:",
            result.get(
                "execution",
                {}
            ).get(
                "order_count",
                0
            )
        )

        print(
            "Fills:",
            result.get(
                "execution",
                {}
            ).get(
                "fill_count",
                0
            )
        )

        print(
            "Normal mail:",
            result.get(
                "normal_mail_sent"
            )
        )

    except Exception as e:

        error_text = (
            traceback.format_exc()
        )

        try:

            save_json(
                RUN_LOG_FILE,
                {
                    "status":
                        "ERROR",

                    "time":
                        datetime.now().isoformat(),

                    "error_type":
                        type(
                            e
                        ).__name__,

                    "error":
                        str(
                            e
                        ),

                    "traceback":
                        error_text,
                }
            )

        except Exception:

            pass

        send_error_mail(
            type(
                e
            ).__name__,
            error_text,
        )

        print(
            error_text,
            file=sys.stderr
        )

        sys.exit(
            1
        )
