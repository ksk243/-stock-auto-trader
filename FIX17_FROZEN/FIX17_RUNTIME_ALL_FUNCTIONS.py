# ============================================================
# FIX17 RUNTIME ALL FUNCTIONS
# STATIC RECURSIVE EXTRACTION
#
# SOURCE:
# FIX17_OFFICIAL_FULL_SOURCE.py
#
# SHA256: 9598156080b81445e5754c7b0f56138900862e8fd7f35ac89960491bec7222c4
#
# IMPORTANT:
# This file is for auditing/extraction.
# Do not use it directly as live trading code.
# ============================================================


# ============================================================
# FUNCTION #1
# NAME   : _fix16_download_bytes
# LAYER  : FIX17_ROOT
# SOURCE : L71-L89
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
# NAME   : simulate_profit_floor_trail
# LAYER  : FIX17_ROOT
# SOURCE : L330-L730
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
# FUNCTION #3
# NAME   : simulate_fix15
# LAYER  : FIX17_ROOT
# SOURCE : L1202-L1537
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
# FUNCTION #4
# NAME   : _download_text
# LAYER  : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# SOURCE : L108-L119
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
# FUNCTION #5
# NAME   : _sha256_text
# LAYER  : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# SOURCE : L122-L126
# ============================================================

def _sha256_text(text):

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


# ============================================================
# FUNCTION #6
# NAME   : fix15_ensure_tax_year
# LAYER  : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# SOURCE : L250-L263
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
# FUNCTION #7
# NAME   : fix15_apply_tax
# LAYER  : FIX17_ROOT::FIX16_EMBEDDED_PARENT_SOURCE
# SOURCE : L266-L347
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

