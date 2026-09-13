#!/bin/bash

set -e

export TZ=Asia/Tokyo

echo "================================"

echo "Cloud Run Paper Trader START"

date

echo "================================"

cd /app

python paper_trader.py

echo "================================"

echo "Cloud Run Paper Trader END"

date

echo "================================"
