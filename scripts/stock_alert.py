#!/usr/bin/env python3
"""Check a stock price and send a Telegram alert when it is below a threshold."""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
TELEGRAM_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: Decimal
    currency: str
    market_state: str
    source: str


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def decimal_from_env(name: str, default: str) -> Decimal:
    raw_value = env(name, default)
    try:
        return Decimal(str(raw_value))
    except InvalidOperation:
        raise SystemExit(f"{name} must be a valid decimal number, got {raw_value!r}")


def fetch_json(url: str, data: bytes | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "lcid-telegram-stock-alert/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_quote(symbol: str) -> Quote:
    params = urllib.parse.urlencode({"interval": "1m", "range": "1d"})
    url = f"{YAHOO_CHART_URL.format(symbol=urllib.parse.quote(symbol))}?{params}"
    payload = fetch_json(url)

    chart = payload.get("chart", {})
    error = chart.get("error")
    if error:
        raise RuntimeError(f"Quote provider returned an error: {error}")

    result = chart.get("result") or []
    if not result:
        raise RuntimeError(f"No quote data returned for {symbol}")

    meta = result[0].get("meta", {})
    price = meta.get("regularMarketPrice")
    if price is None:
        raise RuntimeError(f"No regularMarketPrice returned for {symbol}")

    return Quote(
        symbol=str(meta.get("symbol") or symbol).upper(),
        price=Decimal(str(price)),
        currency=str(meta.get("currency") or "USD"),
        market_state=str(meta.get("marketState") or "UNKNOWN"),
        source="Yahoo Finance chart API",
    )


def send_telegram_message(token: str, chat_id: str, message: str) -> None:
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    response = fetch_json(TELEGRAM_SEND_MESSAGE_URL.format(token=token), data=data)
    if not response.get("ok"):
        raise RuntimeError(f"Telegram API rejected the message: {response}")


def build_alert_message(quote: Quote, threshold: Decimal) -> str:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"Stock alert: {quote.symbol} is below {threshold} {quote.currency}\n"
        f"Current price: {quote.price} {quote.currency}\n"
        f"Market state: {quote.market_state}\n"
        f"Checked at: {checked_at}\n"
        f"Source: {quote.source}"
    )


def main() -> int:
    symbol = env("STOCK_SYMBOL", "LCID")
    if symbol is None:
        raise SystemExit("STOCK_SYMBOL is required")

    threshold = decimal_from_env("PRICE_THRESHOLD", "5")
    dry_run = env("DRY_RUN", "false").lower() in {"1", "true", "yes"}

    quote = fetch_quote(symbol.upper())
    print(
        f"{quote.symbol} price is {quote.price} {quote.currency}; "
        f"threshold is {threshold} {quote.currency}; market state is {quote.market_state}."
    )

    if quote.price >= threshold:
        print("No alert sent.")
        return 0

    message = build_alert_message(quote, threshold)
    if dry_run:
        print("DRY_RUN enabled. Telegram message would be:")
        print(message)
        return 0

    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required when an alert must be sent."
        )

    send_telegram_message(token, chat_id, message)
    print("Telegram alert sent.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
