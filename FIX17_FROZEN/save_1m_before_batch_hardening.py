# ============================================================
# FIX17 1-MINUTE DATA SAVER
#
# PURPOSE
#   yfinance 1分足取得
#   厳格検査
#   Parquet作成
#   GCS永続保存
#
# SUCCESS:
#   メール送信なし
#
# ERROR:
#   即エラーメール
#
# paper_trader.pyとは完全分離
# ============================================================

from __future__ import annotations

import os
import sys
import json
import traceback
import re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from google.cloud import storage

from mailer import send_error_mail


# ============================================================
# CONSTANTS
# ============================================================

JST = ZoneInfo(
    "Asia/Tokyo"
)

REPO_DIR = Path(
    __file__
).resolve().parent

CONFIG_DIR = (
    REPO_DIR
    / "config"
)

RUNTIME_DIR = (
    REPO_DIR
    / "runtime"
)

DATA_DIR = (
    RUNTIME_DIR
    / "minute_1m"
)

UNIVERSE_FILE = (
    CONFIG_DIR
    / "fix17_universe.txt"
)

LAST_RESULT_FILE = (
    RUNTIME_DIR
    / "save_1m_last_result.json"
)

GCS_BUCKET = os.environ.get(
    "GCS_BUCKET",
    "",
).strip()

GCS_PREFIX = os.environ.get(
    "GCS_1M_PREFIX",
    "fix17/minute_1m",
).strip().strip("/")


# ============================================================
# BASIC HELPERS
# ============================================================

