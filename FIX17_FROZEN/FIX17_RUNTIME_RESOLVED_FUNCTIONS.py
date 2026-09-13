# ============================================================
# FIX17 RESOLVED RUNTIME FUNCTIONS
# STATIC EXTRACTION ONLY
# DO NOT USE DIRECTLY FOR LIVE TRADING
# ============================================================


# ============================================================
# FUNCTION #1
# NAME   : _fix16_download_bytes
# SOURCE : FIX17_ROOT
# LINES  : 71-89
# ============================================================

def _fix16_download_bytes(file_id):

    req = _fix16_drive.files().get_media(
        fileId=file_id
    )

    buf = io.BytesIO()

    dl = MediaIoBaseDownload(
        buf,
        req
    )

    done = False

    while not done:
        _, done = dl.next_chunk()

    return buf.getvalue()


# ============================================================
# FUNCTION #2
# NAME   : _download_text
# SOURCE : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# LINES  : 108-119
# ============================================================

def _download_text(file_id):

    data = (
        _drive.files()
        .get_media(fileId=file_id)
        .execute()
    )

    if isinstance(data, bytes):
        return data.decode("utf-8")

    return str(data)


# ============================================================
# FUNCTION #3
# NAME   : _sha256_text
# SOURCE : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# LINES  : 122-126
# ============================================================

def _sha256_text(text):

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# ============================================================
# FUNCTION #4
# NAME   : fix15_ensure_tax_year
# SOURCE : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# LINES  : 250-263
# ============================================================

def fix15_ensure_tax_year(year):

    year = int(year)

    if year not in FIX15_TAX_STATE:

        FIX15_TAX_STATE[year] = {
            "TaxablePnL": 0.0,
            "TheoreticalTax": 0.0,
            "Withheld": 0.0,
            "Refunded": 0.0,
        }

    return FIX15_TAX_STATE[year]


# ============================================================
# FUNCTION #5
# NAME   : fix15_apply_tax
# SOURCE : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# LINES  : 266-347
# ============================================================

def fix15_apply_tax(
    dt,
    taxable_pnl,
    source,
    detail="",
):

    dt = pd.Timestamp(dt)

    s = fix15_ensure_tax_year(
        dt.year
    )

    taxable_pnl = float(
        taxable_pnl
    )

    old_ytd = float(
        s["TaxablePnL"]
    )

    old_tax = float(
        s["TheoreticalTax"]
    )

    new_ytd = (
        old_ytd
        +
        taxable_pnl
    )

    new_tax = (
        max(
            new_ytd,
            0.0,
        )
        *
        TAX_RATE_FIX15
    )

    tax_change = (
        new_tax
        -
        old_tax
    )

    if tax_change > 0:

        s["Withheld"] += (
            tax_change
        )

    elif tax_change < 0:

        s["Refunded"] += (
            -tax_change
        )

    s["TaxablePnL"] = (
        new_ytd
    )

    s["TheoreticalTax"] = (
        new_tax
    )

    FIX15_TAX_LEDGER.append({
        "Datetime": dt,
        "Year": int(dt.year),
        "Source": str(source),
        "Detail": str(detail),
        "TaxablePnL": taxable_pnl,
        "TaxChange": tax_change,
        "YTDBefore": old_ytd,
        "YTDAfter": new_ytd,
        "TaxBefore": old_tax,
        "TaxAfter": new_tax,
    })

    return float(
        tax_change
    )


# ============================================================
# FUNCTION #6
# NAME   : simulate_profit_floor_trail
# SOURCE : FIX17_ROOT
# LINES  : 330-730
# ============================================================

def simulate_profit_floor_trail(
    trade,
    trigger_pct,
    width_pct,
):

    code = str(
        trade["Code"]
    ).zfill(5)

    entry_dt = np.datetime64(
        pd.Timestamp(
            trade["EntryDatetime"]
        ),
        "ns",
    )

    formal_exit_dt = np.datetime64(
        pd.Timestamp(
            trade["ExitDatetime"]
        ),
        "ns",
    )

    entry_price = float(
        trade["EntryPrice"]
    )

    formal_ret = float(
        trade["BrokerReturnPct"]
    )

    arr = minute_np15.get(code)

    if arr is None:
        raise RuntimeError(
            f"1分足なし: {code}"
        )

    dt = arr["dt"]
    dates = arr["date"]

    oo = arr["o"]
    hh = arr["h"]
    ll = arr["l"]


    # ========================================================
    # Trigger価格
    # ========================================================

    trigger_price = (
        entry_price
        * (
            1.0
            + trigger_pct
        )
    )


    # ========================================================
    # ENTRYの次の1分足から開始
    # ========================================================

    start = int(
        np.searchsorted(
            dt,
            entry_dt,
            side="right",
        )
    )


    # ========================================================
    # 正式FIX15 EXIT位置
    # 同じ1分足でTriggerした場合は正式EXIT優先
    # ========================================================

    formal_idx = int(
        np.searchsorted(
            dt,
            formal_exit_dt,
            side="left",
        )
    )


    # ========================================================
    # 正式EXITより前にTriggerしたか
    # ========================================================

    trigger_idx = None

    for i in range(
        start,
        min(
            formal_idx,
            len(dt),
        ),
    ):

        if float(
            hh[i]
        ) >= trigger_price:

            trigger_idx = i
            break


    # ========================================================
    # Triggerなし
    #
    # → FIX15正式EXITを完全維持
    # ========================================================

    if trigger_idx is None:

        return {
            "ExitDatetime":
                pd.Timestamp(
                    formal_exit_dt
                ),

            "ReturnPct":
                formal_ret,

            "ExitReason":
                "FORMAL_EXIT",

            "TriggerHit":
                False,

            "TriggerDatetime":
                pd.NaT,

            "TrailExit":
                False,

            "MaxHigh":
                np.nan,

            "FinalStop":
                np.nan,
        }


    # ========================================================
    # Trigger成立
    # ========================================================

    trigger_dt = dt[
        trigger_idx
    ]

    running_high = max(
        trigger_price,
        float(
            hh[trigger_idx]
        ),
    )


    # ========================================================
    # 最初の売却ライン
    #
    # Trigger価格を絶対床にする
    # ========================================================

    trail_component = (
        running_high
        * (
            1.0
            - width_pct
        )
    )

    stop_price = max(
        trigger_price,
        trail_component,
    )


    # ========================================================
    # Triggerの次の1分足からEXIT判定
    # ========================================================

    for i in range(
        trigger_idx + 1,
        len(dt),
    ):

        o = float(
            oo[i]
        )

        h = float(
            hh[i]
        )

        l = float(
            ll[i]
        )


        # ====================================================
        # 営業日最初のバー
        # ====================================================

        session_first = (
            i == 0
            or
            dates[i]
            != dates[i - 1]
        )


        # ====================================================
        # 1. GAP DOWN
        #
        # Stopより下で寄った場合はOPENでEXIT
        # ====================================================

        if (
            session_first
            and
            o <= stop_price
        ):

            exit_market = o

            exit_exec = (
                exit_market
                * (
                    1.0
                    - EXIT_SLIPPAGE
                )
            )

            ret = (
                exit_exec
                / entry_price
                - 1.0
            ) * 100.0

            return {
                "ExitDatetime":
                    pd.Timestamp(
                        dt[i]
                    ),

                "ReturnPct":
                    ret,

                "ExitReason":
                    "OPEN_BELOW_PROFIT_STOP",

                "TriggerHit":
                    True,

                "TriggerDatetime":
                    pd.Timestamp(
                        trigger_dt
                    ),

                "TrailExit":
                    True,

                "MaxHigh":
                    running_high,

                "FinalStop":
                    stop_price,
            }


        # ====================================================
        # 2. 現在有効な売却ライン
        #
        # Trigger直後:
        #     stop = trigger価格
        #
        # 十分上昇後:
        #     stop = high × (1-width)
        # ====================================================

        if l <= stop_price:

            exit_market = (
                stop_price
            )

            exit_exec = (
                exit_market
                * (
                    1.0
                    - EXIT_SLIPPAGE
                )
            )

            ret = (
                exit_exec
                / entry_price
                - 1.0
            ) * 100.0

            return {
                "ExitDatetime":
                    pd.Timestamp(
                        dt[i]
                    ),

                "ReturnPct":
                    ret,

                "ExitReason":
                    (
                        "TRIGGER_FLOOR"
                        if stop_price
                        <= trigger_price
                        * (
                            1.0
                            + 1e-12
                        )
                        else
                        "TRAIL"
                    ),

                "TriggerHit":
                    True,

                "TriggerDatetime":
                    pd.Timestamp(
                        trigger_dt
                    ),

                "TrailExit":
                    True,

                "MaxHigh":
                    running_high,

                "FinalStop":
                    stop_price,
            }


        # ====================================================
        # 3. High更新
        #
        # 更新したstopは次の1分足から有効
        # ====================================================

        if h > running_high:

            running_high = h

            trail_component = (
                running_high
                * (
                    1.0
                    - width_pct
                )
            )

            stop_price = max(
                trigger_price,
                trail_component,
            )


    # ========================================================
    # データ終了
    # ========================================================

    return {
        "ExitDatetime":
            pd.NaT,

        "ReturnPct":
            np.nan,

        "ExitReason":
            "NO_EXIT",

        "TriggerHit":
            True,

        "TriggerDatetime":
            pd.Timestamp(
                trigger_dt
            ),

        "TrailExit":
            False,

        "MaxHigh":
            running_high,

        "FinalStop":
            stop_price,
    }


