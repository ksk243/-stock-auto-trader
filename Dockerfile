FROM python:3.11-slim

RUN apt-get update \

    && apt-get install -y --no-install-recommends git ca-certificates \

    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir yfinance pandas numpy

WORKDIR /app

COPY . /app

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
