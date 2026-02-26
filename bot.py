import telebot
from telebot import types
import logging
import random
import os

# Импорт данных о глаголах и функциях
from data import GERUND_ONLY, INFINITIVE_ONLY, IRREGULAR_VERBS, ALL_STRICT_VERBS, VERB_TO_CATEGORY, get_random_verb

# -----------------------------
# Настройка логирования
# -----------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# -----------------------------
# Получаем токен бота из переменных окружения
# -----------------------------
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    logging.error("❌ Ошибка: не установлена переменная BOT_TOKEN!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# -----------------------------
# Словарь для хранения данных пользователей
# -----------------------------
user_data = {}

# -----------------------------
# Функции для работы с пользователем
# -----------------------------

def reset_user(uid):
    """Сброс данных пользователя при старте или новом сеансе"""
    user_data[uid] = {
        'score': 0,             # общий счёт
        'mode': None,           # текущий режим
        'translate_score': 0,   # очки за перевод
        'ger_inf_score': 0,     # очки за Gerund/Infinitive
        'quiz_score': 0         # очки за выбор из 4 вариантов
    }

def normalize(text):
    """Приводим текст к нижнему регистру и убираем лишние пробелы"""
    return text.lower().strip()

def check_form(user_input, correct_form):
    """
    Проверяем правильность ответа.
    Если в correct_form есть варианты через "/", считаем любой из них правильным
    """
    user_input = normalize(user_input)
    correct_form = normalize(correct_form)

    if "/" in correct_form:
        variants = correct_form.split("/")
        return user_input in variants

    return user_input == correct_form

# -----------------------------
# Клавиатуры
# -----------------------------

def main_menu_keyboard():
    """Главное меню с кнопками"""
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
    """Клавиатура с кнопкой назад и статистикой"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("Назад в меню"),
        types.KeyboardButton("Статистика")
    )
    return markup

# -----------------------------
# Режимы вопросов
# -----------------------------

# ---- Перевод глагола ----
def send_translate_question(uid):
    """Отправляем пользователю вопрос на перевод глагола"""
    verb = get_random_verb()
    user_data[uid]['current_verb'] = verb
    bot.send_message(
        uid,
        f"Переведи глагол на русский:\n\n**{verb}**",
        reply_markup=back_keyboard(),
        parse_mode='Markdown'
    )

def check_translate_answer(uid, text):
    """Проверяем ответ пользователя в режиме перевода"""
    verb = user_data[uid].get('current_verb')
    if not verb:
        return

    correct = ALL_STRICT_VERBS[verb].lower()

    if normalize(text) in correct:
        user_data[uid]['score'] += 1
        user_data[uid]['translate_score'] += 1
        bot.send_message(uid, "Правильно! +1 ✅")
    else:
        bot.send_message(uid, f"Неправильно. Ответ: {ALL_STRICT_VERBS[verb]}")

    send_translate_question(uid)

# ---- Gerund / Infinitive ----
def send_ger_inf_question(uid):
    """Отправляем вопрос на выбор Gerund/Infinitive"""
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

# ---- Выбор из 4 вариантов ----
def send_quiz_question(uid):
    """Отправляем вопрос с 4 вариантами выбора"""
    eng = get_random_verb()
    ru = ALL_STRICT_VERBS[eng]

    # 1 правильный + 3 случайных варианта
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

# ---- Неправильные глаголы по шагам ----
def start_irregular_step_mode(uid):
    """Начало режима неправильных глаголов (V1, V2, V3)"""
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
    """Обработка ответов в режиме неправильных глаголов"""
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

# -----------------------------
# Обработчики команд
# -----------------------------

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

# -----------------------------
# Основной обработчик текстовых сообщений
# -----------------------------
@bot.message_handler(func=lambda m: True)
def main_handler(message):
    uid = message.chat.id
    text = message.text.strip()

    if uid not in user_data:
        reset_user(uid)

    # ---------------- Статистика ----------------
    if text == "Статистика":
        stats = (
            f"Общий счёт: {user_data[uid]['score']}\n\n"
            f"Перевод (вписать): {user_data[uid]['translate_score']}\n"
            f"Gerund или Infinitive: {user_data[uid]['ger_inf_score']}\n"
            f"Выбор из 4 вариантов: {user_data[uid]['quiz_score']}"
        )
        bot.send_message(uid, stats)
        return

    # ---------------- Выбор режима ----------------
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

    # ---------------- Обработка ответа в выбранном режиме ----------------
    mode = user_data[uid].get('mode')

    if mode == 'translate':
        check_translate_answer(uid, text)
    elif mode == 'irregular_step':
        handle_irregular_step(uid, text)
    else:
        bot.send_message(uid, "Выбери режим через меню 👇", reply_markup=back_keyboard())

# -----------------------------
# Обработчик кнопок InlineKeyboard
# -----------------------------
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    uid = call.message.chat.id
    mode = user_data[uid]['mode']

    # ---- Gerund / Infinitive ----
    if mode == 'ger_inf':
        verb = user_data[uid]['current_verb']
        correct_cat = VERB_TO_CATEGORY[verb]
        correct = 'inf' if correct_cat == 'infinitive' else 'ger'

        if call.data == correct:
            user_data[uid]['score'] += 1
            user_data[uid]['ger_inf_score'] += 1
            bot.answer_callback_query(call.id, "Правильно! ✅")
        else:
            bot.answer_callback_query(call.id, f"Неправильно. Ответ: {correct_cat}")

        send_ger_inf_question(uid)

    # ---- Выбор из 4 вариантов ----
    elif mode == 'quiz':
        correct = user_data[uid]['correct_answer']

        if call.data == correct:
            user_data[uid]['score'] += 1
            user_data[uid]['quiz_score'] += 1
            bot.answer_callback_query(call.id, "Верно! +1 ✅")
        else:
            bot.answer_callback_query(call.id, f"Неправильно. Ответ: {correct}")

        send_quiz_question(uid)

# -----------------------------
# Запуск бота
# -----------------------------
if __name__ == '__main__':
    logging.info("Бот стартовал")
    bot.infinity_polling(timeout=15, long_polling_timeout=5)
    