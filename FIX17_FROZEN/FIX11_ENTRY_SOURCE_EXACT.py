# ============================================================

# STEP23-H-EXACT-FIX11

#

# BROKER-REALISTIC

# + JAPAN 100-SHARE LOT

# + ENTRY-TIME MARGIN CAPACITY CHECK

#

# ============================================================

#

# FIX10からの変更点

#

# Broker ENTRY時に

#

#   1. BrokerStrategyEquity × leverage

#      でTargetNotionalを計算

#

#   2. 100株単位に切り下げ

#

#   3. ENTRY直前の保証金余力を計算

#

#   4. 新規建玉後もMarginRatio >= 30%

#      を満たす最大100株単位まで縮小

#

#   5. 100株も建てられない場合はSKIP

#

# ------------------------------------------------------------

# ENTRY時のNo-Future評価

# ------------------------------------------------------------

#

# Cash:

#   その時点までの実現損益・金利を反映

#

# 1557:

#   当日に価格があれば当日OPEN

#   なければ直近既知Close

#

# 既存信用建玉:

#

#   持越し建玉

#     → 当日より前の最後のAdjClose

#

#   当日すでにENTRYした建玉

#     → EntryPrice（含み損益0扱い）

#

# ※ 当日のEOD CloseはENTRY判定には絶対に使わない。

#

# ------------------------------------------------------------

# Formal Stage5

# ------------------------------------------------------------

#

# 別台帳で従来通り維持。

# 5,755,654円を再現する。

#

# ------------------------------------------------------------

# IMPORTANT

# ------------------------------------------------------------

#

# Signal / Entry / Exit / Trade順序は変更しない。

#

# 1557の月初買付・Cash回復ルールもFIX10のまま。

#

# まだDriveには保存しない。

# ============================================================

import numpy as np

import pandas as pd

import matplotlib.pyplot as plt

print("=" * 240)

print("STEP23-H-EXACT-FIX11")

print("100-SHARE + ENTRY-TIME MARGIN CAPACITY CHECK")

print("=" * 240)

# ============================================================

# 0. 固定設定

# ============================================================

INITIAL_CAPITAL = 1_117_792.0

LONG_LEVERAGE = 1.00

SHORT_LEVERAGE = 0.50

LOT_SIZE = 100

# ============================================================

# TRUE CAP200 LONG-ONLY

# ============================================================

LONG_CAP_PER_STOCK = 2_000_000.0

def calc_long_dynamic_max_positions(

    equity

):

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

    if (

        not np.isfinite(equity)

        or

        equity <= 0

    ):

        return 0

    return max(

        1,

        int(

            np.ceil(

                equity

                /

                LONG_CAP_PER_STOCK

            )

        )

    )



# ------------------------------------------------------------

# CAP200_LONG_ONLY INPUT

# ------------------------------------------------------------

EXPECTED_TRADE_MASTER = 867

EXPECTED_ENTRY_EVENTS = 867

EXPECTED_EXIT_EVENTS = 865

# CAP200_LONG_ONLYではFormal Stage5 583件とは

# 売買ストリーム自体が異なるため、

# 旧5,755,654円をhard checkには使用しない。

EXPECTED_STAGE5_FINAL = None

# ------------------------------------------------------------

# Financing

# ------------------------------------------------------------

LONG_INTEREST_ANNUAL = 0.0285

SHORT_LENDING_ANNUAL = 0.0110

DAY_COUNT = 365.0

# ------------------------------------------------------------

# Margin / 1557

# ------------------------------------------------------------

SUBSTITUTE_HAIRCUT = 0.80

MIN_MARGIN_RATIO = 0.30

MARGIN_CALL_LINE = 0.20

SEVERE_LINE = 0.15

CASH_FLOOR = 0.0

ETF_BUY_FEE = 0.0

ETF_SELL_FEE = 0.0

# ============================================================

# 1. 必須変数

# ============================================================

required = [

    "trade_master_fix6",

    "events_by_date",

    "sim_dates",

    "daily_stock",

    "d1557_fix",

    "open_map",

    "close_map",

    "quote_dates",

    "START_DATE",

    "END_DATE",

]

missing = [

    x for x in required

    if x not in globals()

]

if missing:

    raise RuntimeError(

        "必要な変数がありません:\n"

        + "\n".join(missing)

        + "\n\nFIX10までのセルを確認してください。"

    )

# ============================================================

# 2. Trade master

# ============================================================

tm = trade_master_fix6.copy()

tm["TradeID"] = (

    tm["TradeID"]

    .astype(str)

)

tm["Code"] = (

    tm["Code"]

    .astype(str)

    .str.replace(".0", "", regex=False)

    .str.zfill(5)

)

tm["EntryPrice"] = pd.to_numeric(

    tm["EntryPrice"],

    errors="coerce"

)

if len(tm) != EXPECTED_TRADE_MASTER:

    raise RuntimeError(

        f"Trade master件数異常: {len(tm)} "

        f"(expected {EXPECTED_TRADE_MASTER})"

    )

if tm["TradeID"].nunique() != EXPECTED_TRADE_MASTER:

    raise RuntimeError(

        f"TradeID unique != {EXPECTED_TRADE_MASTER}"

    )

if tm["EntryPrice"].isna().any():

    raise RuntimeError(

        "EntryPrice NaN"

    )

if (tm["EntryPrice"] <= 0).any():

    raise RuntimeError(

        "EntryPrice <= 0"

    )

print(

    "Trade master:",

    len(tm),

    "PASS"

)

# ============================================================

# 3. Strategy events

# ============================================================

event_rows = []

for date, events in events_by_date.items():

    for e in events:

        r = dict(e)

        r["Date"] = pd.Timestamp(

            date

        ).normalize()

        event_rows.append(r)

event_df = pd.DataFrame(

    event_rows

)

event_df["TradeID"] = (

    event_df["TradeID"]

    .astype(str)

)

event_df["Datetime"] = pd.to_datetime(

    event_df["Datetime"]

)

entry_events = (

    event_df[

        event_df["Event"] == "ENTRY"

    ]

    .copy()

)

exit_events = (

    event_df[

        event_df["Event"] == "EXIT"

    ]

    .copy()

)

if len(entry_events) != EXPECTED_ENTRY_EVENTS:

    raise RuntimeError(

        f"ENTRY件数異常: {len(entry_events)} "

        f"(expected {EXPECTED_ENTRY_EVENTS})"

    )

if len(exit_events) != EXPECTED_EXIT_EVENTS:

    raise RuntimeError(

        f"EXIT件数異常: {len(exit_events)} "

        f"(expected {EXPECTED_EXIT_EVENTS})"

    )

print(

    "Strategy events:",

    len(event_df)

)

print(

    "ENTRY:",

    len(entry_events)

)

print(

    "EXIT :",

    len(exit_events)

)

# ============================================================

# 4. Entry metadata

# ============================================================

entry_meta_df = (

    entry_events[

        [

            "TradeID",

            "Side",

            "Datetime",

        ]

    ]

    .merge(

        tm[

            [

                "TradeID",

                "Code",

                "EntryPrice",

            ]

        ],

        on="TradeID",

        how="left"

    )

)

if entry_meta_df[

    [

        "Code",

        "EntryPrice",

    ]

].isna().any().any():

    raise RuntimeError(

        "Entry metadata欠損"

    )

entry_meta = (

    entry_meta_df

    .set_index(

        "TradeID"

    )[

        [

            "Code",

            "EntryPrice",

        ]

    ]

    .to_dict(

        orient="index"

    )

)

# ============================================================

# 5. ExitPrice再構築

# ============================================================

def reconstruct_exit_price(

    side,

    entry_price,

    formal_return_pct

):

    r = (

        float(

            formal_return_pct

        )

        /

        100.0

    )

    entry_price = float(

        entry_price

    )

    if side == "LONG":

        return (

            entry_price

            *

            (

                1.0

                +

                r

            )

        )

    elif side == "SHORT":

        denominator = (

            1.0

            +

            r

        )

        if denominator <= 0:

            raise RuntimeError(

                "SHORT denominator <= 0"

            )

        return (

            entry_price

            /

            denominator

        )

    else:

        raise RuntimeError(

            f"Unknown side: {side}"

        )

# ============================================================

# 6. Broker return

