#!/usr/bin/env python3
"""Check stock prices and send Telegram alerts with Telegram-configured monitors."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"
DEFAULT_CONFIG_PATH = "config/stock_alert.json"
SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,14}")


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: Decimal
    currency: str
    market_state: str
    source: str


@dataclass
class StockMonitor:
    symbol: str
    lower_threshold: Decimal | None = None
    upper_threshold: Decimal | None = None


@dataclass
class AlertConfig:
    stocks: dict[str, StockMonitor] = field(
        default_factory=lambda: {
            "LCID": StockMonitor(symbol="LCID", lower_threshold=Decimal("5")),
        }
    )
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


def normalize_symbol(raw_symbol: str) -> str:
    symbol = raw_symbol.strip().lstrip("$").upper()
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise ValueError("Use a stock ticker like LCID, AAPL, TSLA, or BRK-B.")
    return symbol


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
        raise RuntimeError(f"Quote provider returned an error for {symbol}: {error}")

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
    update_offset = data.get("telegram_update_offset")

    if "stocks" not in data:
        lower = data.get("lower_threshold")
        upper = data.get("upper_threshold")
        symbol = str(data.get("stock_symbol") or "LCID").upper()
        return AlertConfig(
            stocks={
                symbol: StockMonitor(
                    symbol=symbol,
                    lower_threshold=Decimal(str(lower)) if lower is not None else None,
                    upper_threshold=Decimal(str(upper)) if upper is not None else None,
                )
            },
            telegram_update_offset=update_offset,
        )

    stocks: dict[str, StockMonitor] = {}
    for raw_symbol, raw_monitor in dict(data.get("stocks") or {}).items():
        symbol = normalize_symbol(str(raw_symbol))
        lower = raw_monitor.get("lower_threshold")
        upper = raw_monitor.get("upper_threshold")
        stocks[symbol] = StockMonitor(
            symbol=symbol,
            lower_threshold=Decimal(str(lower)) if lower is not None else None,
            upper_threshold=Decimal(str(upper)) if upper is not None else None,
        )

    return AlertConfig(stocks=stocks, telegram_update_offset=update_offset)


def save_config(path: Path, config: AlertConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "stocks": {
            symbol: {
                "lower_threshold": (
                    str(monitor.lower_threshold) if monitor.lower_threshold is not None else None
                ),
                "upper_threshold": (
                    str(monitor.upper_threshold) if monitor.upper_threshold is not None else None
                ),
            }
            for symbol, monitor in sorted(config.stocks.items())
        },
        "telegram_update_offset": config.telegram_update_offset,
    }
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def format_trigger(value: Decimal | None) -> str:
    return str(value) if value is not None else "off"


def format_monitor_line(monitor: StockMonitor, quote: Quote | None = None) -> str:
    price = f"{quote.price} {quote.currency}" if quote else "price unavailable"
    return (
        f"{monitor.symbol}: {price}; "
        f"lower {format_trigger(monitor.lower_threshold)}; "
        f"upper {format_trigger(monitor.upper_threshold)}"
    )


def fetch_monitored_quotes(
    config: AlertConfig,
    quote_fetcher: Callable[[str], Quote],
) -> tuple[dict[str, Quote], dict[str, str]]:
    quotes: dict[str, Quote] = {}
    errors: dict[str, str] = {}
    for symbol in sorted(config.stocks):
        try:
            quotes[symbol] = quote_fetcher(symbol)
        except Exception as exc:
            errors[symbol] = str(exc)
    return quotes, errors


def build_prices_message(
    config: AlertConfig,
    quote_fetcher: Callable[[str], Quote] = fetch_quote,
    include_commands: bool = False,
) -> str:
    if not config.stocks:
        return "No stocks are currently monitored. Use /add LCID to add one."

    quotes, errors = fetch_monitored_quotes(config, quote_fetcher)
    lines = ["Monitored stock prices:"]
    for symbol, monitor in sorted(config.stocks.items()):
        lines.append(format_monitor_line(monitor, quotes.get(symbol)))
        if symbol in errors:
            lines.append(f"{symbol}: quote error: {errors[symbol]}")

    if include_commands:
        lines.extend(
            [
                "",
                "Commands:",
                "/add AAPL",
                "/add AAPL 150 220",
                "/remove AAPL",
                "/setlower AAPL 150",
                "/setupper AAPL 220",
                "/prices",
                "/status",
            ]
        )
    return "\n".join(lines)


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


def parse_add_args(arg: str) -> tuple[str, Decimal | None, Decimal | None] | str:
    parts = arg.split()
    if not 1 <= len(parts) <= 3:
        return "Usage: /add AAPL or /add AAPL 150 220"

    try:
        symbol = normalize_symbol(parts[0])
        lower = parse_decimal(parts[1], "Lower trigger") if len(parts) >= 2 else None
        upper = parse_decimal(parts[2], "Upper trigger") if len(parts) >= 3 else None
    except ValueError as exc:
        return str(exc)

    if lower is not None and upper is not None and lower >= upper:
        return "Lower trigger must be below the upper trigger."
    return symbol, lower, upper


def symbol_from_arg(config: AlertConfig, arg: str, command: str) -> tuple[str | None, str | None]:
    if arg:
        try:
            symbol = normalize_symbol(arg.split()[0])
        except ValueError as exc:
            return None, str(exc)
        if symbol not in config.stocks:
            return None, f"{symbol} is not monitored. Use /add {symbol} first."
        return symbol, None

    if len(config.stocks) == 1:
        return next(iter(config.stocks)), None
    return None, f"Usage: {command} SYMBOL"


def symbol_and_value_from_arg(
    config: AlertConfig,
    arg: str,
    command: str,
) -> tuple[str | None, Decimal | None, str | None]:
    parts = arg.split()
    if len(parts) == 1 and len(config.stocks) == 1:
        symbol = next(iter(config.stocks))
        raw_value = parts[0]
    elif len(parts) == 2:
        try:
            symbol = normalize_symbol(parts[0])
        except ValueError as exc:
            return None, None, str(exc)
        raw_value = parts[1]
    else:
        return None, None, f"Usage: {command} SYMBOL PRICE"

    if symbol not in config.stocks:
        return None, None, f"{symbol} is not monitored. Use /add {symbol} first."

    try:
        value = parse_decimal(raw_value, "Trigger")
    except ValueError as exc:
        return None, None, str(exc)
    return symbol, value, None


def update_config_from_command(
    config: AlertConfig,
    text: str,
    quote_fetcher: Callable[[str], Quote] = fetch_quote,
) -> str:
    command, arg = normalize_command(text)

    if command in {"/start", "/help", "/status", "/list"}:
        return build_prices_message(config, quote_fetcher, include_commands=True)

    if command == "/prices":
        return build_prices_message(config, quote_fetcher)

    if command in {"/add", "/addstock"}:
        parsed = parse_add_args(arg)
        if isinstance(parsed, str):
            return parsed
        symbol, lower, upper = parsed
        try:
            quote = quote_fetcher(symbol)
        except Exception:
            return f"I could not find a live quote for {symbol}. Check the ticker and try again."

        canonical_symbol = normalize_symbol(quote.symbol)
        config.stocks[canonical_symbol] = StockMonitor(
            symbol=canonical_symbol,
            lower_threshold=lower,
            upper_threshold=upper,
        )
        return (
            f"Added {canonical_symbol} at {quote.price} {quote.currency}.\n"
            f"Lower trigger: {format_trigger(lower)}\n"
            f"Upper trigger: {format_trigger(upper)}"
        )

    if command in {"/remove", "/delete", "/removestock", "/deletestock"}:
        symbol, error = symbol_from_arg(config, arg, "/remove")
        if error:
            return error
        assert symbol is not None
        del config.stocks[symbol]
        return f"Removed {symbol} from monitoring."

    if command == "/setlower":
        symbol, value, error = symbol_and_value_from_arg(config, arg, "/setlower")
        if error:
            return error
        assert symbol is not None and value is not None
        monitor = config.stocks[symbol]
        if monitor.upper_threshold is not None and value >= monitor.upper_threshold:
            return "Lower trigger must be below the upper trigger."
        monitor.lower_threshold = value
        return f"{symbol} lower trigger set to {value}."

    if command == "/setupper":
        symbol, value, error = symbol_and_value_from_arg(config, arg, "/setupper")
        if error:
            return error
        assert symbol is not None and value is not None
        monitor = config.stocks[symbol]
        if monitor.lower_threshold is not None and value <= monitor.lower_threshold:
            return "Upper trigger must be above the lower trigger."
        monitor.upper_threshold = value
        return f"{symbol} upper trigger set to {value}."

    if command == "/clearlower":
        symbol, error = symbol_from_arg(config, arg, "/clearlower")
        if error:
            return error
        assert symbol is not None
        config.stocks[symbol].lower_threshold = None
        return f"{symbol} lower trigger cleared."

    if command == "/clearupper":
        symbol, error = symbol_from_arg(config, arg, "/clearupper")
        if error:
            return error
        assert symbol is not None
        config.stocks[symbol].upper_threshold = None
        return f"{symbol} upper trigger cleared."

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


def config_snapshot(config: AlertConfig) -> tuple[tuple[Any, ...], ...]:
    stock_items = tuple(
        (symbol, monitor.lower_threshold, monitor.upper_threshold)
        for symbol, monitor in sorted(config.stocks.items())
    )
    return stock_items + (("telegram_update_offset", config.telegram_update_offset),)


def effective_config(config: AlertConfig) -> AlertConfig:
    symbol = env("STOCK_SYMBOL")
    lower = optional_decimal_from_env("LOWER_PRICE_THRESHOLD")
    if lower is None:
        lower = optional_decimal_from_env("PRICE_THRESHOLD")
    upper = optional_decimal_from_env("UPPER_PRICE_THRESHOLD")

    if symbol is None and lower is None and upper is None:
        return config

    selected_symbol = normalize_symbol(symbol or "LCID")
    existing = config.stocks.get(selected_symbol, StockMonitor(symbol=selected_symbol))
    return AlertConfig(
        stocks={
            selected_symbol: StockMonitor(
                symbol=selected_symbol,
                lower_threshold=lower if lower is not None else existing.lower_threshold,
                upper_threshold=upper if upper is not None else existing.upper_threshold,
            )
        },
        telegram_update_offset=config.telegram_update_offset,
    )


def find_alert(quote: Quote, monitor: StockMonitor) -> tuple[str, Decimal] | None:
    if monitor.lower_threshold is not None and quote.price < monitor.lower_threshold:
        return "below", monitor.lower_threshold
    if monitor.upper_threshold is not None and quote.price > monitor.upper_threshold:
        return "above", monitor.upper_threshold
    return None


def validate_config(config: AlertConfig) -> None:
    for symbol, monitor in config.stocks.items():
        normalize_symbol(symbol)
        if (
            monitor.lower_threshold is not None
            and monitor.upper_threshold is not None
            and monitor.lower_threshold >= monitor.upper_threshold
        ):
            raise SystemExit(f"{symbol}: lower trigger must be below upper trigger")


def check_stock_alerts(config: AlertConfig) -> tuple[list[str], list[str]]:
    alert_messages: list[str] = []
    log_lines: list[str] = []

    if not config.stocks:
        return [], ["No stocks are currently monitored."]

    for symbol, monitor in sorted(config.stocks.items()):
        try:
            quote = fetch_quote(symbol)
        except Exception as exc:
            log_lines.append(f"{symbol}: quote error: {exc}")
            continue

        log_lines.append(
            f"{quote.symbol} price is {quote.price} {quote.currency}; "
            f"lower trigger is {monitor.lower_threshold}; "
            f"upper trigger is {monitor.upper_threshold}; "
            f"market state is {quote.market_state}."
        )

        alert = find_alert(quote, monitor)
        if alert is not None:
            direction, threshold = alert
            alert_messages.append(build_alert_message(quote, direction, threshold))

    return alert_messages, log_lines


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

    alert_messages, log_lines = check_stock_alerts(config)
    for line in log_lines:
        print(line)

    if not alert_messages:
        print("No alert sent.")
        return 0

    message = "\n\n".join(alert_messages)
    if dry_run:
        print("DRY_RUN enabled. Telegram message would be:")
        print(message)
        return 0

    if not token or not chat_id:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required when an alert must be sent."
        )

    send_telegram_message(token, chat_id, message)
    print(f"Telegram alert sent for {len(alert_messages)} stock(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
