# Project Instructions

Build and maintain Telegram-controlled automation bots that run through GitHub Actions.

Bots should use:
- Telegram commands for runtime control.
- GitHub Actions for scheduled, manual, and self-dispatched execution.
- Repository files for durable non-secret configuration.
- GitHub Actions Secrets for credentials.

Security rules:
- Never commit raw tokens, chat IDs, GitHub PATs, API keys, or passwords.
- Store secrets only in GitHub Actions Secrets.
- Use placeholders in docs and prompts.
- If a token was pasted into chat, rotate it in the provider UI before long-term use.

Credential model:
- GitHub owner/account: `jfuenzalidaw`
- GitHub repo example: `jfuenzalidaw/lucid-stock-telegram-alert`
- GitHub Actions runner: `ubuntu-latest`
- Telegram bot username example: `@Stocks_jf_bot`
- Prefer bot-specific GitHub Actions Secrets:
  - `STOCKS_TELEGRAM_BOT_TOKEN`
  - `STOCKS_TELEGRAM_CHAT_ID`
  - `STOCKS_GH_WORKFLOW_PAT`
- Legacy fallback secret names used by the stock bot:
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `GH_WORKFLOW_PAT`

Architecture preferences:
- Python scripts, standard library first.
- No external dependencies unless clearly needed.
- Commands should be idempotent where possible.
- Config should be JSON in the repo.
- Tests should cover command parsing, config migration, and alert behavior.
- Use `python3 -m unittest discover -v` for validation.
- Use GitHub Actions `workflow_dispatch` for manual testing.
- If faster than 5-minute cron is needed, use internal polling or self-dispatch, not unsupported cron syntax.
