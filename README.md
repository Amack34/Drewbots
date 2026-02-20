# Drewbots

Trading bot infrastructure for Kalshi weather prediction markets.

## Structure
- `trading/weather-bot/` — Main trading bot (signal generator, Kalshi API, price monitor, etc.)
- `trading/ntfy_messenger.py` — Bot-to-bot communication via ntfy.sh
- `research/` — Market research, strategy analysis, competitive edge studies
- `tests/` — Validation tests for bot code

## Bots
- **DrewOps** (Brain) — Strategy, execution, automation
- **Worker** (Executor) — Research, testing, monitoring

## Communication
- ntfy.sh topic: `drewops-8e735236-5152-435b-82d7-e20d0b0593de`

## ⚠️ Secrets NOT in repo
- Kalshi API keys → `/root/.secrets.env`
- Private keys → `*.key` (gitignored)
- Database → `weather.db` (gitignored)
