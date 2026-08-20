FROM python:3.11-slim

RUN apt-get update \

    && apt-get install -y --no-install-recommends \

    ca-certificates \

    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY paper_trader.py /app/

RUN pip install --no-cache-dir \

    yfinance \

    pandas \

    numpy

COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
