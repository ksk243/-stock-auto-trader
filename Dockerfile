FROM python:3.11-slim

RUN apt-get update \

    && apt-get install -y --no-install-recommends \

    ca-certificates \

    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \

    yfinance \

    pandas \

    numpy \

    google-cloud-storage

WORKDIR /app

COPY paper_trader.py /app/paper_trader.py

COPY entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
