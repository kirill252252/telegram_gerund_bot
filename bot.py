import telebot
from telebot import types
import logging
import random
import os

from data import GERUND_ONLY, INFINITIVE_ONLY, IRREGULAR_VERBS, ALL_STRICT_VERBS, VERB_TO_CATEGORY, get_random_verb

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --------- Токен с сервера ---------
TOKEN = os.environ.get("BOT_TOKEN")  # Берём токен с переменной окружения

if not TOKEN:
    logging.error("❌ Ошибка: на сервере не установлена переменная BOT_TOKEN!")
    exit(1)  # корректно завершаем скрипт

bot = telebot.TeleBot(TOKEN)
user_data = {}

# ---- Функции ----
def reset_user(uid):
    user_data[uid] = {'score': 0, 'mode': None}

def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton("1. Перевод (вписать)"),
        types.KeyboardButton("2. Gerund или Infinitive"),
        types.KeyboardButton("3. Выбор из 4 вариантов")
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

# ---- Вопросы ----
def send_translate_question(uid):
    verb = get_random_verb()
    user_data[uid]['current_verb'] = verb
    bot.send_message(uid,
                     f"Переведи глагол на русский:\n\n**{verb}**",
                     reply_markup=back_keyboard(),
                     parse_mode='Markdown')

def check_translate_answer(uid, text):
    verb = user_data[uid].get('current_verb')
    if not verb:
        return
    correct = ALL_STRICT_VERBS[verb].lower()
    if text.lower() in correct or correct.startswith(text.lower()):
        user_data[uid]['score'] += 1
        bot.send_message(uid, "Правильно! +1 ✅", parse_mode='Markdown')
    else:
        bot.send_message(uid, f"Неправильно. Правильный ответ: **{ALL_STRICT_VERBS[verb]}**",
                         parse_mode='Markdown')
    send_translate_question(uid)

def send_ger_inf_question(uid):
    verb = get_random_verb()
    user_data[uid]['current_verb'] = verb
    user_data[uid]['attempts'] = 0

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("Infinitive (to + V)", callback_data="inf"),
        types.InlineKeyboardButton("Gerund (V-ing)", callback_data="ger")
    )

    bot.send_message(uid,
                     f"После какого глагола нужна эта форма?\n\n**{verb}**",
                     reply_markup=markup,
                     parse_mode='Markdown')

def send_quiz_question(uid):
    eng = get_random_verb()
    ru = ALL_STRICT_VERBS[eng]
    correct = eng

    options = [correct] + random.sample([v for v in ALL_STRICT_VERBS if v != correct], 3)
    random.shuffle(options)
    user_data[uid]['correct_answer'] = correct

    markup = types.InlineKeyboardMarkup(row_width=1)
    for opt in options:
        markup.add(types.InlineKeyboardButton(opt, callback_data=opt))

    bot.send_message(uid,
                     f"Какой глагол соответствует переводу:\n**{ru}**",
                     reply_markup=markup,
                     parse_mode='Markdown')

# ---- Обработчики сообщений ----
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.chat.id
    reset_user(uid)
    bot.send_message(uid,
                     "Привет! Выбери режим:",
                     reply_markup=main_menu_keyboard())

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
        score = user_data[uid].get('score', 0)
        bot.send_message(uid, f"Твой счёт: **{score}** очков", parse_mode='Markdown')
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

    mode = user_data[uid].get('mode')
    if mode == 'translate':
        check_translate_answer(uid, text)
    else:
        bot.send_message(uid, "Выбери вариант через кнопки или меню 👇", reply_markup=back_keyboard())

# ---- Обработчик inline кнопок ----
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    uid = call.message.chat.id
    if uid not in user_data or 'mode' not in user_data[uid]:
        bot.answer_callback_query(call.id, "Сессия устарела. Нажми /start")
        return

    mode = user_data[uid]['mode']

    if mode == 'ger_inf':
        verb = user_data[uid]['current_verb']
        correct_cat = VERB_TO_CATEGORY[verb]
        correct = 'inf' if correct_cat == 'infinitive' else 'ger'
        if call.data == correct:
            user_data[uid]['score'] += 1
            bot.answer_callback_query(call.id, "Правильно! ✅")
        else:
            bot.answer_callback_query(call.id,
                                      f"Неправильно. Правильный ответ: {correct_cat.title()}",
                                      show_alert=True)
        send_ger_inf_question(uid)

    elif mode == 'quiz':
        correct = user_data[uid]['correct_answer']
        if call.data == correct:
            user_data[uid]['score'] += 1
            bot.answer_callback_query(call.id, "Верно! +1 ✅")
        else:
            bot.answer_callback_query(call.id,
                                      f"Неправильно. Правильный ответ: {correct}",
                                      show_alert=True)
        send_quiz_question(uid)

# ---- Запуск бота ----
if __name__ == '__main__':
    logging.info("Бот стартовал")
    try:
        bot.infinity_polling(timeout=15, long_polling_timeout=5)
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
        bot.stop_polling()