import telebot
from telebot import types
import logging
import random
import os
import time
import re
import datetime
from datetime import date, timedelta
from threading import Thread, Lock

from data import (GERUND_ONLY, INFINITIVE_ONLY, IRREGULAR_VERBS,
                  ALL_STRICT_VERBS, VERB_TO_CATEGORY,
                  get_random_verb, get_accepted_translations)
from database import (
    init_db,
    db_ensure, db_get, db_add_score,
    db_update_best_streak, db_update_best_ta,
    db_update_daily, db_reset_weekly_if_needed,
    db_set_nickname, db_get_nickname,
    db_set_reminder, db_get_all_reminders,
    db_get_all_users, db_leaderboard,
    db_get_daily_scores,
    db_add_mistake, db_get_mistakes, db_get_global_top_mistakes,
    db_give_achievement, db_get_achievements,
    db_export_path, db_stats_summary,
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logging.error("BOT_TOKEN not set!")
    exit(1)

ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

bot = telebot.TeleBot(TOKEN)
init_db()

ACHIEVEMENTS = {
    'first_correct':  ('🌟 Первый шаг',   'Ответь правильно 1 раз'),
    'score_100':      ('💯 Сотня',         'Набери 100 очков'),
    'score_500':      ('🚀 Пятьсот',       'Набери 500 очков'),
    'score_1000':     ('💎 Тысячник',      'Набери 1000 очков'),
    'streak_5':       ('🔥 Серия x5',      '5 правильных подряд'),
    'streak_10':      ('⚡ Серия x10',     '10 правильных подряд'),
    'streak_20':      ('🌪️ Серия x20',    '20 правильных подряд'),
    'streak_50':      ('👑 Серия x50',     '50 правильных подряд'),
    'daily_3':        ('📅 3 дня подряд',  'Заходи 3 дня подряд'),
    'daily_7':        ('🗓️ Неделя',        'Заходи 7 дней подряд'),
    'daily_30':       ('🏆 Месяц',         'Заходи 30 дней подряд'),
    'time_attack_10': ('⏱️ Быстрый',       '10+ правильных в таймер-атаке'),
    'time_attack_20': ('⚡ Молния',        '20+ правильных в таймер-атаке'),
    'time_attack_30': ('🚀 Ракета',        '30+ правильных в таймер-атаке'),
    'level_2':        ('📖 Ученик',        'Достигни 2 уровня'),
    'level_5':        ('💎 Эксперт',       'Достигни 5 уровня'),
    'survival_10':    ('🛡️ Выживший',     'Доживи до 10 вопроса в выживании'),
    'survival_25':    ('⚔️ Воин',         'Доживи до 25 вопроса в выживании'),
    'mistakes_clean': ('✨ Без ошибок',    'Ответь на 10 вопросов без ошибок'),
    'all_modes':      ('🎯 Мультиплеер',   'Сыграй во все режимы'),
}


def notify_achievement(uid, key):
    name, desc = ACHIEVEMENTS[key]
    bot.send_message(uid, f"🏅 *Новое достижение!*\n{name}\n_{desc}_",
                     parse_mode='Markdown')


def check_achievements(uid, context):
    earned = db_get_achievements(uid)
    row = db_get(uid)
    if not row:
        return
    checks = [
        ('first_correct',  row['total_score'] >= 1),
        ('score_100',      row['total_score'] >= 100),
        ('score_500',      row['total_score'] >= 500),
        ('score_1000',     row['total_score'] >= 1000),
        ('streak_5',       row['best_streak'] >= 5),
        ('streak_10',      row['best_streak'] >= 10),
        ('streak_20',      row['best_streak'] >= 20),
        ('streak_50',      row['best_streak'] >= 50),
        ('daily_3',        row['daily_streak'] >= 3),
        ('daily_7',        row['daily_streak'] >= 7),
        ('daily_30',       row['daily_streak'] >= 30),
        ('time_attack_10', row['best_time_attack'] >= 10),
        ('time_attack_20', row['best_time_attack'] >= 20),
        ('time_attack_30', row['best_time_attack'] >= 30),
        ('level_2',        row['level'] >= 2),
        ('level_5',        row['level'] >= 5),
        ('survival_10',    context.get('survival_q', 0) >= 10),
        ('survival_25',    context.get('survival_q', 0) >= 25),
        ('mistakes_clean', context.get('clean_streak', 0) >= 10),
        ('all_modes',      context.get('all_modes', False)),
    ]
    for key, condition in checks:
        if condition and key not in earned:
            if db_give_achievement(uid, key):
                notify_achievement(uid, key)


# ── Session state ──────────────────────────────
user_data = {}
_ud_lock = Lock()


def get_ud(uid):
    with _ud_lock:
        if uid not in user_data:
            _init_ud(uid)
        return user_data[uid]


def _init_ud(uid):
    user_data[uid] = {
        'mode': None, 'streak': 0, 'clean_streak': 0,
        'session_correct': 0, 'session_wrong': 0,
        'session_mistakes': [], 'session_count': 0,
        'difficulty': 'normal',
        'time_attack_active': False, 'time_attack_start': None,
        'time_attack_score': 0,
        'current_verb': None, 'correct_answer': None,
        'irregular_data': None,
        'survival_lives': 3, 'survival_q': 0,
        'modes_played': set(),
    }


def reset_user(uid):
    db_ensure(uid)
    db_update_daily(uid)
    db_reset_weekly_if_needed(uid)
    with _ud_lock:
        _init_ud(uid)


# ── Utilities ──────────────────────────────────
def normalize(text):
    return text.lower().strip()


def check_form(user_input, correct_form):
    return normalize(user_input) in normalize(correct_form).split("/")


def check_translation(user_input, accepted):
    """Exact match only — prevents 'do' matching 'redo'."""
    inp = normalize(user_input)
    return inp in [normalize(a) for a in accepted]


def get_level_name(level):
    names = {1: "🌱 Новичок", 2: "📖 Ученик", 3: "⚡ Знаток",
             4: "🔥 Мастер", 5: "💎 Эксперт"}
    return names.get(min(level, 5), f"🏆 Легенда ({level})")


def get_xp(uid):
    ud = get_ud(uid)
    base = {'easy': 5, 'normal': 10, 'hard': 20}.get(ud.get('difficulty', 'normal'), 10)
    return base + min(ud.get('streak', 0) // 5, 5) * 5


def get_weighted_verb(uid):
    mistakes = db_get_mistakes(uid, limit=20)
    candidates = [m[0] for m in mistakes if m[0] in ALL_STRICT_VERBS]
    if candidates and random.random() < 0.3:
        return random.choice(candidates)
    return get_random_verb()


# ── Keyboards ──────────────────────────────────
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


def settings_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add("🟢 Легко", "🟡 Нормально", "🔴 Сложно")
    m.add("⏰ Напоминание", "❌ Убрать напоминание")
    m.add("Назад в меню")
    return m


def leaderboard_keyboard():
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(
        types.InlineKeyboardButton("🏆 Всё время",  callback_data="lb_alltime"),
        types.InlineKeyboardButton("📅 Эта неделя", callback_data="lb_weekly"),
    )
    return m


# ── Correct / Wrong helpers ────────────────────
def on_correct(uid, score_type):
    ud = get_ud(uid)
    ud['streak'] += 1
    ud['clean_streak'] += 1
    ud['session_correct'] += 1
    ud['session_count'] += 1
    xp = get_xp(uid)
    new_level = db_add_score(uid, **{score_type: 1, 'total': 1, 'xp': xp})
    db_update_best_streak(uid, ud['streak'])
    msg = f"✅ Правильно! +1  (XP +{xp})"
    if ud['streak'] > 1:
        msg += f"\n🔥 Серия: {ud['streak']}"
    if ud['streak'] in (5, 10, 20, 50):
        msg += f"\n🎉 {ud['streak']} ответов подряд!"
    if new_level:
        msg += f"\n\n⬆️ Новый уровень: {get_level_name(new_level)}!"
    check_achievements(uid, {
        'clean_streak': ud['clean_streak'],
        'survival_q': ud.get('survival_q', 0),
        'all_modes': len(ud.get('modes_played', set())) >= 6,
    })
    return msg


def on_wrong(uid, verb, correct):
    ud = get_ud(uid)
    ud['streak'] = 0
    ud['clean_streak'] = 0
    ud['session_wrong'] += 1
    ud['session_count'] += 1
    ud['session_mistakes'].append((verb, correct))
    db_add_mistake(uid, verb)
    return f"❌ Неправильно. Правильный ответ: *{correct}*"


def maybe_summary(uid):
    ud = get_ud(uid)
    count = ud['session_count']
    if count > 0 and count % 10 == 0:
        c, w = ud['session_correct'], ud['session_wrong']
        pct = int(c / count * 100)
        msg = f"📊 *Итог за {count} вопросов:* ✅{c} ❌{w} ({pct}%)\n"
        recent = ud['session_mistakes'][-5:]
        if recent:
            msg += "\n*Последние ошибки:*\n"
            for v, ans in recent:
                msg += f"• {v} → {ans}\n"
        bot.send_message(uid, msg, parse_mode='Markdown')


# ── Translation mode ───────────────────────────
def send_translate_q(uid):
    verb = get_weighted_verb(uid)
    get_ud(uid)['current_verb'] = verb
    bot.send_message(uid, f"Переведи глагол на русский:\n\n*{verb}*",
                     reply_markup=back_keyboard(), parse_mode='Markdown')


def check_translate(uid, text):
    verb = get_ud(uid).get('current_verb')
    if not verb:
        send_translate_q(uid)
        return
    if check_translation(text, get_accepted_translations(verb)):
        msg = on_correct(uid, 'translate')
    else:
        msg = on_wrong(uid, verb, ALL_STRICT_VERBS[verb])
    bot.send_message(uid, msg, parse_mode='Markdown')
    maybe_summary(uid)
    send_translate_q(uid)


# ── Gerund / Infinitive mode ───────────────────
def send_ger_inf_q(uid):
    verb = get_weighted_verb(uid)
    get_ud(uid)['current_verb'] = verb
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Infinitive (to + V)", callback_data="gi_inf"),
        types.InlineKeyboardButton("Gerund (V-ing)",      callback_data="gi_ger"),
    )
    bot.send_message(uid, f"После какого глагола нужна эта форма?\n\n*{verb}*",
                     reply_markup=markup, parse_mode='Markdown')


# ── Quiz mode ──────────────────────────────────
def send_quiz_q(uid):
    eng = get_weighted_verb(uid)
    options = [eng] + random.sample([v for v in ALL_STRICT_VERBS if v != eng], 3)
    random.shuffle(options)
    get_ud(uid)['correct_answer'] = eng
    markup = types.InlineKeyboardMarkup(row_width=1)
    for opt in options:
        markup.add(types.InlineKeyboardButton(opt, callback_data=f"qz_{opt}"))
    bot.send_message(uid, f"Какой глагол соответствует переводу:\n*{ALL_STRICT_VERBS[eng]}*",
                     reply_markup=markup, parse_mode='Markdown')


# ── Irregular verbs mode ───────────────────────
def start_irregular(uid):
    verb = random.choice(list(IRREGULAR_VERBS.keys()))
    v2, v3, ru = IRREGULAR_VERBS[verb]
    ud = get_ud(uid)
    ud['mode'] = 'irregular_step'
    ud['irregular_data'] = {'v1': verb, 'v2': v2, 'v3': v3, 'ru': ru, 'step': 1}
    bot.send_message(uid, f"Переведи на английский (V1):\n\n*{ru}*",
                     reply_markup=back_keyboard(), parse_mode='Markdown')


def handle_irregular(uid, text):
    ud = get_ud(uid)
    data = ud['irregular_data']
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


# ── Survival mode ──────────────────────────────
def start_survival(uid):
    ud = get_ud(uid)
    ud['mode'] = 'survival'
    ud['survival_lives'] = 3
    ud['survival_q'] = 0
    ud['modes_played'].add('survival')
    bot.send_message(uid,
        "💀 *Режим выживания!*\nУ тебя 3 жизни ❤️❤️❤️\n"
        "Одна ошибка — минус жизнь.\nСколько продержишься?",
        reply_markup=back_keyboard(), parse_mode='Markdown')
    send_survival_q(uid)


def send_survival_q(uid):
    verb = get_weighted_verb(uid)
    ud = get_ud(uid)
    ud['current_verb'] = verb
    lives = ud['survival_lives']
    hearts = '❤️' * lives + '🖤' * (3 - lives)
    bot.send_message(uid,
        f"{hearts} | Вопрос {ud['survival_q'] + 1}\n\nПереведи на русский:\n\n*{verb}*",
        parse_mode='Markdown')


def check_survival(uid, text):
    ud = get_ud(uid)
    verb = ud.get('current_verb')
    if not verb:
        send_survival_q(uid)
        return
    if check_translation(text, get_accepted_translations(verb)):
        ud['survival_q'] += 1
        ud['streak'] += 1
        ud['clean_streak'] += 1
        xp = get_xp(uid)
        db_add_score(uid, total=1, translate=1, xp=xp)
        db_update_best_streak(uid, ud['streak'])
        hearts = '❤️' * ud['survival_lives'] + '🖤' * (3 - ud['survival_lives'])
        bot.send_message(uid, f"✅ Правильно! (XP +{xp})\n{hearts} | Вопросов: {ud['survival_q']}")
        check_achievements(uid, {
            'survival_q': ud['survival_q'],
            'clean_streak': ud['clean_streak'],
            'all_modes': len(ud.get('modes_played', set())) >= 6,
        })
        send_survival_q(uid)
    else:
        ud['survival_lives'] -= 1
        ud['streak'] = 0
        ud['clean_streak'] = 0
        db_add_mistake(uid, verb)
        lives = ud['survival_lives']
        hearts = '❤️' * lives + '🖤' * (3 - lives)
        bot.send_message(uid,
            f"❌ Неправильно. Ответ: *{ALL_STRICT_VERBS[verb]}*\n{hearts}",
            parse_mode='Markdown')
        if lives <= 0:
            q = ud['survival_q']
            ud['mode'] = None
            bot.send_message(uid,
                f"💀 *Игра окончена!*\nТы ответил правильно на *{q}* вопросов "
                f"{'🏆' if q >= 25 else '💪'}",
                reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        else:
            send_survival_q(uid)


# ── Time attack mode ───────────────────────────
def start_time_attack(uid):
    ud = get_ud(uid)
    ud['mode'] = 'time_attack'
    ud['time_attack_active'] = True
    ud['time_attack_start'] = time.time()
    ud['time_attack_score'] = 0
    ud['modes_played'].add('time_attack')
    bot.send_message(uid,
        "⏱ *Таймер-атака!*\n60 секунд. Переводи глаголы на русский как можно быстрее!",
        reply_markup=back_keyboard(), parse_mode='Markdown')
    send_ta_q(uid)


def send_ta_q(uid):
    ud = get_ud(uid)
    elapsed = time.time() - ud['time_attack_start']
    if elapsed >= 60:
        end_time_attack(uid)
        return
    ud['current_verb'] = get_random_verb()
    bot.send_message(uid,
        f"⏱ *{int(60 - elapsed)}с* | *{ud['current_verb']}*",
        parse_mode='Markdown')


def end_time_attack(uid):
    ud = get_ud(uid)
    score = ud.get('time_attack_score', 0)
    ud['time_attack_active'] = False
    ud['mode'] = None
    db_update_best_ta(uid, score)
    row = db_get(uid)
    best = row['best_time_attack'] if row else score
    bot.send_message(uid,
        f"⏱ *Время вышло!*\nПравильных ответов: *{score}* за 60 сек! "
        f"{'🏆' if score >= 20 else '💪'}\n🏅 Рекорд: {best}",
        reply_markup=main_menu_keyboard(), parse_mode='Markdown')
    check_achievements(uid, {'all_modes': len(ud.get('modes_played', set())) >= 6})


def check_ta(uid, text):
    ud = get_ud(uid)
    elapsed = time.time() - ud['time_attack_start']
    if elapsed >= 60:
        end_time_attack(uid)
        return
    verb = ud.get('current_verb')
    if not verb:
        send_ta_q(uid)
        return
    remaining = int(60 - elapsed)
    if check_translation(text, get_accepted_translations(verb)):
        ud['time_attack_score'] += 1
        bot.send_message(uid, f"✅ | ⏱ {remaining}с")
    else:
        bot.send_message(uid, f"❌ {ALL_STRICT_VERBS[verb]} | ⏱ {remaining}с")
    send_ta_q(uid)


# ── Background threads ─────────────────────────
def reminder_loop():
    while True:
        now = datetime.datetime.now().strftime("%H:%M")
        for uid, reminder_time in db_get_all_reminders():
            if reminder_time == now:
                try:
                    row = db_get(uid)
                    if row and row['last_active_date'] != str(date.today()):
                        bot.send_message(uid,
                            "⏰ *Напоминание!*\nТы ещё не практиковался сегодня. "
                            "Не теряй серию! 🔥", parse_mode='Markdown')
                except Exception as e:
                    logging.warning(f"Reminder error {uid}: {e}")
        time.sleep(60)


def word_of_day_loop():
    sent_today = set()
    while True:
        now = datetime.datetime.now()
        today = str(date.today())
        if now.hour == 9 and now.minute == 0 and today not in sent_today:
            sent_today.add(today)
            verb = get_random_verb()
            cat = VERB_TO_CATEGORY.get(verb, '')
            msg = (f"📖 *Глагол дня:*\n\n"
                   f"*{verb}* — {ALL_STRICT_VERBS[verb]}\n"
                   f"Форма: {'Gerund (V-ing)' if cat == 'gerund' else 'Infinitive (to + V)'}\n\n"
                   f"_Зайди и попрактикуйся!_")
            for uid in db_get_all_users():
                try:
                    bot.send_message(uid, msg, parse_mode='Markdown')
                except Exception as e:
                    logging.warning(f"Word-of-day error {uid}: {e}")
        time.sleep(55)


Thread(target=reminder_loop,   daemon=True).start()
Thread(target=word_of_day_loop, daemon=True).start()


# ── Command handlers ───────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.chat.id
    reset_user(uid)
    daily_streak = db_update_daily(uid)
    row = db_get(uid)
    bot.send_message(uid,
        f"👋 Привет!\n\n🏅 Уровень: {get_level_name(row['level'] if row else 1)}\n"
        f"✏️ Никнейм: {db_get_nickname(uid) or 'не задан'}\n"
        f"📅 Дней подряд: {daily_streak}\n\nВыбери режим:",
        reply_markup=main_menu_keyboard())


def _is_admin(uid):
    return ADMIN_ID != 0 and uid == ADMIN_ID


@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    uid = message.chat.id
    if ADMIN_ID == 0:
        bot.send_message(uid,
            f"⚠️ ADMIN\\_ID не задан.\n"
            f"Твой Telegram ID: `{uid}`\n"
            f"Установи переменную: `export ADMIN_ID={uid}`",
            parse_mode='Markdown')
        return
    if not _is_admin(uid):
        bot.send_message(uid, "⛔ Нет доступа.")
        return
    try:
        s = db_stats_summary()
        msg = (f"👑 *Админ-панель*\n\n"
               f"👥 Пользователей: {s['users']}\n"
               f"🏅 Достижений выдано: {s['achievements']}\n"
               f"📋 Ошибок записано: {s['mistakes_total']}\n\n"
               f"📋 *Топ сложных глаголов:*\n")
        for verb, count in s['top_mistakes']:
            msg += f"• *{verb}* — {count} ошибок\n"
        msg += "\n📥 /db — скачать БД\n📣 /broadcast <текст> — рассылка"
        bot.send_message(uid, msg, parse_mode='Markdown')
    except Exception as e:
        logging.exception("Admin panel error")
        bot.send_message(uid, f"❌ Ошибка: `{e}`", parse_mode='Markdown')


@bot.message_handler(commands=['db'])
def cmd_db(message):
    uid = message.chat.id
    if not _is_admin(uid):
        bot.send_message(uid, "⛔ Нет доступа.")
        return
    path = db_export_path()
    if not os.path.exists(path):
        bot.send_message(uid, "❌ Файл БД не найден.")
        return
    with open(path, 'rb') as f:
        bot.send_document(uid, f,
            caption=f"🗄 `{path}` — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            parse_mode='Markdown')


@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    uid = message.chat.id
    if not _is_admin(uid):
        bot.send_message(uid, "⛔ Нет доступа.")
        return
    text = message.text.partition(' ')[2].strip()
    if not text:
        bot.send_message(uid, "Использование: /broadcast <текст>")
        return
    sent = failed = 0
    for target in db_get_all_users():
        try:
            bot.send_message(target, text)
            sent += 1
        except Exception:
            failed += 1
    bot.send_message(uid,
        f"📣 Рассылка завершена.\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")


@bot.message_handler(func=lambda m: m.text in ("Назад в меню", "назад", "меню"))
def back_to_menu(message):
    uid = message.chat.id
    ud = get_ud(uid)
    ud['mode'] = None
    ud['time_attack_active'] = False
    bot.send_message(uid, "Главное меню:", reply_markup=main_menu_keyboard())


@bot.message_handler(func=lambda m: True)
def main_handler(message):
    uid = message.chat.id
    text = message.text.strip()
    ud = get_ud(uid)

    # Nickname input
    if text == "✏️ Никнейм":
        current = db_get_nickname(uid)
        ud['mode'] = 'set_nickname'
        prefix = f"Текущий никнейм: *{current}*\n\n" if current else ""
        bot.send_message(uid, prefix + "Напиши новый никнейм (до 20 символов):",
                         reply_markup=back_keyboard(), parse_mode='Markdown')
        return
    if ud.get('mode') == 'set_nickname':
        if 1 <= len(text) <= 20:
            db_set_nickname(uid, text)
            ud['mode'] = None
            bot.send_message(uid, f"✅ Никнейм установлен: *{text}*",
                             reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        else:
            bot.send_message(uid, "❌ Никнейм: от 1 до 20 символов. Попробуй ещё раз:")
        return

    # Reminder input
    if ud.get('mode') == 'set_reminder':
        if re.match(r'^\d{2}:\d{2}$', text):
            db_set_reminder(uid, text)
            ud['mode'] = None
            bot.send_message(uid, f"⏰ Напоминание установлено на *{text}*",
                             reply_markup=main_menu_keyboard(), parse_mode='Markdown')
        else:
            bot.send_message(uid, "❌ Формат: ЧЧ:ММ (например, 19:00)")
        return

    # Stats
    if text == "📊 Статистика":
        row = db_get(uid)
        if not row:
            bot.send_message(uid, "Начни отвечать на вопросы!")
            return
        xp = row['xp']
        xp_to_next = 100 - (xp % 100)
        nick_line = f"✏️ Никнейм: *{row['nickname']}*\n" if row['nickname'] else ""
        daily = db_get_daily_scores(uid, 7)
        chart = "".join(
            f"`{d[-5:]}` {'█' * min(s // 5, 10) or '·'} {s}\n"
            for d, s in daily
        )
        ach_count = len(db_get_achievements(uid))
        bot.send_message(uid,
            f"📊 *Статистика:*\n\n"
            f"{nick_line}"
            f"🏅 {get_level_name(row['level'])}\n"
            f"⚡ XP: {xp} (до след. уровня: {xp_to_next})\n"
            f"📅 Дней подряд: {row['daily_streak']}\n"
            f"🔥 Лучшая серия: {row['best_streak']}\n"
            f"⏱ Рекорд таймер-атаки: {row['best_time_attack']}\n"
            f"🏅 Достижений: {ach_count}/{len(ACHIEVEMENTS)}\n\n"
            f"🎯 Всего: {row['total_score']} | 📅 Неделя: {row['weekly_score']}\n"
            f"📝 Перевод: {row['translate_score']}  |  🔄 Gerund/Inf: {row['ger_inf_score']}\n"
            f"🎯 Викторина: {row['quiz_score']}  |  📚 Irregular: {row['irregular_score']}\n\n"
            f"📈 *График за 7 дней:*\n{chart}",
            parse_mode='Markdown')
        return

    if text == "🏅 Достижения":
        earned = db_get_achievements(uid)
        msg = "🏅 *Достижения:*\n\n" + "".join(
            f"{'✅' if k in earned else '🔒'} {name} — _{desc}_\n"
            for k, (name, desc) in ACHIEVEMENTS.items()
        )
        bot.send_message(uid, msg, parse_mode='Markdown')
        return

    if text == "📋 Мои ошибки":
        mistakes = db_get_mistakes(uid)
        if not mistakes:
            bot.send_message(uid, "Ошибок пока нет. Так держать!")
            return
        msg = "📋 *Частые ошибки:*\n\n" + "".join(
            f"• *{v}* ({ALL_STRICT_VERBS.get(v, '?')}) — {c}×\n"
            for v, c in mistakes
        )
        bot.send_message(uid, msg, parse_mode='Markdown')
        return

    if text == "🏆 Лидерборд":
        bot.send_message(uid, "🏆 Выбери тип лидерборда:", reply_markup=leaderboard_keyboard())
        return

    if text == "⚙️ Настройки":
        row = db_get(uid)
        reminder = row['reminder_time'] if row else ''
        reminder_line = f"⏰ Напоминание: {reminder}" if reminder else "⏰ Напоминание: не задано"
        bot.send_message(uid,
            f"⚙️ Сложность: *{ud.get('difficulty','normal')}*\n{reminder_line}\n\n"
            f"🟢 Легко — 5 XP\n🟡 Нормально — 10 XP\n🔴 Сложно — 20 XP",
            reply_markup=settings_keyboard(), parse_mode='Markdown')
        return

    if text == "⏰ Напоминание":
        ud['mode'] = 'set_reminder'
        bot.send_message(uid, "Напиши время напоминания в формате ЧЧ:ММ (например, *19:00*):",
                         reply_markup=back_keyboard(), parse_mode='Markdown')
        return
    if text == "❌ Убрать напоминание":
        db_set_reminder(uid, '')
        bot.send_message(uid, "✅ Напоминание удалено.", reply_markup=main_menu_keyboard())
        return

    difficulty_map = {"🟢 Легко": "easy", "🟡 Нормально": "normal", "🔴 Сложно": "hard"}
    if text in difficulty_map:
        ud['difficulty'] = difficulty_map[text]
        bot.send_message(uid, f"Сложность: {text}", reply_markup=main_menu_keyboard())
        return

    # Mode selection
    mode_map = {
        "1. Перевод (вписать)":    ('translate',  lambda: send_translate_q(uid)),
        "2. Gerund или Infinitive": ('ger_inf',    lambda: send_ger_inf_q(uid)),
        "3. Выбор из 4 вариантов": ('quiz',       lambda: send_quiz_q(uid)),
        "4. Неправильные глаголы": ('irregular',  lambda: start_irregular(uid)),
        "⏱ Таймер-атака":          ('time_attack', lambda: start_time_attack(uid)),
        "💀 Выживание":            ('survival',   lambda: start_survival(uid)),
    }
    if text in mode_map:
        mode_key, action = mode_map[text]
        if mode_key not in ('time_attack', 'survival'):
            ud['mode'] = mode_key
        ud['modes_played'].add(mode_key)
        action()
        return

    # Answer routing
    mode = ud.get('mode')
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


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    uid = call.message.chat.id
    ud = get_ud(uid)
    mode = ud.get('mode')

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
            nick = db_get_nickname(u) or f"Игрок {str(u)[-4:]}"
            msg += (f"{medal} *{nick}* — {get_level_name(level)} — "
                    f"{score} очков{' ← ты' if u == uid else ''}\n")
        bot.edit_message_text(msg, uid, call.message.message_id,
                              parse_mode='Markdown', reply_markup=leaderboard_keyboard())
        bot.answer_callback_query(call.id)
        return

    if mode == 'ger_inf' and call.data.startswith("gi_"):
        verb = ud['current_verb']
        correct_cat = VERB_TO_CATEGORY[verb]
        correct_cb = 'gi_inf' if correct_cat == 'infinitive' else 'gi_ger'
        if call.data == correct_cb:
            msg = on_correct(uid, 'ger_inf')
            bot.answer_callback_query(call.id, "✅ Правильно!")
            bot.send_message(uid, msg, parse_mode='Markdown')
        else:
            on_wrong(uid, verb, correct_cat)
            bot.answer_callback_query(call.id, f"❌ Ответ: {correct_cat}")
        maybe_summary(uid)
        send_ger_inf_q(uid)

    elif mode == 'quiz' and call.data.startswith("qz_"):
        correct = ud['correct_answer']
        selected = call.data[3:]
        if selected == correct:
            msg = on_correct(uid, 'quiz')
            bot.answer_callback_query(call.id, "✅ Верно!")
            bot.send_message(uid, msg, parse_mode='Markdown')
        else:
            # BUG FIX: record mistake against the correct verb, not the selected one
            on_wrong(uid, correct, correct)
            bot.answer_callback_query(call.id, f"❌ Ответ: {correct}")
        maybe_summary(uid)
        send_quiz_q(uid)


if __name__ == '__main__':
    logging.info("Бот стартовал")
    bot.infinity_polling(timeout=15, long_polling_timeout=5)