# ============================================================

def get_broker_return(

    side,

    entry_price,

    formal_return_pct

):

    exit_price = (

        reconstruct_exit_price(

            side=side,

            entry_price=entry_price,

            formal_return_pct=formal_return_pct

        )

    )

    if side == "LONG":

        broker_return = (

            exit_price

            /

            entry_price

            -

            1.0

        )

    else:

        broker_return = (

            1.0

            -

            exit_price

            /

            entry_price

        )

    return (

        float(

            broker_return

        ),

        float(

            exit_price

        )

    )

# ============================================================

# 7. daily_stock

# ============================================================

ds = daily_stock.copy()

ds["Date"] = pd.to_datetime(

    ds["Date"]

).dt.normalize()

ds["Code"] = (

    ds["Code"]

    .astype(str)

    .str.replace(".0", "", regex=False)

    .str.zfill(5)

)

close_candidates = [

    "AdjClose",

    "AdjC",

    "CloseAdjusted",

    "Close",

    "C",

]

DAILY_CLOSE_COL = None

for col in close_candidates:

    if col in ds.columns:

        DAILY_CLOSE_COL = col

        break

if DAILY_CLOSE_COL is None:

    raise RuntimeError(

        "daily_stockにMTM終値列なし"

    )

codes = set(

    tm["Code"]

)

ds_mtm = (

    ds[

        ds["Code"].isin(

            codes

        )

    ][

        [

            "Date",

            "Code",

            DAILY_CLOSE_COL,

        ]

    ]

    .copy()

)

ds_mtm[

    DAILY_CLOSE_COL

] = pd.to_numeric(

    ds_mtm[

        DAILY_CLOSE_COL

    ],

    errors="coerce"

)

ds_mtm = (

    ds_mtm[

        ds_mtm[

            DAILY_CLOSE_COL

        ].notna()

        &

        (

            ds_mtm[

                DAILY_CLOSE_COL

            ]

            >

            0

        )

    ]

    .sort_values(

        [

            "Code",

            "Date",

        ]

    )

    .copy()

)

# ============================================================

# 8. EOD MTM map

# ============================================================

daily_mark_map = {

    (

        pd.Timestamp(

            r.Date

        ).normalize(),

        str(

            r.Code

        ).zfill(5)

    ):

        float(

            getattr(

                r,

                DAILY_CLOSE_COL

            )

        )

    for r in ds_mtm.itertuples(

        index=False

    )

}

print(

    "MTM close column:",

    DAILY_CLOSE_COL

)

print(

    "Daily mark map:",

    f"{len(daily_mark_map):,}"

)

# ============================================================

# 9. No-Future previous-close history

#

# ENTRY時点では当日のCloseを使わない。

# dateよりSTRICTLY BEFOREの最後のcloseを返す。

# ============================================================

prev_history = {}

for code, g in ds_mtm.groupby(

    "Code",

    sort=False

):

    dates_arr = (

        g[

            "Date"

        ]

        .values

        .astype(

            "datetime64[ns]"

        )

    )

    close_arr = (

        g[

            DAILY_CLOSE_COL

        ]

        .to_numpy(

            dtype=float

        )

    )

    prev_history[

        str(

            code

        ).zfill(5)

    ] = (

        dates_arr,

        close_arr

    )

def get_last_close_before(

    code,

    date

):

    code = str(

        code

    ).zfill(5)

    date64 = np.datetime64(

        pd.Timestamp(

            date

        ).normalize()

    )

    if code not in prev_history:

        return np.nan

    dates_arr, close_arr = (

        prev_history[

            code

        ]

    )

    idx = (

        np.searchsorted(

            dates_arr,

            date64,

            side="left"

        )

        -

        1

    )

    if idx < 0:

        return np.nan

    return float(

        close_arr[

            idx

        ]

    )

# ============================================================

# 10. 月初1557買付日

# ============================================================

q = d1557_fix.copy()

q["Date"] = pd.to_datetime(

    q["Date"]

).dt.normalize()

q = q[

    (q["Date"] >= pd.Timestamp(START_DATE))

    &

    (q["Date"] <= pd.Timestamp(END_DATE))

].copy()

q["Month"] = (

    q["Date"]

    .dt.to_period("M")

)

monthly_buy_dates = set(

    q.groupby(

        "Month",

        sort=True

    )[

        "Date"

    ]

    .min()

    .tolist()

)

print(

    "Monthly buy dates:",

    len(

        monthly_buy_dates

    )

)

# ============================================================

# 11. 100株単位 target quantity

# ============================================================

def calc_target_qty(

    target_notional,

    entry_price

):

    one_lot = (

        float(

            entry_price

        )

        *

        LOT_SIZE

    )

    if (

        target_notional <= 0

        or

        one_lot <= 0

    ):

        return 0

    lots = int(

        np.floor(

            float(

                target_notional

            )

            /

            one_lot

        )

    )

    return int(

        max(

            0,

            lots

            *

            LOT_SIZE

        )

    )

# ============================================================

# 12. ETF max buy

#

# FIX10と同じ。

# ============================================================

def calc_max_etf_buy_shares(

    cash_now,

    shares_now,

    etf_open,

    gross_notional

):

    available_cash = (

        cash_now

        -

        CASH_FLOOR

    )

    if available_cash < etf_open:

        return 0

    max_by_cash = int(

        available_cash

        //

        etf_open

    )

    if gross_notional <= 0:

        return max_by_cash

    current_etf_value = (

        shares_now

        *

        etf_open

    )

    current_collateral = (

        cash_now

        +

        current_etf_value

        *

        SUBSTITUTE_HAIRCUT

    )

    required_collateral = (

        gross_notional

        *

        MIN_MARGIN_RATIO

    )

    room = (

        current_collateral

        -

        required_collateral

    )

    collateral_loss_per_share = (

        etf_open

        *

        (

            1.0

            -

            SUBSTITUTE_HAIRCUT

        )

    )

    if (

        room <= 0

        or

        collateral_loss_per_share <= 0

    ):

        return 0

    max_by_margin = int(

        np.floor(

            room

            /

            collateral_loss_per_share

        )

    )

    return min(

        max_by_cash,

        max(

            0,

            max_by_margin

        )

    )

# ============================================================

# 13. ENTRY直前の既存建玉評価

# ============================================================

def calc_entry_time_position_state(

    broker_active,

    current_date

):

    long_notional = 0.0

    short_notional = 0.0

    long_unrealized = 0.0

    short_unrealized = 0.0

    missing = []

    for trade_id, p in broker_active.items():

        side = p[

            "Side"

        ]

        code = p[

            "Code"

        ]

        qty = int(

            p[

                "Quantity"

            ]

        )

        entry_price = float(

            p[

                "EntryPrice"

            ]

        )

        actual_notional = float(

            p[

                "ActualNotional"

            ]

        )

        entry_date = pd.Timestamp(

            p[

                "EntryDatetime"

            ]

        ).normalize()

        # ----------------------------------------------------

        # 当日ENTRY済み

        #

        # 当日Closeは未来なので使わない。

        # EntryPriceで評価 = unrealized 0。

        # ----------------------------------------------------

        if entry_date == current_date:

            mark = entry_price

        # ----------------------------------------------------

        # 持越し

        #

        # current_dateより前の最後のClose。

        # ----------------------------------------------------

        else:

            mark = get_last_close_before(

                code=code,

                date=current_date

            )

            if not np.isfinite(

                mark

            ):

                # 最悪の場合はEntryPrice。

                # Future dataは使わない。

                mark = entry_price

                missing.append(

                    (

                        trade_id,

                        code

                    )

                )

        if side == "LONG":

            u = (

                qty

                *

                (

                    mark

                    -

                    entry_price

                )

            )

            long_notional += (

                actual_notional

            )

            long_unrealized += (

                u

            )

        else:

            u = (

                qty

                *

                (

                    entry_price

                    -

                    mark

                )

            )

            short_notional += (

                actual_notional

            )

            short_unrealized += (

                u

            )

    return {

        "LongNotional":

            long_notional,

        "ShortNotional":

            short_notional,

        "GrossNotional":

            (

                long_notional

                +

                short_notional

            ),

        "LongUnrealized":

            long_unrealized,

        "ShortUnrealized":

            short_unrealized,

        "TotalUnrealized":

            (

                long_unrealized

                +

                short_unrealized

            ),

        "MissingPrevMarks":

            len(

                missing

            ),

    }

