
IMG_4715.png


貼り付けたマークダウン（1）.md
ファイル


貼り付けたマークダウン（1）(1).md
ファイル


貼り付けたマークダウン（1）(2).md
ファイル

edd70976-ba2c-4504-ac18-a90637d7b886.png
順番が合わない

058dbef3-3f59-4b60-92ce-818b4ef72284.png

3c366351-3720-4f26-8134-5d3e28420d4b.png

b5c751bc-4e63-4345-8364-1575d494c110.png

2a3c60ea-6043-43c1-ac30-347fef4e8638.png


貼り付けたマークダウン（1）(3).md
ファイル

c72b32f8-52eb-4e36-bd3d-875c5b621061.png
動かない

db4094f2-8fa1-439d-8372-9414971d0621.png

e44bc1a9-9c3a-4784-8ba5-799ca89cece0.png

54ef18a8-ddfd-4577-9e9e-3ccab6f05c88.png

804e6f6f-e735-48cb-83a6-b8a6d438293f.png


貼り付けられたテキスト（1 点）.txt
ドキュメント


貼り付けたマークダウン（1）(4).md
ファイル


貼り付けたマークダウン（1）(5).md
ファイル


貼り付けられたテキスト（1 点）(1).txt
ドキュメント

2eb20183-87e2-48eb-863f-c60261eb8935.png
ない


貼り付けられたテキスト（1 点）(2).txt
ドキュメント

8b05deae-0e7e-42d0-a340-b7c4687fc754.png

55d7abb6-11d3-4acb-a623-bc968a0ecb8e.png

40f2e03e-be2d-4e69-af2b-f800345838ae.png
かかりすぎ？

e5706131-0b0e-44e2-8774-a9ee866d7232.png

8313ade0-aadc-4aeb-9a98-3dc67e636cec.png


貼り付けられたテキスト（1 点）(3).txt
ドキュメント

うん。今特定した内容を反映した全文版を出す。

ただ、今こちらで確認できているのは正式4関数と依存定数・ロジックまでで、現在の「3838行版 paper_trader.py」全文そのものは、このターンでは完全な行範囲として取得できていない。ここで全文を推測して作ると、また既存部分を壊す可能性がある。

なので、今使っている3838行版 paper_trader.py をこのチャットに添付して。

受け取ったら、

load_fix17_runtime_module() のDrive依存を除去

calc_entry_time_position_state

calc_long_dynamic_max_positions

calc_margin_capped_qty

calc_target_qty

を、今回特定した正式実装のまま組み込む

ENTRY条件は変更しない

EXITロジックは変更しない

FIX17のsizing/margin/stateロジックも変更しない

部分差し替えではなく、修正済み paper_trader.py 全文

で返す。

正式な calc_target_qty、calc_entry_time_position_state、calc_margin_capped_qty の実装本体までは確認済みです。




貼り付けられたテキスト（1 点）(4).txt
ドキュメント

受け取った。これが現在の 3864行版 paper_trader.py で確認できた。先頭にも「FIX17 official source を single source of truth にする」と明記されている版です。


この版を基準にして、さっき特定した正式4関数を使う形へ直す。部分差し替えではなく、修正反映済み全文で出す。


出して

出しました。アップロードされた最新 3864行版を親にして修正しています。元ファイルはFIX17公式ソースを唯一の基準とし、SHA不一致なら停止する設計です。


修正版 paper_trader.py 全文をダウンロード

今回の修正は、Google Driveの

1srmgAZnbOkYEfj0aQ3QuNUwxz4cBuL6n
を実行時に取りに行って404になる経路を切り、特定済みの正式 sizing / margin runtime を接続しています。

また、正式 calc_margin_capped_qty() の戻り値は AllowedQty が実際の証拠金制限後数量なので、従来の TargetQty を読んでいた接続ミスも修正しています。

Python compile: PASS です。

GitHubではファイル名を paper_trader.py にして全文置き換え → FIX17 Paper Trader Auto をもう一度実行してください。 


paper_trader_FIX17_RUNTIME_FIXED.py
コード


ライブラリ
/
paper_trader_FIX17_RUNTIME_FIXED.py


1
2
3
4
5
6
7
8
9
10
11
12
13
14
15
16
17
18
19
20
21
22
23
24
25
26
27
28
29
30
31
32
33
34
35
36
37
38
39
40
41
42
43
44
45
46
47
48
49
50
51
52
53
54
55
56
57
58
59
60
61
62
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
from mailer import send_error_mail, send_mail
from fix17_contract import validate_fix17_contract

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
