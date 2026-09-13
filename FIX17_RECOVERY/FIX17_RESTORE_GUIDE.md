# FIX17 RESTORE GUIDE

Known-good FIX17 runtime:

Tag:
    FIX17_RUNTIME

Commit:
    dfba056f1e8a86d7f6ee7b9507f16830d9dfaeda

Official source SHA256:
    9598156080b81445e5754c7b0f56138900862e8fd7f35ac89960491bec7222c4


FIX17へ戻す場合:

    git checkout FIX17_RUNTIME


FIX17へ戻したあと売買条件を変更する場合:

最初に:

    FIX17_RECOVERY/FIX17_RULE_INDEX.md

を見る。

過去のDriveや旧FIX11を先に探索しない。

元コード一式は:

    FIX17_FROZEN/

に保存されている。


重要:

FIX17_FROZEN は凍結保存用。

FIX18以降を作る場合も、
このFIX17 recovery packを正式な復元地点として扱う。