# ============================================================

# 14. ENTRY Margin capacity

# ============================================================

def calc_margin_capped_qty(

    target_qty,

    entry_price,

    cash_now,

    etf_mark,

    etf_shares,

    existing_gross_notional,

    existing_unrealized

):

    target_qty = int(

        target_qty

    )

    entry_price = float(

        entry_price

    )

    if target_qty < LOT_SIZE:

        return {

            "AllowedQty": 0,

            "TargetQty": target_qty,

            "MarginLimited": False,

            "PreMarginPct": np.nan,

            "PostMarginPct": np.nan,

            "EffectiveCollateral": np.nan,

            "MaxNotionalByMargin": 0.0,

        }

    # --------------------------------------------------------

    # ETF substitute value

    # --------------------------------------------------------

    if (

        np.isfinite(

            etf_mark

        )

        and

        etf_mark > 0

    ):

        etf_value = (

            int(

                etf_shares

            )

            *

            float(

                etf_mark

            )

        )

    else:

        etf_value = 0.0

    substitute = (

        etf_value

        *

        SUBSTITUTE_HAIRCUT

    )

    # --------------------------------------------------------

    # ENTRY直前 collateral

    # --------------------------------------------------------

    effective_collateral = (

        float(

            cash_now

        )

        +

        substitute

        +

        float(

            existing_unrealized

        )

    )

    existing_gross_notional = float(

        existing_gross_notional

    )

    if existing_gross_notional > 0:

        pre_margin_ratio = (

            effective_collateral

            /

            existing_gross_notional

        )

    else:

        pre_margin_ratio = np.nan

    # --------------------------------------------------------

    # 新規建玉を含めたGrossが

    #

    # EffectiveCollateral / Gross >= 30%

    #

    # となる最大追加Notional

    # --------------------------------------------------------

    max_total_gross = (

        effective_collateral

        /

        MIN_MARGIN_RATIO

    )

    max_additional_notional = (

        max_total_gross

        -

        existing_gross_notional

    )

    max_additional_notional = max(

        0.0,

        max_additional_notional

    )

    one_lot_value = (

        entry_price

        *

        LOT_SIZE

    )

    max_lots_by_margin = int(

        np.floor(

            max_additional_notional

            /

            one_lot_value

        )

    )

    max_qty_by_margin = (

        max_lots_by_margin

        *

        LOT_SIZE

    )

    allowed_qty = min(

        target_qty,

        max(

            0,

            max_qty_by_margin

        )

    )

    margin_limited = (

        allowed_qty

        <

        target_qty

    )

    actual_new_notional = (

        allowed_qty

        *

        entry_price

    )

    post_gross = (

        existing_gross_notional

        +

        actual_new_notional

    )

    if post_gross > 0:

        post_margin_ratio = (

            effective_collateral

            /

            post_gross

        )

    else:

        post_margin_ratio = np.nan

    return {

        "AllowedQty":

            int(

                allowed_qty

            ),

        "TargetQty":

            int(

                target_qty

            ),

        "MarginLimited":

            bool(

                margin_limited

            ),

        "PreMarginPct":

            (

                pre_margin_ratio

                *

                100.0

                if np.isfinite(

                    pre_margin_ratio

                )

                else np.nan

            ),

        "PostMarginPct":

            (

                post_margin_ratio

                *

                100.0

                if np.isfinite(

                    post_margin_ratio

                )

                else np.nan

            ),

        "EffectiveCollateral":

            effective_collateral,

        "MaxNotionalByMargin":

            max_additional_notional,

    }

# ============================================================

# 15. Simulator

# ============================================================

