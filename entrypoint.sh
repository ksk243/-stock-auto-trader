#!/bin/bash

set -e

cd /tmp

rm -rf Stock-auto-trader

git clone "https://${GH_TOKEN}@github.com/ksk243/Stock-auto-trader.git"

cd Stock-auto-trader

git config user.name "cloud-run-paper-trader"

git config user.email "cloud-run-paper-trader@users.noreply.github.com"

export TZ=Asia/Tokyo

export RUN_MODE=auto

python paper_trader.py

git add data/ *.csv 2>/dev/null || true

if ! git diff --cached --quiet; then

    git commit -m "Update v33.8 paper trading data"

    git push

else

    echo "No changes"

fi
