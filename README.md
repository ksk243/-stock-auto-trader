# FIX17 Stock Auto Trader

## Official FIX17

File:
FIX17_OFFICIAL_FULL_SOURCE.py

Drive ID:
1vEUHcDrW7Bi-JUiKzu9C5n_AexKKPMji

SHA256:
9598156080b81445e5754c7b0f56138900862e8fd7f35ac89960491bec7222c4

Parent:
FIX16_OFFICIAL_FULL_SOURCE.py

Parent SHA256:
fa9cad62f446feeed6478d283d6f06bca25ff4e3d073693c614081a752a9aca8

## FIX17 change

FIX16:
target_notional = min(LONG_CAP_PER_STOCK, long_remaining_capacity)

FIX17:
target_notional = long_remaining_capacity

Rule:
REMOVE_FIXED_LONG_PER_STOCK_CAP

## Jobs

paper_trader.py
- ペーパートレーダー専用
- 1分足保存とは独立
- 通常メールは夕方のみ
- 異常時は即時メール

save_1m.py
- 1分足保存専用
- ペーパートレーダーとは独立
- 正常時メールなし
- 保存失敗時は即時メール

## Important

FIX17正式ロジックを勝手に再構築しない。
正式ソースは FIX17_OFFICIAL_FULL_SOURCE.py。