def simulate_fix11():

    # --------------------------------------------------------

    # Cash / ETF

    # --------------------------------------------------------

    cash = float(

        INITIAL_CAPITAL

    )

    etf_shares = 0

    # --------------------------------------------------------

    # Formal Stage5 ledger

    # --------------------------------------------------------

    formal_equity = float(

        INITIAL_CAPITAL

    )

    # --------------------------------------------------------

    # Broker realized strategy ledger

    # --------------------------------------------------------

    broker_strategy_equity = float(

        INITIAL_CAPITAL

    )

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

    # ========================================================

    # Current Broker gross notional

    # ========================================================

    def current_broker_notional():

        long_n = 0.0

        short_n = 0.0

        for p in broker_active.values():

            if p["Side"] == "LONG":

                long_n += float(

                    p[

                        "ActualNotional"

                    ]

                )

            else:

                short_n += float(

                    p[

                        "ActualNotional"

                    ]

                )

        return (

            long_n,

            short_n

        )

    # ========================================================

    # Main daily loop

    # ========================================================

    for date in sorted(

        pd.to_datetime(

            sim_dates

        )

    ):

        date = pd.Timestamp(

            date

        ).normalize()

        has_quote = (

            date in quote_dates

        )

        is_monthly_buy = (

            date in monthly_buy_dates

        )

        # ====================================================

        # A. 1557

        # ====================================================

        if has_quote:

            etf_open = float(

                open_map[

                    date

                ]

            )

            etf_close = float(

                close_map[

                    date

                ]

            )

            if (

                np.isfinite(

                    etf_close

                )

                and

                etf_close > 0

            ):

                last_etf_close = (

                    etf_close

                )

        else:

            etf_open = np.nan

            etf_close = (

                float(

                    last_etf_close

                )

                if np.isfinite(

                    last_etf_close

                )

                else np.nan

            )

        # ====================================================

        # B. Financing

        # ====================================================

        long_interest_today = 0.0

        short_fee_today = 0.0

        if previous_date is not None:

            calendar_days = int(

                (

                    date

                    -

                    previous_date

                ).days

            )

            for p in broker_active.values():

                n = float(

                    p[

                        "ActualNotional"

                    ]

                )

                if p["Side"] == "LONG":

                    cost = (

                        n

                        *

                        LONG_INTEREST_ANNUAL

                        *

                        calendar_days

                        /

                        DAY_COUNT

                    )

                    long_interest_today += (

                        cost

                    )

                else:

                    cost = (

                        n

                        *

                        SHORT_LENDING_ANNUAL

                        *

                        calendar_days

                        /

                        DAY_COUNT

                    )

                    short_fee_today += (

                        cost

                    )

        financing_today = (

            long_interest_today

            +

            short_fee_today

        )

        cash -= (

            financing_today

        )

        broker_strategy_equity -= (

            financing_today

        )

        cum_long_interest += (

            long_interest_today

        )

        cum_short_fee += (

            short_fee_today

        )

        # ====================================================

        # C. Morning ETF actions

        #

        # FIX10と同じ。

        # ====================================================

        bought_etf_today = 0

        sold_etf_today = 0

        recovery_sell_today = False

        if (

            has_quote

            and

            np.isfinite(

                etf_open

            )

            and

            etf_open > 0

        ):

            # ------------------------------------------------

            # Cash recovery

            # ------------------------------------------------

            if cash < CASH_FLOOR:

                deficit = (

                    CASH_FLOOR

                    -

                    cash

                )

                required_sell = int(

                    np.ceil(

                        deficit

                        /

                        etf_open

                    )

                )

                sell_shares = min(

                    required_sell,

                    etf_shares

                )

                if sell_shares > 0:

                    proceeds = (

                        sell_shares

                        *

                        etf_open

                    )

                    cash_before = float(

                        cash

                    )

                    etf_shares -= (

                        sell_shares

                    )

                    cash += (

                        proceeds

                        -

                        ETF_SELL_FEE

                    )

                    sold_etf_today = (

                        sell_shares

                    )

                    recovery_sell_today = (

                        True

                    )

                    tx_rows.append({

                        "Date":

                            date,

                        "Type":

                            "SELL_CASH_RECOVERY",

                        "Price":

                            etf_open,

                        "Shares":

                            sell_shares,

                        "CashBefore":

                            cash_before,

                        "CashAfter":

                            cash,

                        "ETF_SharesAfter":

                            etf_shares,

                    })

            # ------------------------------------------------

            # Monthly / Initial ETF buy

            # ------------------------------------------------

            should_buy = (

                (

                    not initial_purchase_done

                )

                or

                is_monthly_buy

            )

            if (

                should_buy

                and

                not recovery_sell_today

            ):

                long_n, short_n = (

                    current_broker_notional()

                )

                gross_n = (

                    long_n

                    +

                    short_n

                )

                buy_shares = (

                    calc_max_etf_buy_shares(

                        cash_now=cash,

                        shares_now=etf_shares,

                        etf_open=etf_open,

                        gross_notional=gross_n

                    )

                )

                if buy_shares > 0:

                    total_cost = (

                        buy_shares

                        *

                        etf_open

                        +

                        ETF_BUY_FEE

                    )

                    if (

                        cash

                        -

                        total_cost

                        <

                        CASH_FLOOR

                    ):

                        buy_shares = int(

                            max(

                                0,

                                (

                                    cash

                                    -

                                    CASH_FLOOR

                                    -

                                    ETF_BUY_FEE

                                )

                                //

                                etf_open

                            )

                        )

                        total_cost = (

                            buy_shares

                            *

                            etf_open

                            +

                            ETF_BUY_FEE

                        )

                    if buy_shares > 0:

                        cash_before = float(

                            cash

                        )

                        etf_shares += (

                            buy_shares

                        )

                        cash -= (

                            total_cost

                        )

                        bought_etf_today = (

                            buy_shares

                        )

                        tx_rows.append({

                            "Date":

                                date,

                            "Type":

                                (

                                    "INITIAL_BUY"

                                    if not initial_purchase_done

                                    else

                                    "MONTHLY_BUY"

                                ),

                            "Price":

                                etf_open,

                            "Shares":

                                buy_shares,

                            "CashBefore":

                                cash_before,

                            "CashAfter":

                                cash,

                            "ETF_SharesAfter":

                                etf_shares,

                        })

                        initial_purchase_done = (

                            True

                        )

        # ====================================================

        # ETF mark usable at intraday ENTRY

        # ====================================================

        if (

            has_quote

            and

            np.isfinite(

                etf_open

            )

            and

            etf_open > 0

        ):

            entry_etf_mark = (

                etf_open

            )

        else:

            entry_etf_mark = (

                last_etf_close

                if np.isfinite(

                    last_etf_close

                )

                else np.nan

            )

        # ====================================================

        # D. Strategy Events

        # ====================================================

        formal_realized_today = 0.0

        broker_realized_today = 0.0

        for e in events_by_date.get(

            date,

            []

        ):

            trade_id = str(

                e[

                    "TradeID"

                ]

            )

            side = str(

                e[

                    "Side"

                ]

            ).upper()

            # =================================================

            # EXIT

            # =================================================

            if e["Event"] == "EXIT":

                # ---------------------------------------------

                # Formal

                # ---------------------------------------------

                if trade_id not in formal_active:

                    raise RuntimeError(

                        f"{e['Datetime']} "

                        f"Formal EXIT positionなし: "

                        f"{trade_id}"

                    )

                fp = formal_active[

                    trade_id

                ]

                formal_r = (

                    float(

                        e[

                            "ReturnPct"

                        ]

                    )

                    /

                    100.0

                )

                formal_pnl = (

                    fp[

                        "EntryNotional"

                    ]

                    *

                    formal_r

                )

                formal_equity += (

                    formal_pnl

                )

                formal_realized_today += (

                    formal_pnl

                )

                del formal_active[

                    trade_id

                ]

                # ---------------------------------------------

                # Broker SKIP

                # ---------------------------------------------

                if trade_id in broker_skipped:

                    broker_skipped.remove(

                        trade_id

                    )

                    continue

                if trade_id not in broker_active:

                    raise RuntimeError(

                        f"{e['Datetime']} "

                        f"Broker EXIT positionなし: "

                        f"{trade_id}"

                    )

                bp = broker_active[

                    trade_id

                ]

                entry_price = float(

                    bp[

                        "EntryPrice"

                    ]

                )

                broker_r, exit_price = (

                    get_broker_return(

                        side=side,

                        entry_price=entry_price,

                        formal_return_pct=e[

                            "ReturnPct"

                        ]

                    )

                )

                qty = int(

                    bp[

                        "Quantity"

                    ]

                )

                if side == "LONG":

                    broker_pnl = (

                        qty

                        *

                        (

                            exit_price

                            -

                            entry_price

                        )

                    )

                else:

                    broker_pnl = (

                        qty

                        *

                        (

                            entry_price

                            -

                            exit_price

                        )

                    )

                broker_strategy_equity += (

                    broker_pnl

                )

                cash += (

                    broker_pnl

                )

                broker_realized_today += (

                    broker_pnl

                )

                trade_rows.append({

                    "TradeID":

                        trade_id,

                    "Side":

                        side,

                    "Code":

                        bp[

                            "Code"

                        ],

                    "EntryDatetime":

                        bp[

                            "EntryDatetime"

                        ],

                    "ExitDatetime":

                        pd.Timestamp(

                            e[

                                "Datetime"

                            ]

                        ),

                    "EntryPrice":

                        entry_price,

                    "ExitPrice":

                        exit_price,

                    "Quantity":

                        qty,

                    "TargetNotional":

                        bp[

                            "TargetNotional"

                        ],

                    "LotNotionalBeforeMargin":

                        bp[

                            "LotNotionalBeforeMargin"

                        ],

                    "ActualNotional":

                        bp[

                            "ActualNotional"

                        ],

                    "TargetUtilizationPct":

                        bp[

                            "TargetUtilizationPct"

                        ],

                    "FormalReturnPct":

                        float(

                            e[

                                "ReturnPct"

                            ]

                        ),

                    "BrokerReturnPct":

                        broker_r

                        *

                        100.0,

                    "BrokerPnL":

                        broker_pnl,

                    "MarginLimitedAtEntry":

                        bp[

                            "MarginLimitedAtEntry"

                        ],

                })

                del broker_active[

                    trade_id

                ]

            # =================================================

            # ENTRY

            # =================================================

            else:

                meta = entry_meta.get(

                    trade_id

                )

                if meta is None:

                    raise RuntimeError(

                        f"entry_metaなし: "

                        f"{trade_id}"

                    )

                entry_price = float(

                    meta[

                        "EntryPrice"

                    ]

                )

                leverage = (

                    LONG_LEVERAGE

                    if side == "LONG"

                    else

                    SHORT_LEVERAGE

                )

                # ---------------------------------------------

                # Formal Stage5

                # ---------------------------------------------

                formal_notional = (

                    formal_equity

                    *

                    leverage

                )

                formal_active[

                    trade_id

                ] = {

                    "Side":

                        side,

                    "EntryNotional":

                        formal_notional,

                }

                # ---------------------------------------------

                # Broker Target

                # ---------------------------------------------

                if broker_strategy_equity <= 0:

                    raise RuntimeError(

                        f"Broker strategy equity <= 0: "

                        f"{date.date()}"

                    )

                # =================================================

                # TRUE CAP200 LONG-ONLY BROKER TARGET

                #

                # LONG:

                #   1銘柄最大 2,000,000円

                #   Dynamic max positions

                #   LONG総建玉 <= broker strategy equity × 1.0

                #

                # SHORT:

                #   元FIX11 sizingをそのまま使用

                # =================================================

                if side == "LONG":

                    # ---------------------------------------------

                    # 現在のLONG建玉だけを取得

                    # ---------------------------------------------

                    current_long_positions = [

                        p

                        for p in broker_active.values()

                        if str(

                            p.get(

                                "Side",

                                ""

                            )

                        ).upper() == "LONG"

                    ]

                    current_long_count = len(

                        current_long_positions

                    )

                    # ---------------------------------------------

                    # Dynamic position limit

                    # ---------------------------------------------

                    long_allowed_positions = (

                        calc_long_dynamic_max_positions(

                            broker_strategy_equity

                        )

                    )

                    # ---------------------------------------------

                    # 既に最大ポジション数ならENTRY不可

                    #

                    # target_notional=0 にして、

                    # 既存FIX11のLOT処理へ流す

                    # ---------------------------------------------

                    if (

                        current_long_count

                        >=

                        long_allowed_positions

                    ):

                        target_notional = 0.0

                    else:

                        # -----------------------------------------

                        # 現在LONG gross notional

                        #

                        # EntryNotionalが存在すればそれを使用。

                        # なければ EntryPrice × Shares。

                        # -----------------------------------------

                        current_long_gross = 0.0

                        for _p in current_long_positions:

                            _notional = _p.get(

                                "ActualNotional",

                                np.nan

                            )

                            if not np.isfinite(

                                pd.to_numeric(

                                    _notional,

                                    errors="coerce"

                                )

                            ):

                                _px = pd.to_numeric(

                                    _p.get(

                                        "EntryPrice",

                                        np.nan

                                    ),

                                    errors="coerce"

                                )

                                _qty = pd.to_numeric(

                                    _p.get(

                                        "Quantity",

                                        np.nan

                                    ),

                                    errors="coerce"

                                )

                                if (

                                    np.isfinite(_px)

                                    and

                                    np.isfinite(_qty)

                                ):

                                    _notional = (

                                        float(_px)

                                        *

                                        float(_qty)

                                    )

                                else:

                                    _notional = 0.0

                            current_long_gross += float(

                                _notional

                            )

                        # -----------------------------------------

                        # LONG総建玉上限 = strategy equity × 1.0

                        # -----------------------------------------

                        long_total_limit = max(

                            0.0,

                            float(

                                broker_strategy_equity

                            )

                            *

                            LONG_LEVERAGE

                        )

                        long_remaining_capacity = max(

                            0.0,

                            long_total_limit

                            -

                            current_long_gross

                        )

                        # -----------------------------------------

                        # 1銘柄最大200万円

                        # -----------------------------------------

                        target_notional = min(

                            LONG_CAP_PER_STOCK,

                            long_remaining_capacity

                        )

                else:

                    # ---------------------------------------------

                    # SHORTは元FIX11そのまま

                    # ---------------------------------------------

                    target_notional = (

                        broker_strategy_equity

                        *

                        leverage

                    )

                target_qty = (

                    calc_target_qty(

                        target_notional=

                            target_notional,

                        entry_price=

                            entry_price

                    )

                )

                lot_notional_before_margin = (

                    target_qty

                    *

                    entry_price

                )

                # ---------------------------------------------

                # ENTRY直前 position state

                # ---------------------------------------------

                pre = (

                    calc_entry_time_position_state(

                        broker_active=

                            broker_active,

                        current_date=

                            date

                    )

                )

                # ---------------------------------------------

                # Margin capacity

                # ---------------------------------------------

                margin_check = (

                    calc_margin_capped_qty(

                        target_qty=

                            target_qty,

                        entry_price=

                            entry_price,

                        cash_now=

                            cash,

                        etf_mark=

                            entry_etf_mark,

                        etf_shares=

                            etf_shares,

                        existing_gross_notional=

                            pre[

                                "GrossNotional"

                            ],

                        existing_unrealized=

                            pre[

                                "TotalUnrealized"

                            ]

                    )

                )

                qty = int(

                    margin_check[

                        "AllowedQty"

                    ]

                )

                actual_notional = (

                    qty

                    *

                    entry_price

                )

                utilization = (

                    actual_notional

                    /

                    target_notional

                    *

                    100.0

                    if target_notional > 0

                    else np.nan

                )

                skipped = (

                    qty == 0

                )

                # ---------------------------------------------

                # Skip reason

                # ---------------------------------------------

                if target_qty == 0:

                    skip_reason = (

                        "LOT_TOO_LARGE"

                    )

                elif qty == 0:

                    skip_reason = (

                        "MARGIN_CAPACITY"

                    )

                else:

                    skip_reason = (

                        ""

                    )

                entry_rows.append({

                    "TradeID":

                        trade_id,

                    "Side":

                        side,

                    "Code":

                        str(

                            meta[

                                "Code"

                            ]

                        ).zfill(5),

                    "EntryDatetime":

                        pd.Timestamp(

                            e[

                                "Datetime"

                            ]

                        ),

                    "EntryPrice":

                        entry_price,

                    "BrokerStrategyEquity":

                        broker_strategy_equity,

                    "Leverage":

                        leverage,

                    "TargetNotional":

                        target_notional,

                    "TargetQty100":

                        target_qty,

                    "LotNotionalBeforeMargin":

                        lot_notional_before_margin,

                    "PreExistingGrossNotional":

                        pre[

                            "GrossNotional"

                        ],

                    "PreExistingUnrealized":

                        pre[

                            "TotalUnrealized"

                        ],

                    "EntryEffectiveCollateral":

                        margin_check[

                            "EffectiveCollateral"

                        ],

                    "MaxAdditionalNotionalByMargin":

                        margin_check[

                            "MaxNotionalByMargin"

                        ],

                    "PreMarginPct":

                        margin_check[

                            "PreMarginPct"

                        ],

                    "PostMarginPct":

                        margin_check[

                            "PostMarginPct"

                        ],

                    "Quantity":

                        qty,

                    "ActualNotional":

                        actual_notional,

                    "UnusedTargetNotional":

                        (

                            target_notional

                            -

                            actual_notional

                        ),

                    "TargetUtilizationPct":

                        utilization,

                    "MarginLimited":

                        margin_check[

                            "MarginLimited"

                        ],

                    "MissingPrevMarks":

                        pre[

                            "MissingPrevMarks"

                        ],

                    "Skipped":

                        skipped,

                    "SkipReason":

                        skip_reason,

                })

                # ---------------------------------------------

                # Broker Skip

                # ---------------------------------------------

                if skipped:

                    broker_skipped.add(

                        trade_id

                    )

                    continue

                # ---------------------------------------------

                # Safety assertion

                # ---------------------------------------------

                post_margin_pct = (

                    margin_check[

                        "PostMarginPct"

                    ]

                )

                if (

                    np.isfinite(

                        post_margin_pct

                    )

                    and

                    post_margin_pct

                    <

                    MIN_MARGIN_RATIO

                    *

                    100.0

                    -

                    1e-9

                ):

                    raise RuntimeError(

                        "ENTRY margin check failure: "

                        f"{trade_id} "

                        f"{post_margin_pct:.6f}%"

                    )

                broker_active[

                    trade_id

                ] = {

                    "TradeID":

                        trade_id,

                    "Side":

                        side,

                    "Code":

                        str(

                            meta[

                                "Code"

                            ]

                        ).zfill(5),

                    "EntryDatetime":

                        pd.Timestamp(

                            e[

                                "Datetime"

                            ]

                        ),

                    "EntryPrice":

                        entry_price,

                    "Quantity":

                        qty,

                    "TargetNotional":

                        target_notional,

                    "LotNotionalBeforeMargin":

                        lot_notional_before_margin,

                    "ActualNotional":

                        actual_notional,

                    "TargetUtilizationPct":

                        utilization,

                    "MarginLimitedAtEntry":

                        margin_check[

                            "MarginLimited"

                        ],

                }

        # ====================================================

        # E. EOD Broker MTM

        # ====================================================

        long_notional = 0.0

        short_notional = 0.0

        long_unrealized = 0.0

        short_unrealized = 0.0

        missing_marks = []

        for trade_id, p in broker_active.items():

            code = p[

                "Code"

            ]

            entry_price = float(

                p[

                    "EntryPrice"

                ]

            )

            qty = int(

                p[

                    "Quantity"

                ]

            )

            actual_notional = float(

                p[

                    "ActualNotional"

                ]

            )

            mark = daily_mark_map.get(

                (

                    date,

                    code

                ),

                np.nan

            )

            if not np.isfinite(

                mark

            ):

                missing_marks.append(

                    (

                        trade_id,

                        code

                    )

                )

                continue

            if p["Side"] == "LONG":

                u = (

                    qty

                    *

                    (

                        mark

                        -

                        entry_price

                    )

                )

                long_notional += (

                    actual_notional

                )

                long_unrealized += (

                    u

                )

            else:

                u = (

                    qty

                    *

                    (

                        entry_price

                        -

                        mark

                    )

                )

                short_notional += (

                    actual_notional

                )

                short_unrealized += (

                    u

                )

        gross_notional = (

            long_notional

            +

            short_notional

        )

        total_unrealized = (

            long_unrealized

            +

            short_unrealized

        )

        # ====================================================

        # F. ETF EOD

        # ====================================================

        if np.isfinite(

            etf_close

        ):

            etf_value = (

                etf_shares

                *

                etf_close

            )

        else:

            etf_value = 0.0

        substitute80 = (

            etf_value

            *

            SUBSTITUTE_HAIRCUT

        )

        # ====================================================

        # G. EOD Margin

        # ====================================================

        effective_collateral = (

            cash

            +

            substitute80

            +

            total_unrealized

        )

        if gross_notional > 0:

            margin_ratio = (

                effective_collateral

                /

                gross_notional

            )

        else:

            margin_ratio = np.nan

        # ====================================================

        # H. Equity

        # ====================================================

        realized_total_equity = (

            cash

            +

            etf_value

        )

        total_equity_mtm = (

            realized_total_equity

            +

            total_unrealized

        )

        daily_rows.append({

            "Date":

                date,

            "ETF_Shares":

                etf_shares,

            "ETF_Value":

                etf_value,

            "BoughtETFToday":

                bought_etf_today,

            "SoldETFToday":

                sold_etf_today,

            "Cash":

                cash,

            "CashNegative":

                cash < 0,

            "FormalStrategyEquity":

                formal_equity,

            "BrokerStrategyEquity":

                broker_strategy_equity,

            "FormalRealizedPnLToday":

                formal_realized_today,

            "BrokerRealizedPnLToday":

                broker_realized_today,

            "LongInterestToday":

                long_interest_today,

            "ShortFeeToday":

                short_fee_today,

            "FinancingToday":

                financing_today,

            "CumLongInterest":

                cum_long_interest,

            "CumShortFee":

                cum_short_fee,

            "CumFinancingCost":

                (

                    cum_long_interest

                    +

                    cum_short_fee

                ),

            "LongNotional":

                long_notional,

            "ShortNotional":

                short_notional,

            "GrossNotional":

                gross_notional,

            "LongUnrealized":

                long_unrealized,

            "ShortUnrealized":

                short_unrealized,

            "TotalUnrealized":

                total_unrealized,

            "Substitute80":

                substitute80,

            "EffectiveCollateralMTM":

                effective_collateral,

            "MarginRatioMTMPct":

                (

                    margin_ratio

                    *

                    100.0

                    if np.isfinite(

                        margin_ratio

                    )

                    else np.nan

                ),

            "Below30":

                (

                    gross_notional > 0

                    and

                    margin_ratio

                    <

                    MIN_MARGIN_RATIO

                ),

            "Below20":

                (

                    gross_notional > 0

                    and

                    margin_ratio

                    <

                    MARGIN_CALL_LINE

                ),

            "Below15":

                (

                    gross_notional > 0

                    and

                    margin_ratio

                    <

                    SEVERE_LINE

                ),

            "MissingMarks":

                len(

                    missing_marks

                ),

            "BrokerOpenPositions":

                len(

                    broker_active

                ),

            "BrokerSkippedOpen":

                len(

                    broker_skipped

                ),

            "RealizedTotalEquity":

                realized_total_equity,

            "TotalEquityMTM":

                total_equity_mtm,

        })

        previous_date = (

            date

        )

    # ========================================================

    # DataFrames

    # ========================================================

    daily = pd.DataFrame(

        daily_rows

    )

    entries = pd.DataFrame(

        entry_rows

    )

    trades = pd.DataFrame(

        trade_rows

    )

    tx = pd.DataFrame(

        tx_rows

    )

    # ========================================================

    # DD

    # ========================================================

    eq = (

        daily[

            "TotalEquityMTM"

        ]

        .to_numpy(

            dtype=float

        )

    )

    peak = np.maximum.accumulate(

        eq

    )

    daily[

        "DrawdownMTMPct"

    ] = (

        eq

        /

        peak

        -

        1.0

    ) * 100.0

    return (

        daily,

        entries,

        trades,

        tx,

        formal_active,

        broker_active,

        broker_skipped

    )

