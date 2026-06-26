# Lucid Stock Telegram Alert

This GitHub Actions bot checks Lucid Group stock (`LCID`) every five minutes and sends a Telegram message when the latest price is below `$5`.

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
PRICE_THRESHOLD=5
```

GitHub scheduled workflows use a five-minute cron because that is GitHub Actions' shortest supported schedule interval. Runs can be delayed by GitHub, so this is best for lightweight alerts, not real-time trading automation.
