import telebot
from telebot import types
import logging

from config import TOKEN
from data import GERUND_ONLY, INFINITIVE_ONLY, ALL_STRICT_VERBS, VERB_TO_CATEGORY, get_random_verb

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

bot = telebot.TeleBot(TOKEN)

user_data = {}

def reset_user(uid):
    user_data[uid] = {'score': 0, 'mode': None}

# ---- клавиатуры ----
def main_menu_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(
        types.KeyboardButton("1. Перевод (вписать)"),
        types.KeyboardButton("2. Gerund или Infinitive"),
        types.KeyboardButton("3. Выбор из 4 вариантов")
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

# ---- хендлеры ----
@bot.message_handler(commands=['start'])
def cmd_start(message):
    uid = message.chat.id
    reset_user(uid)
    bot.send_message(uid,
        "Привет! Выбери режим:",
        reply_markup=main_menu_keyboard()
    )

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

    # Здесь вызываем функции для разных режимов (translate, ger_inf, quiz)
    # Можно вставить твой старый код отправки вопросов и проверки ответов

# ---- запуск бота ----
if __name__ == '__main__':
    logging.info("Бот стартовал")
    try:
        bot.infinity_polling(timeout=15, long_polling_timeout=5)
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")
        bot.stop_polling()