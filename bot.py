import telebot
from telebot import types
import logging
import random
import os

from data import GERUND_ONLY, INFINITIVE_ONLY, IRREGULAR_VERBS, ALL_STRICT_VERBS, VERB_TO_CATEGORY, get_random_verb

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.environ.get("BOT_TOKEN")

if not TOKEN:
    logging.error("❌ Ошибка: не установлена переменная BOT_TOKEN!")
    exit(1)

bot = telebot.TeleBot(TOKEN)
user_data = {}

# =========================
# СИСТЕМНЫЕ ФУНКЦИИ
# =========================

def reset_user(uid):
    user_data[uid] = {'score': 0, 'mode': None}

def normalize(text):
    return text.lower().strip()

def check_form(user_input, correct_form):
    user_input = normalize(user_input)
    correct_form = normalize(correct_form)

    if "/" in correct_form:
        variants = correct_form.split("/")
        return user_input in variants

    return user_input == correct_form


# =========================
# КЛАВИАТУРЫ
# =========================

def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton("1. Перевод (вписать)"),
        types.KeyboardButton("2. Gerund или Infinitive"),
        types.KeyboardButton("3. Выбор из 4 вариантов"),
        types.KeyboardButton("4. Неправильные глаголы (по шагам)")
    )
    markup.add(types.KeyboardButton("Статистика"))
    return markup

def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("Назад в меню"),
        types.KeyboardButton("Статистика")
    )
    return markup


# =========================
# ОБЫЧНЫЕ ВОПРОСЫ
# =========================

def send_translate_question(uid):
    verb = get_random_verb()
    user_data[uid]['current_verb'] = verb
    bot.send_message(
        uid,
        f"Переведи глагол на русский:\n\n**{verb}**",
        reply_markup=back_keyboard(),
        parse_mode='Markdown'
    )

def check_translate_answer(uid, text):
    verb = user_data[uid].get('current_verb')
    if not verb:
        return

    correct = ALL_STRICT_VERBS[verb].lower()

    if normalize(text) in correct:
        user_data[uid]['score'] += 1
        bot.send_message(uid, "Правильно! +1 ✅")
    else:
        bot.send_message(uid, f"Неправильно. Ответ: {ALL_STRICT_VERBS[verb]}")

    send_translate_question(uid)


def send_ger_inf_question(uid):
    verb = get_random_verb()
    user_data[uid]['current_verb'] = verb

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Infinitive (to + V)", callback_data="inf"),
        types.InlineKeyboardButton("Gerund (V-ing)", callback_data="ger")
    )

    bot.send_message(
        uid,
        f"После какого глагола нужна эта форма?\n\n**{verb}**",
        reply_markup=markup,
        parse_mode='Markdown'
    )


def send_quiz_question(uid):
    eng = get_random_verb()
    ru = ALL_STRICT_VERBS[eng]

    options = [eng] + random.sample([v for v in ALL_STRICT_VERBS if v != eng], 3)
    random.shuffle(options)

    user_data[uid]['correct_answer'] = eng

    markup = types.InlineKeyboardMarkup(row_width=1)
    for opt in options:
        markup.add(types.InlineKeyboardButton(opt, callback_data=opt))

    bot.send_message(
        uid,
        f"Какой глагол соответствует переводу:\n**{ru}**",
        reply_markup=markup,
        parse_mode='Markdown'
    )


# =========================
# НЕПРАВИЛЬНЫЕ ГЛАГОЛЫ (ПО ШАГАМ)
# =========================

def start_irregular_step_mode(uid):
    verb = random.choice(list(IRREGULAR_VERBS.keys()))
    v2, v3, ru = IRREGULAR_VERBS[verb]

    user_data[uid]['mode'] = 'irregular_step'
    user_data[uid]['irregular_data'] = {
        'v1': verb,
        'v2': v2,
        'v3': v3,
        'ru': ru,
        'step': 1
    }

    bot.send_message(
        uid,
        f"Переведи на английский (V1):\n\n**{ru}**",
        reply_markup=back_keyboard(),
        parse_mode="Markdown"
    )


