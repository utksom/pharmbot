import json, os, logging, random
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(level=logging.INFO)

with open("cases.json") as f:
    CASES = json.load(f)

STATS_FILE = "stats.json"
ADMIN_FILE = "admins.json"
PENDING_FILE = "pending_cases.json"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "pharma2024")

ANSWERING, CHOOSING_CATEGORY = 1, 2
ACV, ACQ, ACO, ACA, ACE, ACC = 10, 11, 12, 13, 14, 15

TIPS = {
    "Cardiovascular": "ACE inhibitor vs ARB: dry cough is ACE inhibitor only. Bradykinin accumulation. ARBs skip that pathway.",
    "Cardiology": "Amiodarone toxicity: thyroid (hypo and hyper), pulmonary fibrosis, hepatotoxicity, corneal deposits, photosensitivity.",
    "Endocrine": "SGLT-2 causes genital mycotic infections via glucosuria. Metformin depletes B12 over years, monitor annually.",
    "Pulmonology": "Inhaled corticosteroids cause oral candidiasis. Fix: rinse mouth after every dose.",
    "Psychiatry": "EPS timeline: acute dystonia (hours), akathisia (days), parkinsonism (weeks), tardive dyskinesia (months+). Benztropine only for first three.",
    "Nephrology": "Lithium nephrogenic DI: lithium blocks adenylyl cyclase so ADH cannot insert aquaporins. Desmopressin has no effect.",
    "Hematology": "Warfarin raised by CYP2C9 inhibitors: fluconazole, metronidazole, amiodarone. Rifampin lowers it.",
    "Gastroenterology": "Disulfiram-like reaction: metronidazole + alcohol. ALDH blocked, acetaldehyde accumulates.",
    "Neurology": "INH inhibits CYP2C9, initially raises phenytoin. Monitor levels when starting TB therapy.",
    "Infectious Disease": "G6PD triggers: primaquine, dapsone, nitrofurantoin, sulfonamides, rasburicase. Heinz bodies on smear.",
    "Pharmacology": "Cholinergic toxidrome = SLUDGE + bradycardia + miosis. Atropine + pralidoxime (give pralidoxime early).",
    "Obstetrics": "Safe in pregnancy: LMWH only. Warfarin causes embryopathy weeks 6-12. DOACs contraindicated throughout.",
}


