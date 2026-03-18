# PharmBot — USMLE Pharmacology Telegram Bot

A Telegram bot that quizzes pharmacy/medical students on USMLE-style pharmacology cases with A/B/C/D answers, explanations, and a performance summary at the end.

---

## Setup (5 minutes)

### 1. Get a Bot Token
1. Open Telegram → search **@BotFather**
2. Send `/newbot`
3. Follow prompts → name it (e.g. `PharmBot`) and pick a username (e.g. `usmle_pharma_bot`)
4. Copy the token (looks like `7123456789:AAH...`)

### 2. Run Locally (for testing)

```bash
pip install -r requirements.txt
export BOT_TOKEN="your_token_here"
python bot.py
```

---

## Deploy Free on Railway

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
2. Add env variable: `BOT_TOKEN = your_token`
3. Start command: `python bot.py`
4. Done — bot runs 24/7

---

## Adding the Teacher's Cases

Edit `cases.json`. Each case follows this structure:

```json
{
  "id": 16,
  "category": "Cardiovascular",
  "vignette": "A 58-year-old man presents with...",
  "question": "Which drug is most likely responsible?",
  "options": {
    "A": "Drug name",
    "B": "Drug name",
    "C": "Drug name",
    "D": "Drug name"
  },
  "answer": "B",
  "explanation": "Full explanation of why B is correct and others are wrong."
}
```

Just append new objects to the array. No code changes needed.

---

## Bot Commands

| Command | Action |
|---------|--------|
| `/start` | Begin a new quiz session |
| `/stop` | End session and see results |
| `/cancel` | Same as stop |

---

## Features

- 15 real USMLE pharmacology cases (seeded)
- A/B/C/D keyboard buttons for easy answering
- Immediate feedback + explanation after each case
- End-of-session summary: score, topic breakdown, weak areas
- Supports up to 200 cases (plug in teacher's database)
- Stateless per user — each `/start` resets the session
