#!/bin/bash

set -e

cd /app

export TZ=Asia/Tokyo

export RUN_MODE=auto

python paper_trader.py

git add data/ *.csv 2>/dev/null || true

if ! git diff --cached --quiet; then

    git config user.name "cloud-run-paper-trader"

    git config user.email "cloud-run-paper-trader@users.noreply.github.com"

    git commit -m "Update v33.8 paper trading data"

    git push

else

    echo "No changes"

fi