# ============================================================

# 16. 実行

# ============================================================

(

    fix11_daily,

    fix11_entry_audit,

    fix11_trade_audit,

    fix11_tx,

    fix11_formal_open,

    fix11_broker_open,

    fix11_broker_skipped

) = simulate_fix11()

last = (

    fix11_daily

    .iloc[-1]

)

# ============================================================

# 17. Formal hard check

# ============================================================

formal_final = float(

    last[

        "FormalStrategyEquity"

    ]

)

# ============================================================

# CAP200_LONG_ONLY Formal result check

#

# 元FORMAL 583件の期待値 5,755,654円は使用しない。

# CAP200_LONG_ONLYは867件の別売買ストリームなので、

# 初回FIX11では結果を取得する。

#

# FIX11のsimulation logic自体は変更しない。

# ============================================================

if EXPECTED_STAGE5_FINAL is None:

    formal_diff = np.nan

    print()

    print("=" * 240)

    print("CAP200_LONG_ONLY FORMAL RESULT")

    print("=" * 240)

    print(

        "Current :",

        f"{formal_final:,.2f}"

    )

    print(

        "Expected:",

        "NOT SET"

    )

    print(

        "Diff    :",

        "N/A"

    )

    print(

        "CAP200 FORMAL BASELINE CAPTURE: PASS"

    )

