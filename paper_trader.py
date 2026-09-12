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

    RUNTIME_DIR.mkdir(
        parents=True,
        exist_ok=True
    )


    with tempfile.TemporaryDirectory() as td:

        td = Path(
            td
        )

        runner = (
            td
            / "runner.py"
        )

        result_path = (
            td
            / "result.json"
        )

        log_path = (
            td
            / "runtime.log"
        )


        runner.write_text(
            ENGINE_AUDIT_SCRIPT,
            encoding="utf-8"
        )


        p = subprocess.run(
            [
                sys.executable,
                str(
                    runner
                ),
                str(
                    OFFICIAL_FILE
                ),
                str(
                    result_path
                ),
                str(
                    log_path
                ),
            ],
            text=True,
            capture_output=True,
            timeout=3600,
        )


        if not result_path.exists():

            raise RuntimeError(
                "FIX17 engine audit結果が作成されませんでした。\n"
                + (
                    p.stderr
                    or ""
                )
            )


        with result_path.open(
            "r",
            encoding="utf-8"
        ) as f:

            result = json.load(
                f
            )


        if not result.get(
            "success"
        ):

            err = result.get(
                "error",
                {}
            )

            raise RuntimeError(
                "FIX17 engine load失敗\n"
                + err.get(
                    "traceback",
                    ""
                )
            )


    functions = set(
        result.get(
            "functions",
            []
        )
    )


    missing = [
        name
        for name
        in REQUIRED_FUNCTIONS
        if name not in functions
    ]


    if missing:

        raise RuntimeError(
            "FIX17必須関数不足:\n"
            + "\n".join(
                missing
            )
        )


    # 正式監査結果は26関数・0クラス
    if len(
        functions
    ) != 26:

        raise RuntimeError(
            "FIX17 runtime function数が正式監査値と不一致\n"
            f"actual={len(functions)}\n"
            "expected=26"
        )


    classes = result.get(
        "classes",
        []
    )


    if len(
        classes
    ) != 0:

        raise RuntimeError(
            "FIX17 runtime class数が正式監査値と不一致\n"
            f"actual={len(classes)}\n"
            "expected=0"
        )


    save_json(
        ENGINE_CHECK_FILE,
        {
            "checked_at": datetime.now().isoformat(),
            "official_sha256": OFFICIAL_SHA256,
            "function_count": len(
                functions
            ),
            "functions": sorted(
                functions
            ),
            "class_count": len(
                classes
            ),
            "classes": classes,
            "scalars": result.get(
                "scalars",
                {}
            ),
        }
    )


    return result


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
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        error_text = (
            traceback.format_exc()
        )


        try:

            save_json(
                RUN_LOG_FILE,
                {
                    "status": "ERROR",
                    "time": datetime.now().isoformat(),
                    "error_type": type(
                        e
                    ).__name__,
                    "error": str(
                        e
                    ),
                    "traceback": error_text,
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

def validate_candidate(

    candidate

):

    required = [

        "code",

        "side",

        "entry_price",

        "target_notional",

    ]

    missing = [

        x

        for x in required

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

    if (

        not math.isfinite(

            entry_price

        )

        or entry_price <= 0

    ):

        raise RuntimeError(

            f"entry_price不正: {entry_price}"

        )

    if (

        not math.isfinite(

            target_notional

        )

        or target_notional <= 0

    ):

        raise RuntimeError(

            f"target_notional不正: {target_notional}"

        )

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

    return {

        **candidate,

        "trade_id": str(

            trade_id

        ),

        "code": code,

        "side": side,

        "entry_price": entry_price,

        "target_notional": target_notional,

    }

# ============================================================

# OFFICIAL FIX17 POSITION SIZE

# ============================================================

def calculate_fix17_order(

    runtime,

    candidate,

    state,

):

    candidate = validate_candidate(

        candidate

    )

    code = candidate[

        "code"

    ]

    side = candidate[

        "side"

    ]

    entry_price = candidate[

        "entry_price"

    ]

    target_notional = candidate[

        "target_notional"

    ]

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

    capped_qty = int(

        capped_qty

    )

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

def execute_fix17_candidate_batch():

    state = ensure_paper_state()

    payload = load_fix17_candidates()

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
