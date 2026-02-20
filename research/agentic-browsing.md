# Agentic Browsing: Research Summary

*Feb 15, 2026 — Sources cited inline*

## 1. Product Overview

### Google Project Mariner
A Chrome extension (now available to Google AI Ultra subscribers in the US) that **observes** web elements (text, images, forms), **plans** multi-step actions, and **acts** by navigating and interacting with sites. Example workflows: finding jobs from a resume, ordering groceries from a Drive recipe, hiring a TaskRabbit from an email order. Users can interrupt or take over at any time. Coming to the Gemini API for developer access. **Limitations:** Research prototype; US-only; requires Google AI Ultra subscription; no autonomous purchases (stops at cart). ([deepmind.google/models/project-mariner](https://deepmind.google/models/project-mariner/))

### Microsoft Edge Copilot Mode
An experimental browsing mode in Edge that integrates AI directly into core browsing. Copilot can see your screen (Copilot Vision), summarize pages, compare prices, and streamline workflows. **Copilot Actions** (announced at Ignite 2024) automate recurring tasks like summarizing emails and generating reports across M365. **Limitations:** Feature set varies by device/market/account; enterprise features require IT enablement; less autonomous than Project Mariner — more assistant than agent. ([microsoft.com/edge/copilot](https://www.microsoft.com/en-us/edge/copilot), [Copilot Mode page](https://www.microsoft.com/en-us/edge/copilot-mode))

## 2. Likely Technical Approach

Both products follow a similar architecture:

1. **Perception:** Parse the page via DOM / accessibility tree / screenshot → structured representation of interactive elements.
2. **Planning:** LLM (Gemini for Google, GPT-4+ for Microsoft) receives the page state + user goal → emits a plan as a sequence of actions (click, type, navigate, scroll).
3. **Execution:** Browser control layer (Chrome DevTools Protocol / extension APIs) executes each action; the loop repeats with updated page state.
4. **Guardrails:** Action allow-lists, sensitive-action confirmation prompts, domain restrictions, and human-in-the-loop checkpoints before irreversible operations (purchases, form submissions).

Project Mariner explicitly shows its reasoning trace; Copilot Mode keeps the user "in control" with toggle-able permissions per feature.

## 3. Top 5 Security Risks & Mitigations

| # | Risk | Mitigation |
|---|------|------------|
| 1 | **Prompt injection** — malicious page content hijacks the agent's plan | Separate system/user/page contexts; treat page content as untrusted data; output filtering |
| 2 | **Credential / cookie exfiltration** — agent reads and leaks auth tokens | Least-privilege credential vaulting; never expose raw cookies to LLM; isolated execution context |
| 3 | **Phishing redirects** — agent follows a link to a spoofed login page | Domain allowlists; URL reputation checks; pause on domain changes during auth flows |
| 4 | **Malicious form fill** — agent auto-fills sensitive data into attacker-controlled forms | Sensitive-action confirmation gates; field-type awareness (password, CC#); user approval before submit |
| 5 | **Tool hijacking** — injected instructions cause the agent to misuse browser APIs | Action allow-lists; rate limiting; comprehensive logging + replay for audit |

**Cross-cutting mitigations:** isolated browser profiles, session recording, kill-switch UI, evaluation suites that test adversarial pages.

## 4. How We'd Build It — 3-Step Path

### Step 1: Prototype
- **Stack:** Playwright + LLM (Claude/GPT-4) in a simple observe → plan → act loop.
- **Observe:** Extract accessible DOM tree + screenshot per step.
- **Log everything:** HTML snapshots, screenshots, LLM prompts/responses, actions taken.
- **Goal:** Complete 5 end-to-end tasks (search, fill form, add to cart, read email, compare prices).

### Step 2: Hardening
- **Retries & error recovery:** Classify failures (element-not-found, navigation-timeout, captcha, auth-wall) and route to appropriate handlers.
- **Stable selectors:** Prefer ARIA roles/labels > CSS selectors > XPath; fall back gracefully.
- **Policy engine:** Define per-domain action permissions (read-only vs. interact vs. transact); block sensitive actions without user approval.

### Step 3: Production
- **Credential vaulting:** Integrate with a secrets manager; inject credentials at execution time without LLM visibility.
- **Approval UI:** Human-in-the-loop confirmation for purchases, account changes, and new-domain navigation.
- **Monitoring:** Real-time dashboard of agent sessions; anomaly detection on action patterns.
- **Eval suite:** Adversarial test pages (prompt injection, phishing, hidden fields); task success benchmarks; regression testing.

## 5. Recommended Experiments This Month

1. **Prompt-injection stress test:** Build 10 adversarial web pages with hidden instructions and measure how often our prototype agent is hijacked. Baseline the risk before adding mitigations.

2. **Observe→Plan→Act prototype on 3 real sites:** Implement the Playwright agent loop against Amazon (add to cart), Google Flights (search), and GitHub (create issue). Measure step-success rate and tokens per task.

3. **Selector stability benchmark:** Run the same 5 tasks daily for 2 weeks; track how often selectors break due to site changes. Compare ARIA-based vs. CSS-based vs. vision-based element targeting.
