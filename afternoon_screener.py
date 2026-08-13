午後買い候補スクリーナー v0.1

完全仮想取引版

目的:

  12:00時点の情報を使って、12:30以降のブレイク候補を抽出する。

  実注文は一切行わない。

今回は検証用として、

  ・データ取得成功数

  ・スコアリング到達数

  ・候補選定数

  ・除外理由

を表示する。

"""

import math

import json

from datetime import datetime

from pathlib import Path

import numpy as np

import pandas as pd

import yfinance as yf

# =========================

# 設定

# =========================

VIRTUAL_CAPITAL = 3_400_000

MAX_RISK_PER_TRADE = 5_000

MAX_POSITIONS = 2

TOP_N = 5

TICKERS = [

    "7011.T", "7013.T", "8306.T", "8411.T", "9101.T",

    "9984.T", "5803.T", "6981.T", "8035.T", "6857.T",

    "6146.T", "6723.T", "7735.T", "4062.T", "6762.T",

    "6501.T", "6503.T", "7267.T", "7203.T", "6902.T",

    "8001.T", "8031.T", "8058.T", "8053.T", "8002.T",

    "4502.T", "4568.T", "4503.T", "4507.T",

    "8316.T", "8750.T", "8766.T",

    "9104.T", "9107.T",

    "1605.T", "5020.T",

    "6098.T", "4385.T", "2413.T",

    "2914.T", "3382.T", "8267.T",

    "9843.T", "9983.T",

    "2802.T", "2801.T",

    "7269.T", "7270.T",

    "6724.T", "6594.T",

    "6506.T", "6367.T",

]

LOG_FILE = Path("paper_trades.csv")

# =========================

# 5分足取得

# =========================

def get_intraday(ticker: str):

    """直近5日間の5分足を取得。"""

    try:

        df = yf.download(

            ticker,

            period="5d",

            interval="5m",

            auto_adjust=False,

            progress=False,

            threads=False,

        )

        if df is None or df.empty:

            return None, "データなし"

        if isinstance(df.columns, pd.MultiIndex):

            df.columns = df.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}

        if not required.issubset(df.columns):

            return None, "必要列不足"

        df = df[list(required)].dropna().copy()

        if df.empty:

            return None, "NaN除去後データなし"

        df.index = pd.to_datetime(df.index)

        # 日本時間へ変換

        if df.index.tz is None:

            df.index = df.index.tz_localize("UTC").tz_convert("Asia/Tokyo")

        else:

            df.index = df.index.tz_convert("Asia/Tokyo")

        return df, "OK"

    except Exception as e:

        return None, f"取得エラー: {type(e).__name__}"

# =========================

# スコアリング

# =========================

def score_candidate(df: pd.DataFrame, ticker: str):

    """

    12:00時点までのデータでスコア。

    """

    if df is None or df.empty:

        return None, "データなし"

    now = df.index[-1]

    today = now.date()

    d = df[df.index.date == today].copy()

    if len(d) < 10:

        return None, "当日データ不足"

    # 12:00以前だけ使用

    d = d[d.index.time <= pd.Timestamp("12:00").time()]

    if len(d) < 10:

        return None, "12:00までのデータ不足"

    # =========================

    # 基本指標

    # =========================

    close = float(d["Close"].iloc[-1])

    high = float(d["High"].max())

    low = float(d["Low"].min())

    volume = float(d["Volume"].sum())

    if close <= 0:

        return None, "価格異常"

    # VWAP

    typical = (

        d["High"] +

        d["Low"] +

        d["Close"]

    ) / 3

    volume_sum = d["Volume"].sum()

    if volume_sum <= 0:

        return None, "出来高なし"

    vwap = float(

        (typical * d["Volume"]).sum()

        / volume_sum

    )

    if not np.isfinite(vwap):

        return None, "VWAP異常"

    # =========================

    # 直近30分

    # =========================

    recent = d.tail(6)

    if len(recent) < 6:

        return None, "30分データ不足"

    recent_change = float(

        recent["Close"].iloc[-1]

        / recent["Close"].iloc[0]

        - 1

    )

    # =========================

    # 前半→後半

    # =========================

    mid = len(d) // 2

    if mid <= 0:

        return None, "前半データ不足"

    first_half = float(

        d["Close"].iloc[:mid].mean()

    )

    second_half = float(

        d["Close"].iloc[mid:].mean()

    )

    intraday_trend = (

        second_half / first_half - 1

        if first_half

        else 0

    )

    # =========================

    # VWAP乖離

    # =========================

    vwap_gap = close / vwap - 1

    # =========================

    # 高値からの距離

    # =========================

    high_gap = high / close - 1

    # =========================

    # スコア

    # =========================

    score = 0

    # VWAPより上

    if vwap_gap > 0:

        score += 25

        if vwap_gap >= 0.003:

            score += 5

    # 高値圏

    if high_gap <= 0.003:

        score += 20

    elif high_gap <= 0.008:

        score += 12

    # 直近30分上昇

    if recent_change > 0.003:

        score += 20

    elif recent_change > 0:

        score += 10

    # 午前後半改善

    if intraday_trend > 0.002:

        score += 15

    elif intraday_trend > 0:

        score += 8

    # 出来高

    if volume >= 300_000:

        score += 10

    elif volume >= 100_000:

        score += 5

    # 過熱減点

    if vwap_gap > 0.025:

        score -= 15

    elif vwap_gap > 0.015:

        score -= 8

    # =========================

    # 逆指値

    # =========================

    trigger = math.ceil(

        (high * 1.001) / 5

    ) * 5

    # =========================

    # 損切り

    # =========================

    stop_base = max(vwap, low)

    stop = math.floor(

        (stop_base * 0.995) / 5

    ) * 5

    risk_per_share = trigger - stop

    if risk_per_share <= 0:

        return None, "リスク幅異常"

    # =========================

    # 推奨株数

    # =========================

    shares = int(

        MAX_RISK_PER_TRADE

        // risk_per_share

    )

    shares = (

        shares // 100

    ) * 100

    if shares < 100:

        shares = 0

    required_cash = trigger * shares

    # =========================

    # 結果

    # =========================

    result = {

        "ticker": ticker,

        "time": d.index[-1].strftime(

            "%Y-%m-%d %H:%M"

        ),

        "score": int(score),

        "price": round(close, 1),

        "vwap": round(vwap, 1),

        "morning_high": round(high, 1),

        "morning_low": round(low, 1),

        "vwap_gap_pct": round(

            vwap_gap * 100,

            2

        ),

        "recent30m_pct": round(

            recent_change * 100,

            2

        ),

        "intraday_trend_pct": round(

            intraday_trend * 100,

            2

        ),

        "volume": int(volume),

        "trigger": trigger,

        "stop": stop,

        "risk_per_share": round(

            risk_per_share,

            1

        ),

        "shares": shares,

        "required_cash": required_cash,

    }

    return result, "OK"

# =========================

# ログ

# =========================

def load_log():

    if LOG_FILE.exists():

        return pd.read_csv(LOG_FILE)

    return pd.DataFrame()

def append_virtual_candidates(results):

    rows = []

    for r in results:

        if (

            r["shares"] >= 100

            and r["score"] >= 60

        ):

            rows.append({

                "date": r["time"][:10],

                "signal_time": r["time"],

                "ticker": r["ticker"],

                "score": r["score"],

                "entry_trigger": r["trigger"],

                "stop": r["stop"],

                "shares": r["shares"],

                "status": "PENDING",

                "exit_price": "",

                "pnl": "",

            })

    if not rows:

        return

    new = pd.DataFrame(rows)

    old = load_log()

    out = pd.concat(

        [old, new],

        ignore_index=True

    )

    out.to_csv(

        LOG_FILE,

        index=False,

        encoding="utf-8-sig"

    )

# =========================

# メイン

# =========================

def main():

    results = []

    total = len(TICKERS)

    download_success = 0

    scoring_success = 0

    failure_reasons = {}

    print("=" * 78)

    print(

        "午後買い候補スクリーナー v0.1 "

        "（仮想取引）"

    )

    print(

        "実注文は行いません"

    )

    print("=" * 78)

    print(

        f"対象銘柄数: {total}"

    )

    print()

    # =========================

    # データ取得

    # =========================

    for ticker in TICKERS:

        df, status = get_intraday(ticker)

        if df is None:

            failure_reasons[status] = (

                failure_reasons.get(

                    status,

                    0

                ) + 1

            )

            continue

        download_success += 1

        r, score_status = score_candidate(

            df,

            ticker

        )

        if r is None:

            failure_reasons[

                score_status

            ] = (

                failure_reasons.get(

                    score_status,

                    0

                ) + 1

            )

            continue

        scoring_success += 1

        results.append(r)

    # =========================

    # 並び替え

    # =========================

    results = sorted(

        results,

        key=lambda x: x["score"],

        reverse=True

    )

    # =========================

    # 統計

    # =========================

    print()

    print("=" * 78)

    print("データ取得状況")

    print("=" * 78)

    print(

        f"対象銘柄数       : {total}"

    )

    print(

        f"データ取得成功   : {download_success}"

    )

    print(

        f"スコアリング成功 : {scoring_success}"

    )

    print(

        f"候補選定         : "

        f"{sum("

        f"1 for r in results "

        f"if r['shares'] >= 100 "

        f"and r['score'] >= 60"

        f")}"

    )

    # =========================

    # 除外理由

    # =========================

    if failure_reasons:

        print()

        print(

            "除外・失敗理由:"

        )

        for reason, count in sorted(

            failure_reasons.items(),

            key=lambda x: x[1],

            reverse=True

        ):

            print(

                f"  {reason}: {count}"

            )

    # =========================

    # 上位候補

    # =========================

    print()

    print("=" * 78)

    print("スコア上位銘柄")

    print("=" * 78)

    if not results:

        print(

            "スコアリング可能な銘柄なし"

        )

    else:

        for i, r in enumerate(

            results[:TOP_N],

            1

        ):

            print(

                f"{i}. "

                f"{r['ticker']} "

                f"Score={r['score']} "

                f"現在={r['price']} "

                f"VWAP={r['vwap']} "

                f"前場高値={r['morning_high']} "

                f"30分={r['recent30m_pct']}% "

                f"逆指値={r['trigger']} "

                f"損切={r['stop']} "

                f"株数={r['shares']}"

            )

    # =========================

    # 最終候補

    # =========================

    selected = [

        r

        for r in results

        if (

            r["shares"] >= 100

            and r["score"] >= 60

        )

    ][:TOP_N]

    print()

    print("=" * 78)

    print("最終候補")

    print("=" * 78)

    if not selected:

        print(

            "条件を満たす候補なし"

        )

    else:

        for i, r in enumerate(

            selected,

            1

        ):

            print(

                f"{i}. "

                f"{r['ticker']} "

                f"Score={r['score']} "

                f"逆指値={r['trigger']} "

                f"損切={r['stop']} "

                f"株数={r['shares']}"

            )

    # =========================

    # 仮想注文ログ

    # =========================

    append_virtual_candidates(

        selected

    )

    # =========================

    # JSON

    # =========================

    with open(

        "latest_candidates.json",

        "w",

        encoding="utf-8"

    ) as f:

        json.dump(

            selected,

            f,

            ensure_ascii=False,

            indent=2

        )

    print()

    print(

        f"仮想注文ログ: {LOG_FILE}"

    )

    print(

        "次の段階で "

        "「逆指値が実際に約定したか」"

        "「その後の損益」を自動判定します。"

    )

if __name__ == "__main__":

    main()
