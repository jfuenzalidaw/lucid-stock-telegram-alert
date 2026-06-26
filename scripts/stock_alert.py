#!/usr/bin/env python3
"""Check a stock price and send Telegram alerts with Telegram-configured thresholds."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_CONFIG_PATH = "config/stock_alert.json"


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: Decimal
    currency: str
    market_state: str
    source: str


@dataclass
class AlertConfig:
    stock_symbol: str = "LCID"
    lower_threshold: Decimal | None = Decimal("5")
    upper_threshold: Decimal | None = None
    telegram_update_offset: int | None = None


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def parse_decimal(value: str, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"{field_name} must be a valid decimal number")


def optional_decimal_from_env(name: str) -> Decimal | None:
    raw_value = env(name)
    if raw_value is None:
        return None
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


def telegram_api(token: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    if params is not None:
        data = urllib.parse.urlencode(params).encode("utf-8")
    response = fetch_json(TELEGRAM_API_URL.format(token=token, method=method), data=data)
    if not response.get("ok"):
        raise RuntimeError(f"Telegram API call {method} failed: {response}")
    return response


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
    telegram_api(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "true",
        },
    )


def load_config(path: Path) -> AlertConfig:
    if not path.exists():
        return AlertConfig()

    data = json.loads(path.read_text(encoding="utf-8"))
    lower = data.get("lower_threshold")
    upper = data.get("upper_threshold")
    return AlertConfig(
        stock_symbol=str(data.get("stock_symbol") or "LCID").upper(),
        lower_threshold=Decimal(str(lower)) if lower is not None else None,
        upper_threshold=Decimal(str(upper)) if upper is not None else None,
        telegram_update_offset=data.get("telegram_update_offset"),
    )


def save_config(path: Path, config: AlertConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "stock_symbol": config.stock_symbol,
        "lower_threshold": str(config.lower_threshold) if config.lower_threshold is not None else None,
        "upper_threshold": str(config.upper_threshold) if config.upper_threshold is not None else None,
        "telegram_update_offset": config.telegram_update_offset,
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_status_message(config: AlertConfig) -> str:
    lower = config.lower_threshold if config.lower_threshold is not None else "off"
    upper = config.upper_threshold if config.upper_threshold is not None else "off"
    return (
        f"{config.stock_symbol} alert settings\n"
        f"Lower trigger: {lower}\n"
        f"Upper trigger: {upper}\n\n"
        "Commands:\n"
        "/setlower 4.50\n"
        "/setupper 8.00\n"
        "/clearlower\n"
        "/clearupper\n"
        "/status"
    )


def build_alert_message(quote: Quote, direction: str, threshold: Decimal) -> str:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"Stock alert: {quote.symbol} is {direction} {threshold} {quote.currency}\n"
        f"Current price: {quote.price} {quote.currency}\n"
        f"Market state: {quote.market_state}\n"
        f"Checked at: {checked_at}\n"
        f"Source: {quote.source}"
    )


def normalize_command(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    command = parts[0].split("@", maxsplit=1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return command, arg


def update_config_from_command(config: AlertConfig, text: str) -> str:
    command, arg = normalize_command(text)

    if command in {"/start", "/help", "/status"}:
        return build_status_message(config)

    if command == "/setlower":
        if not arg:
            return "Usage: /setlower 4.50"
        try:
            value = parse_decimal(arg, "Lower trigger")
        except ValueError as exc:
            return str(exc)
        if config.upper_threshold is not None and value >= config.upper_threshold:
            return "Lower trigger must be below the upper trigger."
        config.lower_threshold = value
        return f"Lower trigger set to {value}."

    if command == "/setupper":
        if not arg:
            return "Usage: /setupper 8.00"
        try:
            value = parse_decimal(arg, "Upper trigger")
        except ValueError as exc:
            return str(exc)
        if config.lower_threshold is not None and value <= config.lower_threshold:
            return "Upper trigger must be above the lower trigger."
        config.upper_threshold = value
        return f"Upper trigger set to {value}."

    if command == "/clearlower":
        config.lower_threshold = None
        return "Lower trigger cleared."

    if command == "/clearupper":
        config.upper_threshold = None
        return "Upper trigger cleared."

    if command.startswith("/"):
        return "Unknown command. Send /status to see available commands."

    return ""


def fetch_telegram_updates(token: str, offset: int | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": 0, "allowed_updates": json.dumps(["message"])}
    if offset is not None:
        params["offset"] = offset
    response = telegram_api(token, "getUpdates", params)
    return list(response.get("result") or [])


def process_telegram_commands(
    token: str,
    chat_id: str,
    config: AlertConfig,
    dry_run: bool,
) -> bool:
    updates = fetch_telegram_updates(token, config.telegram_update_offset)
    changed = False

    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = update_id + 1
            if config.telegram_update_offset != next_offset:
                config.telegram_update_offset = next_offset
                changed = True

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if str(chat.get("id")) != str(chat_id):
            continue

        text = str(message.get("text") or "").strip()
        if not text:
            continue

        before = config_snapshot(config)
        reply = update_config_from_command(config, text)
        if config_snapshot(config) != before:
            changed = True
        if reply and not dry_run:
            send_telegram_message(token, chat_id, reply)
            print(f"Processed Telegram command: {normalize_command(text)[0]}")

    return changed


def config_snapshot(config: AlertConfig) -> tuple[str, Decimal | None, Decimal | None, int | None]:
    return (
        config.stock_symbol,
        config.lower_threshold,
        config.upper_threshold,
        config.telegram_update_offset,
    )


def effective_config(config: AlertConfig) -> AlertConfig:
    symbol = env("STOCK_SYMBOL", config.stock_symbol)
    lower = optional_decimal_from_env("LOWER_PRICE_THRESHOLD")
    if lower is None:
        lower = optional_decimal_from_env("PRICE_THRESHOLD")
    upper = optional_decimal_from_env("UPPER_PRICE_THRESHOLD")

    return AlertConfig(
        stock_symbol=(symbol or config.stock_symbol).upper(),
        lower_threshold=lower if lower is not None else config.lower_threshold,
        upper_threshold=upper if upper is not None else config.upper_threshold,
        telegram_update_offset=config.telegram_update_offset,
    )


def find_alert(quote: Quote, config: AlertConfig) -> tuple[str, Decimal] | None:
    if config.lower_threshold is not None and quote.price < config.lower_threshold:
        return "below", config.lower_threshold
    if config.upper_threshold is not None and quote.price > config.upper_threshold:
        return "above", config.upper_threshold
    return None


def validate_config(config: AlertConfig) -> None:
    if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", config.stock_symbol):
        raise SystemExit(f"Invalid STOCK_SYMBOL: {config.stock_symbol!r}")
    if (
        config.lower_threshold is not None
        and config.upper_threshold is not None
        and config.lower_threshold >= config.upper_threshold
    ):
        raise SystemExit("Lower trigger must be below upper trigger")


def main() -> int:
    dry_run = env("DRY_RUN", "false").lower() in {"1", "true", "yes"}
    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    config_path = Path(env("CONFIG_PATH", DEFAULT_CONFIG_PATH) or DEFAULT_CONFIG_PATH)

    stored_config = load_config(config_path)
    if token and chat_id:
        if process_telegram_commands(token, chat_id, stored_config, dry_run):
            save_config(config_path, stored_config)

    config = effective_config(stored_config)
    validate_config(config)

    quote = fetch_quote(config.stock_symbol)
    print(
        f"{quote.symbol} price is {quote.price} {quote.currency}; "
        f"lower trigger is {config.lower_threshold}; upper trigger is {config.upper_threshold}; "
        f"market state is {quote.market_state}."
    )

    alert = find_alert(quote, config)
    if alert is None:
        print("No alert sent.")
        return 0

    direction, threshold = alert
    message = build_alert_message(quote, direction, threshold)
    if dry_run:
        print("DRY_RUN enabled. Telegram message would be:")
        print(message)
        return 0

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