def handle_irregular_step(uid, text):
    data = user_data[uid]['irregular_data']
    step = data['step']
    user_input = normalize(text)

    if step == 1:
        if check_form(user_input, data['v1']):
            data['step'] = 2
            bot.send_message(uid, "✅ Правильно!\nТеперь напиши V2:")
        else:
            bot.send_message(uid, f"❌ Неправильно.\nПравильный ответ: {data['v1']}")
            start_irregular_step_mode(uid)

    elif step == 2:
        if check_form(user_input, data['v2']):
            data['step'] = 3
            bot.send_message(uid, "✅ Верно!\nТеперь напиши V3:")
        else:
            bot.send_message(uid, f"❌ Неправильно.\nПравильный ответ: {data['v2']}")
            start_irregular_step_mode(uid)

    elif step == 3:
        if check_form(user_input, data['v3']):
            user_data[uid]['score'] += 1
            bot.send_message(uid, "🔥 Всё правильно! +1 балл")
        else:
            bot.send_message(uid, f"❌ Неправильно.\nПравильный ответ: {data['v3']}")

        start_irregular_step_mode(uid)


# =========================
# ОБРАБОТЧИКИ
# =========================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.chat.id
    reset_user(uid)
    bot.send_message(uid, "Привет! Выбери режим:", reply_markup=main_menu_keyboard())


@bot.message_handler(func=lambda m: m.text in ["Назад в меню", "назад", "меню"])
def back_to_menu(message):
    uid = message.chat.id
    user_data[uid]['mode'] = None
    bot.send_message(uid, "Главное меню:", reply_markup=main_menu_keyboard())


@bot.message_handler(func=lambda m: True)
def main_handler(message):
    uid = message.chat.id
    text = message.text.strip()

    if uid not in user_data:
        reset_user(uid)

    if text == "Статистика":
        bot.send_message(uid, f"Твой счёт: {user_data[uid]['score']}")
        return

    if text == "1. Перевод (вписать)":
        user_data[uid]['mode'] = 'translate'
        send_translate_question(uid)
        return

    elif text == "2. Gerund или Infinitive":
        user_data[uid]['mode'] = 'ger_inf'
        send_ger_inf_question(uid)
        return

    elif text == "3. Выбор из 4 вариантов":
        user_data[uid]['mode'] = 'quiz'
        send_quiz_question(uid)
        return

    elif text == "4. Неправильные глаголы (по шагам)":
        start_irregular_step_mode(uid)
        return

    mode = user_data[uid].get('mode')

    if mode == 'translate':
        check_translate_answer(uid, text)

    elif mode == 'irregular_step':
        handle_irregular_step(uid, text)

    else:
        bot.send_message(uid, "Выбери режим через меню 👇", reply_markup=back_keyboard())


@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    uid = call.message.chat.id
    mode = user_data[uid]['mode']

    if mode == 'ger_inf':
        verb = user_data[uid]['current_verb']
        correct_cat = VERB_TO_CATEGORY[verb]
        correct = 'inf' if correct_cat == 'infinitive' else 'ger'

        if call.data == correct:
            user_data[uid]['score'] += 1
            bot.answer_callback_query(call.id, "Правильно! ✅")
        else:
            bot.answer_callback_query(call.id, f"Неправильно. Ответ: {correct_cat}")

        send_ger_inf_question(uid)

    elif mode == 'quiz':
        correct = user_data[uid]['correct_answer']

        if call.data == correct:
            user_data[uid]['score'] += 1
            bot.answer_callback_query(call.id, "Верно! +1 ✅")
        else:
            bot.answer_callback_query(call.id, f"Неправильно. Ответ: {correct}")

        send_quiz_question(uid)


# =========================
# ЗАПУСК
# =========================

if __name__ == '__main__':
    logging.info("Бот стартовал")
    bot.infinity_polling(timeout=15, long_polling_timeout=5)