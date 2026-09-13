# ============================================================
# FIX17 1-MINUTE DATA SAVER
#
# yfinance 1-minute data
# ↓
# batch download
# ↓
# strict validation
# ↓
# parquet
# ↓
# GCS persistent storage
#
# SUCCESS:
#   emailなし
#
# MARKET CLOSED:
#   正常SKIP
#   emailなし
#
# ERROR:
#   即エラーメール
#
# paper_traderとは完全別ジョブ
# ============================================================

from __future__ import annotations

import os
import sys
import re
import json
import traceback
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
import jpholiday
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


# 4208銘柄を一括で投げない。
# yfinance側負荷・レスポンスサイズを抑える。
BATCH_SIZE = int(
    os.environ.get(
        "SAVE1M_BATCH_SIZE",
        "100",
    )
)

MIN_SUCCESS_RATIO = float(
    os.environ.get(
        "SAVE1M_MIN_SUCCESS_RATIO",
        "0.95",
    )
)


# ============================================================
# HELPERS
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
    #   72030 -> 7203
    #   130A0 -> 130A
    #
    # 優先株・種類株:
    #   25935 -> 25935
    if (
        len(s) == 5
        and
        s.endswith("0")
    ):
        s = s[:-1]

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


def yahoo_symbol(
    code,
):

    return (
        normalize_code(
            code
        )
        + ".T"
    )


# ============================================================
# UNIVERSE
# ============================================================

def load_universe():

    if not UNIVERSE_FILE.exists():

        raise RuntimeError(
            "config/fix17_universe.txt がありません"
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
            "FIX17 universeが空です"
        )

    return codes


# ============================================================
# DATE / SESSION
# ============================================================

def now_jst():

    return datetime.now(
        JST
    )


def today_jst():

    return now_jst().date()


def is_weekend():

    return (
        today_jst().weekday()
        >= 5
    )


def is_jpx_trading_day(
    target_date=None,
):
    """
    JPX現物株の営業日判定。

    非営業:
      ・土曜日
      ・日曜日
      ・日本の祝日
      ・1月1日〜3日
      ・12月31日

    ここではyfinanceのデータ有無を営業日判定には使わない。
    Yahoo側障害と市場休場を分離するため。
    """

    if target_date is None:

        target_date = (
            today_jst()
        )


    # Saturday / Sunday
    if (
        target_date.weekday()
        >= 5
    ):

        return False


    # JPX year-end / new-year closure
    if (
        target_date.month == 1
        and
        target_date.day
        in (
            1,
            2,
            3,
        )
    ):

        return False


    if (
        target_date.month == 12
        and
        target_date.day == 31
    ):

        return False


    # Japanese national holiday
    if jpholiday.is_holiday(
        target_date
    ):

        return False


    return True


def jpx_non_trading_reason(
    target_date=None,
):

    if target_date is None:

        target_date = (
            today_jst()
        )


    if (
        target_date.weekday()
        >= 5
    ):

        return "WEEKEND"


    if (
        target_date.month == 1
        and
        target_date.day
        in (
            1,
            2,
            3,
        )
    ):

        return (
            "JPX_NEW_YEAR_CLOSED"
        )


    if (
        target_date.month == 12
        and
        target_date.day == 31
    ):

        return (
            "JPX_YEAR_END_CLOSED"
        )


    holiday_name = (
        jpholiday.is_holiday_name(
            target_date
        )
    )


    if holiday_name:

        return (
            "JAPANESE_HOLIDAY:"
            + str(
                holiday_name
            )
        )


    return None



# ============================================================
# YFINANCE SHAPE NORMALIZATION
# ============================================================

def extract_symbol_frame(
    downloaded,
    symbol,
):

    if downloaded is None:

        return None

    if downloaded.empty:

        return None


    # --------------------------------------------------------
    # MultiIndex
    #
    # yfinanceはバッチ取得時、
    # (Price, Ticker) または (Ticker, Price)
    # のどちらかになる場合があるため両方対応。
    # --------------------------------------------------------

    if isinstance(
        downloaded.columns,
        pd.MultiIndex,
    ):

        level0 = set(
            map(
                str,
                downloaded.columns.get_level_values(
                    0
                ),
            )
        )

        level1 = set(
            map(
                str,
                downloaded.columns.get_level_values(
                    1
                ),
            )
        )


        if symbol in level0:

            frame = downloaded[
                symbol
            ].copy()

        elif symbol in level1:

            frame = downloaded.xs(
                symbol,
                axis=1,
                level=1,
            ).copy()

        else:

            return None

    else:

        # 単一tickerだけ返ったケース
        frame = downloaded.copy()


    if frame.empty:

        return None


    wanted = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    ]


    if not all(
        x in frame.columns
        for x in wanted
    ):

        return None


    frame = frame[
        wanted
    ].copy()


    return frame


