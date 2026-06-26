# Lucid Stock Telegram Alert

This GitHub Actions bot checks monitored stock tickers every 30 seconds while its scheduled GitHub Actions run is active, and sends a Telegram message when a latest price is below its configured lower trigger or above its configured upper trigger.

## Setup

1. Create a Telegram bot with BotFather and copy the bot token.
2. Open your bot at `t.me/Stocks_jf_bot` and send `/start` from the Telegram chat where you want alerts.
3. Find your chat id by opening:

   ```text
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```

4. In your GitHub repository, add these repository secrets:

   ```text
   TELEGRAM_BOT_TOKEN
   TELEGRAM_CHAT_ID
   ```

5. Push this repository to GitHub. The workflow is in `.github/workflows/lucid-stock-alert.yml`.

You can also run it manually from GitHub's **Actions** tab with **Run workflow**.

## Telegram commands

Send commands to `t.me/Stocks_jf_bot`. GitHub Actions checks for new commands every five minutes.

```text
/add AAPL
/add AAPL 150 220
/remove AAPL
/setlower LCID 4.50
/setupper LCID 8.00
/clearlower LCID
/clearupper LCID
/prices
/status
```

The default monitored stock is `LCID` with a `$5` lower trigger. Upper triggers are off until you configure them.

The bot validates new tickers by fetching a live quote before saving them. `/prices` and `/status` show current prices for the monitored stocks.

## Local test

Run a dry check without sending Telegram:

```bash
DRY_RUN=true python3 scripts/stock_alert.py
```

To test an actual Telegram message:

```bash
TELEGRAM_BOT_TOKEN="your-token" \
TELEGRAM_CHAT_ID="your-chat-id" \
PRICE_THRESHOLD="999999" \
python3 scripts/stock_alert.py
```

## Configuration

The defaults are:

```text
STOCK_SYMBOL=LCID
LOWER_PRICE_THRESHOLD=5
UPPER_PRICE_THRESHOLD=
```

GitHub scheduled workflows use a five-minute cron because that is GitHub Actions' shortest supported schedule interval. Each scheduled run performs 10 monitoring cycles with 30 seconds between cycles. Runs can still be delayed by GitHub, so this is best for lightweight alerts, not real-time trading automation.
