#!/bin/bash

set -e

cd /app

export TZ=Asia/Tokyo

export RUN_MODE=auto

python paper_trader.py