# ============================================================
# ONE FRAME -> STANDARD FORMAT
# ============================================================

def standardize_symbol_frame(
    frame,
    code,
):

    if frame is None:

        return None

    if frame.empty:

        return None


    temp = frame.reset_index()


    dt_col = None

    for c in [
        "Datetime",
        "Date",
        "index",
    ]:

        if c in temp.columns:

            dt_col = c

            break


    if dt_col is None:

        return None


    dt = pd.to_datetime(
        temp[
            dt_col
        ],
        errors="coerce",
        utc=True,
    )


    if dt.isna().all():

        return None


    dt = dt.dt.tz_convert(
        JST
    )


    out = pd.DataFrame(
        {
            "Date":
                dt.dt.strftime(
                    "%Y-%m-%d"
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
                    temp[
                        "Open"
                    ],
                    errors="coerce",
                ),

            "High":
                pd.to_numeric(
                    temp[
                        "High"
                    ],
                    errors="coerce",
                ),

            "Low":
                pd.to_numeric(
                    temp[
                        "Low"
                    ],
                    errors="coerce",
                ),

            "Close":
                pd.to_numeric(
                    temp[
                        "Close"
                    ],
                    errors="coerce",
                ),

            "Volume":
                pd.to_numeric(
                    temp[
                        "Volume"
                    ],
                    errors="coerce",
                ),
        }
    )


    # --------------------------------------------------------
    # JPX session
    #
    # 2024/11以降の現物株:
    # 09:00-11:30 / 12:30-15:30
    #
    # 取得データに11:30/15:30が存在する場合も許容。
    # --------------------------------------------------------

    t = out[
        "Time"
    ]


    market_mask = (
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
        market_mask
    ].copy()


    out = out.dropna(
        subset=[
            "Open",
            "High",
            "Low",
            "Close",
        ]
    )


    if out.empty:

        return None


    out[
        "Volume"
    ] = (
        out[
            "Volume"
        ]
        .fillna(
            0
        )
        .clip(
            lower=0
        )
        .astype(
            "int64"
        )
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
        ]
    ).reset_index(
        drop=True
    )


    return out


# ============================================================
# BATCH DOWNLOAD
# ============================================================

