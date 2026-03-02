import telebot
from telebot import types
import logging
import random
import os
import sqlite3
import time
from datetime import date, timedelta
from threading import Thread

from data import GERUND_ONLY, INFINITIVE_ONLY, IRREGULAR_VERBS, ALL_STRICT_VERBS, VERB_TO_CATEGORY, get_random_verb, get_accepted_translations

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logging.error("❌ BOT_TOKEN not set!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# ─────────────────────────────────────────────
# DATABASE
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
        daily_streak INTEGER DEFAULT 0,
        nickname TEXT DEFAULT '',
        best_time_attack INTEGER DEFAULT 0,
        reminder_time TEXT DEFAULT '',
        weekly_score INTEGER DEFAULT 0,
        weekly_reset_date TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS mistakes (
        uid INTEGER,
        verb TEXT,
        wrong_count INTEGER DEFAULT 1,
        PRIMARY KEY (uid, verb)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS achievements (
        uid INTEGER,
        achievement TEXT,
        earned_at TEXT,
        PRIMARY KEY (uid, achievement)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_scores (
        uid INTEGER,
        score_date TEXT,
        score INTEGER DEFAULT 0,
        PRIMARY KEY (uid, score_date)
    )''')
    conn.commit()
    # Migrations
    migrations = [
        "ALTER TABLE users ADD COLUMN nickname TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN best_time_attack INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN reminder_time TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN weekly_score INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN weekly_reset_date TEXT DEFAULT ''",
    ]
    for m in migrations:
        try:
            c.execute(m)
            conn.commit()
        except sqlite3.OperationalError:
            pass
    conn.close()

init_db()

# ─────────────────────────────────────────────
# ACHIEVEMENTS DEFINITION
# ─────────────────────────────────────────────
ACHIEVEMENTS = {
    'first_correct':     ('🌟 Первый шаг',        'Ответь правильно 1 раз'),
    'score_100':         ('💯 Сотня',              'Набери 100 очков'),
    'score_500':         ('🚀 Пятьсот',            'Набери 500 очков'),
    'score_1000':        ('💎 Тысячник',           'Набери 1000 очков'),
    'streak_5':          ('🔥 Серия x5',           '5 правильных подряд'),
    'streak_10':         ('⚡ Серия x10',          '10 правильных подряд'),
    'streak_20':         ('🌪️ Серия x20',          '20 правильных подряд'),
    'streak_50':         ('👑 Серия x50',          '50 правильных подряд'),
    'daily_3':           ('📅 3 дня подряд',       'Заходи 3 дня подряд'),
    'daily_7':           ('🗓️ Неделя',             'Заходи 7 дней подряд'),
    'daily_30':          ('🏆 Месяц',              'Заходи 30 дней подряд'),
    'time_attack_10':    ('⏱️ Быстрый',            '10+ правильных в таймер-атаке'),
    'time_attack_20':    ('⚡ Молния',             '20+ правильных в таймер-атаке'),
    'time_attack_30':    ('🚀 Ракета',             '30+ правильных в таймер-атаке'),
    'level_2':           ('📖 Ученик',             'Достигни 2 уровня'),
    'level_5':           ('💎 Эксперт',            'Достигни 5 уровня'),
    'survival_10':       ('🛡️ Выживший',          'Доживи до 10 вопроса в выживании'),
    'survival_25':       ('⚔️ Воин',              'Доживи до 25 вопроса в выживании'),
    'mistakes_clean':    ('✨ Без ошибок',         'Ответь на 10 вопросов без единой ошибки'),
    'all_modes':         ('🎯 Мультиплеер',        'Сыграй во все режимы'),
}

def db_give_achievement(uid, key):
    """Returns True if this is a NEW achievement"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM achievements WHERE uid=? AND achievement=?", (uid, key))
    exists = c.fetchone()
    if not exists:
        c.execute("INSERT INTO achievements(uid,achievement,earned_at) VALUES(?,?,?)",
                  (uid, key, str(date.today())))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def db_get_achievements(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT achievement FROM achievements WHERE uid=?", (uid,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def notify_achievement(uid, key):
    name, desc = ACHIEVEMENTS[key]
    bot.send_message(uid, f"🏅 *Новое достижение!*\n{name}\n_{desc}_", parse_mode='Markdown')

def check_achievements(uid, context: dict):
    """Check and award achievements based on context dict"""
    earned = db_get_achievements(uid)
    row = db_get(uid)
    if not row:
        return
    uid2, total, tr, gi, qz, irr, xp, level, best_streak, last_date, daily_streak, nickname, best_ta, reminder, weekly, weekly_reset = row

    checks = [
        ('first_correct',  total >= 1),
        ('score_100',      total >= 100),
        ('score_500',      total >= 500),
        ('score_1000',     total >= 1000),
        ('streak_5',       best_streak >= 5),
        ('streak_10',      best_streak >= 10),
        ('streak_20',      best_streak >= 20),
        ('streak_50',      best_streak >= 50),
        ('daily_3',        daily_streak >= 3),
        ('daily_7',        daily_streak >= 7),
        ('daily_30',       daily_streak >= 30),
        ('time_attack_10', best_ta >= 10),
        ('time_attack_20', best_ta >= 20),
        ('time_attack_30', best_ta >= 30),
        ('level_2',        level >= 2),
        ('level_5',        level >= 5),
        ('survival_10',    context.get('survival_q', 0) >= 10),
        ('survival_25',    context.get('survival_q', 0) >= 25),
        ('mistakes_clean', context.get('clean_streak', 0) >= 10),
        ('all_modes',      context.get('all_modes', False)),
    ]
    for key, condition in checks:
        if condition and key not in earned:
            if db_give_achievement(uid, key):
                notify_achievement(uid, key)

# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────
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
    today = str(date.today())
    c.execute('''UPDATE users SET
        total_score=total_score+?, translate_score=translate_score+?,
        ger_inf_score=ger_inf_score+?, quiz_score=quiz_score+?,
        irregular_score=irregular_score+?, xp=xp+?,
        weekly_score=weekly_score+?
        WHERE uid=?''', (total, translate, ger_inf, quiz, irregular, xp, total, uid))
    # Daily score tracking
    c.execute('''INSERT INTO daily_scores(uid,score_date,score) VALUES(?,?,?)
                 ON CONFLICT(uid,score_date) DO UPDATE SET score=score+?''',
              (uid, today, total, total))
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

def db_update_best_ta(uid, score):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET best_time_attack=MAX(best_time_attack,?) WHERE uid=?", (score, uid))
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

def db_reset_weekly_if_needed(uid):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT weekly_reset_date FROM users WHERE uid=?", (uid,))
    row = c.fetchone()
    today = date.today()
    monday = str(today - timedelta(days=today.weekday()))
    if row and row[0] != monday:
        c.execute("UPDATE users SET weekly_score=0, weekly_reset_date=? WHERE uid=?", (monday, uid))
        conn.commit()
    conn.close()

def db_leaderboard(limit=10, weekly=False):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    col = "weekly_score" if weekly else "total_score"
    c.execute(f"SELECT uid,{col},level FROM users ORDER BY {col} DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def db_set_nickname(uid, nickname):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET nickname=? WHERE uid=?", (nickname, uid))
    conn.commit()
    conn.close()

def db_get_nickname(uid):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT nickname FROM users WHERE uid=?", (uid,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else None

def db_set_reminder(uid, time_str):
    db_ensure(uid)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET reminder_time=? WHERE uid=?", (time_str, uid))
    conn.commit()
    conn.close()

def db_get_all_reminders():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT uid, reminder_time FROM users WHERE reminder_time != ''")
    rows = c.fetchall()
    conn.close()
    return rows

def db_get_daily_scores(uid, days=7):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    dates = [str(date.today() - timedelta(days=i)) for i in range(days-1, -1, -1)]
    rows = []
    for d in dates:
        c.execute("SELECT score FROM daily_scores WHERE uid=? AND score_date=?", (uid, d))
        r = c.fetchone()
        rows.append((d, r[0] if r else 0))
    conn.close()
    return rows

def db_get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT uid FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ─────────────────────────────────────────────
# IN-MEMORY SESSION STATE
# ─────────────────────────────────────────────
user_data = {}

def reset_user(uid):
    db_ensure(uid)
    db_update_daily(uid)
    db_reset_weekly_if_needed(uid)
    user_data[uid] = {
        'mode': None,
        'streak': 0,
        'clean_streak': 0,        # consecutive correct with no wrong
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
        'survival_lives': 3,
        'survival_q': 0,
        'modes_played': set(),     # for all_modes achievement
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
    bonus = min(streak // 5, 5) * 5
    return base + bonus

def get_weighted_verb(uid):
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
    m.add("⏱ Таймер-атака", "💀 Выживание")
    m.add("📊 Статистика", "🏆 Лидерборд")
    m.add("🏅 Достижения", "⚙️ Настройки")
    m.add("📋 Мои ошибки", "✏️ Никнейм")
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

def leaderboard_keyboard():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("🏆 Всё время", callback_data="lb_alltime"),
        types.InlineKeyboardButton("📅 Эта неделя", callback_data="lb_weekly")
    )
    return m

def settings_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("🟢 Легко", "🟡 Нормально", "🔴 Сложно")
    m.add("⏰ Напоминание", "❌ Убрать напоминание")
    m.add("Назад в меню")
    return m

# ─────────────────────────────────────────────
# CORRECT / WRONG HELPERS
# ─────────────────────────────────────────────
def on_correct(uid, score_type):
    user_data[uid]['streak'] += 1
    user_data[uid]['clean_streak'] = user_data[uid].get('clean_streak', 0) + 1
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

    check_achievements(uid, {
        'clean_streak': user_data[uid]['clean_streak'],
        'survival_q': user_data[uid].get('survival_q', 0),
        'all_modes': len(user_data[uid].get('modes_played', set())) >= 5,
    })
    return msg

def on_wrong(uid, verb, correct):
    user_data[uid]['streak'] = 0
    user_data[uid]['clean_streak'] = 0
    user_data[uid]['session_wrong'] += 1
    user_data[uid]['session_count'] += 1
    user_data[uid]['session_mistakes'].append((verb, correct))
    db_add_mistake(uid, verb)
    return f"❌ Неправильно. Правильный ответ: *{correct}*"

def maybe_summary(uid):
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
    correct = any(user_input == a or user_input in a or a in user_input for a in accepted)
    if correct:
        msg = on_correct(uid, 'translate')
    else:
        msg = on_wrong(uid, verb, ALL_STRICT_VERBS[verb])
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
# SURVIVAL MODE
# ─────────────────────────────────────────────
def start_survival(uid):
    user_data[uid]['mode'] = 'survival'
    user_data[uid]['survival_lives'] = 3
    user_data[uid]['survival_q'] = 0
    user_data[uid]['modes_played'].add('survival')
    bot.send_message(uid,
        "💀 *Режим выживания!*\nУ тебя 3 жизни ❤️❤️❤️\nОдна ошибка — минус жизнь.\nСколько продержишься?",
        reply_markup=back_keyboard(), parse_mode='Markdown')
    send_survival_q(uid)

def send_survival_q(uid):
    verb = get_weighted_verb(uid)
    user_data[uid]['current_verb'] = verb
    lives = user_data[uid]['survival_lives']
    q = user_data[uid]['survival_q']
    hearts = '❤️' * lives + '🖤' * (3 - lives)
    bot.send_message(uid,
        f"{hearts} | Вопрос {q + 1}\n\nПереведи на русский:\n\n*{verb}*",
        parse_mode='Markdown')

def check_survival(uid, text):
    verb = user_data[uid].get('current_verb')
    if not verb:
        return
    accepted = get_accepted_translations(verb)
    user_input = normalize(text)
    correct = any(user_input == a or user_input in a or a in user_input for a in accepted)

    if correct:
        user_data[uid]['survival_q'] += 1
        user_data[uid]['streak'] += 1
        user_data[uid]['clean_streak'] = user_data[uid].get('clean_streak', 0) + 1
        q = user_data[uid]['survival_q']
        xp = get_xp(uid)
        db_add_score(uid, total=1, translate=1, xp=xp)
        db_update_best_streak(uid, user_data[uid]['streak'])
        lives = user_data[uid]['survival_lives']
        hearts = '❤️' * lives + '🖤' * (3 - lives)
        bot.send_message(uid, f"✅ Правильно! (XP +{xp})\n{hearts} | Вопросов: {q}")
        check_achievements(uid, {
            'survival_q': q,
            'clean_streak': user_data[uid]['clean_streak'],
            'all_modes': len(user_data[uid].get('modes_played', set())) >= 5,
        })
        send_survival_q(uid)
    else:
        user_data[uid]['survival_lives'] -= 1
        user_data[uid]['streak'] = 0
        user_data[uid]['clean_streak'] = 0
        db_add_mistake(uid, verb)
        lives = user_data[uid]['survival_lives']
        hearts = '❤️' * lives + '🖤' * (3 - lives)
        bot.send_message(uid, f"❌ Неправильно. Ответ: *{ALL_STRICT_VERBS[verb]}*\n{hearts}", parse_mode='Markdown')
        if lives <= 0:
            q = user_data[uid]['survival_q']
            user_data[uid]['mode'] = None
            emoji = "🏆" if q >= 25 else "💪"
            bot.send_message(uid,
                f"💀 *Игра окончена!*\nТы ответил правильно на *{q}* вопросов {emoji}",
                reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        else:
            send_survival_q(uid)

# ─────────────────────────────────────────────
# TIME ATTACK
# ─────────────────────────────────────────────
def start_time_attack(uid):
    user_data[uid]['mode'] = 'time_attack'
    user_data[uid]['time_attack_active'] = True
    user_data[uid]['time_attack_start'] = time.time()
    user_data[uid]['time_attack_score'] = 0
    user_data[uid]['modes_played'].add('time_attack')
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
    db_update_best_ta(uid, score)
    row = db_get(uid)
    best = row[12] if row else score
    emoji = "🏆" if score >= 20 else "💪"
    msg = f"⏱ *Время вышло!*\nПравильных ответов: *{score}* за 60 сек! {emoji}\n🏅 Рекорд: {best}"
    bot.send_message(uid, msg, reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    check_achievements(uid, {
        'all_modes': len(user_data[uid].get('modes_played', set())) >= 5,
    })

def check_ta(uid, text):
    elapsed = time.time() - user_data[uid]['time_attack_start']
    if elapsed >= 60:
        end_time_attack(uid)
        return
    verb = user_data[uid].get('current_verb')
    if not verb:
        send_ta_q(uid)
        return
    accepted = get_accepted_translations(verb)
    user_input = normalize(text)
    correct = any(user_input == a or user_input in a or a in user_input for a in accepted)
    remaining = int(60 - elapsed)
    if correct:
        user_data[uid]['time_attack_score'] += 1
        bot.send_message(uid, f"✅ | ⏱ {remaining}с")
    else:
        bot.send_message(uid, f"❌ {ALL_STRICT_VERBS[verb]} | ⏱ {remaining}с")
    send_ta_q(uid)

# ─────────────────────────────────────────────
# REMINDER THREAD
# ─────────────────────────────────────────────
def reminder_loop():
    import datetime
    while True:
        now = datetime.datetime.now().strftime("%H:%M")
        reminders = db_get_all_reminders()
        for uid, reminder_time in reminders:
            if reminder_time == now:
                try:
                    # Check if user practiced today
                    row = db_get(uid)
                    if row:
                        last_active = row[9]
                        if last_active != str(date.today()):
                            bot.send_message(uid,
                                "⏰ *Напоминание!*\nТы ещё не практиковался сегодня. Не теряй серию! 🔥",
                                parse_mode='Markdown')
                except Exception:
                    pass
        time.sleep(60)

Thread(target=reminder_loop, daemon=True).start()

# ─────────────────────────────────────────────
# WORD OF THE DAY
# ─────────────────────────────────────────────
def word_of_day_loop():
    import datetime
    sent_today = set()
    while True:
        now = datetime.datetime.now()
        today = str(date.today())
        if now.hour == 9 and now.minute == 0:
            if today not in sent_today:
                sent_today.add(today)
                verb = get_random_verb()
                translation = ALL_STRICT_VERBS[verb]
                category = VERB_TO_CATEGORY.get(verb, '')
                cat_label = "Gerund (V-ing)" if category == 'gerund' else "Infinitive (to + V)"
                msg = (f"📖 *Глагол дня:*\n\n"
                       f"*{verb}* — {translation}\n"
                       f"Форма: {cat_label}\n\n"
                       f"_Зайди и попрактикуйся!_")
                for uid in db_get_all_users():
                    try:
                        bot.send_message(uid, msg, parse_mode='Markdown')
                    except Exception:
                        pass
        time.sleep(55)

Thread(target=word_of_day_loop, daemon=True).start()

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
    nickname = db_get_nickname(uid) or "не задан"
    bot.send_message(uid,
        f"👋 Привет!\n\n🏅 Уровень: {get_level_name(level)}\n"
        f"✏️ Никнейм: {nickname}\n"
        f"📅 Дней подряд: {daily_streak}\n\nВыбери режим:",
        reply_markup=main_menu_keyboard())

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    uid = message.chat.id
    admin_id = int(os.environ.get("ADMIN_ID", 0))
    if uid != admin_id:
        bot.send_message(uid, "⛔ Нет доступа.")
        return
    users = db_get_all_users()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT verb, SUM(wrong_count) as total FROM mistakes GROUP BY verb ORDER BY total DESC LIMIT 10")
    top_mistakes = c.fetchall()
    conn.close()
    msg = f"👑 *Админ-панель*\n\n👥 Пользователей: {len(users)}\n\n📋 *Топ сложных глаголов:*\n"
    for verb, count in top_mistakes:
        msg += f"• *{verb}* — {count} ошибок\n"
    bot.send_message(uid, msg, parse_mode='Markdown')

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

    # ── Никнейм ──
    if text == "✏️ Никнейм":
        current = db_get_nickname(uid)
        msg = f"Текущий никнейм: *{current}*\n\n" if current else "У тебя пока нет никнейма.\n\n"
        msg += "Напиши новый никнейм (до 20 символов):"
        user_data[uid]['mode'] = 'set_nickname'
        bot.send_message(uid, msg, reply_markup=back_keyboard(), parse_mode='Markdown')
        return

    if user_data[uid].get('mode') == 'set_nickname':
        if 1 <= len(text) <= 20:
            db_set_nickname(uid, text)
            user_data[uid]['mode'] = None
            bot.send_message(uid, f"✅ Никнейм установлен: *{text}*",
                             reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        else:
            bot.send_message(uid, "❌ Никнейм должен быть от 1 до 20 символов. Попробуй ещё раз:")
        return

    # ── Reminder setup ──
    if user_data[uid].get('mode') == 'set_reminder':
        import re
        if re.match(r'^\d{2}:\d{2}$', text):
            db_set_reminder(uid, text)
            user_data[uid]['mode'] = None
            bot.send_message(uid, f"⏰ Напоминание установлено на *{text}*",
                             reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        else:
            bot.send_message(uid, "❌ Формат: ЧЧ:ММ (например, 19:00)")
        return

    # ── Статистика ──
    if text == "📊 Статистика":
        row = db_get(uid)
        if not row:
            bot.send_message(uid, "Начни отвечать на вопросы!")
            return
        uid2, total, tr, gi, qz, irr, xp, level, best_streak, last_date, daily_streak, nickname, best_ta, reminder, weekly, weekly_reset = row
        xp_to_next = 100 - (xp % 100)
        nick_line = f"✏️ Никнейм: *{nickname}*\n" if nickname else ""

        # Weekly progress bar
        daily = db_get_daily_scores(uid, 7)
        chart = ""
        for d, s in daily:
            day_label = d[-5:]
            bar = "█" * min(s // 5, 10)
            chart += f"`{day_label}` {bar or '·'} {s}\n"

        achievements_count = len(db_get_achievements(uid))
        bot.send_message(uid,
            f"📊 *Статистика:*\n\n"
            f"{nick_line}"
            f"🏅 {get_level_name(level)}\n"
            f"⚡ XP: {xp} (до след. уровня: {xp_to_next})\n"
            f"📅 Дней подряд: {daily_streak}\n"
            f"🔥 Лучшая серия: {best_streak}\n"
            f"⏱ Рекорд таймер-атаки: {best_ta}\n"
            f"🏅 Достижений: {achievements_count}/{len(ACHIEVEMENTS)}\n\n"
            f"🎯 Всего: {total} | 📅 Неделя: {weekly}\n"
            f"📝 Перевод: {tr}  |  🔄 Gerund/Inf: {gi}\n"
            f"🎯 Викторина: {qz}  |  📚 Irregular: {irr}\n\n"
            f"📈 *График за 7 дней:*\n{chart}",
            parse_mode='Markdown')
        return

    # ── Достижения ──
    if text == "🏅 Достижения":
        earned = db_get_achievements(uid)
        msg = "🏅 *Достижения:*\n\n"
        for key, (name, desc) in ACHIEVEMENTS.items():
            if key in earned:
                msg += f"✅ {name} — _{desc}_\n"
            else:
                msg += f"🔒 {name} — _{desc}_\n"
        bot.send_message(uid, msg, parse_mode='Markdown')
        return

    # ── Мои ошибки ──
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

    # ── Лидерборд ──
    if text == "🏆 Лидерборд":
        bot.send_message(uid, "🏆 Выбери тип лидерборда:", reply_markup=leaderboard_keyboard())
        return

    # ── Настройки ──
    if text == "⚙️ Настройки":
        diff = user_data[uid].get('difficulty', 'normal')
        row = db_get(uid)
        reminder = row[13] if row else ''
        reminder_line = f"⏰ Напоминание: {reminder}" if reminder else "⏰ Напоминание: не задано"
        bot.send_message(uid,
            f"⚙️ Сложность: *{diff}*\n{reminder_line}\n\n"
            f"🟢 Легко — 5 XP\n🟡 Нормально — 10 XP\n🔴 Сложно — 20 XP",
            reply_markup=settings_keyboard(), parse_mode='Markdown')
        return

    if text == "⏰ Напоминание":
        user_data[uid]['mode'] = 'set_reminder'
        bot.send_message(uid, "Напиши время напоминания в формате ЧЧ:ММ (например, *19:00*):",
                         reply_markup=back_keyboard(), parse_mode='Markdown')
        return

    if text == "❌ Убрать напоминание":
        db_set_reminder(uid, '')
        bot.send_message(uid, "✅ Напоминание удалено.", reply_markup=main_menu_keyboard())
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

    # ── Выбор режима ──
    if text == "1. Перевод (вписать)":
        user_data[uid]['mode'] = 'translate'
        user_data[uid]['modes_played'].add('translate')
        send_translate_q(uid)
        return
    elif text == "2. Gerund или Infinitive":
        user_data[uid]['mode'] = 'ger_inf'
        user_data[uid]['modes_played'].add('ger_inf')
        send_ger_inf_q(uid)
        return
    elif text == "3. Выбор из 4 вариантов":
        user_data[uid]['mode'] = 'quiz'
        user_data[uid]['modes_played'].add('quiz')
        send_quiz_q(uid)
        return
    elif text == "4. Неправильные глаголы":
        user_data[uid]['modes_played'].add('irregular')
        start_irregular(uid)
        return
    elif text == "⏱ Таймер-атака":
        start_time_attack(uid)
        return
    elif text == "💀 Выживание":
        start_survival(uid)
        return

    # ── Обработка ответов ──
    mode = user_data[uid].get('mode')
    if mode == 'translate':
        check_translate(uid, text)
    elif mode == 'irregular_step':
        handle_irregular(uid, text)
    elif mode == 'time_attack':
        check_ta(uid, text)
    elif mode == 'survival':
        check_survival(uid, text)
    else:
        bot.send_message(uid, "Выбери режим через меню 👇", reply_markup=main_menu_keyboard())

# ─────────────────────────────────────────────
# CALLBACK HANDLERS
# ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    uid = call.message.chat.id
    if uid not in user_data:
        reset_user(uid)
    mode = user_data[uid].get('mode')

    # ── Leaderboard tabs ──
    if call.data in ("lb_alltime", "lb_weekly"):
        weekly = call.data == "lb_weekly"
        rows = db_leaderboard(weekly=weekly)
        title = "📅 Топ за неделю" if weekly else "🏆 Топ всех времён"
        if not rows:
            bot.answer_callback_query(call.id, "Лидерборд пуст!")
            return
        medals = ["🥇", "🥈", "🥉"]
        msg = f"*{title}:*\n\n"
        for i, (u, score, level) in enumerate(rows):
            medal = medals[i] if i < 3 else f"{i+1}."
            nickname = db_get_nickname(u) or f"Игрок {str(u)[-4:]}"
            marker = " ← ты" if u == uid else ""
            msg += f"{medal} *{nickname}* — {get_level_name(level)} — {score} очков{marker}\n"
        bot.edit_message_text(msg, uid, call.message.message_id,
                              parse_mode='Markdown', reply_markup=leaderboard_keyboard())
        bot.answer_callback_query(call.id)
        return

    # ── Gerund / Infinitive ──
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

    # ── Quiz ──
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

# ─────────────────────────────────────────────
# LAUNCH
# ─────────────────────────────────────────────
if __name__ == '__main__':
    logging.info("Бот стартовал")
    bot.infinity_polling(timeout=15, long_polling_timeout=5)