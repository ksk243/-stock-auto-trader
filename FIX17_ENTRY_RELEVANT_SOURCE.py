
# ====================================================================================================
# FUNCTION: simulate_fix11
# SOURCE: FIX17_RUNTIME_RESOLVED_FUNCTIONS.py
# ====================================================================================================
0004:     formal_equity = float(INITIAL_CAPITAL)
0005:     broker_strategy_equity = float(INITIAL_CAPITAL)
0006:     formal_active = {}
0007:     broker_active = {}
0008:     broker_skipped = set()
0009:     tx_rows = []
0010:     entry_rows = []
0011:     trade_rows = []
0012:     daily_rows = []
0013:     previous_date = None
0014:     last_etf_close = np.nan
0015:     initial_purchase_done = False
0016:     cum_long_interest = 0.0
0017:     cum_short_fee = 0.0
0018: 
0019:     def current_broker_notional():
0020:         long_n = 0.0
0021:         short_n = 0.0
0022:         for p in broker_active.values():
0023:             if p['Side'] == 'LONG':
0024:                 long_n += float(p['ActualNotional'])
0025:             else:
0026:                 short_n += float(p['ActualNotional'])
0027:         return (long_n, short_n)
0028:     for date in sorted(pd.to_datetime(sim_dates)):
0029:         date = pd.Timestamp(date).normalize()

# ...

0034:             etf_close = float(close_map[date])
0035:             if np.isfinite(etf_close) and etf_close > 0:
0036:                 last_etf_close = etf_close
0037:         else:
0038:             etf_open = np.nan
0039:             etf_close = float(last_etf_close) if np.isfinite(last_etf_close) else np.nan
0040:         long_interest_today = 0.0
0041:         short_fee_today = 0.0
0042:         if previous_date is not None:
0043:             calendar_days = int((date - previous_date).days)
0044:             for p in broker_active.values():
0045:                 n = float(p['ActualNotional'])
0046:                 if p['Side'] == 'LONG':
0047:                     cost = n * LONG_INTEREST_ANNUAL * calendar_days / DAY_COUNT
0048:                     long_interest_today += cost
0049:                 else:
0050:                     cost = n * SHORT_LENDING_ANNUAL * calendar_days / DAY_COUNT
0051:                     short_fee_today += cost
0052:         financing_today = long_interest_today + short_fee_today
0053:         cash -= financing_today
0054:         broker_strategy_equity -= financing_today
0055:         cum_long_interest += long_interest_today
0056:         cum_short_fee += short_fee_today
0057:         bought_etf_today = 0
0058:         sold_etf_today = 0

# ...