def download_batch(
    codes,
):

    symbols = [
        yahoo_symbol(
            x
        )
        for x in codes
    ]


    downloaded = yf.download(
        tickers=symbols,
        period="1d",
        interval="1m",
        auto_adjust=False,
        progress=False,
        prepost=False,
        threads=True,
        group_by="column",
        timeout=30,
    )


    frames = []

    failures = []


    for code, symbol in zip(
        codes,
        symbols,
    ):

        try:

            frame = extract_symbol_frame(
                downloaded,
                symbol,
            )

            frame = standardize_symbol_frame(
                frame,
                code,
            )


            if (
                frame is None
                or frame.empty
            ):

                failures.append(
                    {
                        "code":
                            code,

                        "symbol":
                            symbol,

                        "reason":
                            "NO_DATA",
                    }
                )

                continue


            frames.append(
                frame
            )


        except Exception as e:

            failures.append(
                {
                    "code":
                        code,

                    "symbol":
                        symbol,

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


    return (
        frames,
        failures,
    )


# ============================================================
# DOWNLOAD ALL
# ============================================================

def download_all(
    codes,
):

    all_frames = []

    all_failures = []


    total = len(
        codes
    )


    for start in range(
        0,
        total,
        BATCH_SIZE,
    ):

        batch_codes = codes[
            start:
            start + BATCH_SIZE
        ]


        frames, failures = download_batch(
            batch_codes
        )


        all_frames.extend(
            frames
        )

        all_failures.extend(
            failures
        )


        done = min(
            start + len(
                batch_codes
            ),
            total,
        )


        print(
            f"{done}/{total} "
            f"成功={len(all_frames)} "
            f"失敗={len(all_failures)}"
        )


    if not all_frames:

        return (
            pd.DataFrame(),
            all_failures,
        )


    data = pd.concat(
        all_frames,
        ignore_index=True,
    )


    return (
        data,
        all_failures,
    )


# ============================================================
# MARKET CLOSED DETECTION
# ============================================================

def is_market_closed_result(
    data,
):

    if data is None:

        return True

    if data.empty:

        return True


    today = str(
        today_jst()
    )


    dates = set(
        data[
            "Date"
        ].astype(
            str
        )
    )


    return (
        today not in dates
    )


# ============================================================
# VALIDATION
# ============================================================

def validate_data(
    data,
    codes,
    failures,
):

    today = str(
        today_jst()
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
            "重複1分足があります: "
            f"{duplicate_count}"
        )


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


    if success_ratio < MIN_SUCCESS_RATIO:

        raise RuntimeError(
            "1分足取得成功率不足\n"
            f"成功={success}/{total}\n"
            f"成功率={success_ratio:.2%}\n"
            f"必要={MIN_SUCCESS_RATIO:.2%}\n"
            f"missing例={missing_codes[:30]}"
        )


    prices = today_df[
        [
            "Open",
            "High",
            "Low",
            "Close",
        ]
    ]


    if (
        prices
        <= 0
    ).any(
        axis=None
    ):

        raise RuntimeError(
            "0以下の価格データがあります"
        )


    bad_high = (
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


    bad_low = (
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


    if (
        bad_high
        |
        bad_low
    ).any():

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

        "missing_count":
            len(
                missing_codes
            ),

        "missing_codes":
            missing_codes,

        "download_failure_count":
            len(
                failures
            ),

        "download_failures":
            failures,

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
# SKIP RESULT
# ============================================================

def write_skip_result(
    reason,
):

    result = {
        "status":
            "SKIP",

        "reason":
            reason,

        "time":
            now_jst().isoformat(),

        "market_date":
            str(
                today_jst()
            ),
    }


    save_json(
        LAST_RESULT_FILE,
        result,
    )


    print(
        "SKIP:",
        reason
    )


    return result


# ============================================================
# MAIN
# ============================================================

def main():

    started = now_jst()


    print(
        "FIX17 1分足保存開始:",
        started.isoformat()
    )


    market_date = today_jst()


    # --------------------------------------------------------
    # JPX営業日を先に判定
    #
    # 非営業日はYahooへ4208銘柄を投げない。
    # --------------------------------------------------------

    if not is_jpx_trading_day(
        market_date
    ):

        reason = (
            jpx_non_trading_reason(
                market_date
            )
            or
            "JPX_NON_TRADING_DAY"
        )

        return write_skip_result(
            reason
        )


    codes = load_universe()


    print(
        "対象銘柄数:",
        len(
            codes
        )
    )


    print(
        "Batch size:",
        BATCH_SIZE
    )


    print(
        "JPX trading day:",
        market_date
    )


    data, failures = download_all(
        codes
    )


    # --------------------------------------------------------
    # ここまで来ている時点でJPX営業日。
    #
    # したがって全銘柄で当日データ0件なら、
    # 「祝日」ではなくデータ取得障害。
    # --------------------------------------------------------

    if is_market_closed_result(
        data
    ):

        raise RuntimeError(
            "JPX営業日なのに当日1分足が"
            "全銘柄0件です。\n"
            "Yahoo Finance取得障害・遅延・"
            "ネットワーク障害の可能性があります。\n"
            f"market_date={market_date}\n"
            f"universe={len(codes)}"
        )


    validation = validate_data(
        data,
        codes,
        failures,
    )


    market_date_str = validation[
        "market_date"
    ]


    local_path = write_local_parquet(
        data,
        market_date_str,
    )


    gcs = upload_to_gcs(
        local_path,
        market_date_str,
    )


    result = {
        "status":
            "SUCCESS",

        "time":
            now_jst().isoformat(),

        "market_date":
            market_date_str,

        "jpx_trading_day":
            True,

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
        market_date_str
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
        "success ratio:",
        f"{validation['success_ratio']:.2%}"
    )


    print(
        "GCS:",
        gcs[
            "gs_uri"
        ]
    )


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

        error_text = (
            traceback.format_exc()
        )


        try:

            save_json(
                LAST_RESULT_FILE,
                {
                    "status":
                        "ERROR",

                    "time":
                        now_jst().isoformat(),

                    "market_date":
                        str(
                            today_jst()
                        ),

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
