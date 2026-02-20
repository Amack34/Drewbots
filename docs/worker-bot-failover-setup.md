# Worker Bot LLM Failover Setup Guide

*Last updated: Feb 20, 2026*

## Current Working Config (Worker Bot @ 66.228.60.51)

- **Primary**: `anthropic/claude-sonnet-4-5` (Pro plan, $20/mo)
- **Fallback**: `google/gemini-3-flash-preview` (free, 1500 req/day)
- **OpenClaw version**: v2026.2.19-2

## Critical Lesson: Check the Model Registry First!

OpenClaw only works with models registered in its internal registry. Before configuring ANY provider:

```bash
# List all known model IDs
grep -oP 'id: "[^"]+"' /usr/lib/node_modules/openclaw/dist/model-auth-*.js | sort -u

# Check if a specific model exists
grep 'mistral-large' /usr/lib/node_modules/openclaw/dist/model-auth-*.js
```

**v2026.2.19-2 known models include:**
- `anthropic/claude-sonnet-4-5`, `anthropic/claude-haiku-3-5`
- `google/gemini-3-flash-preview`, `google/gemini-3-pro-preview`
- `openai/gpt-4o`, `openai/gpt-4o-mini`
- `groq/llama-3.3-70b`
- `mistral-31-24b` (Venice provider only — NOT `mistral/mistral-large-latest`)

**`mistral/mistral-large-latest` is NOT in the registry.** Don't use it.

## Setup Steps (Proven Working)

### 1. Get API Keys

**Anthropic** (paid): Already have token from Pro plan OAuth
**Google Gemini** (free): https://aistudio.google.com/apikey → Create API Key

### 2. Configure openclaw.json

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "anthropic/claude-sonnet-4-5",
        "fallbacks": ["google/gemini-3-flash-preview"]
      }
    }
  },
  "env": {
    "GEMINI_API_KEY": "<your-gemini-key>"
  }
}
```

### 3. Configure auth-profiles.json

Location: `~/.openclaw/agents/main/agent/auth-profiles.json`

```json
{
  "version": 1,
  "profiles": {
    "anthropic:manual": {
      "type": "token",
      "provider": "anthropic",
      "token": "<anthropic-oauth-token>"
    },
    "google:default": {
      "type": "token",
      "provider": "google",
      "token": "<gemini-api-key>"
    }
  },
  "lastGood": {},
  "usageStats": {}
}
```

### 4. Restart Gateway

```bash
systemctl --user restart openclaw-gateway
# Verify
journalctl --user -u openclaw-gateway -n 10 --no-pager | grep "agent model"
```

Should show: `agent model: anthropic/claude-sonnet-4-5`

### 5. Verify Failover Works

When Claude hits rate limits, OpenClaw automatically fails over to Gemini. Check with:
```bash
journalctl --user -u openclaw-gateway --no-pager | grep -i "failover\|fallback\|gemini"
```

## What NOT to Do

1. **Don't use `mistral/mistral-large-latest`** — not in model registry
2. **Don't add `thinking` key to `agents.defaults`** — invalid config, crashes gateway
3. **Don't use `openai/` prefix for non-OpenAI APIs** — "Unknown model" error
4. **Don't forget auth-profiles.json** — openclaw.json `env` block alone is NOT sufficient
5. **Don't assume curl working = OpenClaw working** — OpenClaw has its own model registry

## Troubleshooting

### "Unknown model: X"
Model not in OpenClaw registry. Check with grep command above.

### "rate_limit" but curl works fine
Either: (a) model not actually supported, (b) cooldown cached in `usageStats`, (c) wrong auth profile format.
Fix: Clear `usageStats` in auth-profiles.json, restart gateway.

### Config invalid errors
Run `openclaw doctor --fix` to identify bad keys. Common: `thinking` in agents.defaults.

## Free Tier Providers (v2026.2.19-2)

| Provider | Free Tier | Best Model |
|----------|-----------|------------|
| Google Gemini | 1500 req/day | `google/gemini-3-flash-preview` |
| Groq | ~1000 req/day | `groq/llama-3.3-70b` |
| OpenRouter | Some free models | Various |
| Together | Free trial | Llama models |

## Files Modified

- `~/.openclaw/openclaw.json` — model config + env vars
- `~/.openclaw/agents/main/agent/auth-profiles.json` — API credentials
- Systemd env override (optional): `~/.config/systemd/user/openclaw-gateway.service.d/`
