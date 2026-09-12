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