# ============================================================
# FUNCTION #7
# NAME   : simulate_fix15
# SOURCE : FIX17_ROOT
# LINES  : 1202-1537
# ============================================================

def simulate_fix15():
    cash = float(INITIAL_CAPITAL)
    etf_shares = 0
    formal_equity = float(INITIAL_CAPITAL)
    broker_strategy_equity = float(INITIAL_CAPITAL)
    formal_active = {}
    broker_active = {}
    broker_skipped = set()
    tx_rows = []
    entry_rows = []
    trade_rows = []
    daily_rows = []
    previous_date = None
    last_etf_close = np.nan
    initial_purchase_done = False
    cum_long_interest = 0.0
    cum_short_fee = 0.0

    def current_broker_notional():
        long_n = 0.0
        short_n = 0.0
        for p in broker_active.values():
            if p['Side'] == 'LONG':
                long_n += float(p['ActualNotional'])
            else:
                short_n += float(p['ActualNotional'])
        return (long_n, short_n)
    for date in sorted(pd.to_datetime(sim_dates)):
        date = pd.Timestamp(date).normalize()
        has_quote = date in quote_dates
        is_monthly_buy = date in monthly_buy_dates
        if has_quote:
            etf_open = float(open_map[date])
            etf_close = float(close_map[date])
            if np.isfinite(etf_close) and etf_close > 0:
                last_etf_close = etf_close
        else:
            etf_open = np.nan
            etf_close = float(last_etf_close) if np.isfinite(last_etf_close) else np.nan
        long_interest_today = 0.0
        short_fee_today = 0.0
        if previous_date is not None:
            calendar_days = int((date - previous_date).days)
            for p in broker_active.values():
                n = float(p['ActualNotional'])
                if p['Side'] == 'LONG':
                    cost = n * LONG_INTEREST_ANNUAL * calendar_days / DAY_COUNT
                    long_interest_today += cost
                else:
                    cost = n * SHORT_LENDING_ANNUAL * calendar_days / DAY_COUNT
                    short_fee_today += cost
        financing_today = long_interest_today + short_fee_today
        cash -= financing_today
        broker_strategy_equity -= financing_today
        cum_long_interest += long_interest_today
        cum_short_fee += short_fee_today
        bought_etf_today = 0
        sold_etf_today = 0
        recovery_sell_today = False
        if has_quote and np.isfinite(etf_open) and (etf_open > 0):
            if cash < CASH_FLOOR:
                deficit = CASH_FLOOR - cash
                required_sell = int(np.ceil(deficit / etf_open))
                sell_shares = min(required_sell, etf_shares)
                if sell_shares > 0:
                    proceeds = sell_shares * etf_open
                    cash_before = float(cash)
                    fix15_etf_realized = (
                        float(sell_shares)
                        * (
                            float(etf_open)
                            - float(FIX15_ETF_BOOK["avg_cost"])
                        )
                        - float(ETF_SELL_FEE)
                    )

                    etf_shares -= sell_shares
                    cash += proceeds - ETF_SELL_FEE

                    fix15_spot_tax = fix15_apply_tax(
                        date,
                        fix15_etf_realized,
                        "1557_SPOT",
                        "SELL_CASH_RECOVERY",
                    )

                    cash -= fix15_spot_tax

                    if etf_shares == 0:
                        FIX15_ETF_BOOK["avg_cost"] = 0.0

                    sold_etf_today = sell_shares
                    recovery_sell_today = True
                    tx_rows.append({'Date': date, 'Type': 'SELL_CASH_RECOVERY', 'Price': etf_open, 'Shares': sell_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
            should_buy = not initial_purchase_done or is_monthly_buy
            if should_buy and (not recovery_sell_today):
                long_n, short_n = current_broker_notional()
                gross_n = long_n + short_n
                buy_shares = calc_max_etf_buy_shares(cash_now=cash, shares_now=etf_shares, etf_open=etf_open, gross_notional=gross_n)
                if buy_shares > 0:
                    total_cost = buy_shares * etf_open + ETF_BUY_FEE
                    if cash - total_cost < CASH_FLOOR:
                        buy_shares = int(max(0, (cash - CASH_FLOOR - ETF_BUY_FEE) // etf_open))
                        total_cost = buy_shares * etf_open + ETF_BUY_FEE
                    if buy_shares > 0:
                        cash_before = float(cash)

                        fix15_old_etf_shares = int(
                            etf_shares
                        )

                        fix15_old_cost = (
                            float(fix15_old_etf_shares)
                            * float(FIX15_ETF_BOOK["avg_cost"])
                        )

                        fix15_new_cost = (
                            float(buy_shares)
                            * float(etf_open)
                            + float(ETF_BUY_FEE)
                        )

                        etf_shares += buy_shares

                        if etf_shares > 0:

                            FIX15_ETF_BOOK["avg_cost"] = (
                                fix15_old_cost
                                + fix15_new_cost
                            ) / float(etf_shares)

                        cash -= total_cost

                        bought_etf_today = buy_shares
                        tx_rows.append({'Date': date, 'Type': 'INITIAL_BUY' if not initial_purchase_done else 'MONTHLY_BUY', 'Price': etf_open, 'Shares': buy_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
                        initial_purchase_done = True
        if has_quote and np.isfinite(etf_open) and (etf_open > 0):
            entry_etf_mark = etf_open
        else:
            entry_etf_mark = last_etf_close if np.isfinite(last_etf_close) else np.nan
        formal_realized_today = 0.0
        broker_realized_today = 0.0
        for e in events_by_date.get(date, []):
            trade_id = str(e['TradeID'])
            side = str(e['Side']).upper()
            if e['Event'] == 'EXIT':
                if trade_id not in formal_active:
                    raise RuntimeError(f"{e['Datetime']} Formal EXIT positionなし: {trade_id}")
                fp = formal_active[trade_id]
                formal_r = float(e['ReturnPct']) / 100.0
                formal_pnl = fp['EntryNotional'] * formal_r
                formal_equity += formal_pnl
                formal_realized_today += formal_pnl
                del formal_active[trade_id]
                if trade_id in broker_skipped:
                    broker_skipped.remove(trade_id)
                    continue
                if trade_id not in broker_active:
                    raise RuntimeError(f"{e['Datetime']} Broker EXIT positionなし: {trade_id}")
                bp = broker_active[trade_id]
                entry_price = float(bp['EntryPrice'])
                broker_r, exit_price = get_broker_return(side=side, entry_price=entry_price, formal_return_pct=e['ReturnPct'])
                qty = int(bp['Quantity'])
                if side == 'LONG':
                    broker_pnl = qty * (exit_price - entry_price)
                else:
                    broker_pnl = qty * (entry_price - exit_price)
                broker_strategy_equity += broker_pnl
                cash += broker_pnl

                fix15_exit_dt = pd.Timestamp(
                    e["Datetime"]
                )

                fix15_entry_dt = pd.Timestamp(
                    bp["EntryDatetime"]
                )

                fix15_raw_days = max(
                    (
                        fix15_exit_dt
                        - fix15_entry_dt
                    ).total_seconds()
                    / 86400.0,
                    0.0,
                )

                fix15_financing_days = max(
                    fix15_raw_days,
                    1.0,
                )

                fix15_notional = float(
                    bp["ActualNotional"]
                )

                if side == "LONG":

                    fix15_financing_tax = (
                        fix15_notional
                        * LONG_INTEREST_ANNUAL
                        * fix15_financing_days
                        / DAY_COUNT
                    )

                else:

                    fix15_financing_tax = (
                        fix15_notional
                        * SHORT_LENDING_ANNUAL
                        * fix15_financing_days
                        / DAY_COUNT
                    )

                fix15_taxable_pnl = (
                    float(broker_pnl)
                    - float(fix15_financing_tax)
                )

                fix15_tax_change = fix15_apply_tax(
                    fix15_exit_dt,
                    fix15_taxable_pnl,
                    f"CREDIT_{side}",
                    bp["Code"],
                )

                cash -= fix15_tax_change

                broker_strategy_equity -= (
                    fix15_tax_change
                )

                broker_realized_today += broker_pnl
                trade_rows.append({'TradeID': trade_id, 'Side': side, 'Code': bp['Code'], 'EntryDatetime': bp['EntryDatetime'], 'ExitDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'ExitPrice': exit_price, 'Quantity': qty, 'TargetNotional': bp['TargetNotional'], 'LotNotionalBeforeMargin': bp['LotNotionalBeforeMargin'], 'ActualNotional': bp['ActualNotional'], 'TargetUtilizationPct': bp['TargetUtilizationPct'], 'FormalReturnPct': float(e['ReturnPct']), 'BrokerReturnPct': broker_r * 100.0, 'BrokerPnL': broker_pnl, 'MarginLimitedAtEntry': bp['MarginLimitedAtEntry']})
                del broker_active[trade_id]
            else:
                meta = entry_meta.get(trade_id)
                if meta is None:
                    raise RuntimeError(f'entry_metaなし: {trade_id}')
                entry_price = float(meta['EntryPrice'])
                leverage = LONG_LEVERAGE if side == 'LONG' else SHORT_LEVERAGE
                formal_notional = formal_equity * leverage
                formal_active[trade_id] = {'Side': side, 'EntryNotional': formal_notional}
                if broker_strategy_equity <= 0:
                    raise RuntimeError(f'Broker strategy equity <= 0: {date.date()}')
                if side == 'LONG':
                    current_long_positions = [p for p in broker_active.values() if str(p.get('Side', '')).upper() == 'LONG']
                    current_long_count = len(current_long_positions)
                    long_allowed_positions = calc_long_dynamic_max_positions(broker_strategy_equity)
                    if current_long_count >= long_allowed_positions:
                        target_notional = 0.0
                    else:
                        current_long_gross = 0.0
                        for _p in current_long_positions:
                            _notional = _p.get('ActualNotional', np.nan)
                            if not np.isfinite(pd.to_numeric(_notional, errors='coerce')):
                                _px = pd.to_numeric(_p.get('EntryPrice', np.nan), errors='coerce')
                                _qty = pd.to_numeric(_p.get('Quantity', np.nan), errors='coerce')
                                if np.isfinite(_px) and np.isfinite(_qty):
                                    _notional = float(_px) * float(_qty)
                                else:
                                    _notional = 0.0
                            current_long_gross += float(_notional)
                        long_total_limit = max(0.0, float(broker_strategy_equity) * LONG_LEVERAGE)
                        long_remaining_capacity = max(0.0, long_total_limit - current_long_gross)
                        target_notional = long_remaining_capacity
                else:
                    target_notional = broker_strategy_equity * leverage
                target_qty = calc_target_qty(target_notional=target_notional, entry_price=entry_price)
                lot_notional_before_margin = target_qty * entry_price
                pre = calc_entry_time_position_state(broker_active=broker_active, current_date=date)
                margin_check = calc_margin_capped_qty(target_qty=target_qty, entry_price=entry_price, cash_now=cash, etf_mark=entry_etf_mark, etf_shares=etf_shares, existing_gross_notional=pre['GrossNotional'], existing_unrealized=pre['TotalUnrealized'])
                qty = int(margin_check['AllowedQty'])
                actual_notional = qty * entry_price
                utilization = actual_notional / target_notional * 100.0 if target_notional > 0 else np.nan
                skipped = qty == 0
                if target_qty == 0:
                    skip_reason = 'LOT_TOO_LARGE'
                elif qty == 0:
                    skip_reason = 'MARGIN_CAPACITY'
                else:
                    skip_reason = ''
                entry_rows.append({'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'BrokerStrategyEquity': broker_strategy_equity, 'Leverage': leverage, 'TargetNotional': target_notional, 'TargetQty100': target_qty, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'PreExistingGrossNotional': pre['GrossNotional'], 'PreExistingUnrealized': pre['TotalUnrealized'], 'EntryEffectiveCollateral': margin_check['EffectiveCollateral'], 'MaxAdditionalNotionalByMargin': margin_check['MaxNotionalByMargin'], 'PreMarginPct': margin_check['PreMarginPct'], 'PostMarginPct': margin_check['PostMarginPct'], 'Quantity': qty, 'ActualNotional': actual_notional, 'UnusedTargetNotional': target_notional - actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimited': margin_check['MarginLimited'], 'MissingPrevMarks': pre['MissingPrevMarks'], 'Skipped': skipped, 'SkipReason': skip_reason})
                if skipped:
                    broker_skipped.add(trade_id)
                    continue
                post_margin_pct = margin_check['PostMarginPct']
                if np.isfinite(post_margin_pct) and post_margin_pct < MIN_MARGIN_RATIO * 100.0 - 1e-09:
                    raise RuntimeError(f'ENTRY margin check failure: {trade_id} {post_margin_pct:.6f}%')
                broker_active[trade_id] = {'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'Quantity': qty, 'TargetNotional': target_notional, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'ActualNotional': actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimitedAtEntry': margin_check['MarginLimited']}
        long_notional = 0.0
        short_notional = 0.0
        long_unrealized = 0.0
        short_unrealized = 0.0
        missing_marks = []
        for trade_id, p in broker_active.items():
            code = p['Code']
            entry_price = float(p['EntryPrice'])
            qty = int(p['Quantity'])
            actual_notional = float(p['ActualNotional'])
            mark = daily_mark_map.get((date, code), np.nan)
            if not np.isfinite(mark):
                missing_marks.append((trade_id, code))
                continue
            if p['Side'] == 'LONG':
                u = qty * (mark - entry_price)
                long_notional += actual_notional
                long_unrealized += u
            else:
                u = qty * (entry_price - mark)
                short_notional += actual_notional
                short_unrealized += u
        gross_notional = long_notional + short_notional
        total_unrealized = long_unrealized + short_unrealized
        if np.isfinite(etf_close):
            etf_value = etf_shares * etf_close
        else:
            etf_value = 0.0
        substitute80 = etf_value * SUBSTITUTE_HAIRCUT
        effective_collateral = cash + substitute80 + total_unrealized
        if gross_notional > 0:
            margin_ratio = effective_collateral / gross_notional
        else:
            margin_ratio = np.nan
        realized_total_equity = cash + etf_value
        total_equity_mtm = realized_total_equity + total_unrealized
        daily_rows.append({'Date': date, 'ETF_Shares': etf_shares, 'ETF_Value': etf_value, 'BoughtETFToday': bought_etf_today, 'SoldETFToday': sold_etf_today, 'Cash': cash, 'CashNegative': cash < 0, 'FormalStrategyEquity': formal_equity, 'BrokerStrategyEquity': broker_strategy_equity, 'FormalRealizedPnLToday': formal_realized_today, 'BrokerRealizedPnLToday': broker_realized_today, 'LongInterestToday': long_interest_today, 'ShortFeeToday': short_fee_today, 'FinancingToday': financing_today, 'CumLongInterest': cum_long_interest, 'CumShortFee': cum_short_fee, 'CumFinancingCost': cum_long_interest + cum_short_fee, 'LongNotional': long_notional, 'ShortNotional': short_notional, 'GrossNotional': gross_notional, 'LongUnrealized': long_unrealized, 'ShortUnrealized': short_unrealized, 'TotalUnrealized': total_unrealized, 'Substitute80': substitute80, 'EffectiveCollateralMTM': effective_collateral, 'MarginRatioMTMPct': margin_ratio * 100.0 if np.isfinite(margin_ratio) else np.nan, 'Below30': gross_notional > 0 and margin_ratio < MIN_MARGIN_RATIO, 'Below20': gross_notional > 0 and margin_ratio < MARGIN_CALL_LINE, 'Below15': gross_notional > 0 and margin_ratio < SEVERE_LINE, 'MissingMarks': len(missing_marks), 'BrokerOpenPositions': len(broker_active), 'BrokerSkippedOpen': len(broker_skipped), 'RealizedTotalEquity': realized_total_equity, 'TotalEquityMTM': total_equity_mtm})
        previous_date = date
    daily = pd.DataFrame(daily_rows)
    entries = pd.DataFrame(entry_rows)
    trades = pd.DataFrame(trade_rows)
    tx = pd.DataFrame(tx_rows)
    eq = daily['TotalEquityMTM'].to_numpy(dtype=float)
    peak = np.maximum.accumulate(eq)
    daily['DrawdownMTMPct'] = (eq / peak - 1.0) * 100.0
    return (daily, entries, trades, tx, formal_active, broker_active, broker_skipped)


# ============================================================
# FUNCTION #8
# NAME   : download_drive_file
# SOURCE : DRIVE::FIX11_RECOVERY_ID::1srmgAZnbOkYEfj0aQ3QuNUwxz4cBuL6n
# LINES  : 167-199
# ============================================================

def download_drive_file(file_id, filename):

    path = os.path.join(

        "/content",

        filename

    )

    request = drive_service.files().get_media(

        fileId=file_id

    )

    with open(path, "wb") as f:

        downloader = MediaIoBaseDownload(

            f,

            request

        )

        done = False

        while not done:

            _, done = downloader.next_chunk()

    return path


# ============================================================
# FUNCTION #9
# NAME   : pick_runtime_value
# SOURCE : DRIVE::FIX11_RECOVERY_ID::1srmgAZnbOkYEfj0aQ3QuNUwxz4cBuL6n
# LINES  : 317-325
# ============================================================

def pick_runtime_value(*names):

    for name in names:

        if name in runtime_maps:

            return runtime_maps[name]

    return None


# ============================================================
# FUNCTION #10
# NAME   : calc_long_dynamic_max_positions
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 46-67
# ============================================================

def calc_long_dynamic_max_positions(equity):
    """

    CAP200 Dynamic

    equity <= 2m : 1

    equity <= 4m : 2

    equity <= 6m : 3

    ...

    2,000,000 exactly -> 1

    4,000,000 exactly -> 2

    """
    equity = float(equity)
    if not np.isfinite(equity) or equity <= 0:
        return 0
    return max(1, int(np.ceil(equity / LONG_CAP_PER_STOCK)))


# ============================================================
# FUNCTION #11
# NAME   : reconstruct_exit_price
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 122-133
# ============================================================

def reconstruct_exit_price(side, entry_price, formal_return_pct):
    r = float(formal_return_pct) / 100.0
    entry_price = float(entry_price)
    if side == 'LONG':
        return entry_price * (1.0 + r)
    elif side == 'SHORT':
        denominator = 1.0 + r
        if denominator <= 0:
            raise RuntimeError('SHORT denominator <= 0')
        return entry_price / denominator
    else:
        raise RuntimeError(f'Unknown side: {side}')


# ============================================================
# FUNCTION #12
# NAME   : get_broker_return
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 135-141
# ============================================================

def get_broker_return(side, entry_price, formal_return_pct):
    exit_price = reconstruct_exit_price(side=side, entry_price=entry_price, formal_return_pct=formal_return_pct)
    if side == 'LONG':
        broker_return = exit_price / entry_price - 1.0
    else:
        broker_return = 1.0 - exit_price / entry_price
    return (float(broker_return), float(exit_price))


# ============================================================
# FUNCTION #13
# NAME   : get_last_close_before
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 166-175
# ============================================================

def get_last_close_before(code, date):
    code = str(code).zfill(5)
    date64 = np.datetime64(pd.Timestamp(date).normalize())
    if code not in prev_history:
        return np.nan
    dates_arr, close_arr = prev_history[code]
    idx = np.searchsorted(dates_arr, date64, side='left') - 1
    if idx < 0:
        return np.nan
    return float(close_arr[idx])


# ============================================================
# FUNCTION #14
# NAME   : calc_target_qty
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 183-188
# ============================================================

def calc_target_qty(target_notional, entry_price):
    one_lot = float(entry_price) * LOT_SIZE
    if target_notional <= 0 or one_lot <= 0:
        return 0
    lots = int(np.floor(float(target_notional) / one_lot))
    return int(max(0, lots * LOT_SIZE))


# ============================================================
# FUNCTION #15
# NAME   : _fix13_calc_max_etf_buy_shares
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 190-205
# ============================================================

def _fix13_calc_max_etf_buy_shares(cash_now, shares_now, etf_open, gross_notional):
    available_cash = cash_now - CASH_FLOOR
    if available_cash < etf_open:
        return 0
    max_by_cash = int(available_cash // etf_open)
    if gross_notional <= 0:
        return max_by_cash
    current_etf_value = shares_now * etf_open
    current_collateral = cash_now + current_etf_value * SUBSTITUTE_HAIRCUT
    required_collateral = gross_notional * MIN_MARGIN_RATIO
    room = current_collateral - required_collateral
    collateral_loss_per_share = etf_open * (1.0 - SUBSTITUTE_HAIRCUT)
    if room <= 0 or collateral_loss_per_share <= 0:
        return 0
    max_by_margin = int(np.floor(room / collateral_loss_per_share))
    return min(max_by_cash, max(0, max_by_margin))


# ============================================================
# FUNCTION #16
# NAME   : calc_max_etf_buy_shares
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 207-213
# ============================================================

def calc_max_etf_buy_shares(cash_now, shares_now, etf_open, gross_notional):
    original_max = _fix13_calc_max_etf_buy_shares(cash_now=cash_now, shares_now=shares_now, etf_open=etf_open, gross_notional=gross_notional)
    liquid_assets = float(cash_now) + float(shares_now) * float(etf_open)
    target_cash = liquid_assets * 0.1
    spendable = max(0.0, float(cash_now) - target_cash - float(ETF_BUY_FEE))
    max_by_reserve = int(spendable // float(etf_open))
    return int(max(0, min(int(original_max), int(max_by_reserve))))


# ============================================================
# FUNCTION #17
# NAME   : calc_entry_time_position_state
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 215-243
# ============================================================

def calc_entry_time_position_state(broker_active, current_date):
    long_notional = 0.0
    short_notional = 0.0
    long_unrealized = 0.0
    short_unrealized = 0.0
    missing = []
    for trade_id, p in broker_active.items():
        side = p['Side']
        code = p['Code']
        qty = int(p['Quantity'])
        entry_price = float(p['EntryPrice'])
        actual_notional = float(p['ActualNotional'])
        entry_date = pd.Timestamp(p['EntryDatetime']).normalize()
        if entry_date == current_date:
            mark = entry_price
        else:
            mark = get_last_close_before(code=code, date=current_date)
            if not np.isfinite(mark):
                mark = entry_price
                missing.append((trade_id, code))
        if side == 'LONG':
            u = qty * (mark - entry_price)
            long_notional += actual_notional
            long_unrealized += u
        else:
            u = qty * (entry_price - mark)
            short_notional += actual_notional
            short_unrealized += u
    return {'LongNotional': long_notional, 'ShortNotional': short_notional, 'GrossNotional': long_notional + short_notional, 'LongUnrealized': long_unrealized, 'ShortUnrealized': short_unrealized, 'TotalUnrealized': long_unrealized + short_unrealized, 'MissingPrevMarks': len(missing)}


# ============================================================
# FUNCTION #18
# NAME   : calc_margin_capped_qty
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 245-275
# ============================================================

def calc_margin_capped_qty(target_qty, entry_price, cash_now, etf_mark, etf_shares, existing_gross_notional, existing_unrealized):
    target_qty = int(target_qty)
    entry_price = float(entry_price)
    if target_qty < LOT_SIZE:
        return {'AllowedQty': 0, 'TargetQty': target_qty, 'MarginLimited': False, 'PreMarginPct': np.nan, 'PostMarginPct': np.nan, 'EffectiveCollateral': np.nan, 'MaxNotionalByMargin': 0.0}
    if np.isfinite(etf_mark) and etf_mark > 0:
        etf_value = int(etf_shares) * float(etf_mark)
    else:
        etf_value = 0.0
    substitute = etf_value * SUBSTITUTE_HAIRCUT
    effective_collateral = float(cash_now) + substitute + float(existing_unrealized)
    existing_gross_notional = float(existing_gross_notional)
    if existing_gross_notional > 0:
        pre_margin_ratio = effective_collateral / existing_gross_notional
    else:
        pre_margin_ratio = np.nan
    max_total_gross = effective_collateral / MIN_MARGIN_RATIO
    max_additional_notional = max_total_gross - existing_gross_notional
    max_additional_notional = max(0.0, max_additional_notional)
    one_lot_value = entry_price * LOT_SIZE
    max_lots_by_margin = int(np.floor(max_additional_notional / one_lot_value))
    max_qty_by_margin = max_lots_by_margin * LOT_SIZE
    allowed_qty = min(target_qty, max(0, max_qty_by_margin))
    margin_limited = allowed_qty < target_qty
    actual_new_notional = allowed_qty * entry_price
    post_gross = existing_gross_notional + actual_new_notional
    if post_gross > 0:
        post_margin_ratio = effective_collateral / post_gross
    else:
        post_margin_ratio = np.nan
    return {'AllowedQty': int(allowed_qty), 'TargetQty': int(target_qty), 'MarginLimited': bool(margin_limited), 'PreMarginPct': pre_margin_ratio * 100.0 if np.isfinite(pre_margin_ratio) else np.nan, 'PostMarginPct': post_margin_ratio * 100.0 if np.isfinite(post_margin_ratio) else np.nan, 'EffectiveCollateral': effective_collateral, 'MaxNotionalByMargin': max_additional_notional}


# ============================================================
# FUNCTION #19
# NAME   : simulate_fix11
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 277-502
# ============================================================

def simulate_fix11():
    cash = float(INITIAL_CAPITAL)
    etf_shares = 0
    formal_equity = float(INITIAL_CAPITAL)
    broker_strategy_equity = float(INITIAL_CAPITAL)
    formal_active = {}
    broker_active = {}
    broker_skipped = set()
    tx_rows = []
    entry_rows = []
    trade_rows = []
    daily_rows = []
    previous_date = None
    last_etf_close = np.nan
    initial_purchase_done = False
    cum_long_interest = 0.0
    cum_short_fee = 0.0

    def current_broker_notional():
        long_n = 0.0
        short_n = 0.0
        for p in broker_active.values():
            if p['Side'] == 'LONG':
                long_n += float(p['ActualNotional'])
            else:
                short_n += float(p['ActualNotional'])
        return (long_n, short_n)
    for date in sorted(pd.to_datetime(sim_dates)):
        date = pd.Timestamp(date).normalize()
        has_quote = date in quote_dates
        is_monthly_buy = date in monthly_buy_dates
        if has_quote:
            etf_open = float(open_map[date])
            etf_close = float(close_map[date])
            if np.isfinite(etf_close) and etf_close > 0:
                last_etf_close = etf_close
        else:
            etf_open = np.nan
            etf_close = float(last_etf_close) if np.isfinite(last_etf_close) else np.nan
        long_interest_today = 0.0
        short_fee_today = 0.0
        if previous_date is not None:
            calendar_days = int((date - previous_date).days)
            for p in broker_active.values():
                n = float(p['ActualNotional'])
                if p['Side'] == 'LONG':
                    cost = n * LONG_INTEREST_ANNUAL * calendar_days / DAY_COUNT
                    long_interest_today += cost
                else:
                    cost = n * SHORT_LENDING_ANNUAL * calendar_days / DAY_COUNT
                    short_fee_today += cost
        financing_today = long_interest_today + short_fee_today
        cash -= financing_today
        broker_strategy_equity -= financing_today
        cum_long_interest += long_interest_today
        cum_short_fee += short_fee_today
        bought_etf_today = 0
        sold_etf_today = 0
        recovery_sell_today = False
        if has_quote and np.isfinite(etf_open) and (etf_open > 0):
            if cash < CASH_FLOOR:
                deficit = CASH_FLOOR - cash
                required_sell = int(np.ceil(deficit / etf_open))
                sell_shares = min(required_sell, etf_shares)
                if sell_shares > 0:
                    proceeds = sell_shares * etf_open
                    cash_before = float(cash)
                    etf_shares -= sell_shares
                    cash += proceeds - ETF_SELL_FEE
                    sold_etf_today = sell_shares
                    recovery_sell_today = True
                    tx_rows.append({'Date': date, 'Type': 'SELL_CASH_RECOVERY', 'Price': etf_open, 'Shares': sell_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
            should_buy = not initial_purchase_done or is_monthly_buy
            if should_buy and (not recovery_sell_today):
                long_n, short_n = current_broker_notional()
                gross_n = long_n + short_n
                buy_shares = calc_max_etf_buy_shares(cash_now=cash, shares_now=etf_shares, etf_open=etf_open, gross_notional=gross_n)
                if buy_shares > 0:
                    total_cost = buy_shares * etf_open + ETF_BUY_FEE
                    if cash - total_cost < CASH_FLOOR:
                        buy_shares = int(max(0, (cash - CASH_FLOOR - ETF_BUY_FEE) // etf_open))
                        total_cost = buy_shares * etf_open + ETF_BUY_FEE
                    if buy_shares > 0:
                        cash_before = float(cash)
                        etf_shares += buy_shares
                        cash -= total_cost
                        bought_etf_today = buy_shares
                        tx_rows.append({'Date': date, 'Type': 'INITIAL_BUY' if not initial_purchase_done else 'MONTHLY_BUY', 'Price': etf_open, 'Shares': buy_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
                        initial_purchase_done = True
        if has_quote and np.isfinite(etf_open) and (etf_open > 0):
            entry_etf_mark = etf_open
        else:
            entry_etf_mark = last_etf_close if np.isfinite(last_etf_close) else np.nan
        formal_realized_today = 0.0
        broker_realized_today = 0.0
        for e in events_by_date.get(date, []):
            trade_id = str(e['TradeID'])
            side = str(e['Side']).upper()
            if e['Event'] == 'EXIT':
                if trade_id not in formal_active:
                    raise RuntimeError(f"{e['Datetime']} Formal EXIT positionなし: {trade_id}")
                fp = formal_active[trade_id]
                formal_r = float(e['ReturnPct']) / 100.0
                formal_pnl = fp['EntryNotional'] * formal_r
                formal_equity += formal_pnl
                formal_realized_today += formal_pnl
                del formal_active[trade_id]
                if trade_id in broker_skipped:
                    broker_skipped.remove(trade_id)
                    continue
                if trade_id not in broker_active:
                    raise RuntimeError(f"{e['Datetime']} Broker EXIT positionなし: {trade_id}")
                bp = broker_active[trade_id]
                entry_price = float(bp['EntryPrice'])
                broker_r, exit_price = get_broker_return(side=side, entry_price=entry_price, formal_return_pct=e['ReturnPct'])
                qty = int(bp['Quantity'])
                if side == 'LONG':
                    broker_pnl = qty * (exit_price - entry_price)
                else:
                    broker_pnl = qty * (entry_price - exit_price)
                broker_strategy_equity += broker_pnl
                cash += broker_pnl
                broker_realized_today += broker_pnl
                trade_rows.append({'TradeID': trade_id, 'Side': side, 'Code': bp['Code'], 'EntryDatetime': bp['EntryDatetime'], 'ExitDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'ExitPrice': exit_price, 'Quantity': qty, 'TargetNotional': bp['TargetNotional'], 'LotNotionalBeforeMargin': bp['LotNotionalBeforeMargin'], 'ActualNotional': bp['ActualNotional'], 'TargetUtilizationPct': bp['TargetUtilizationPct'], 'FormalReturnPct': float(e['ReturnPct']), 'BrokerReturnPct': broker_r * 100.0, 'BrokerPnL': broker_pnl, 'MarginLimitedAtEntry': bp['MarginLimitedAtEntry']})
                del broker_active[trade_id]
            else:
                meta = entry_meta.get(trade_id)
                if meta is None:
                    raise RuntimeError(f'entry_metaなし: {trade_id}')
                entry_price = float(meta['EntryPrice'])
                leverage = LONG_LEVERAGE if side == 'LONG' else SHORT_LEVERAGE
                formal_notional = formal_equity * leverage
                formal_active[trade_id] = {'Side': side, 'EntryNotional': formal_notional}
                if broker_strategy_equity <= 0:
                    raise RuntimeError(f'Broker strategy equity <= 0: {date.date()}')
                if side == 'LONG':
                    current_long_positions = [p for p in broker_active.values() if str(p.get('Side', '')).upper() == 'LONG']
                    current_long_count = len(current_long_positions)
                    long_allowed_positions = calc_long_dynamic_max_positions(broker_strategy_equity)
                    if current_long_count >= long_allowed_positions:
                        target_notional = 0.0
                    else:
                        current_long_gross = 0.0
                        for _p in current_long_positions:
                            _notional = _p.get('ActualNotional', np.nan)
                            if not np.isfinite(pd.to_numeric(_notional, errors='coerce')):
                                _px = pd.to_numeric(_p.get('EntryPrice', np.nan), errors='coerce')
                                _qty = pd.to_numeric(_p.get('Quantity', np.nan), errors='coerce')
                                if np.isfinite(_px) and np.isfinite(_qty):
                                    _notional = float(_px) * float(_qty)
                                else:
                                    _notional = 0.0
                            current_long_gross += float(_notional)
                        long_total_limit = max(0.0, float(broker_strategy_equity) * LONG_LEVERAGE)
                        long_remaining_capacity = max(0.0, long_total_limit - current_long_gross)
                        target_notional = min(LONG_CAP_PER_STOCK, long_remaining_capacity)
                else:
                    target_notional = broker_strategy_equity * leverage
                target_qty = calc_target_qty(target_notional=target_notional, entry_price=entry_price)
                lot_notional_before_margin = target_qty * entry_price
                pre = calc_entry_time_position_state(broker_active=broker_active, current_date=date)
                margin_check = calc_margin_capped_qty(target_qty=target_qty, entry_price=entry_price, cash_now=cash, etf_mark=entry_etf_mark, etf_shares=etf_shares, existing_gross_notional=pre['GrossNotional'], existing_unrealized=pre['TotalUnrealized'])
                qty = int(margin_check['AllowedQty'])
                actual_notional = qty * entry_price
                utilization = actual_notional / target_notional * 100.0 if target_notional > 0 else np.nan
                skipped = qty == 0
                if target_qty == 0:
                    skip_reason = 'LOT_TOO_LARGE'
                elif qty == 0:
                    skip_reason = 'MARGIN_CAPACITY'
                else:
                    skip_reason = ''
                entry_rows.append({'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'BrokerStrategyEquity': broker_strategy_equity, 'Leverage': leverage, 'TargetNotional': target_notional, 'TargetQty100': target_qty, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'PreExistingGrossNotional': pre['GrossNotional'], 'PreExistingUnrealized': pre['TotalUnrealized'], 'EntryEffectiveCollateral': margin_check['EffectiveCollateral'], 'MaxAdditionalNotionalByMargin': margin_check['MaxNotionalByMargin'], 'PreMarginPct': margin_check['PreMarginPct'], 'PostMarginPct': margin_check['PostMarginPct'], 'Quantity': qty, 'ActualNotional': actual_notional, 'UnusedTargetNotional': target_notional - actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimited': margin_check['MarginLimited'], 'MissingPrevMarks': pre['MissingPrevMarks'], 'Skipped': skipped, 'SkipReason': skip_reason})
                if skipped:
                    broker_skipped.add(trade_id)
                    continue
                post_margin_pct = margin_check['PostMarginPct']
                if np.isfinite(post_margin_pct) and post_margin_pct < MIN_MARGIN_RATIO * 100.0 - 1e-09:
                    raise RuntimeError(f'ENTRY margin check failure: {trade_id} {post_margin_pct:.6f}%')
                broker_active[trade_id] = {'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'Quantity': qty, 'TargetNotional': target_notional, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'ActualNotional': actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimitedAtEntry': margin_check['MarginLimited']}
        long_notional = 0.0
        short_notional = 0.0
        long_unrealized = 0.0
        short_unrealized = 0.0
        missing_marks = []
        for trade_id, p in broker_active.items():
            code = p['Code']
            entry_price = float(p['EntryPrice'])
            qty = int(p['Quantity'])
            actual_notional = float(p['ActualNotional'])
            mark = daily_mark_map.get((date, code), np.nan)
            if not np.isfinite(mark):
                missing_marks.append((trade_id, code))
                continue
            if p['Side'] == 'LONG':
                u = qty * (mark - entry_price)
                long_notional += actual_notional
                long_unrealized += u
            else:
                u = qty * (entry_price - mark)
                short_notional += actual_notional
                short_unrealized += u
        gross_notional = long_notional + short_notional
        total_unrealized = long_unrealized + short_unrealized
        if np.isfinite(etf_close):
            etf_value = etf_shares * etf_close
        else:
            etf_value = 0.0
        substitute80 = etf_value * SUBSTITUTE_HAIRCUT
        effective_collateral = cash + substitute80 + total_unrealized
        if gross_notional > 0:
            margin_ratio = effective_collateral / gross_notional
        else:
            margin_ratio = np.nan
        realized_total_equity = cash + etf_value
        total_equity_mtm = realized_total_equity + total_unrealized
        daily_rows.append({'Date': date, 'ETF_Shares': etf_shares, 'ETF_Value': etf_value, 'BoughtETFToday': bought_etf_today, 'SoldETFToday': sold_etf_today, 'Cash': cash, 'CashNegative': cash < 0, 'FormalStrategyEquity': formal_equity, 'BrokerStrategyEquity': broker_strategy_equity, 'FormalRealizedPnLToday': formal_realized_today, 'BrokerRealizedPnLToday': broker_realized_today, 'LongInterestToday': long_interest_today, 'ShortFeeToday': short_fee_today, 'FinancingToday': financing_today, 'CumLongInterest': cum_long_interest, 'CumShortFee': cum_short_fee, 'CumFinancingCost': cum_long_interest + cum_short_fee, 'LongNotional': long_notional, 'ShortNotional': short_notional, 'GrossNotional': gross_notional, 'LongUnrealized': long_unrealized, 'ShortUnrealized': short_unrealized, 'TotalUnrealized': total_unrealized, 'Substitute80': substitute80, 'EffectiveCollateralMTM': effective_collateral, 'MarginRatioMTMPct': margin_ratio * 100.0 if np.isfinite(margin_ratio) else np.nan, 'Below30': gross_notional > 0 and margin_ratio < MIN_MARGIN_RATIO, 'Below20': gross_notional > 0 and margin_ratio < MARGIN_CALL_LINE, 'Below15': gross_notional > 0 and margin_ratio < SEVERE_LINE, 'MissingMarks': len(missing_marks), 'BrokerOpenPositions': len(broker_active), 'BrokerSkippedOpen': len(broker_skipped), 'RealizedTotalEquity': realized_total_equity, 'TotalEquityMTM': total_equity_mtm})
        previous_date = date
    daily = pd.DataFrame(daily_rows)
    entries = pd.DataFrame(entry_rows)
    trades = pd.DataFrame(trade_rows)
    tx = pd.DataFrame(tx_rows)
    eq = daily['TotalEquityMTM'].to_numpy(dtype=float)
    peak = np.maximum.accumulate(eq)
    daily['DrawdownMTMPct'] = (eq / peak - 1.0) * 100.0
    return (daily, entries, trades, tx, formal_active, broker_active, broker_skipped)


# ============================================================
# FUNCTION #20
# NAME   : _fix13_first_value
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 508-514
# ============================================================

def _fix13_first_value(d, names):
    for name in names:
        if name in d:
            v = d.get(name)
            if v is not None:
                return v
    return None


# ============================================================
# FUNCTION #21
# NAME   : _fix13_event_type
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 516-520
# ============================================================

def _fix13_event_type(e):
    v = _fix13_first_value(e, ['Event', 'EventType', 'Type', 'event', 'event_type', 'type'])
    if v is None:
        return ''
    return str(v).strip().upper()


# ============================================================
# FUNCTION #22
# NAME   : _fix13_side
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 522-526
# ============================================================

def _fix13_side(e):
    v = _fix13_first_value(e, ['Side', 'side', 'PositionSide', 'position_side'])
    if v is None:
        return ''
    return str(v).strip().upper()


# ============================================================
# FUNCTION #23
# NAME   : _fix13_trade_id
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 528-532
# ============================================================

def _fix13_trade_id(e):
    v = _fix13_first_value(e, ['TradeID', 'TradeId', 'trade_id', 'tradeid'])
    if v is None:
        return None
    return str(v)


# ============================================================
# FUNCTION #24
# NAME   : _fix13_datetime
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 534-546
# ============================================================

def _fix13_datetime(e):
    v = _fix13_first_value(e, ['EntryDatetime', 'Datetime', 'DateTime', 'Timestamp', 'timestamp', 'datetime', 'Time', 'time'])
    if v is None:
        return None
    try:
        z = pd.Timestamp(v)
        if pd.isna(z):
            return None
        if z.tzinfo is not None:
            z = z.tz_convert('Asia/Tokyo').tz_localize(None)
        return z
    except Exception:
        return None


# ============================================================
# FUNCTION #25
# NAME   : _fix13_ban_reason
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 548-562
# ============================================================

def _fix13_ban_reason(e):
    if _fix13_event_type(e) != 'ENTRY':
        return None
    dt = _fix13_datetime(e)
    if dt is None:
        return None
    side = _fix13_side(e)
    minute_of_day = int(dt.hour) * 60 + int(dt.minute)
    if minute_of_day >= 14 * 60 + 30 and minute_of_day < 15 * 60:
        return 'ALL_1430_1459'
    if side == 'LONG' and dt.weekday() == 0 and (minute_of_day >= 9 * 60) and (minute_of_day < 9 * 60 + 30):
        return 'LONG_MON_0900_0929'
    if side == 'LONG' and dt.weekday() == 4 and (minute_of_day >= 9 * 60) and (minute_of_day < 9 * 60 + 30):
        return 'LONG_FRI_0900_0929'
    return None


# ============================================================
# FUNCTION #26
# NAME   : _fix13_apply_event_filter
# SOURCE : DRIVE::FIX14_FILE_ID::1mBLtCf39ar4I60GuKLS_HWAbVUYhbgmk
# LINES  : 564-616
# ============================================================

def _fix13_apply_event_filter(src_events_by_date):
    if not isinstance(src_events_by_date, dict):
        raise RuntimeError('FIX13: events_by_date がdictではありません。')
    banned_trade_ids = set()
    n_1430 = 0
    n_mon = 0
    n_fri = 0
    entry_before = 0
    exit_before = 0
    for _, events in src_events_by_date.items():
        for e in events:
            et = _fix13_event_type(e)
            if et == 'ENTRY':
                entry_before += 1
                reason = _fix13_ban_reason(e)
                if reason is None:
                    continue
                tid = _fix13_trade_id(e)
                if tid is None:
                    raise RuntimeError('FIX13: 禁止対象ENTRYにTradeIDがありません。')
                banned_trade_ids.add(tid)
                if reason == 'ALL_1430_1459':
                    n_1430 += 1
                elif reason == 'LONG_MON_0900_0929':
                    n_mon += 1
                elif reason == 'LONG_FRI_0900_0929':
                    n_fri += 1
            elif et == 'EXIT':
                exit_before += 1
    filtered = {}
    removed_entry = 0
    removed_exit = 0
    entry_after = 0
    exit_after = 0
    for date_key, events in src_events_by_date.items():
        keep = []
        for e in events:
            et = _fix13_event_type(e)
            tid = _fix13_trade_id(e)
            if tid in banned_trade_ids:
                if et == 'ENTRY':
                    removed_entry += 1
                elif et == 'EXIT':
                    removed_exit += 1
                continue
            keep.append(e)
            if et == 'ENTRY':
                entry_after += 1
            elif et == 'EXIT':
                exit_after += 1
        filtered[date_key] = keep
    audit = {'Version': 'FIX13', 'Parent': 'FIX11', 'ParentSHA256': FIX13_PARENT_SHA256, 'EntryBefore': entry_before, 'ExitBefore': exit_before, 'RemovedTradeIDs': len(banned_trade_ids), 'RemovedEntry': removed_entry, 'RemovedExit': removed_exit, 'Removed1430_1459': n_1430, 'RemovedLongMonday0900_0929': n_mon, 'RemovedLongFriday0900_0929': n_fri, 'EntryAfter': entry_after, 'ExitAfter': exit_after}
    return (filtered, audit)