def load_json(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def save_json(path, data):
    json.dump(data, open(path, "w"), indent=2)


def is_admin(uid):
    return str(uid) in [str(a) for a in load_json(ADMIN_FILE, [])]


def get_all_cases():
    pending = load_json(PENDING_FILE, [])
    return CASES + [c for c in pending if c.get("approved")]


def build_session(cases=None):
    return {
        "case_index": 0, "score": 0, "answers": [],
        "wrong_categories": defaultdict(int),
        "total_categories": defaultdict(int),
        "cases": cases or get_all_cases(),
        "paused": False,
    }


def fmt_case(case, i, total, timed=False):
    opts = "\n".join(f"{k}) {v}" for k, v in case["options"].items())
    t = "\n(90 seconds per question)" if timed else ""
    return f"CASE {i+1} of {total} - {case['category']}{t}\n\n{case['vignette']}\n\n{case['question']}\n\n{opts}"


def ans_kb():
    return ReplyKeyboardMarkup([["A","B"],["C","D"],["Hint","Pause"]], resize_keyboard=True, one_time_keyboard=False)


def make_remarks(session, ustats):
    answers = session["answers"]
    total = len(answers)
    score = session["score"]
    pct = round(score/total*100) if total else 0
    wrong_cats = defaultdict(int)
    cat_totals = defaultdict(int)
    for a in answers:
        cat_totals[a["category"]] += 1
        if not a["correct"]:
            wrong_cats[a["category"]] += 1
    lines = []
    if pct == 100:
        lines.append("Perfect session. Every case correct.")
    elif pct >= 80:
        lines.append(str(pct) + "% - above the USMLE passing threshold.")
    elif pct >= 60:
        lines.append(str(pct) + "% - passing range, a few areas to tighten.")
    elif pct >= 40:
        lines.append(str(pct) + "% - below threshold. Use this as a diagnostic.")
    else:
        lines.append(str(pct) + "% - rough session. One more will tell you more.")
    if wrong_cats:
        worst_cat, worst_n = sorted(wrong_cats.items(), key=lambda x: -x[1])[0]
        lines.append("")
        lines.append("Weakest area: " + worst_cat + " - " + str(worst_n) + "/" + str(cat_totals[worst_cat]) + " wrong.")
        if worst_cat in TIPS:
            lines.append(TIPS[worst_cat])
    aq = ustats.get("total_questions", 0)
    ac = ustats.get("total_correct", 0)
    if aq > 0 and ustats.get("sessions", 0) > 1:
        ap = round(ac/aq*100)
        if pct > ap+5:
            lines.append("")
            lines.append("This session (" + str(pct) + "%) beat your average (" + str(ap) + "%). Trending up.")
        elif pct < ap-5:
            lines.append("")
            lines.append("Below your usual (" + str(ap) + "%). Off session, happens.")
    streak = ustats.get("streak", 0)
    if streak >= 2:
        lines.append("")
        lines.append(str(streak) + "-day streak. Consistency beats cramming.")
    return "\n".join(lines)


def update_stats(uid, session, username=""):
    stats = load_json(STATS_FILE, {})
    uid = str(uid)
    u = stats.get(uid, {
        "username": username, "sessions": 0, "total_correct": 0, "total_questions": 0,
        "category_correct": {}, "category_total": {}, "case_wrong": {},
        "streak": 0, "last_active": "", "badges": []
    })
    if username:
        u["username"] = username
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
    if u.get("last_active") == yesterday:
        u["streak"] = u.get("streak", 0) + 1
    elif u.get("last_active") != today:
        u["streak"] = 1
    u["last_active"] = today
    u["sessions"] = u.get("sessions", 0) + 1
    u["total_correct"] = u.get("total_correct", 0) + session["score"]
    u["total_questions"] = u.get("total_questions", 0) + len(session["answers"])
    cc = u.get("category_correct", {})
    ct = u.get("category_total", {})
    cw = u.get("case_wrong", {})
    for a in session["answers"]:
        cat = a["category"]
        ct[cat] = ct.get(cat, 0) + 1
        if a["correct"]:
            cc[cat] = cc.get(cat, 0) + 1
        else:
            cw[str(a["case_id"])] = cw.get(str(a["case_id"]), 0) + 1
    u["category_correct"] = cc
    u["category_total"] = ct
    u["case_wrong"] = cw
    b = u.get("badges", [])
    if u["sessions"] == 1 and "First Session" not in b:
        b.append("First Session")
    if u["total_correct"] >= 50 and "50 Correct" not in b:
        b.append("50 Correct")
    if u["total_correct"] >= 100 and "100 Correct" not in b:
        b.append("100 Correct")
    if session["score"] == len(session["answers"]) and len(session["answers"]) >= 5 and "Perfect Score" not in b:
        b.append("Perfect Score")
    if u.get("streak", 0) >= 3 and "3-Day Streak" not in b:
        b.append("3-Day Streak")
    if u.get("streak", 0) >= 7 and "Week Streak" not in b:
        b.append("Week Streak")
    u["badges"] = b
    stats[uid] = u
    save_json(STATS_FILE, stats)
    return u


async def start(update, context):
    uid = update.effective_user.id
    kb = [
        [InlineKeyboardButton("Full Quiz", callback_data="mode_full"), InlineKeyboardButton("Quick Drill (10)", callback_data="mode_quick")],
        [InlineKeyboardButton("By Category", callback_data="mode_category"), InlineKeyboardButton("Retry Wrong", callback_data="mode_retry")],
        [InlineKeyboardButton("Timed Mode (90s)", callback_data="mode_timed")],
    ]
    if is_admin(uid):
        kb.append([InlineKeyboardButton("Admin Panel", callback_data="admin_panel")])
    total = len(get_all_cases())
    await update.message.reply_text(
        "PharmBot - USMLE Pharmacology\n\n" + str(total) + " cases loaded. Pick a mode:",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return ANSWERING


async def handle_mode(update, context):
    q = update.callback_query
    await q.answer()
    d = q.data
    all_cases = get_all_cases()

    if d == "admin_panel":
        if not is_admin(q.from_user.id):
            await q.edit_message_text("Access denied.")
            return ConversationHandler.END
        kb = [
            [InlineKeyboardButton("Add Case", callback_data="admin_addcase")],
            [InlineKeyboardButton("Class Stats", callback_data="admin_stats")],
            [InlineKeyboardButton("Approve Cases", callback_data="admin_approve")],
        ]
        await q.edit_message_text("Admin Panel", reply_markup=InlineKeyboardMarkup(kb))
        return ANSWERING

    if d == "admin_stats":
        if not is_admin(q.from_user.id):
            await q.edit_message_text("Access denied.")
            return ANSWERING
        stats = load_json(STATS_FILE, {})
        cwa = defaultdict(int)
        for u in stats.values():
            for cid, cnt in u.get("case_wrong", {}).items():
                cwa[cid] += cnt
        hardest = sorted(cwa.items(), key=lambda x: -x[1])[:5]
        lines = ["Class Stats\n\nUsers: " + str(len(stats)) + "\nSessions: " + str(sum(u.get("sessions",0) for u in stats.values())) + "\n\nHardest cases:\n"]
        for cid, cnt in hardest:
            case = next((c for c in all_cases if str(c["id"]) == cid), None)
            if case:
                lines.append("Case " + cid + " (" + case["category"] + "): " + str(cnt) + " wrong\n")
        await q.edit_message_text("".join(lines))
        return ANSWERING

    if d == "admin_approve":
        if not is_admin(q.from_user.id):
            await q.edit_message_text("Access denied.")
            return ANSWERING
        pending = load_json(PENDING_FILE, [])
        unapproved = [c for c in pending if not c.get("approved")]
        if not unapproved:
            await q.edit_message_text("No pending cases.")
            return ANSWERING
        for case in unapproved[:5]:
            text = "Case " + str(case["id"]) + " - " + case.get("category","?") + "\n\n" + case["vignette"] + "\n\n" + case["question"] + "\n\n" + "\n".join(k+") "+v for k,v in case["options"].items()) + "\n\nAnswer: " + case["answer"] + "\n" + case["explanation"]
            kb2 = [[InlineKeyboardButton("Approve", callback_data="approve_"+str(case["id"])), InlineKeyboardButton("Reject", callback_data="reject_"+str(case["id"]))]]
            await q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb2))
        await q.edit_message_text("Showing " + str(min(5,len(unapproved))) + " pending cases above.")
        return ANSWERING

    if d.startswith("approve_") or d.startswith("reject_"):
        if not is_admin(q.from_user.id):
            await q.answer("Access denied.")
            return ANSWERING
        parts = d.split("_", 1)
        action, cid = parts[0], parts[1]
        pending = load_json(PENDING_FILE, [])
        for case in pending:
            if str(case["id"]) == cid:
                case["approved"] = (action == "approve")
        save_json(PENDING_FILE, pending)
        label = "approved" if action == "approve" else "rejected"
        await q.edit_message_text("Case " + cid + " " + label + ".")
        return ANSWERING

    timed = False
    if d == "mode_full":
        cases = all_cases
        msg = "Full quiz - " + str(len(cases)) + " cases."
    elif d == "mode_quick":
        cases = random.sample(all_cases, min(10, len(all_cases)))
        msg = "Quick drill - 10 random cases."
    elif d == "mode_timed":
        cases = random.sample(all_cases, min(10, len(all_cases)))
        msg = "Timed mode - 90 seconds per case."
        timed = True
    elif d == "mode_retry":
        uid = str(q.from_user.id)
        ustats = load_json(STATS_FILE, {}).get(uid, {})
        wrong_ids = set(ustats.get("case_wrong", {}).keys())
        cases = [c for c in all_cases if str(c["id"]) in wrong_ids]
        if not cases:
            await q.edit_message_text("No wrong cases on record yet. Complete a full quiz first.")
            return ConversationHandler.END
        msg = "Retrying " + str(len(cases)) + " cases you got wrong before."
    elif d == "mode_category":
        cats = sorted(set(c["category"] for c in all_cases))
        kb = [[InlineKeyboardButton(cat, callback_data="cat_"+cat)] for cat in cats]
        await q.edit_message_text("Pick a category:", reply_markup=InlineKeyboardMarkup(kb))
        return CHOOSING_CATEGORY
    else:
        return ANSWERING

    context.user_data["session"] = build_session(cases)
    context.user_data["timed"] = timed
    session = context.user_data["session"]
    case = session["cases"][0]
    session["total_categories"][case["category"]] += 1
    await q.edit_message_text(msg)
    await context.bot.send_message(q.message.chat_id, fmt_case(case, 0, len(cases), timed), reply_markup=ans_kb())
    return ANSWERING


