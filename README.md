# Varje Dag Svenska – Telegram automation

This repository generates and publishes a new Swedish B2–C1 learning package every day at about 06:00 Europe/Stockholm.

## What it publishes
- 15 vocabulary items with Persian translation
- 9 expressions/idioms
- one B2–C1 grammar topic
- reading comprehension + questions + answers
- 8–10 minute two-voice Swedish podcast
- PDF with learning material and podcast script
- Telegram post to `@varjedagsvenska`

## Required GitHub Secrets
Go to:
Settings → Secrets and variables → Actions → New repository secret

Create:
1. `OPENAI_API_KEY`
2. `TELEGRAM_BOT_TOKEN`

Do NOT put these secrets inside the code.

## First test
Go to:
Actions → Daily Swedish B2-C1 Package → Run workflow

For a manual test outside 06:00, temporarily add `FORCE_RUN: "1"` under the workflow's `env:` section,
run once, then remove it. Alternatively run locally with FORCE_RUN=1.

## Scheduling
GitHub Actions uses UTC. The workflow starts at both 04:07 and 05:07 UTC.
`main.py` checks `Europe/Stockholm`, so only the run that occurs during local 06:xx publishes.
This automatically handles Swedish summer/winter time.