else:

    formal_diff = (

        formal_final

        -

        EXPECTED_STAGE5_FINAL

    )

    print()

    print("=" * 240)

    print("FORMAL STAGE5 HARD CHECK")

    print("=" * 240)

    print(

        "Current :",

        f"{formal_final:,.2f}"

    )

    print(

        "Expected:",

        f"{EXPECTED_STAGE5_FINAL:,.2f}"

    )

    print(

        "Diff    :",

        f"{formal_diff:+,.2f}"

    )

    if abs(

        formal_diff

    ) > 10:

        raise RuntimeError(

            "Formal Stage5 reproduction FAILED"

        )

    print(

        "★★★★★ FORMAL PASS ★★★★★"

    )

# ============================================================

# 18. ENTRY audit

# ============================================================

entries = (

    fix11_entry_audit

    .copy()

)

executed = (

    entries[

        ~entries[

            "Skipped"

        ]

    ]

)

skipped = (

    entries[

        entries[

            "Skipped"

        ]

    ]

)

lot_skipped = (

    skipped[

        skipped[

            "SkipReason"

        ]

        ==

        "LOT_TOO_LARGE"

    ]

)

margin_skipped = (

    skipped[

        skipped[

            "SkipReason"

        ]

        ==

        "MARGIN_CAPACITY"

    ]

)

margin_limited = (

    entries[

        entries[

            "MarginLimited"

        ]

    ]

)

margin_reduced = (

    entries[

        (

            entries[

                "MarginLimited"

            ]

        )

        &

        (

            entries[

                "Quantity"

            ]

            >

            0

        )

    ]

)

print()

print("=" * 240)

print("ENTRY-TIME MARGIN CAPACITY AUDIT")

print("=" * 240)

print(

    "Candidate entries:",

    len(

        entries

    )

)

print(

    "Executed:",

    len(

        executed

    )

)

print(

    "Skipped total:",

    len(

        skipped

    )

)

print()

print(

    "LOT_TOO_LARGE skipped:",

    len(

        lot_skipped

    )

)

print(

    "MARGIN_CAPACITY skipped:",

    len(

        margin_skipped

    )

)

print()

print(

    "Margin-limited signals:",

    len(

        margin_limited

    )

)

print(

    "Margin-reduced but executed:",

    len(

        margin_reduced

    )

)

print()

print(

    "Execution rate:",

    f"{len(executed) / len(entries) * 100:.2f}%"

)

# ============================================================

# 19. No-Future mark audit

# ============================================================

missing_prev = (

    entries[

        entries[

            "MissingPrevMarks"

        ]

        >

        0

    ]

)

print()

print("=" * 240)

print("ENTRY NO-FUTURE MARK AUDIT")

print("=" * 240)

print(

    "Entries with missing previous marks:",

    len(

        missing_prev

    )

)

print(

    "Maximum missing previous marks:",

    int(

        entries[

            "MissingPrevMarks"

        ].max()

    )

)

# ============================================================

# 20. Entry margin statistics

# ============================================================

post_valid = (

    executed[

        executed[

            "PostMarginPct"

        ].notna()

    ]

)

