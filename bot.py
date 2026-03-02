import telebot
from telebot import types
import logging
import random
import os
import sqlite3
import time
from datetime import date, timedelta

from data import GERUND_ONLY, INFINITIVE_ONLY, IRREGULAR_VERBS, ALL_STRICT_VERBS, VERB_TO_CATEGORY, get_random_verb, get_accepted_translations

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logging.error("❌ BOT_TOKEN not set!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# ─────────────────────────────────────────────
# DATABASE (SQLite — persists across restarts)
# ─────────────────────────────────────────────
DB_PATH = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        uid INTEGER PRIMARY KEY,
        total_score INTEGER DEFAULT 0,
        translate_score INTEGER DEFAULT 0,
        ger_inf_score INTEGER DEFAULT 0,
        quiz_score INTEGER DEFAULT 0,
        irregular_score INTEGER DEFAULT 0,
        xp INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        best_streak INTEGER DEFAULT 0,
        last_active_date TEXT DEFAULT '',
        daily_streak INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS mistakes (
        uid INTEGER,
        verb TEXT,
        wrong_count INTEGER DEFAULT 1,
        PRIMARY KEY (uid, verb)
    )''')
    conn.commit()
    conn.close()

init_db()

def db_ensure(uid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR IGNORE INTO users (uid) VALUES (?)", (uid,))
    conn.commit()
    conn.close()

def db_get(uid):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uid=?", (uid,))
    row = c.fetchone()
    conn.close()
    return row

def db_add_score(uid, total=0, translate=0, ger_inf=0, quiz=0, irregular=0, xp=0):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''UPDATE users SET
        total_score=total_score+?, translate_score=translate_score+?,
        ger_inf_score=ger_inf_score+?, quiz_score=quiz_score+?,
        irregular_score=irregular_score+?, xp=xp+?
        WHERE uid=?''', (total, translate, ger_inf, quiz, irregular, xp, uid))
    c.execute("SELECT xp, level FROM users WHERE uid=?", (uid,))
    row = c.fetchone()
    new_level = None
    if row:
        xp_total, level = row
        calc = 1 + xp_total // 100
        if calc != level:
            c.execute("UPDATE users SET level=? WHERE uid=?", (calc, uid))
            new_level = calc
    conn.commit()
    conn.close()
    return new_level

def db_update_best_streak(uid, streak):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET best_streak=MAX(best_streak,?) WHERE uid=?", (streak, uid))
    conn.commit()
    conn.close()