0069:                     cash += proceeds - ETF_SELL_FEE
0070:                     sold_etf_today = sell_shares
0071:                     recovery_sell_today = True
0072:                     tx_rows.append({'Date': date, 'Type': 'SELL_CASH_RECOVERY', 'Price': etf_open, 'Shares': sell_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
0073:             should_buy = not initial_purchase_done or is_monthly_buy
0074:             if should_buy and (not recovery_sell_today):
0075:                 long_n, short_n = current_broker_notional()
0076:                 gross_n = long_n + short_n
0077:                 buy_shares = calc_max_etf_buy_shares(cash_now=cash, shares_now=etf_shares, etf_open=etf_open, gross_notional=gross_n)
0078:                 if buy_shares > 0:
0079:                     total_cost = buy_shares * etf_open + ETF_BUY_FEE
0080:                     if cash - total_cost < CASH_FLOOR:
0081:                         buy_shares = int(max(0, (cash - CASH_FLOOR - ETF_BUY_FEE) // etf_open))
0082:                         total_cost = buy_shares * etf_open + ETF_BUY_FEE

# ...

0085:                         etf_shares += buy_shares
0086:                         cash -= total_cost
0087:                         bought_etf_today = buy_shares
0088:                         tx_rows.append({'Date': date, 'Type': 'INITIAL_BUY' if not initial_purchase_done else 'MONTHLY_BUY', 'Price': etf_open, 'Shares': buy_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
0089:                         initial_purchase_done = True
0090:         if has_quote and np.isfinite(etf_open) and (etf_open > 0):
0091:             entry_etf_mark = etf_open
0092:         else:
0093:             entry_etf_mark = last_etf_close if np.isfinite(last_etf_close) else np.nan
0094:         formal_realized_today = 0.0
0095:         broker_realized_today = 0.0
0096:         for e in events_by_date.get(date, []):
0097:             trade_id = str(e['TradeID'])
0098:             side = str(e['Side']).upper()
0099:             if e['Event'] == 'EXIT':
0100:                 if trade_id not in formal_active:
0101:                     raise RuntimeError(f"{e['Datetime']} Formal EXIT positionなし: {trade_id}")
0102:                 fp = formal_active[trade_id]
0103:                 formal_r = float(e['ReturnPct']) / 100.0
0104:                 formal_pnl = fp['EntryNotional'] * formal_r
0105:                 formal_equity += formal_pnl
0106:                 formal_realized_today += formal_pnl
0107:                 del formal_active[trade_id]
0108:                 if trade_id in broker_skipped:
0109:                     broker_skipped.remove(trade_id)
0110:                     continue
0111:                 if trade_id not in broker_active:
0112:                     raise RuntimeError(f"{e['Datetime']} Broker EXIT positionなし: {trade_id}")
0113:                 bp = broker_active[trade_id]
0114:                 entry_price = float(bp['EntryPrice'])
0115:                 broker_r, exit_price = get_broker_return(side=side, entry_price=entry_price, formal_return_pct=e['ReturnPct'])
0116:                 qty = int(bp['Quantity'])
0117:                 if side == 'LONG':
0118:                     broker_pnl = qty * (exit_price - entry_price)
0119:                 else:
0120:                     broker_pnl = qty * (entry_price - exit_price)
0121:                 broker_strategy_equity += broker_pnl
0122:                 cash += broker_pnl
0123:                 broker_realized_today += broker_pnl
0124:                 trade_rows.append({'TradeID': trade_id, 'Side': side, 'Code': bp['Code'], 'EntryDatetime': bp['EntryDatetime'], 'ExitDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'ExitPrice': exit_price, 'Quantity': qty, 'TargetNotional': bp['TargetNotional'], 'LotNotionalBeforeMargin': bp['LotNotionalBeforeMargin'], 'ActualNotional': bp['ActualNotional'], 'TargetUtilizationPct': bp['TargetUtilizationPct'], 'FormalReturnPct': float(e['ReturnPct']), 'BrokerReturnPct': broker_r * 100.0, 'BrokerPnL': broker_pnl, 'MarginLimitedAtEntry': bp['MarginLimitedAtEntry']})
0125:                 del broker_active[trade_id]
0126:             else:
0127:                 meta = entry_meta.get(trade_id)
0128:                 if meta is None:
0129:                     raise RuntimeError(f'entry_metaなし: {trade_id}')
0130:                 entry_price = float(meta['EntryPrice'])
0131:                 leverage = LONG_LEVERAGE if side == 'LONG' else SHORT_LEVERAGE
0132:                 formal_notional = formal_equity * leverage
0133:                 formal_active[trade_id] = {'Side': side, 'EntryNotional': formal_notional}
0134:                 if broker_strategy_equity <= 0:
0135:                     raise RuntimeError(f'Broker strategy equity <= 0: {date.date()}')
0136:                 if side == 'LONG':
0137:                     current_long_positions = [p for p in broker_active.values() if str(p.get('Side', '')).upper() == 'LONG']
0138:                     current_long_count = len(current_long_positions)
0139:                     long_allowed_positions = calc_long_dynamic_max_positions(broker_strategy_equity)
0140:                     if current_long_count >= long_allowed_positions:
0141:                         target_notional = 0.0
0142:                     else:
0143:                         current_long_gross = 0.0
0144:                         for _p in current_long_positions:
0145:                             _notional = _p.get('ActualNotional', np.nan)
0146:                             if not np.isfinite(pd.to_numeric(_notional, errors='coerce')):
0147:                                 _px = pd.to_numeric(_p.get('EntryPrice', np.nan), errors='coerce')
0148:                                 _qty = pd.to_numeric(_p.get('Quantity', np.nan), errors='coerce')
0149:                                 if np.isfinite(_px) and np.isfinite(_qty):
0150:                                     _notional = float(_px) * float(_qty)
0151:                                 else:
0152:                                     _notional = 0.0
0153:                             current_long_gross += float(_notional)
0154:                         long_total_limit = max(0.0, float(broker_strategy_equity) * LONG_LEVERAGE)
0155:                         long_remaining_capacity = max(0.0, long_total_limit - current_long_gross)
0156:                         target_notional = min(LONG_CAP_PER_STOCK, long_remaining_capacity)
0157:                 else:
0158:                     target_notional = broker_strategy_equity * leverage
0159:                 target_qty = calc_target_qty(target_notional=target_notional, entry_price=entry_price)
0160:                 lot_notional_before_margin = target_qty * entry_price
0161:                 pre = calc_entry_time_position_state(broker_active=broker_active, current_date=date)
0162:                 margin_check = calc_margin_capped_qty(target_qty=target_qty, entry_price=entry_price, cash_now=cash, etf_mark=entry_etf_mark, etf_shares=etf_shares, existing_gross_notional=pre['GrossNotional'], existing_unrealized=pre['TotalUnrealized'])
0163:                 qty = int(margin_check['AllowedQty'])
0164:                 actual_notional = qty * entry_price
0165:                 utilization = actual_notional / target_notional * 100.0 if target_notional > 0 else np.nan
0166:                 skipped = qty == 0
0167:                 if target_qty == 0:
0168:                     skip_reason = 'LOT_TOO_LARGE'
0169:                 elif qty == 0:
0170:                     skip_reason = 'MARGIN_CAPACITY'
0171:                 else:
0172:                     skip_reason = ''
0173:                 entry_rows.append({'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'BrokerStrategyEquity': broker_strategy_equity, 'Leverage': leverage, 'TargetNotional': target_notional, 'TargetQty100': target_qty, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'PreExistingGrossNotional': pre['GrossNotional'], 'PreExistingUnrealized': pre['TotalUnrealized'], 'EntryEffectiveCollateral': margin_check['EffectiveCollateral'], 'MaxAdditionalNotionalByMargin': margin_check['MaxNotionalByMargin'], 'PreMarginPct': margin_check['PreMarginPct'], 'PostMarginPct': margin_check['PostMarginPct'], 'Quantity': qty, 'ActualNotional': actual_notional, 'UnusedTargetNotional': target_notional - actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimited': margin_check['MarginLimited'], 'MissingPrevMarks': pre['MissingPrevMarks'], 'Skipped': skipped, 'SkipReason': skip_reason})
0174:                 if skipped:
0175:                     broker_skipped.add(trade_id)
0176:                     continue
0177:                 post_margin_pct = margin_check['PostMarginPct']
0178:                 if np.isfinite(post_margin_pct) and post_margin_pct < MIN_MARGIN_RATIO * 100.0 - 1e-09:
0179:                     raise RuntimeError(f'ENTRY margin check failure: {trade_id} {post_margin_pct:.6f}%')
0180:                 broker_active[trade_id] = {'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'Quantity': qty, 'TargetNotional': target_notional, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'ActualNotional': actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimitedAtEntry': margin_check['MarginLimited']}
0181:         long_notional = 0.0
0182:         short_notional = 0.0
0183:         long_unrealized = 0.0
0184:         short_unrealized = 0.0
0185:         missing_marks = []
0186:         for trade_id, p in broker_active.items():
0187:             code = p['Code']
0188:             entry_price = float(p['EntryPrice'])
0189:             qty = int(p['Quantity'])
0190:             actual_notional = float(p['ActualNotional'])
0191:             mark = daily_mark_map.get((date, code), np.nan)
0192:             if not np.isfinite(mark):
0193:                 missing_marks.append((trade_id, code))
0194:                 continue
0195:             if p['Side'] == 'LONG':
0196:                 u = qty * (mark - entry_price)
0197:                 long_notional += actual_notional
0198:                 long_unrealized += u
0199:             else:
0200:                 u = qty * (entry_price - mark)
0201:                 short_notional += actual_notional
0202:                 short_unrealized += u
0203:         gross_notional = long_notional + short_notional
0204:         total_unrealized = long_unrealized + short_unrealized
0205:         if np.isfinite(etf_close):
0206:             etf_value = etf_shares * etf_close
0207:         else:
0208:             etf_value = 0.0
0209:         substitute80 = etf_value * SUBSTITUTE_HAIRCUT
0210:         effective_collateral = cash + substitute80 + total_unrealized
0211:         if gross_notional > 0:
0212:             margin_ratio = effective_collateral / gross_notional
0213:         else:
0214:             margin_ratio = np.nan
0215:         realized_total_equity = cash + etf_value
0216:         total_equity_mtm = realized_total_equity + total_unrealized
0217:         daily_rows.append({'Date': date, 'ETF_Shares': etf_shares, 'ETF_Value': etf_value, 'BoughtETFToday': bought_etf_today, 'SoldETFToday': sold_etf_today, 'Cash': cash, 'CashNegative': cash < 0, 'FormalStrategyEquity': formal_equity, 'BrokerStrategyEquity': broker_strategy_equity, 'FormalRealizedPnLToday': formal_realized_today, 'BrokerRealizedPnLToday': broker_realized_today, 'LongInterestToday': long_interest_today, 'ShortFeeToday': short_fee_today, 'FinancingToday': financing_today, 'CumLongInterest': cum_long_interest, 'CumShortFee': cum_short_fee, 'CumFinancingCost': cum_long_interest + cum_short_fee, 'LongNotional': long_notional, 'ShortNotional': short_notional, 'GrossNotional': gross_notional, 'LongUnrealized': long_unrealized, 'ShortUnrealized': short_unrealized, 'TotalUnrealized': total_unrealized, 'Substitute80': substitute80, 'EffectiveCollateralMTM': effective_collateral, 'MarginRatioMTMPct': margin_ratio * 100.0 if np.isfinite(margin_ratio) else np.nan, 'Below30': gross_notional > 0 and margin_ratio < MIN_MARGIN_RATIO, 'Below20': gross_notional > 0 and margin_ratio < MARGIN_CALL_LINE, 'Below15': gross_notional > 0 and margin_ratio < SEVERE_LINE, 'MissingMarks': len(missing_marks), 'BrokerOpenPositions': len(broker_active), 'BrokerSkippedOpen': len(broker_skipped), 'RealizedTotalEquity': realized_total_equity, 'TotalEquityMTM': total_equity_mtm})
0218:         previous_date = date
0219:     daily = pd.DataFrame(daily_rows)
0220:     entries = pd.DataFrame(entry_rows)
0221:     trades = pd.DataFrame(trade_rows)
0222:     tx = pd.DataFrame(tx_rows)
0223:     eq = daily['TotalEquityMTM'].to_numpy(dtype=float)
0224:     peak = np.maximum.accumulate(eq)
0225:     daily['DrawdownMTMPct'] = (eq / peak - 1.0) * 100.0
0226:     return (daily, entries, trades, tx, formal_active, broker_active, broker_skipped)

# ====================================================================================================
# FUNCTION: simulate_fix15
# SOURCE: FIX17_LIVE_FUNCTION_SOURCES.json
# ====================================================================================================
0004:     formal_equity = float(INITIAL_CAPITAL)
0005:     broker_strategy_equity = float(INITIAL_CAPITAL)
0006:     formal_active = {}
0007:     broker_active = {}
0008:     broker_skipped = set()
0009:     tx_rows = []
0010:     entry_rows = []
0011:     trade_rows = []
0012:     daily_rows = []
0013:     previous_date = None
0014:     last_etf_close = np.nan
0015:     initial_purchase_done = False
0016:     cum_long_interest = 0.0
0017:     cum_short_fee = 0.0
0018: 
0019:     def current_broker_notional():
0020:         long_n = 0.0
0021:         short_n = 0.0
0022:         for p in broker_active.values():
0023:             if p['Side'] == 'LONG':
0024:                 long_n += float(p['ActualNotional'])
0025:             else:
0026:                 short_n += float(p['ActualNotional'])
0027:         return (long_n, short_n)
0028:     for date in sorted(pd.to_datetime(sim_dates)):
0029:         date = pd.Timestamp(date).normalize()

# ...

0034:             etf_close = float(close_map[date])
0035:             if np.isfinite(etf_close) and etf_close > 0:
0036:                 last_etf_close = etf_close
0037:         else:
0038:             etf_open = np.nan
0039:             etf_close = float(last_etf_close) if np.isfinite(last_etf_close) else np.nan
0040:         long_interest_today = 0.0
0041:         short_fee_today = 0.0
0042:         if previous_date is not None:
0043:             calendar_days = int((date - previous_date).days)
0044:             for p in broker_active.values():
0045:                 n = float(p['ActualNotional'])
0046:                 if p['Side'] == 'LONG':
0047:                     cost = n * LONG_INTEREST_ANNUAL * calendar_days / DAY_COUNT
0048:                     long_interest_today += cost
0049:                 else:
0050:                     cost = n * SHORT_LENDING_ANNUAL * calendar_days / DAY_COUNT
0051:                     short_fee_today += cost
0052:         financing_today = long_interest_today + short_fee_today
0053:         cash -= financing_today
0054:         broker_strategy_equity -= financing_today
0055:         cum_long_interest += long_interest_today
0056:         cum_short_fee += short_fee_today
0057:         bought_etf_today = 0
0058:         sold_etf_today = 0

# ...

0091: 
0092:                     sold_etf_today = sell_shares
0093:                     recovery_sell_today = True
0094:                     tx_rows.append({'Date': date, 'Type': 'SELL_CASH_RECOVERY', 'Price': etf_open, 'Shares': sell_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
0095:             should_buy = not initial_purchase_done or is_monthly_buy
0096:             if should_buy and (not recovery_sell_today):
0097:                 long_n, short_n = current_broker_notional()
0098:                 gross_n = long_n + short_n
0099:                 buy_shares = calc_max_etf_buy_shares(cash_now=cash, shares_now=etf_shares, etf_open=etf_open, gross_notional=gross_n)
0100:                 if buy_shares > 0:
0101:                     total_cost = buy_shares * etf_open + ETF_BUY_FEE
0102:                     if cash - total_cost < CASH_FLOOR:
0103:                         buy_shares = int(max(0, (cash - CASH_FLOOR - ETF_BUY_FEE) // etf_open))
0104:                         total_cost = buy_shares * etf_open + ETF_BUY_FEE

# ...

0132:                         cash -= total_cost
0133: 
0134:                         bought_etf_today = buy_shares
0135:                         tx_rows.append({'Date': date, 'Type': 'INITIAL_BUY' if not initial_purchase_done else 'MONTHLY_BUY', 'Price': etf_open, 'Shares': buy_shares, 'CashBefore': cash_before, 'CashAfter': cash, 'ETF_SharesAfter': etf_shares})
0136:                         initial_purchase_done = True
0137:         if has_quote and np.isfinite(etf_open) and (etf_open > 0):
0138:             entry_etf_mark = etf_open
0139:         else:
0140:             entry_etf_mark = last_etf_close if np.isfinite(last_etf_close) else np.nan
0141:         formal_realized_today = 0.0
0142:         broker_realized_today = 0.0
0143:         for e in events_by_date.get(date, []):
0144:             trade_id = str(e['TradeID'])
0145:             side = str(e['Side']).upper()
0146:             if e['Event'] == 'EXIT':
0147:                 if trade_id not in formal_active:
0148:                     raise RuntimeError(f"{e['Datetime']} Formal EXIT positionなし: {trade_id}")
0149:                 fp = formal_active[trade_id]
0150:                 formal_r = float(e['ReturnPct']) / 100.0
0151:                 formal_pnl = fp['EntryNotional'] * formal_r
0152:                 formal_equity += formal_pnl
0153:                 formal_realized_today += formal_pnl
0154:                 del formal_active[trade_id]
0155:                 if trade_id in broker_skipped:
0156:                     broker_skipped.remove(trade_id)
0157:                     continue
0158:                 if trade_id not in broker_active:
0159:                     raise RuntimeError(f"{e['Datetime']} Broker EXIT positionなし: {trade_id}")
0160:                 bp = broker_active[trade_id]
0161:                 entry_price = float(bp['EntryPrice'])
0162:                 broker_r, exit_price = get_broker_return(side=side, entry_price=entry_price, formal_return_pct=e['ReturnPct'])
0163:                 qty = int(bp['Quantity'])
0164:                 if side == 'LONG':
0165:                     broker_pnl = qty * (exit_price - entry_price)
0166:                 else:
0167:                     broker_pnl = qty * (entry_price - exit_price)
0168:                 broker_strategy_equity += broker_pnl
0169:                 cash += broker_pnl
0170: 
0171:                 fix15_exit_dt = pd.Timestamp(
0172:                     e["Datetime"]
0173:                 )
0174: 
0175:                 fix15_entry_dt = pd.Timestamp(
0176:                     bp["EntryDatetime"]
0177:                 )
0178: 
0179:                 fix15_raw_days = max(
0180:                     (
0181:                         fix15_exit_dt
0182:                         - fix15_entry_dt
0183:                     ).total_seconds()
0184:                     / 86400.0,
0185:                     0.0,
0186:                 )

# ...

0191:                 )
0192: 
0193:                 fix15_notional = float(
0194:                     bp["ActualNotional"]
0195:                 )
0196: 
0197:                 if side == "LONG":
0198: 
0199:                     fix15_financing_tax = (
0200:                         fix15_notional
0201:                         * LONG_INTEREST_ANNUAL
0202:                         * fix15_financing_days
0203:                         / DAY_COUNT
0204:                     )
0205: 
0206:                 else:
0207: 
0208:                     fix15_financing_tax = (
0209:                         fix15_notional
0210:                         * SHORT_LENDING_ANNUAL
0211:                         * fix15_financing_days
0212:                         / DAY_COUNT
0213:                     )
0214: 
0215:                 fix15_taxable_pnl = (
0216:                     float(broker_pnl)
0217:                     - float(fix15_financing_tax)
0218:                 )
0219: 
0220:                 fix15_tax_change = fix15_apply_tax(
0221:                     fix15_exit_dt,
0222:                     fix15_taxable_pnl,
0223:                     f"CREDIT_{side}",
0224:                     bp["Code"],
0225:                 )
0226: 

# ...

0228: 
0229:                 broker_strategy_equity -= (
0230:                     fix15_tax_change
0231:                 )
0232: 
0233:                 broker_realized_today += broker_pnl
0234:                 trade_rows.append({'TradeID': trade_id, 'Side': side, 'Code': bp['Code'], 'EntryDatetime': bp['EntryDatetime'], 'ExitDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'ExitPrice': exit_price, 'Quantity': qty, 'TargetNotional': bp['TargetNotional'], 'LotNotionalBeforeMargin': bp['LotNotionalBeforeMargin'], 'ActualNotional': bp['ActualNotional'], 'TargetUtilizationPct': bp['TargetUtilizationPct'], 'FormalReturnPct': float(e['ReturnPct']), 'BrokerReturnPct': broker_r * 100.0, 'BrokerPnL': broker_pnl, 'MarginLimitedAtEntry': bp['MarginLimitedAtEntry']})
0235:                 del broker_active[trade_id]
0236:             else:
0237:                 meta = entry_meta.get(trade_id)
0238:                 if meta is None:
0239:                     raise RuntimeError(f'entry_metaなし: {trade_id}')
0240:                 entry_price = float(meta['EntryPrice'])
0241:                 leverage = LONG_LEVERAGE if side == 'LONG' else SHORT_LEVERAGE
0242:                 formal_notional = formal_equity * leverage
0243:                 formal_active[trade_id] = {'Side': side, 'EntryNotional': formal_notional}
0244:                 if broker_strategy_equity <= 0:
0245:                     raise RuntimeError(f'Broker strategy equity <= 0: {date.date()}')
0246:                 if side == 'LONG':
0247:                     current_long_positions = [p for p in broker_active.values() if str(p.get('Side', '')).upper() == 'LONG']
0248:                     current_long_count = len(current_long_positions)
0249:                     long_allowed_positions = calc_long_dynamic_max_positions(broker_strategy_equity)
0250:                     if current_long_count >= long_allowed_positions:
0251:                         target_notional = 0.0
0252:                     else:
0253:                         current_long_gross = 0.0
0254:                         for _p in current_long_positions:
0255:                             _notional = _p.get('ActualNotional', np.nan)
0256:                             if not np.isfinite(pd.to_numeric(_notional, errors='coerce')):
0257:                                 _px = pd.to_numeric(_p.get('EntryPrice', np.nan), errors='coerce')
0258:                                 _qty = pd.to_numeric(_p.get('Quantity', np.nan), errors='coerce')
0259:                                 if np.isfinite(_px) and np.isfinite(_qty):
0260:                                     _notional = float(_px) * float(_qty)
0261:                                 else:
0262:                                     _notional = 0.0
0263:                             current_long_gross += float(_notional)
0264:                         long_total_limit = max(0.0, float(broker_strategy_equity) * LONG_LEVERAGE)
0265:                         long_remaining_capacity = max(0.0, long_total_limit - current_long_gross)
0266:                         target_notional = long_remaining_capacity
0267:                 else:
0268:                     target_notional = broker_strategy_equity * leverage
0269:                 target_qty = calc_target_qty(target_notional=target_notional, entry_price=entry_price)
0270:                 lot_notional_before_margin = target_qty * entry_price
0271:                 pre = calc_entry_time_position_state(broker_active=broker_active, current_date=date)
0272:                 margin_check = calc_margin_capped_qty(target_qty=target_qty, entry_price=entry_price, cash_now=cash, etf_mark=entry_etf_mark, etf_shares=etf_shares, existing_gross_notional=pre['GrossNotional'], existing_unrealized=pre['TotalUnrealized'])
0273:                 qty = int(margin_check['AllowedQty'])
0274:                 actual_notional = qty * entry_price
0275:                 utilization = actual_notional / target_notional * 100.0 if target_notional > 0 else np.nan
0276:                 skipped = qty == 0
0277:                 if target_qty == 0:
0278:                     skip_reason = 'LOT_TOO_LARGE'
0279:                 elif qty == 0:
0280:                     skip_reason = 'MARGIN_CAPACITY'
0281:                 else:
0282:                     skip_reason = ''
0283:                 entry_rows.append({'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'BrokerStrategyEquity': broker_strategy_equity, 'Leverage': leverage, 'TargetNotional': target_notional, 'TargetQty100': target_qty, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'PreExistingGrossNotional': pre['GrossNotional'], 'PreExistingUnrealized': pre['TotalUnrealized'], 'EntryEffectiveCollateral': margin_check['EffectiveCollateral'], 'MaxAdditionalNotionalByMargin': margin_check['MaxNotionalByMargin'], 'PreMarginPct': margin_check['PreMarginPct'], 'PostMarginPct': margin_check['PostMarginPct'], 'Quantity': qty, 'ActualNotional': actual_notional, 'UnusedTargetNotional': target_notional - actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimited': margin_check['MarginLimited'], 'MissingPrevMarks': pre['MissingPrevMarks'], 'Skipped': skipped, 'SkipReason': skip_reason})
0284:                 if skipped:
0285:                     broker_skipped.add(trade_id)
0286:                     continue
0287:                 post_margin_pct = margin_check['PostMarginPct']
0288:                 if np.isfinite(post_margin_pct) and post_margin_pct < MIN_MARGIN_RATIO * 100.0 - 1e-09:
0289:                     raise RuntimeError(f'ENTRY margin check failure: {trade_id} {post_margin_pct:.6f}%')
0290:                 broker_active[trade_id] = {'TradeID': trade_id, 'Side': side, 'Code': str(meta['Code']).zfill(5), 'EntryDatetime': pd.Timestamp(e['Datetime']), 'EntryPrice': entry_price, 'Quantity': qty, 'TargetNotional': target_notional, 'LotNotionalBeforeMargin': lot_notional_before_margin, 'ActualNotional': actual_notional, 'TargetUtilizationPct': utilization, 'MarginLimitedAtEntry': margin_check['MarginLimited']}
0291:         long_notional = 0.0
0292:         short_notional = 0.0
0293:         long_unrealized = 0.0
0294:         short_unrealized = 0.0
0295:         missing_marks = []
0296:         for trade_id, p in broker_active.items():
0297:             code = p['Code']
0298:             entry_price = float(p['EntryPrice'])
0299:             qty = int(p['Quantity'])
0300:             actual_notional = float(p['ActualNotional'])
0301:             mark = daily_mark_map.get((date, code), np.nan)
0302:             if not np.isfinite(mark):
0303:                 missing_marks.append((trade_id, code))
0304:                 continue
0305:             if p['Side'] == 'LONG':
0306:                 u = qty * (mark - entry_price)
0307:                 long_notional += actual_notional
0308:                 long_unrealized += u
0309:             else:
0310:                 u = qty * (entry_price - mark)
0311:                 short_notional += actual_notional
0312:                 short_unrealized += u
0313:         gross_notional = long_notional + short_notional
0314:         total_unrealized = long_unrealized + short_unrealized
0315:         if np.isfinite(etf_close):
0316:             etf_value = etf_shares * etf_close
0317:         else:
0318:             etf_value = 0.0
0319:         substitute80 = etf_value * SUBSTITUTE_HAIRCUT
0320:         effective_collateral = cash + substitute80 + total_unrealized
0321:         if gross_notional > 0:
0322:             margin_ratio = effective_collateral / gross_notional
0323:         else:
0324:             margin_ratio = np.nan
0325:         realized_total_equity = cash + etf_value
0326:         total_equity_mtm = realized_total_equity + total_unrealized
0327:         daily_rows.append({'Date': date, 'ETF_Shares': etf_shares, 'ETF_Value': etf_value, 'BoughtETFToday': bought_etf_today, 'SoldETFToday': sold_etf_today, 'Cash': cash, 'CashNegative': cash < 0, 'FormalStrategyEquity': formal_equity, 'BrokerStrategyEquity': broker_strategy_equity, 'FormalRealizedPnLToday': formal_realized_today, 'BrokerRealizedPnLToday': broker_realized_today, 'LongInterestToday': long_interest_today, 'ShortFeeToday': short_fee_today, 'FinancingToday': financing_today, 'CumLongInterest': cum_long_interest, 'CumShortFee': cum_short_fee, 'CumFinancingCost': cum_long_interest + cum_short_fee, 'LongNotional': long_notional, 'ShortNotional': short_notional, 'GrossNotional': gross_notional, 'LongUnrealized': long_unrealized, 'ShortUnrealized': short_unrealized, 'TotalUnrealized': total_unrealized, 'Substitute80': substitute80, 'EffectiveCollateralMTM': effective_collateral, 'MarginRatioMTMPct': margin_ratio * 100.0 if np.isfinite(margin_ratio) else np.nan, 'Below30': gross_notional > 0 and margin_ratio < MIN_MARGIN_RATIO, 'Below20': gross_notional > 0 and margin_ratio < MARGIN_CALL_LINE, 'Below15': gross_notional > 0 and margin_ratio < SEVERE_LINE, 'MissingMarks': len(missing_marks), 'BrokerOpenPositions': len(broker_active), 'BrokerSkippedOpen': len(broker_skipped), 'RealizedTotalEquity': realized_total_equity, 'TotalEquityMTM': total_equity_mtm})
0328:         previous_date = date
0329:     daily = pd.DataFrame(daily_rows)
0330:     entries = pd.DataFrame(entry_rows)
0331:     trades = pd.DataFrame(trade_rows)
0332:     tx = pd.DataFrame(tx_rows)
0333:     eq = daily['TotalEquityMTM'].to_numpy(dtype=float)
0334:     peak = np.maximum.accumulate(eq)
0335:     daily['DrawdownMTMPct'] = (eq / peak - 1.0) * 100.0
0336:     return (daily, entries, trades, tx, formal_active, broker_active, broker_skipped)