def save_json(
    path: Path,
    obj,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def normalize_code(
    value,
):

    s = str(
        value
    ).strip().upper()

    if s.endswith(
        ".T"
    ):
        s = s[:-2]

    if s.endswith(
        ".0"
    ):
        s = s[:-2]

    # JPX/J-Quants:
    #
    # 通常銘柄:
    #   72030 -> 7203
    #   130A0 -> 130A
    #
    # 優先株・種類株:
    #   25935 -> 25935
    #   94346 -> 94346
    #
    # 末尾0だけpaddingとして除去する。
    if (
        len(s) == 5
        and
        s.endswith("0")
    ):
        s = s[:-1]

    if not s:
        raise RuntimeError(
            "空の銘柄コードがあります"
        )

    valid_4 = bool(
        re.fullmatch(
            r"[0-9A-Z]{4}",
            s,
        )
    )

    valid_5 = bool(
        re.fullmatch(
            r"[0-9]{5}",
            s,
        )
    )

    if not (
        valid_4
        or valid_5
    ):

        raise RuntimeError(
            f"銘柄コード形式不正: {s}"
        )

    return s



# ============================================================
# UNIVERSE
# ============================================================

def load_universe():

    if not UNIVERSE_FILE.exists():

        raise RuntimeError(
            "config/fix17_universe.txt がありません。\n"
            "FIX17の正式な対象銘柄を確定するまで、"
            "銘柄を勝手に生成して1分足取得は行いません。"
        )

    codes = []

    for raw in UNIVERSE_FILE.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():

        raw = raw.strip()

        if (
            not raw
            or raw.startswith("#")
        ):
            continue

        code = normalize_code(
            raw
        )

        if code not in codes:
            codes.append(
                code
            )

    if not codes:

        raise RuntimeError(
            "fix17_universe.txt が空です"
        )

    return codes


# ============================================================
# MARKET TIME
# ============================================================

def market_date_jst():

    return datetime.now(
        JST
    ).date()


# ============================================================
# YFINANCE DOWNLOAD
# ============================================================

def download_one_symbol(
    code: str,
):

    ticker = (
        code
        + ".T"
    )

    df = yf.download(
        ticker,
        period="1d",
        interval="1m",
        auto_adjust=False,
        progress=False,
        prepost=False,
        threads=False,
        timeout=20,
    )

    if df is None:
        return None

    if len(
        df
    ) == 0:
        return None

    # --------------------------------------------
    # MultiIndex対策
    # --------------------------------------------

    if isinstance(
        df.columns,
        pd.MultiIndex,
    ):

        df.columns = [
            x[0]
            if isinstance(
                x,
                tuple,
            )
            else x
            for x in df.columns
        ]

    df = df.reset_index()

    dt_col = None

    for c in [
        "Datetime",
        "Date",
        "index",
    ]:

        if c in df.columns:
            dt_col = c
            break

    if dt_col is None:

        raise RuntimeError(
            f"{code}: Datetime列なし"
        )

    dt = pd.to_datetime(
        df[
            dt_col
        ],
        errors="coerce",
        utc=True,
    )

    if dt.isna().all():

        raise RuntimeError(
            f"{code}: Datetime変換失敗"
        )

    dt = dt.dt.tz_convert(
        JST
    )

    out = pd.DataFrame(
        {
            "Date":
                dt.dt.date.astype(
                    str
                ),

            "Time":
                dt.dt.strftime(
                    "%H:%M"
                ),

            "Datetime":
                dt.dt.strftime(
                    "%Y-%m-%d %H:%M:%S%z"
                ),

            "Code":
                code,

            "Open":
                pd.to_numeric(
                    df.get(
                        "Open"
                    ),
                    errors="coerce",
                ),

            "High":
                pd.to_numeric(
                    df.get(
                        "High"
                    ),
                    errors="coerce",
                ),

            "Low":
                pd.to_numeric(
                    df.get(
                        "Low"
                    ),
                    errors="coerce",
                ),

            "Close":
                pd.to_numeric(
                    df.get(
                        "Close"
                    ),
                    errors="coerce",
                ),

            "Volume":
                pd.to_numeric(
                    df.get(
                        "Volume"
                    ),
                    errors="coerce",
                ),
        }
    )

    # --------------------------------------------
    # 日本市場時間のみ
    # 09:00-11:30
    # 12:30-15:30
    # --------------------------------------------

    t = out[
        "Time"
    ]

    mask = (
        (
            (t >= "09:00")
            &
            (t <= "11:30")
        )
        |
        (
            (t >= "12:30")
            &
            (t <= "15:30")
        )
    )

    out = out.loc[
        mask
    ].copy()

    out = out.dropna(
        subset=[
            "Open",
            "High",
            "Low",
            "Close",
        ]
    )

    out[
        "Volume"
    ] = out[
        "Volume"
    ].fillna(
        0
    )

    out[
        "Volume"
    ] = out[
        "Volume"
    ].astype(
        "int64"
    )

    out = out.drop_duplicates(
        subset=[
            "Date",
            "Time",
            "Code",
        ],
        keep="last",
    )

    out = out.sort_values(
        [
            "Date",
            "Time",
            "Code",
        ]
    ).reset_index(
        drop=True
    )

    if out.empty:
        return None

    return out


# ============================================================
# DOWNLOAD ALL
# ============================================================

def download_all(
    codes,
):

    frames = []

    failed = []

    for i, code in enumerate(
        codes,
        start=1,
    ):

        try:

            df = download_one_symbol(
                code
            )

            if (
                df is None
                or df.empty
            ):

                failed.append(
                    {
                        "code":
                            code,

                        "reason":
                            "NO_DATA",
                    }
                )

                continue

            frames.append(
                df
            )

        except Exception as e:

            failed.append(
                {
                    "code":
                        code,

                    "reason":
                        (
                            type(
                                e
                            ).__name__
                            + ": "
                            + str(
                                e
                            )
                        ),
                }
            )

        if (
            i % 50 == 0
            or i == len(
                codes
            )
        ):

            print(
                f"{i}/{len(codes)} "
                f"成功={len(frames)} "
                f"失敗={len(failed)}"
            )

    if not frames:

        raise RuntimeError(
            "1分足を1銘柄も取得できませんでした"
        )

    data = pd.concat(
        frames,
        ignore_index=True,
    )

    return (
        data,
        failed,
    )


# ============================================================
# STRICT VALIDATION
# ============================================================

def validate_data(
    data,
    codes,
    failed,
):

    if data.empty:

        raise RuntimeError(
            "1分足データが空です"
        )

    today = str(
        market_date_jst()
    )

    available_dates = sorted(
        data[
            "Date"
        ].astype(
            str
        ).unique()
    )

    if today not in available_dates:

        raise RuntimeError(
            "当日の1分足がありません\n"
            f"today={today}\n"
            f"dates={available_dates[-5:]}"
        )

    today_df = data[
        data[
            "Date"
        ].astype(
            str
        )
        == today
    ].copy()

    if today_df.empty:

        raise RuntimeError(
            "当日データが0行です"
        )

    duplicate_count = int(
        today_df.duplicated(
            subset=[
                "Date",
                "Time",
                "Code",
            ]
        ).sum()
    )

    if duplicate_count:

        raise RuntimeError(
            f"重複1分足があります: "
            f"{duplicate_count}"
        )

    # --------------------------------------------
    # 取得成功率
    # --------------------------------------------

    success_codes = set(
        today_df[
            "Code"
        ].astype(
            str
        ).unique()
    )

    expected_codes = set(
        codes
    )

    missing_codes = sorted(
        expected_codes
        - success_codes
    )

    total = len(
        expected_codes
    )

    success = len(
        success_codes
    )

    success_ratio = (
        success
        / total
        if total
        else 0.0
    )

    # --------------------------------------------
    # データ源障害を候補ゼロとして扱わない
    #
    # 95%未満ならその日のデータ保存自体を失敗扱い
    # --------------------------------------------

    if success_ratio < 0.95:

        raise RuntimeError(
            "1分足取得成功率が95%未満です。\n"
            f"成功={success}/{total}\n"
            f"成功率={success_ratio:.2%}\n"
            f"missing例={missing_codes[:30]}"
        )

    # --------------------------------------------
    # OHLC validity
    # --------------------------------------------

    bad_price = today_df[
        (
            today_df[
                [
                    "Open",
                    "High",
                    "Low",
                    "Close",
                ]
            ]
            <= 0
        ).any(
            axis=1
        )
    ]

    if not bad_price.empty:

        raise RuntimeError(
            "0以下の価格データがあります"
        )

    # --------------------------------------------
    # high / low sanity
    # --------------------------------------------

    bad_ohlc = today_df[
        (
            today_df[
                "High"
            ]
            <
            today_df[
                [
                    "Open",
                    "Close",
                ]
            ].max(
                axis=1
            )
        )
        |
        (
            today_df[
                "Low"
            ]
            >
            today_df[
                [
                    "Open",
                    "Close",
                ]
            ].min(
                axis=1
            )
        )
    ]

    if not bad_ohlc.empty:

        raise RuntimeError(
            "OHLC整合性エラーがあります"
        )

    return {
        "market_date":
            today,

        "expected_codes":
            total,

        "success_codes":
            success,

        "success_ratio":
            success_ratio,

        "missing_codes":
            missing_codes,

        "download_failures":
            failed,

        "rows":
            int(
                len(
                    today_df
                )
            ),

        "first_time":
            str(
                today_df[
                    "Time"
                ].min()
            ),

        "last_time":
            str(
                today_df[
                    "Time"
                ].max()
            ),
    }


# ============================================================
# LOCAL PARQUET
# ============================================================

def write_local_parquet(
    data,
    market_date,
):

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        DATA_DIR
        / f"{market_date}.parquet"
    )

    today_df = data[
        data[
            "Date"
        ].astype(
            str
        )
        == market_date
    ].copy()

    today_df.to_parquet(
        path,
        index=False,
        compression="snappy",
    )

    return path


