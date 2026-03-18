import json
import os
import logging
from collections import defaultdict
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

with open("cases.json", "r") as f:
    CASES = json.load(f)

ANSWERING = 1

def build_session():
    return {"case_index": 0, "score": 0, "answers": [], "wrong_categories": defaultdict(int), "total_categories": defaultdict(int)}

def format_case(case, index, total):
    opts = "\n".join(f"{k}) {v}" for k, v in case["options"].items())
    return f"CASE {index + 1} of {total}\nCategory: {case['category']}\n\n{case['vignette']}\n\nQuestion: {case['question']}\n\n{opts}"

def answer_keyboard():
    return ReplyKeyboardMarkup([["A", "B"], ["C", "D"]], resize_keyboard=True, one_time_keyboard=True)

async def start(update, context):
    context.user_data["session"] = build_session()
    session = context.user_data["session"]
    case = CASES[session["case_index"]]
    session["total_categories"][case["category"]] += 1
    await update.message.reply_text(f"Welcome to PharmBot - USMLE Pharmacology Trainer\n\n{len(CASES)} cases. Answer A/B/C/D. Type /stop to end.")
    await update.message.reply_text(format_case(case, session["case_index"], len(CASES)), reply_markup=answer_keyboard())
    return ANSWERING

async def handle_answer(update, context):
    session = context.user_data.get("session")
    if not session:
        await update.message.reply_text("Send /start to begin.")
        return ConversationHandler.END
    user_input = update.message.text.strip().upper()
    if user_input not in ["A", "B", "C", "D"]:
        await update.message.reply_text("Please reply A, B, C or D.", reply_markup=answer_keyboard())
        return ANSWERING
    case = CASES[session["case_index"]]
    correct = case["answer"]
    is_correct = user_input == correct
    session["answers"].append({"case_id": case["id"], "category": case["category"], "user_answer": user_input, "correct_answer": correct, "correct": is_correct})
    if is_correct:
        session["score"] += 1
        msg = f"Correct! Answer: {correct}) {case['options'][correct]}"
    else:
        session["wrong_categories"][case["category"]] += 1
        msg = f"Incorrect. You chose {user_input}. Correct: {correct}) {case['options'][correct]}"
    await update.message.reply_text(f"{msg}\n\nExplanation: {case['explanation']}", reply_markup=ReplyKeyboardRemove())
    session["case_index"] += 1
    if session["case_index"] >= len(CASES):
        await send_summary(update, session)
        return ConversationHandler.END
    nxt = CASES[session["case_index"]]
    session["total_categories"][nxt["category"]] += 1
    await update.message.reply_text(format_case(nxt, session["case_index"], len(CASES)), reply_markup=answer_keyboard())
    return ANSWERING

async def send_summary(update, session):
    total = len(session["answers"])
    score = session["score"]
    pct = round((score / total) * 100) if total else 0
    grade = "Excellent" if pct >= 80 else "Good" if pct >= 60 else "Needs work" if pct >= 40 else "Review required"
    lines = [f"Session Complete!\nScore: {score}/{total} ({pct}%) - {grade}\n\nPerformance by topic:\n"]
    for cat, wrong in sorted(session["wrong_categories"].items(), key=lambda x: -x[1]):
        total_cat = session["total_categories"][cat]
        lines.append(f"{cat}: {total_cat - wrong}/{total_cat} correct\n")
    if not session["wrong_categories"]: lines.append("Perfect score!\n")
    weak = [c for c, w in session["wrong_categories"].items() if w > 0]
    if weak: lines.append(f"\nFocus areas: {', '.join(weak)}")
    lines.append("\n\nType /start for a new session.")
    await update.message.reply_text("".join(lines), reply_markup=ReplyKeyboardRemove())

async def stop(update, context):
    session = context.user_data.get("session")
    if session and session["answers"]: await send_summary(update, session)
    else: await update.message.reply_text("No active session.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token: raise ValueError("BOT_TOKEN not set.")
    app = Application.builder().token(token).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={ANSWERING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer)]},
        fallbacks=[CommandHandler("stop", stop), CommandHandler("cancel", stop)],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.run_polling()

if __name__ == "__main__":
    main()