def db_add_mistake(uid, verb):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''INSERT INTO mistakes(uid,verb,wrong_count) VALUES(?,?,1)
                    ON CONFLICT(uid,verb) DO UPDATE SET wrong_count=wrong_count+1''', (uid, verb))
    conn.commit()
    conn.close()

def db_get_mistakes(uid, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT verb,wrong_count FROM mistakes WHERE uid=? ORDER BY wrong_count DESC LIMIT ?", (uid, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def db_update_daily(uid):
    db_ensure(uid)
    today = str(date.today())
    yesterday = str(date.today() - timedelta(days=1))
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT last_active_date, daily_streak FROM users WHERE uid=?", (uid,))
    row = c.fetchone()
    streak = 1
    if row:
        last, ds = row
        if last == today:
            conn.close()
            return ds
        streak = ds + 1 if last == yesterday else 1
    c.execute("UPDATE users SET last_active_date=?, daily_streak=? WHERE uid=?", (today, streak, uid))
    conn.commit()
    conn.close()
    return streak

def db_leaderboard(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT uid,total_score,level FROM users ORDER BY total_score DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# ─────────────────────────────────────────────
# IN-MEMORY SESSION STATE
# ─────────────────────────────────────────────
user_data = {}

def reset_user(uid):
    db_ensure(uid)
    db_update_daily(uid)
    user_data[uid] = {
        'mode': None,
        'streak': 0,
        'session_correct': 0,
        'session_wrong': 0,
        'session_mistakes': [],
        'session_count': 0,
        'difficulty': 'normal',
        'time_attack_active': False,
        'time_attack_start': None,
        'time_attack_score': 0,
        'current_verb': None,
        'correct_answer': None,
        'irregular_data': None,
    }

def normalize(text):
    return text.lower().strip()

def check_form(user_input, correct_form):
    user_input = normalize(user_input)
    correct_form = normalize(correct_form)
    if "/" in correct_form:
        return user_input in correct_form.split("/")
    return user_input == correct_form

def get_level_name(level):
    names = {1: "🌱 Новичок", 2: "📖 Ученик", 3: "⚡ Знаток", 4: "🔥 Мастер", 5: "💎 Эксперт"}
    return names.get(min(level, 5), f"🏆 Легенда ({level})")

def get_xp(uid):
    diff = user_data[uid].get('difficulty', 'normal')
    streak = user_data[uid].get('streak', 0)
    base = {'easy': 5, 'normal': 10, 'hard': 20}.get(diff, 10)
    bonus = min(streak // 5, 5) * 5  # +5 XP per 5-streak, max +25
    return base + bonus

def get_weighted_verb(uid):
    """30% chance to pick a previously-mistaken verb (spaced repetition)"""
    mistakes = db_get_mistakes(uid, limit=20)
    mistake_verbs = [m[0] for m in mistakes if m[0] in ALL_STRICT_VERBS]
    if mistake_verbs and random.random() < 0.3:
        return random.choice(mistake_verbs)
    return get_random_verb()

# ─────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────
def main_menu_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("1. Перевод (вписать)", "2. Gerund или Infinitive")
    m.add("3. Выбор из 4 вариантов", "4. Неправильные глаголы")
    m.add("⏱ Таймер-атака", "📊 Статистика")
    m.add("🏆 Лидерборд", "⚙️ Настройки")
    m.add("📋 Мои ошибки")
    return m

def back_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("Назад в меню", "📊 Статистика")
    return m

def difficulty_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    m.add("🟢 Легко", "🟡 Нормально", "🔴 Сложно")
    m.add("Назад в меню")
    return m

# ─────────────────────────────────────────────
# CORRECT / WRONG HELPERS
# ─────────────────────────────────────────────
def on_correct(uid, score_type):
    user_data[uid]['streak'] += 1
    user_data[uid]['session_correct'] += 1
    user_data[uid]['session_count'] += 1
    streak = user_data[uid]['streak']
    xp = get_xp(uid)
    new_level = db_add_score(uid, **{score_type: 1, 'total': 1, 'xp': xp})
    db_update_best_streak(uid, streak)

    msg = f"✅ Правильно! +1  (XP +{xp})"
    if streak > 1:
        msg += f"\n🔥 Серия: {streak}"
    if streak in (5, 10, 20, 50):
        msg += f"\n🎉 {streak} ответов подряд!"
    if new_level:
        msg += f"\n\n⬆️ Новый уровень: {get_level_name(new_level)}!"
    return msg

def on_wrong(uid, verb, correct):
    user_data[uid]['streak'] = 0
    user_data[uid]['session_wrong'] += 1
    user_data[uid]['session_count'] += 1
    user_data[uid]['session_mistakes'].append((verb, correct))
    db_add_mistake(uid, verb)
    return f"❌ Неправильно. Правильный ответ: *{correct}*"

def maybe_summary(uid):
    """Show session summary every 10 questions"""
    count = user_data[uid]['session_count']
    if count > 0 and count % 10 == 0:
        c = user_data[uid]['session_correct']
        w = user_data[uid]['session_wrong']
        pct = int(c / count * 100)
        msg = f"📊 *Итог за {count} вопросов:* ✅{c} ❌{w} ({pct}%)\n"
        recent = user_data[uid]['session_mistakes'][-5:]
        if recent:
            msg += "\n*Последние ошибки:*\n"
            for verb, ans in recent:
                msg += f"• {verb} → {ans}\n"
        bot.send_message(uid, msg, parse_mode='Markdown')

# ─────────────────────────────────────────────
# QUESTION MODES
# ─────────────────────────────────────────────
def send_translate_q(uid):
    verb = get_weighted_verb(uid)
    user_data[uid]['current_verb'] = verb
    bot.send_message(uid, f"Переведи глагол на русский:\n\n*{verb}*",
                     reply_markup=back_keyboard(), parse_mode='Markdown')

def check_translate(uid, text):
    verb = user_data[uid].get('current_verb')
    if not verb:
        return
    
    accepted = get_accepted_translations(verb)
    user_input = normalize(text)
    
    correct = any(
        user_input == a or user_input in a or a in user_input
        for a in accepted
    )
    
    if correct:
        msg = on_correct(uid, 'translate')
    else:
        main_translation = ALL_STRICT_VERBS[verb]
        msg = on_wrong(uid, verb, main_translation)
    
    bot.send_message(uid, msg, parse_mode='Markdown')
    maybe_summary(uid)
    send_translate_q(uid)

def send_ger_inf_q(uid):
    verb = get_weighted_verb(uid)
    user_data[uid]['current_verb'] = verb
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Infinitive (to + V)", callback_data="gi_inf"),
        types.InlineKeyboardButton("Gerund (V-ing)", callback_data="gi_ger")
    )
    bot.send_message(uid, f"После какого глагола нужна эта форма?\n\n*{verb}*",
                     reply_markup=markup, parse_mode='Markdown')

def send_quiz_q(uid):
    eng = get_weighted_verb(uid)
    ru = ALL_STRICT_VERBS[eng]
    options = [eng] + random.sample([v for v in ALL_STRICT_VERBS if v != eng], 3)
    random.shuffle(options)
    user_data[uid]['correct_answer'] = eng
    markup = types.InlineKeyboardMarkup(row_width=1)
    for opt in options:
        markup.add(types.InlineKeyboardButton(opt, callback_data=f"qz_{opt}"))
    bot.send_message(uid, f"Какой глагол соответствует переводу:\n*{ru}*",
                     reply_markup=markup, parse_mode='Markdown')

def start_irregular(uid):
    verb = random.choice(list(IRREGULAR_VERBS.keys()))
    v2, v3, ru = IRREGULAR_VERBS[verb]
    user_data[uid]['mode'] = 'irregular_step'
    user_data[uid]['irregular_data'] = {'v1': verb, 'v2': v2, 'v3': v3, 'ru': ru, 'step': 1}
    bot.send_message(uid, f"Переведи на английский (V1):\n\n*{ru}*",
                     reply_markup=back_keyboard(), parse_mode="Markdown")

def handle_irregular(uid, text):
    data = user_data[uid]['irregular_data']
    step = data['step']
    inp = normalize(text)
    if step == 1:
        if check_form(inp, data['v1']):
            data['step'] = 2
            bot.send_message(uid, "✅ Правильно!\nТеперь напиши V2:")
        else:
            bot.send_message(uid, f"❌ Неправильно. Правильный ответ: {data['v1']}")
            db_add_mistake(uid, data['v1'])
            start_irregular(uid)
    elif step == 2:
        if check_form(inp, data['v2']):
            data['step'] = 3
            bot.send_message(uid, "✅ Верно!\nТеперь напиши V3:")
        else:
            bot.send_message(uid, f"❌ Неправильно. Правильный ответ: {data['v2']}")
            db_add_mistake(uid, data['v1'])
            start_irregular(uid)
    elif step == 3:
        if check_form(inp, data['v3']):
            msg = on_correct(uid, 'irregular')
            bot.send_message(uid, f"🔥 Все три формы верны!\n{msg}", parse_mode='Markdown')
        else:
            bot.send_message(uid, f"❌ Неправильно. Правильный ответ: {data['v3']}")
            db_add_mistake(uid, data['v1'])
        start_irregular(uid)

# ─────────────────────────────────────────────
# TIME ATTACK MODE
# ─────────────────────────────────────────────
def start_time_attack(uid):
    user_data[uid]['mode'] = 'time_attack'
    user_data[uid]['time_attack_active'] = True
    user_data[uid]['time_attack_start'] = time.time()
    user_data[uid]['time_attack_score'] = 0
    bot.send_message(uid,
        "⏱ *Таймер-атака!*\n60 секунд. Переводи глаголы на русский как можно быстрее!",
        reply_markup=back_keyboard(), parse_mode='Markdown')
    send_ta_q(uid)

def send_ta_q(uid):
    elapsed = time.time() - user_data[uid]['time_attack_start']
    if elapsed >= 60:
        end_time_attack(uid)
        return
    verb = get_random_verb()
    user_data[uid]['current_verb'] = verb
    remaining = int(60 - elapsed)
    bot.send_message(uid, f"⏱ *{remaining}с* | *{verb}*", parse_mode='Markdown')

def end_time_attack(uid):
    score = user_data[uid].get('time_attack_score', 0)
    user_data[uid]['time_attack_active'] = False
    user_data[uid]['mode'] = None
    emoji = "🏆" if score >= 20 else "💪"
    bot.send_message(uid,
        f"⏱ *Время вышло!*\nПравильных ответов: *{score}* за 60 сек! {emoji}",
        reply_markup=main_menu_keyboard(), parse_mode='Markdown')

def check_ta(uid, text):
    elapsed = time.time() - user_data[uid]['time_attack_start']
    if elapsed >= 60:
        end_time_attack(uid)
        return
    verb = user_data[uid].get('current_verb')
    if not verb:
        send_ta_q(uid)
        return
    correct = ALL_STRICT_VERBS[verb].lower()
    remaining = int(60 - elapsed)
    if normalize(text) in correct:
        user_data[uid]['time_attack_score'] += 1
        bot.send_message(uid, f"✅ | ⏱ {remaining}с")
    else:
        bot.send_message(uid, f"❌ {ALL_STRICT_VERBS[verb]} | ⏱ {remaining}с")
    send_ta_q(uid)

# ─────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.chat.id
    reset_user(uid)
    daily_streak = db_update_daily(uid)
    row = db_get(uid)
    level = row[7] if row else 1
    bot.send_message(uid,
        f"👋 Привет!\n\n🏅 Уровень: {get_level_name(level)}\n📅 Дней подряд: {daily_streak}\n\nВыбери режим:",
        reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: m.text in ["Назад в меню", "назад", "меню"])
def back_to_menu(message):
    uid = message.chat.id
    if uid not in user_data:
        reset_user(uid)
    user_data[uid]['mode'] = None
    user_data[uid]['time_attack_active'] = False
    bot.send_message(uid, "Главное меню:", reply_markup=main_menu_keyboard())

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    uid = message.chat.id
    text = message.text.strip()
    if uid not in user_data:
        reset_user(uid)

    if text == "📊 Статистика":
        row = db_get(uid)
        if not row:
            bot.send_message(uid, "Начни отвечать на вопросы!")
            return
        _, total, tr, gi, qz, irr, xp, level, best_streak, _, daily_streak = row
        xp_to_next = 100 - (xp % 100)
        bot.send_message(uid,
            f"📊 *Статистика:*\n\n"
            f"🏅 {get_level_name(level)}\n"
            f"⚡ XP: {xp} (до след. уровня: {xp_to_next})\n"
            f"📅 Дней подряд: {daily_streak}\n"
            f"🔥 Лучшая серия: {best_streak}\n\n"
            f"🎯 Всего: {total}\n"
            f"📝 Перевод: {tr}  |  🔄 Gerund/Inf: {gi}\n"
            f"🎯 Викторина: {qz}  |  📚 Irregular: {irr}",
            parse_mode='Markdown')
        return

    if text == "📋 Мои ошибки":
        mistakes = db_get_mistakes(uid)
        if not mistakes:
            bot.send_message(uid, "Ошибок пока нет. Так держать!")
            return
        msg = "📋 *Частые ошибки:*\n\n"
        for verb, count in mistakes:
            tr = ALL_STRICT_VERBS.get(verb, "?")
            msg += f"• *{verb}* ({tr}) — {count}×\n"
        bot.send_message(uid, msg, parse_mode='Markdown')
        return

    if text == "🏆 Лидерборд":
        rows = db_leaderboard()
        if not rows:
            bot.send_message(uid, "Лидерборд пуст. Будь первым!")
            return
        medals = ["🥇", "🥈", "🥉"]
        msg = "🏆 *Топ игроков:*\n\n"
        for i, (u, score, level) in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            marker = " ← ты" if u == uid else ""
            msg += f"{medal} {get_level_name(level)} — {score} очков{marker}\n"
        bot.send_message(uid, msg, parse_mode='Markdown')
        return

    if text == "⚙️ Настройки":
        diff = user_data[uid].get('difficulty', 'normal')
        bot.send_message(uid,
            f"⚙️ Сложность: *{diff}*\n\n🟢 Легко — 5 XP\n🟡 Нормально — 10 XP\n🔴 Сложно — 20 XP",
            reply_markup=difficulty_keyboard(), parse_mode='Markdown')
        return

    if text == "🟢 Легко":
        user_data[uid]['difficulty'] = 'easy'
        bot.send_message(uid, "Сложность: 🟢 Легко", reply_markup=main_menu_keyboard())
        return
    if text == "🟡 Нормально":
        user_data[uid]['difficulty'] = 'normal'
        bot.send_message(uid, "Сложность: 🟡 Нормально", reply_markup=main_menu_keyboard())
        return
    if text == "🔴 Сложно":
        user_data[uid]['difficulty'] = 'hard'
        bot.send_message(uid, "Сложность: 🔴 Сложно", reply_markup=main_menu_keyboard())
        return

    if text == "1. Перевод (вписать)":
        user_data[uid]['mode'] = 'translate'
        send_translate_q(uid)
        return
    elif text == "2. Gerund или Infinitive":
        user_data[uid]['mode'] = 'ger_inf'
        send_ger_inf_q(uid)
        return
    elif text == "3. Выбор из 4 вариантов":
        user_data[uid]['mode'] = 'quiz'
        send_quiz_q(uid)
        return
    elif text == "4. Неправильные глаголы":
        start_irregular(uid)
        return
    elif text == "⏱ Таймер-атака":
        start_time_attack(uid)
        return

    mode = user_data[uid].get('mode')
    if mode == 'translate':
        check_translate(uid, text)
    elif mode == 'irregular_step':
        handle_irregular(uid, text)
    elif mode == 'time_attack':
        check_ta(uid, text)
    else:
        bot.send_message(uid, "Выбери режим через меню 👇", reply_markup=main_menu_keyboard())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    uid = call.message.chat.id
    if uid not in user_data:
        reset_user(uid)
    mode = user_data[uid].get('mode')

    if mode == 'ger_inf' and call.data.startswith("gi_"):
        verb = user_data[uid]['current_verb']
        correct_cat = VERB_TO_CATEGORY[verb]
        correct = 'gi_inf' if correct_cat == 'infinitive' else 'gi_ger'
        if call.data == correct:
            msg = on_correct(uid, 'ger_inf')
            bot.answer_callback_query(call.id, "✅ Правильно!")
            bot.send_message(uid, msg, parse_mode='Markdown')
        else:
            on_wrong(uid, verb, correct_cat)
            bot.answer_callback_query(call.id, f"❌ Ответ: {correct_cat}")
        maybe_summary(uid)
        send_ger_inf_q(uid)

    elif mode == 'quiz' and call.data.startswith("qz_"):
        correct = user_data[uid]['correct_answer']
        selected = call.data[3:]
        if selected == correct:
            msg = on_correct(uid, 'quiz')
            bot.answer_callback_query(call.id, "✅ Верно!")
            bot.send_message(uid, msg, parse_mode='Markdown')
        else:
            on_wrong(uid, selected, correct)
            bot.answer_callback_query(call.id, f"❌ Ответ: {correct}")
        maybe_summary(uid)
        send_quiz_q(uid)

if __name__ == '__main__':
    logging.info("Бот стартовал")
    bot.infinity_polling(timeout=15, long_polling_timeout=5)