# ============================================================
# GCS
# ============================================================

def upload_to_gcs(
    local_path,
    market_date,
):

    if not GCS_BUCKET:

        raise RuntimeError(
            "GCS_BUCKET が設定されていません"
        )

    client = storage.Client()

    bucket = client.bucket(
        GCS_BUCKET
    )

    object_name = (
        f"{GCS_PREFIX}/"
        f"date={market_date}/"
        f"minute_1m.parquet"
    )

    blob = bucket.blob(
        object_name
    )

    blob.upload_from_filename(
        str(
            local_path
        ),
        content_type=(
            "application/octet-stream"
        ),
    )

    return {
        "bucket":
            GCS_BUCKET,

        "object":
            object_name,

        "gs_uri":
            (
                f"gs://"
                f"{GCS_BUCKET}/"
                f"{object_name}"
            ),
    }


# ============================================================
# MAIN
# ============================================================

def main():

    started = datetime.now(
        JST
    )

    print(
        "FIX17 1分足保存開始:",
        started.isoformat()
    )

    codes = load_universe()

    print(
        "対象銘柄数:",
        len(
            codes
        )
    )

    data, failed = download_all(
        codes
    )

    validation = validate_data(
        data,
        codes,
        failed,
    )

    market_date = validation[
        "market_date"
    ]

    local_path = write_local_parquet(
        data,
        market_date,
    )

    gcs = upload_to_gcs(
        local_path,
        market_date,
    )

    result = {
        "status":
            "SUCCESS",

        "time":
            datetime.now(
                JST
            ).isoformat(),

        "market_date":
            market_date,

        "validation":
            validation,

        "local_file":
            str(
                local_path
            ),

        "gcs":
            gcs,
    }

    save_json(
        LAST_RESULT_FILE,
        result,
    )

    print()
    print(
        "保存成功"
    )

    print(
        "market_date:",
        market_date
    )

    print(
        "rows:",
        validation[
            "rows"
        ]
    )

    print(
        "codes:",
        (
            f"{validation['success_codes']}"
            f"/{validation['expected_codes']}"
        )
    )

    print(
        "GCS:",
        gcs[
            "gs_uri"
        ]
    )

    print()
    print(
        "SUCCESS EMAIL: NONE"
    )

    return result


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        error_text = traceback.format_exc()

        try:

            save_json(
                LAST_RESULT_FILE,
                {
                    "status":
                        "ERROR",

                    "time":
                        datetime.now(
                            JST
                        ).isoformat(),

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
                },
            )

        except Exception:
            pass

        try:

            send_error_mail(
                "1分足保存エラー",
                error_text,
            )

        except Exception as mail_error:

            print(
                "エラーメール送信失敗:",
                mail_error,
                file=sys.stderr,
            )

        print(
            error_text,
            file=sys.stderr,
        )

        sys.exit(
            1
        )
