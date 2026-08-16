
            df["close"],

            errors="coerce"

        ).dropna()

        if len(close) < RS_LOOKBACK + 2:

            continue

        close.index = pd.to_datetime(

            close.index

        ).normalize()

        returns[ticker] = (

            close.shift(1)

            /

            close.shift(

                RS_LOOKBACK + 1

            )

            - 1

        )

    if not returns:

        return {}

    stocks = pd.DataFrame(

        returns

    )

    common = stocks.index.intersection(

        market_return.index

    )

    stocks = stocks.loc[common]

    market_return = market_return.loc[common]

    relative = stocks.sub(

        market_return,

        axis=0

    )

    rs = (

        relative

        .rank(

            axis=1,

            pct=True

        )

        * 100

    )

    today = datetime.now(TZ).date()

    valid = rs[

        rs.index.date < today

    ]

    if valid.empty:

        return {}

    return valid.iloc[-1].dropna().to_dict()

# ============================================================

# Morning High

# ============================================================

def get_morning_high(df, date):

    day = df[

        df.index.date == date

    ]

    if day.empty:

        return None

    morning = day.between_time(

        MORNING_START,

        MORNING_END

    )

    if morning.empty:

        return None

    return float(

        morning["high"].max()

    )

# ============================================================

# 12:45候補抽出

# ============================================================

def find_candidates():

    print("RS計算中...")

    rs = calculate_rs()

    if not rs:

        return []

    today = datetime.now(TZ).date()

    candidates = []

    for ticker, rs_value in rs.items():

        if rs_value < RS_THRESHOLD:

            continue

        df = download_5m(ticker)

        if df is None:

            continue

        morning_high = get_morning_high(

            df,

            today

        )

        if morning_high is None:

            continue

        day = df[

            df.index.date == today

        ]

        afternoon = day[

            day.index.strftime("%H:%M")

            >= ENTRY_TIME

        ]

        if afternoon.empty:

            continue

        price = float(

            afternoon.iloc[-1]["close"]

        )

        # Morning High突破

        if price < morning_high:

            continue

        candidates.append({

            "ticker": ticker,

            "rs": float(rs_value),

            "morning_high": morning_high,

            "entry": price,

            "tp": price * (1 + TP),

            "sl": price * (1 - SL)

        })

    candidates.sort(

        key=lambda x: x["rs"],

        reverse=True

    )

    return candidates

# ============================================================

# 仮想エントリー

# ============================================================

def enter_positions(

    portfolio,

    candidates

):

    existing = {

        p["ticker"]

        for p in portfolio["positions"]

    }

    candidates = [

        c for c in candidates

        if c["ticker"] not in existing

    ]

    slots = (

        MAX_POSITIONS

        - len(existing)

    )

    candidates = candidates[:slots]

    executed = []

    capital_per_position = (

        INITIAL_CAPITAL

        / MAX_POSITIONS

    )

    for c in candidates:

        price = c["entry"]

        shares = int(

            capital_per_position

            / price

            / 100

        ) * 100

        if shares <= 0:

            continue

        cost = (

            price * shares

        )

        if cost > portfolio["cash"]:

            continue

        position = {

            "ticker": c["ticker"],

            "entry_date": datetime.now(

                TZ

            ).date().isoformat(),

            "entry_price": price,

            "shares": shares,

            "tp": c["tp"],

            "sl": c["sl"],

            "rs": c["rs"],

            "morning_high": c[

                "morning_high"

            ]

        }

        portfolio["positions"].append(

            position

        )

        portfolio["cash"] -= cost

        executed.append(position)

    return executed

# ============================================================

# TP / SL判定

# ============================================================

def check_positions(portfolio):

    today = datetime.now(TZ).date()

    closed = []

    holding = []

    for p in portfolio["positions"]:

        df = download_5m(

            p["ticker"]

        )

        if df is None:

            holding.append(p)

            continue

        day = df[

            df.index.date == today

        ]

        if day.empty:

            holding.append(p)

            continue

        tp = float(p["tp"])

        sl = float(p["sl"])

        exit_price = None

        reason = None

        for _, row in day.iterrows():

            high = float(row["high"])

            low = float(row["low"])

            # 同一5分足でTP/SL両方に到達した場合

            # 保守的にSLを優先

            if low <= sl:

                exit_price = sl

                reason = "SL"

                break

            if high >= tp:

                exit_price = tp

                reason = "TP"

                break

        if exit_price is None:

            holding.append(p)

            continue

        pnl = (

            exit_price

            - p["entry_price"]

        ) * p["shares"]

        portfolio["cash"] += (

            exit_price

            * p["shares"]

        )

        portfolio["realized_pnl"] += pnl

        closed.append({

            "ticker": p["ticker"],

            "entry": p["entry_price"],

            "exit": exit_price,

            "shares": p["shares"],

            "pnl": pnl,

            "reason": reason

        })

    portfolio["positions"] = holding

    return closed

# ============================================================

# CSV記録

# ============================================================