if len(

    post_valid

):

    min_post_idx = (

        post_valid[

            "PostMarginPct"

        ]

        .idxmin()

    )

    min_post_row = (

        entries

        .loc[

            min_post_idx

        ]

    )

    min_post_margin = float(

        min_post_row[

            "PostMarginPct"

        ]

    )

else:

    min_post_row = None

    min_post_margin = np.nan

print()

print("=" * 240)

print("ENTRY POST-MARGIN AUDIT")

print("=" * 240)

print(

    "Minimum post-entry margin:",

    (

        f"{min_post_margin:.2f}%"

        if np.isfinite(

            min_post_margin

        )

        else "NaN"

    )

)

if min_post_row is not None:

    print(

        "TradeID:",

        min_post_row[

            "TradeID"

        ]

    )

    print(

        "Side:",

        min_post_row[

            "Side"

        ]

    )

    print(

        "Code:",

        min_post_row[

            "Code"

        ]

    )

    print(

        "EntryDatetime:",

        min_post_row[

            "EntryDatetime"

        ]

    )

    print(

        "TargetQty:",

        int(

            min_post_row[

                "TargetQty100"

            ]

        )

    )

    print(

        "ActualQty:",

        int(

            min_post_row[

                "Quantity"

            ]

        )

    )

# ============================================================

# 21. Daily mark audit

# ============================================================

missing_days = (

    fix11_daily[

        fix11_daily[

            "MissingMarks"

        ]

        >

        0

    ]

)

print()

print("=" * 240)

print("EOD DAILY MARK AUDIT")

print("=" * 240)

print(

    "Days with missing mark:",

    len(

        missing_days

    )

)

print(

    "Max missing positions:",

    int(

        fix11_daily[

            "MissingMarks"

        ].max()

    )

)

# ============================================================

# 22. Financing

# ============================================================

print()

print("=" * 240)

print("FINANCING COST")

print("=" * 240)

print(

    "LONG interest:",

    f"{last['CumLongInterest']:,.2f}"

)

print(

    "SHORT lending:",

    f"{last['CumShortFee']:,.2f}"

)

print(

    "Total:",

    f"{last['CumFinancingCost']:,.2f}"

)

# ============================================================

# 23. Cash

# ============================================================

negative_days = (

    fix11_daily[

        fix11_daily[

            "CashNegative"

        ]

    ]

)

min_cash_idx = (

    fix11_daily[

        "Cash"

    ]

    .idxmin()

)

min_cash_row = (

    fix11_daily

    .loc[

        min_cash_idx

    ]

)

if len(

    fix11_tx

):

    recovery_sells = (

        fix11_tx[

            fix11_tx[

                "Type"

            ]

            ==

            "SELL_CASH_RECOVERY"

        ]

    )

else:

    recovery_sells = pd.DataFrame()

print()

print("=" * 240)

print("CASH AUDIT")

print("=" * 240)

print(

    "Minimum EOD cash:",

    f"{min_cash_row['Cash']:,.2f}"

)

print(

    "Minimum cash date:",

    min_cash_row[

        "Date"

    ].date()

)

print(

    "Negative cash days:",

    len(

        negative_days

    )

)

print(

    "Recovery sell events:",

    len(

        recovery_sells

    )

)

print(

    "Recovery shares sold:",

    (

        int(

            recovery_sells[

                "Shares"

            ].sum()

        )

        if len(

            recovery_sells

        )

        else 0

    )

)

# ============================================================

# 24. EOD margin

# ============================================================

valid_margin = (

    fix11_daily[

        (

            fix11_daily[

                "GrossNotional"

            ]

            >

            0

        )

        &

        (

            fix11_daily[

                "MarginRatioMTMPct"

            ].notna()

        )

    ]

    .copy()

)

worst_idx = (

    valid_margin[

        "MarginRatioMTMPct"

    ]

    .idxmin()

)

worst = (

    fix11_daily

    .loc[

        worst_idx

    ]

)

below30 = (

    valid_margin[

        valid_margin[

            "Below30"

        ]

    ]

)

below20 = (

    valid_margin[

        valid_margin[

            "Below20"

        ]

    ]

)

below15 = (

    valid_margin[

        valid_margin[

            "Below15"

        ]

    ]

)

print()

print("=" * 240)

print("EOD BROKER MTM MARGIN AUDIT")

print("=" * 240)

print(

    "Worst date:",

    worst[

        "Date"

    ].date()

)

print(

    "Minimum EOD margin ratio:",

    f"{worst['MarginRatioMTMPct']:.2f}%"

)

print(

    "<30% days:",

    len(

        below30

    )

)

print(

    "<20% days:",

    len(

        below20

    )

)

print(

    "<15% days:",

    len(

        below15

    )

)

# ============================================================

# 25. Final result

# ============================================================

broker_strategy_final = float(

    last[

        "BrokerStrategyEquity"

    ]

)

final_realized = float(

    last[

        "RealizedTotalEquity"

    ]

)

final_unrealized = float(

    last[

        "TotalUnrealized"

    ]

)

final_mtm = float(

    last[

        "TotalEquityMTM"

    ]

)

return_mtm = (

    final_mtm

    /

    INITIAL_CAPITAL

    -

    1.0

) * 100.0

maxdd = float(

    fix11_daily[

        "DrawdownMTMPct"

    ].min()

)

years = (

    (

        pd.Timestamp(

            END_DATE

        )

        -

        pd.Timestamp(

            START_DATE

        )

    ).days

    /

    365.25

)

cagr = (

    (

        final_mtm

        /

        INITIAL_CAPITAL

    )

    **

    (

        1.0

        /

        years

    )

    -

    1.0

) * 100.0

print()

print("=" * 240)

print("FIX11 FINAL RESULT")

print("=" * 240)

print(

    "Initial capital:",

    f"{INITIAL_CAPITAL:,.2f}"

)

print()

print(

    "Formal Stage5 strategy:",

    f"{formal_final:,.2f}"

)

print(

    "Broker strategy:",

    f"{broker_strategy_final:,.2f}"

)

print()

print(

    "Final realized equity:",

    f"{final_realized:,.2f}"

)

print(

    "Final open unrealized:",

    f"{final_unrealized:+,.2f}"

)

print(

    "Final MTM equity:",

    f"{final_mtm:,.2f}"

)

print(

    "MTM return:",

    f"{return_mtm:+.2f}%"

)

print(

    "MTM CAGR:",

    f"{cagr:+.2f}%"

)

print(

    "MTM MaxDD:",

    f"{maxdd:.2f}%"

)

print()

print(

    "Final 1557 shares:",

    int(

        last[

            "ETF_Shares"

        ]

    )

)

print(

    "Final 1557 value:",

    f"{last['ETF_Value']:,.2f}"

)

print(

    "Final Cash:",

    f"{last['Cash']:,.2f}"

)

# ============================================================

# 26. FIX10 vs FIX11

# ============================================================

comparison_rows = []

if "fix10_daily" in globals():

    f10 = (

        fix10_daily

        .iloc[-1]

    )

    comparison_rows.append({

        "Rule":

            "FIX10_100_SHARE",

        "FinalMTM":

            float(

                f10[

                    "TotalEquityMTM"

                ]

            ),

        "ReturnPct":

            (

                float(

                    f10[

                        "TotalEquityMTM"

                    ]

                )

                /

                INITIAL_CAPITAL

                -

                1.0

            )

            *

            100.0,

        "MaxDDPct":

            float(

                fix10_daily[

                    "DrawdownMTMPct"

                ].min()

            ),

        "BrokerStrategyFinal":

            float(

                f10[

                    "BrokerStrategyEquity"

                ]

            ),

        "FinancingCost":

            float(

                f10[

                    "CumFinancingCost"

                ]

            ),

        "FinalShares":

            int(

                f10[

                    "ETF_Shares"

                ]

            ),

        "FinalCash":

            float(

                f10[

                    "Cash"

                ]

            ),

    })

comparison_rows.append({

    "Rule":

        "FIX11_ENTRY_MARGIN",

    "FinalMTM":

        final_mtm,

    "ReturnPct":

        return_mtm,

    "MaxDDPct":

        maxdd,

    "BrokerStrategyFinal":

        broker_strategy_final,

    "FinancingCost":

        float(

            last[

                "CumFinancingCost"

            ]

        ),

    "FinalShares":

        int(

            last[

                "ETF_Shares"

            ]

        ),

    "FinalCash":

        float(

            last[

                "Cash"

            ]

        ),

})