async def handle_category(update, context):
    q = update.callback_query
    await q.answer()
    cat = q.data.replace("cat_", "")
    cases = [c for c in get_all_cases() if c["category"] == cat]
    context.user_data["session"] = build_session(cases)
    context.user_data["timed"] = False
    session = context.user_data["session"]
    case = session["cases"][0]
    session["total_categories"][case["category"]] += 1
    await q.edit_message_text(cat + " - " + str(len(cases)) + " cases.")
    await context.bot.send_message(q.message.chat_id, fmt_case(case, 0, len(cases)), reply_markup=ans_kb())
    return ANSWERING


async def handle_answer(update, context):
    session = context.user_data.get("session")
    if not session:
        await update.message.reply_text("Send /start to begin.")
        return ConversationHandler.END
    text = update.message.text.strip()

    if text == "Pause":
        session["paused"] = True
        await update.message.reply_text("Session paused. Send /resume to continue.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    if text == "Hint":
        cases = session["cases"]
        if session["case_index"] < len(cases):
            case = cases[session["case_index"]]
            wrong = [k for k in case["options"] if k != case["answer"]]
            elim = random.choice(wrong)
            await update.message.reply_text("Hint: Option " + elim + ") is incorrect - " + case["options"][elim], reply_markup=ans_kb())
        return ANSWERING

    user_input = text.upper()
    if user_input not in ["A","B","C","D"]:
        await update.message.reply_text("Reply with A, B, C or D.", reply_markup=ans_kb())
        return ANSWERING

    cases = session["cases"]
    case = cases[session["case_index"]]
    correct = case["answer"]
    is_correct = user_input == correct
    session["answers"].append({
        "case_id": case["id"], "category": case["category"],
        "user_answer": user_input, "correct_answer": correct, "correct": is_correct
    })

    if is_correct:
        session["score"] += 1
        result = "Correct! " + correct + ") " + case["options"][correct]
    else:
        session["wrong_categories"][case["category"]] += 1
        result = "Incorrect. You chose: " + user_input + ") " + case["options"][user_input] + "\nCorrect: " + correct + ") " + case["options"][correct]

    await update.message.reply_text(result + "\n\nExplanation:\n" + case["explanation"], reply_markup=ReplyKeyboardRemove())
    session["case_index"] += 1

    if session["case_index"] >= len(cases):
        uid = update.effective_user.id
        username = update.effective_user.first_name or ""
        ustats = update_stats(uid, session, username)
        await send_summary(update, session, ustats)
        return ConversationHandler.END

    next_case = cases[session["case_index"]]
    session["total_categories"][next_case["category"]] += 1
    timed = context.user_data.get("timed", False)
    await update.message.reply_text(fmt_case(next_case, session["case_index"], len(cases), timed), reply_markup=ans_kb())
    return ANSWERING


async def send_summary(update, session, ustats):
    total = len(session["answers"])
    score = session["score"]
    pct = round(score/total*100) if total else 0
    grade = "Excellent" if pct>=80 else "Good" if pct>=60 else "Needs work" if pct>=40 else "Review required"
    lines = ["Session Complete\n\nScore: " + str(score) + "/" + str(total) + " (" + str(pct) + "%) - " + grade + "\n\nBy topic:\n"]
    for cat, wrong in sorted(session["wrong_categories"].items(), key=lambda x: -x[1]):
        t = session["total_categories"][cat]
        c = t - wrong
        lines.append(cat + ": " + str(c) + "/" + str(t) + " correct\n")
    if not session["wrong_categories"]:
        lines.append("All topics clean\n")
    await update.message.reply_text("".join(lines), reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("Remarks\n\n" + make_remarks(session, ustats))
    badges = ustats.get("badges", [])
    if badges:
        await update.message.reply_text("Badges: " + ", ".join(badges))
    await update.message.reply_text("/start - new session | /progress - stats | /leaderboard - rankings | /weak - review areas")


async def cmd_resume(update, context):
    session = context.user_data.get("session")
    if not session or not session.get("paused"):
        await update.message.reply_text("No paused session. Send /start.")
        return ConversationHandler.END
    session["paused"] = False
    cases = session["cases"]
    idx = session["case_index"]
    if idx >= len(cases):
        await update.message.reply_text("Session was already complete. Send /start.")
        return ConversationHandler.END
    timed = context.user_data.get("timed", False)
    await update.message.reply_text("Resuming from case " + str(idx+1) + " of " + str(len(cases)) + ".")
    await update.message.reply_text(fmt_case(cases[idx], idx, len(cases), timed), reply_markup=ans_kb())
    return ANSWERING


async def cmd_stop(update, context):
    session = context.user_data.get("session")
    if session and session.get("answers"):
        uid = update.effective_user.id
        username = update.effective_user.first_name or ""
        ustats = update_stats(uid, session, username)
        await send_summary(update, session, ustats)
    else:
        await update.message.reply_text("No active session.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END


async def cmd_progress(update, context):
    uid = str(update.effective_user.id)
    u = load_json(STATS_FILE, {}).get(uid)
    if not u or u.get("total_questions", 0) == 0:
        await update.message.reply_text("No data yet. Complete a quiz first.")
        return
    tq = u["total_questions"]
    tc = u["total_correct"]
    pct = round(tc/tq*100)
    lines = ["Your Progress\n\nSessions: " + str(u.get("sessions",0)) + "\nOverall: " + str(tc) + "/" + str(tq) + " (" + str(pct) + "%)\nStreak: " + str(u.get("streak",0)) + " days\n\nBy category:\n"]
    cc = u.get("category_correct", {})
    ct = u.get("category_total", {})
    for cat in sorted(ct.keys()):
        c = cc.get(cat, 0)
        t = ct[cat]
        p = round(c/t*100)
        lines.append(cat + ": " + str(p) + "% (" + str(c) + "/" + str(t) + ")\n")
    badges = u.get("badges", [])
    if badges:
        lines.append("\nBadges: " + ", ".join(badges) + "\n")
    await update.message.reply_text("".join(lines))


async def cmd_weak(update, context):
    uid = str(update.effective_user.id)
    u = load_json(STATS_FILE, {}).get(uid)
    if not u or not u.get("category_total"):
        await update.message.reply_text("No data yet. Complete a quiz first.")
        return
    cc = u.get("category_correct", {})
    ct = u.get("category_total", {})
    weak = []
    for cat, t in ct.items():
        c = cc.get(cat, 0)
        p = round(c/t*100)
        if p < 70:
            weak.append((cat, p, t-c, t))
    weak.sort(key=lambda x: x[1])
    if not weak:
        await update.message.reply_text("Nothing below 70%. Strong across the board.")
        return
    lines = ["Weak Areas (below 70%)\n\n"]
    for cat, pct, wrong, total in weak:
        lines.append(cat + ": " + str(pct) + "% (" + str(wrong) + "/" + str(total) + " wrong)\n")
        if cat in TIPS:
            lines.append(TIPS[cat] + "\n\n")
    await update.message.reply_text("".join(lines))


async def cmd_leaderboard(update, context):
    stats = load_json(STATS_FILE, {})
    scores = []
    for uid, u in stats.items():
        tq = u.get("total_questions", 0)
        tc = u.get("total_correct", 0)
        if tq >= 5:
            scores.append((u.get("username") or "User"+uid[-4:], tc, tq, round(tc/tq*100)))
    scores.sort(key=lambda x: (-x[3], -x[1]))
    if not scores:
        await update.message.reply_text("No leaderboard data yet. Complete 5+ questions to appear.")
        return
    lines = ["Leaderboard\n\n"]
    for i, (name, correct, total, pct) in enumerate(scores[:10]):
        prefix = str(i+1) + "."
        lines.append(prefix + " " + name + ": " + str(pct) + "% (" + str(correct) + "/" + str(total) + ")\n")
    await update.message.reply_text("".join(lines))


async def cmd_random(update, context):
    all_cases = get_all_cases()
    args = context.args
    n = min(int(args[0]), len(all_cases)) if args and args[0].isdigit() else 10
    cases = random.sample(all_cases, n)
    context.user_data["session"] = build_session(cases)
    context.user_data["timed"] = False
    session = context.user_data["session"]
    case = session["cases"][0]
    session["total_categories"][case["category"]] += 1
    await update.message.reply_text("Random drill - " + str(n) + " cases.")
    await update.message.reply_text(fmt_case(case, 0, n), reply_markup=ans_kb())
    return ANSWERING


async def cmd_admin(update, context):
    args = context.args
    uid = str(update.effective_user.id)
    if not args:
        await update.message.reply_text("Usage: /admin <password>")
        return
    if args[0] == ADMIN_PASSWORD:
        admins = load_json(ADMIN_FILE, [])
        if uid not in admins:
            admins.append(uid)
            save_json(ADMIN_FILE, admins)
        await update.message.reply_text("Admin access granted. Commands: /addcase, /broadcast, /classstats")
    else:
        await update.message.reply_text("Wrong password.")


async def cmd_addcase(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only. Use /admin <password> first.")
        return ConversationHandler.END
    context.user_data["new_case"] = {}
    await update.message.reply_text("New case. Send the vignette (clinical scenario):", reply_markup=ReplyKeyboardRemove())
    return ACV


async def ac_vignette(update, context):
    context.user_data["new_case"]["vignette"] = update.message.text.strip()
    await update.message.reply_text("Send the question:")
    return ACQ


async def ac_question(update, context):
    context.user_data["new_case"]["question"] = update.message.text.strip()
    await update.message.reply_text("Send 4 options, one per line:\nA) text\nB) text\nC) text\nD) text")
    return ACO


async def ac_options(update, context):
    lines = update.message.text.strip().split("\n")
    options = {}
    for line in lines:
        line = line.strip()
        if line and line[0] in "ABCD" and len(line) > 2:
            options[line[0]] = line[2:].strip() if line[1] in ") " else line[1:].strip()
    if len(options) < 4:
        await update.message.reply_text("Need exactly 4 options. Try again:")
        return ACO
    context.user_data["new_case"]["options"] = options
    await update.message.reply_text("Correct answer? (A, B, C or D)")
    return ACA


async def ac_answer(update, context):
    ans = update.message.text.strip().upper()
    if ans not in ["A","B","C","D"]:
        await update.message.reply_text("A, B, C or D only.")
        return ACA
    context.user_data["new_case"]["answer"] = ans
    await update.message.reply_text("Send the explanation:")
    return ACE


async def ac_explanation(update, context):
    context.user_data["new_case"]["explanation"] = update.message.text.strip()
    await update.message.reply_text("Category? (e.g. Cardiovascular, Endocrine, Psychiatry)")
    return ACC


async def ac_category(update, context):
    context.user_data["new_case"]["category"] = update.message.text.strip()
    pending = load_json(PENDING_FILE, [])
    all_ids = [c["id"] for c in CASES] + [c["id"] for c in pending]
    new_id = max(all_ids)+1 if all_ids else 1
    case = context.user_data["new_case"]
    case.update({"id": new_id, "approved": True, "added_by": str(update.effective_user.id), "added_at": datetime.now().isoformat()})
    pending.append(case)
    save_json(PENDING_FILE, pending)
    await update.message.reply_text("Case " + str(new_id) + " added to " + case["category"] + ".")
    context.user_data.pop("new_case", None)
    return ConversationHandler.END


async def cmd_broadcast(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    message = " ".join(context.args)
    stats = load_json(STATS_FILE, {})
    sent = failed = 0
    for uid in stats.keys():
        try:
            await context.bot.send_message(int(uid), "Announcement\n\n" + message)
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text("Sent to " + str(sent) + " users. " + str(failed) + " failed.")


async def cmd_classstats(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Admin only.")
        return
    all_cases = get_all_cases()
    stats = load_json(STATS_FILE, {})
    cwa = {}; cca = {}; cta = {}
    for u in stats.values():
        for cid, cnt in u.get("case_wrong", {}).items():
            cwa[cid] = cwa.get(cid, 0) + cnt
        for cat, cnt in u.get("category_correct", {}).items():
            cca[cat] = cca.get(cat, 0) + cnt
        for cat, cnt in u.get("category_total", {}).items():
            cta[cat] = cta.get(cat, 0) + cnt
    hardest = sorted(cwa.items(), key=lambda x: -x[1])[:5]
    total_sessions = sum(u.get("sessions", 0) for u in stats.values())
    lines = ["Class Statistics\n\nStudents: " + str(len(stats)) + "\nSessions: " + str(total_sessions) + "\n\nHardest cases:\n"]
    for cid, cnt in hardest:
        case = next((c for c in all_cases if str(c["id"]) == cid), None)
        if case:
            lines.append("Case " + cid + " (" + case["category"] + "): " + str(cnt) + " wrong\n")
    lines.append("\nCategory accuracy:\n")
    for cat in sorted(cta.keys()):
        t = cta[cat]
        c = cca.get(cat, 0)
        p = round(c/t*100) if t else 0
        lines.append(cat + ": " + str(p) + "% (" + str(c) + "/" + str(t) + ")\n")
    await update.message.reply_text("".join(lines))


async def cmd_help(update, context):
    uid = update.effective_user.id
    lines = ["PharmBot Commands\n\n/start - new quiz\n/resume - continue paused session\n/random [n] - random drill (default 10)\n/progress - your stats\n/weak - categories below 70%\n/leaderboard - top scores\n/stop - end session early\n/help - this list\n"]
    if is_admin(uid):
        lines.append("\nAdmin:\n/addcase - add a new case\n/broadcast <msg> - message all students\n/classstats - class performance\n/admin <password> - get admin access\n")
    await update.message.reply_text("".join(lines))


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN not set.")
    app = Application.builder().token(token).build()

    addcase_conv = ConversationHandler(
        entry_points=[CommandHandler("addcase", cmd_addcase)],
        states={
            ACV: [MessageHandler(filters.TEXT & ~filters.COMMAND, ac_vignette)],
            ACQ: [MessageHandler(filters.TEXT & ~filters.COMMAND, ac_question)],
            ACO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ac_options)],
            ACA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ac_answer)],
            ACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ac_explanation)],
            ACC: [MessageHandler(filters.TEXT & ~filters.COMMAND, ac_category)],
        },
        fallbacks=[CommandHandler("stop", cmd_stop)],
        allow_reentry=True
    )

    main_conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("random", cmd_random),
            CommandHandler("resume", cmd_resume),
        ],
        states={
            ANSWERING: [
                CallbackQueryHandler(handle_mode),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer),
            ],
            CHOOSING_CATEGORY: [
                CallbackQueryHandler(handle_category, pattern="^cat_"),
                CallbackQueryHandler(handle_mode),
            ],
        },
        fallbacks=[CommandHandler("stop", cmd_stop)],
        allow_reentry=True
    )

    app.add_handler(addcase_conv)
    app.add_handler(main_conv)
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("weak", cmd_weak))
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("classstats", cmd_classstats))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("help", cmd_help))
    app.run_polling()


if __name__ == "__main__":
    main()