def save_trades(trades):

    if not trades:

        return

    os.makedirs(

        "data",

        exist_ok=True

    )

    rows = []

    now = datetime.now(

        TZ

    ).isoformat()

    for t in trades:

        rows.append({

            "datetime": now,

            "ticker": t["ticker"],

            "entry": t["entry"],

            "exit": t["exit"],

            "shares": t["shares"],

            "pnl": t["pnl"],

            "reason": t["reason"]

        })

    new = pd.DataFrame(rows)

    if os.path.exists(

        TRADES_FILE

    ):

        old = pd.read_csv(

            TRADES_FILE

        )

        new = pd.concat(

            [old, new],

            ignore_index=True

        )

    new.to_csv(

        TRADES_FILE,

        index=False,

        encoding="utf-8-sig"

    )

# ============================================================

# メール

# ============================================================

def send_email(subject, body):

    host = os.environ.get(

        "SMTP_HOST"

    )

    port = int(

        os.environ.get(

            "SMTP_PORT",

            "587"

        )

    )

    user = os.environ.get(

        "SMTP_USER"

    )

    password = os.environ.get(

        "SMTP_PASSWORD"

    )

    recipient = os.environ.get(

        "MAIL_TO"

    )

    if not all([

        host,

        user,

        password,

        recipient

    ]):

        raise RuntimeError(

            "メール用GitHub Secretsが未設定です"

        )

    msg = MIMEText(

        body,

        "plain",

        "utf-8"

    )

    msg["Subject"] = Header(

        subject,

        "utf-8"

    )

    msg["From"] = user

    msg["To"] = recipient

    with smtplib.SMTP(

        host,

        port,

        timeout=30

    ) as server:

        server.starttls()

        server.login(

            user,

            password

        )

        server.send_message(

            msg

        )

# ============================================================

# 12:45

# ============================================================

def run_1245():

    portfolio = load_portfolio()

    candidates = find_candidates()

    executed = enter_positions(

        portfolio,

        candidates

    )

    save_portfolio(

        portfolio

    )

    lines = []

    lines.append(

        "【仮想取引】12:45 売買指示"

    )

    lines.append("")

    if executed:

        lines.append(

            "【仮想エントリー】"

        )

        for p in executed:

            lines.append(

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f} "

                f"TP ¥{p['tp']:,.1f} "

                f"SL ¥{p['sl']:,.1f} "

                f"RS {p['rs']:.1f}"

            )

    else:

        lines.append(

            "【新規エントリーなし】"

        )

        if candidates:

            lines.append("")

            lines.append("候補:") 

            for c in candidates[:10]:

                lines.append(

                    f"{c['ticker']} "

                    f"RS {c['rs']:.1f} "

                    f"Entry ¥{c['entry']:,.1f}"

                )

        else:

            lines.append(

                "RS70 + Morning High Breakout"

            )

            lines.append(

                "条件を満たす銘柄なし"

            )

    lines.append("")

    lines.append("【持越し】")

    if portfolio["positions"]:

        for p in portfolio["positions"]:

            lines.append(

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f}"

            )

    else:

        lines.append("なし")

    send_email(

        "【仮想取引】12:45 売買指示",

        "\n".join(lines)

    )

# ============================================================

# 15:45

# ============================================================

def run_1545():

    portfolio = load_portfolio()

    closed = check_positions(

        portfolio

    )

    save_trades(closed)

    save_portfolio(

        portfolio

    )

    lines = []

    lines.append(

        "【仮想取引】15:45 結果報告"

    )

    lines.append("")

    lines.append(

        f"仮想現金: ¥{portfolio['cash']:,.0f}"

    )

    lines.append(

        f"累計確定損益: "

        f"¥{portfolio['realized_pnl']:,.0f}"

    )

    lines.append("")

    lines.append("【本日の決済】")

    if closed:

        for t in closed:

            sign = "+" if t["pnl"] >= 0 else ""

            lines.append(

                f"{t['ticker']} "

                f"{t['reason']} "

                f"{sign}¥{t['pnl']:,.0f}"

            )

    else:

        lines.append(

            "決済なし"

        )

    lines.append("")

    lines.append("【持越し】")

    if portfolio["positions"]:

        for p in portfolio["positions"]:

            lines.append(

                f"{p['ticker']} "

                f"{p['shares']}株 "

                f"Entry ¥{p['entry_price']:,.1f}"

            )

    else:

        lines.append("なし")

    send_email(

        "【仮想取引】15:45 結果・持越し報告",

        "\n".join(lines)

    )

# ============================================================

# MAIN

# ============================================================

def main():

    now = datetime.now(TZ)

    print(

        f"現在時刻: {now:%Y-%m-%d %H:%M:%S}"

    )

    if (

        now.hour == 12

        and 40 <= now.minute <= 55
) or (

    os.environ.get("FORCE_1245") == "1"
    ):

        run_1245()

    elif (

        now.hour == 15

        and 40 <= now.minute <= 55

    ):

        run_1545()

    else:

        print(

            "実行時間外"

        )

if __name__ == "__main__":

    main()