fix11_comparison = pd.DataFrame(

    comparison_rows

)

print()

print("=" * 250)

print("FIX10 vs FIX11")

print("=" * 250)

print(

    fix11_comparison.to_string(

        index=False,

        formatters={

            "FinalMTM":

                lambda x:

                f"{x:,.0f}",

            "ReturnPct":

                lambda x:

                f"{x:+.2f}%",

            "MaxDDPct":

                lambda x:

                f"{x:.2f}%",

            "BrokerStrategyFinal":

                lambda x:

                f"{x:,.0f}",

            "FinancingCost":

                lambda x:

                f"{x:,.0f}",

            "FinalShares":

                lambda x:

                f"{int(x)}",

            "FinalCash":

                lambda x:

                f"{x:,.0f}",

        }

    )

)

# ============================================================

# 27. Margin-limited details

# ============================================================

print()

print("=" * 260)

print("MARGIN-LIMITED ENTRY DETAILS")

print("=" * 260)

if len(

    margin_limited

) == 0:

    print(

        "0件"

    )

else:

    print(

        margin_limited[

            [

                "TradeID",

                "Side",

                "Code",

                "EntryDatetime",

                "EntryPrice",

                "BrokerStrategyEquity",

                "TargetNotional",

                "TargetQty100",

                "PreExistingGrossNotional",

                "PreExistingUnrealized",

                "EntryEffectiveCollateral",

                "PreMarginPct",

                "PostMarginPct",

                "Quantity",

                "ActualNotional",

                "TargetUtilizationPct",

                "Skipped",

                "SkipReason",

            ]

        ]

        .to_string(

            index=False,

            formatters={

                "EntryPrice":

                    lambda x:

                    f"{x:,.2f}",

                "BrokerStrategyEquity":

                    lambda x:

                    f"{x:,.0f}",

                "TargetNotional":

                    lambda x:

                    f"{x:,.0f}",

                "PreExistingGrossNotional":

                    lambda x:

                    f"{x:,.0f}",

                "PreExistingUnrealized":

                    lambda x:

                    f"{x:+,.0f}",

                "EntryEffectiveCollateral":

                    lambda x:

                    f"{x:,.0f}",

                "PreMarginPct":

                    lambda x:

                    (

                        f"{x:.2f}%"

                        if np.isfinite(

                            x

                        )

                        else "-"

                    ),

                "PostMarginPct":

                    lambda x:

                    (

                        f"{x:.2f}%"

                        if np.isfinite(

                            x

                        )

                        else "-"

                    ),

                "ActualNotional":

                    lambda x:

                    f"{x:,.0f}",

                "TargetUtilizationPct":

                    lambda x:

                    f"{x:.2f}%",

            }

        )

    )

# ============================================================

# 28. Graph

# ============================================================

plt.figure(

    figsize=(14, 7)

)

if "fix10_daily" in globals():

    plt.plot(

        fix10_daily[

            "Date"

        ],

        fix10_daily[

            "TotalEquityMTM"

        ],

        label="FIX10 100-share"

    )

plt.plot(

    fix11_daily[

        "Date"

    ],

    fix11_daily[

        "TotalEquityMTM"

    ],

    label="FIX11 Entry Margin"

)

plt.xlabel(

    "Date"

)

plt.ylabel(

    "Equity (JPY)"

)

plt.title(

    "FIX10 vs FIX11"

)

plt.legend()

plt.grid(

    alpha=0.25

)

plt.show()

# ============================================================

# 29. Summary

# ============================================================

fix11_summary = pd.DataFrame([

    {

        "InitialCapital":

            INITIAL_CAPITAL,

        "FormalStage5Final":

            formal_final,

        "FormalStage5Diff":

            formal_diff,

        "BrokerStrategyFinal":

            broker_strategy_final,

        "FinalRealizedEquity":

            final_realized,

        "FinalOpenUnrealized":

            final_unrealized,

        "FinalMTMEquity":

            final_mtm,

        "MTMReturnPct":

            return_mtm,

        "MTMCAGR_Pct":

            cagr,

        "MTMMaxDDPct":

            maxdd,

        "CandidateEntries":

            len(

                entries

            ),

        "ExecutedEntries":

            len(

                executed

            ),

        "SkippedEntries":

            len(

                skipped

            ),

        "LotTooLargeSkipped":

            len(

                lot_skipped

            ),

        "MarginCapacitySkipped":

            len(

                margin_skipped

            ),

        "MarginLimitedEntries":

            len(

                margin_limited

            ),

        "MarginReducedExecuted":

            len(

                margin_reduced

            ),

        "MinimumPostEntryMarginPct":

            min_post_margin,

        "EntryMissingPrevMarkRows":

            len(

                missing_prev

            ),

        "LongInterestTotal":

            float(

                last[

                    "CumLongInterest"

                ]

            ),

        "ShortLendingTotal":

            float(

                last[

                    "CumShortFee"

                ]

            ),

        "TotalFinancingCost":

            float(

                last[

                    "CumFinancingCost"

                ]

            ),

        "Final1557Shares":

            int(

                last[

                    "ETF_Shares"

                ]

            ),

        "Final1557Value":

            float(

                last[

                    "ETF_Value"

                ]

            ),

        "FinalCash":

            float(

                last[

                    "Cash"

                ]

            ),

        "MinimumCash":

            float(

                fix11_daily[

                    "Cash"

                ].min()

            ),

        "NegativeCashDays":

            len(

                negative_days

            ),

        "RecoverySellEvents":

            len(

                recovery_sells

            ),

        "MinimumEODMarginPct":

            float(

                valid_margin[

                    "MarginRatioMTMPct"

                ].min()

            ),

        "Below30Days":

            len(

                below30

            ),

        "Below20Days":

            len(

                below20

            ),

        "Below15Days":

            len(

                below15

            ),

        "MissingEODMarkDays":

            len(

                missing_days

            ),

    }

])

# ============================================================

# 30. 保存

# ============================================================

SUMMARY_PATH = (

    "/content/"

    "stage5_1557_FIX11_ENTRY_MARGIN_summary.csv"

)

DAILY_PATH = (

    "/content/"

    "stage5_1557_FIX11_ENTRY_MARGIN_daily.parquet"

)

ENTRY_PATH = (

    "/content/"

    "stage5_1557_FIX11_ENTRY_MARGIN_entry_audit.parquet"

)

TRADE_PATH = (

    "/content/"

    "stage5_1557_FIX11_ENTRY_MARGIN_trade_audit.parquet"

)

TX_PATH = (

    "/content/"

    "stage5_1557_FIX11_ENTRY_MARGIN_etf_transactions.csv"

)

COMPARE_PATH = (

    "/content/"

    "stage5_1557_FIX10_vs_FIX11_comparison.csv"

)

MARGIN_LIMIT_PATH = (

    "/content/"

    "stage5_1557_FIX11_margin_limited_entries.csv"

)

SKIP_PATH = (

    "/content/"

    "stage5_1557_FIX11_skipped_entries.csv"

)

fix11_summary.to_csv(

    SUMMARY_PATH,

    index=False

)

fix11_daily.to_parquet(

    DAILY_PATH,

    index=False

)

fix11_entry_audit.to_parquet(

    ENTRY_PATH,

    index=False

)

fix11_trade_audit.to_parquet(

    TRADE_PATH,

    index=False

)

fix11_tx.to_csv(

    TX_PATH,

    index=False

)

fix11_comparison.to_csv(

    COMPARE_PATH,

    index=False

)

margin_limited.to_csv(

    MARGIN_LIMIT_PATH,

    index=False

)

skipped.to_csv(

    SKIP_PATH,

    index=False

)

print()

print("=" * 240)

print("保存完了")

print("=" * 240)

print(

    SUMMARY_PATH

)

print(

    DAILY_PATH

)

print(

    ENTRY_PATH

)

print(

    TRADE_PATH

)

print(

    TX_PATH

)

print(

    COMPARE_PATH

)

print(

    MARGIN_LIMIT_PATH

)

print(

    SKIP_PATH

)

print()

print(

    "※ まだDriveには保存していません。"

)

print()

print(

    "★★★★★ STEP23-H-EXACT-FIX11 完了 ★★★★★"

)