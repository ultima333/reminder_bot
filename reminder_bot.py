import logging
import os
import json
from datetime import time, datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# Налаштування логування
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Створення Flask додатку
app = Flask(__name__)

# Глобальна змінна для Application
application = None

# Шлях до файлу для зберігання даних
DATA_FILE = "tasks_data.json"

# Завантаження даних з файлу
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {"tasks": {}, "user_data": {}}

# Збереження даних у файл
def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=4)

# Оновлення даних у файлі
def update_data():
    data_to_save = {
        "tasks": tasks,
        "user_data": user_data
    }
    save_data(data_to_save)

# Ініціалізація даних при запуску бота
data = load_data()
tasks = data.get("tasks", {})
user_data = data.get("user_data", {})

# Стани бота
STATE_SELECT_USER = 1
STATE_ENTER_TASK = 2
STATE_SELECT_PRIORITY = 3
STATE_CANNOT_COMPLETE = 4

# Словник для перекладу пріоритетів
priority_translation = {
    'urgent': 'Терміново',
    'medium': 'Середній',
    'low': 'Низький'
}

# Головне меню
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ['📝 Додати завдання', '✅ Завершити завдання'],
        ['📋 Мої завдання', '🚫 Не можу виконати']
    ], resize_keyboard=True)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення, щоб додати завдання.")
        return

    user = update.effective_user

    # Додавання користувача до user_data, якщо його там немає
    if user.id not in user_data:
        user_data[user.id] = {
            'username': user.username if user.username else f"Користувач {user.id}",
            'chat_id': user.id
        }
        update_data()  # Оновлення даних у файлі

    await update.message.reply_text(
        "Вітаю! Оберіть дію:",
        reply_markup=main_menu_keyboard()
    )

# Команда /tasks
async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення, щоб переглянути завдання.")
        return

    user_id = update.effective_user.id
    if user_id not in tasks or not tasks[user_id]:
        await update.message.reply_text("У вас немає активних завдань.")
        return

    tasks_list = []
    for task in tasks[user_id]:
        tasks_list.append(f"📝 {task['task_text']} ({priority_translation[task['priority']]})\n   👤 Призначено: {task['assigned_by']}")
    await update.message.reply_text("Ваші активні завдання:\n\n" + "\n".join(tasks_list))

# Команда /completetask
async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення, щоб завершити завдання.")
        return

    user_id = update.effective_user.id
    if user_id not in tasks or not tasks[user_id]:
        await update.message.reply_text("У вас немає активних завдань.")
        return

    keyboard = []
    for index, task in enumerate(tasks[user_id]):
        keyboard.append([InlineKeyboardButton(f"{task['task_text']} ({priority_translation[task['priority']]})", callback_data=f"complete_{index}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Оберіть завдання для завершення:", reply_markup=reply_markup)

# Команда "Не можу виконати"
async def cannot_complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення, щоб використати цю команду.")
        return

    user_id = update.effective_user.id
    if user_id not in tasks or not tasks[user_id]:
        await update.message.reply_text("У вас немає активних завдань.")
        return

    keyboard = []
    for index, task in enumerate(tasks[user_id]):
        keyboard.append([InlineKeyboardButton(f"{task['task_text']} ({priority_translation[task['priority']]})", callback_data=f"cannot_complete_{index}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Оберіть завдання, яке ви не можете виконати:", reply_markup=reply_markup)

# Обробник текстових повідомлень (для кнопок головного меню)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    text = update.message.text
    if text == '📝 Додати завдання':
        await add_task(update, context)
    elif text == '✅ Завершити завдання':
        await complete_task(update, context)
    elif text == '📋 Мої завдання':
        await show_tasks(update, context)
    elif text == '🚫 Не можу виконати':
        await cannot_complete_task(update, context)
    else:
        user_state = context.user_data.get('state')
        if user_state == STATE_ENTER_TASK:
            task_text = update.message.text
            context.user_data['task_text'] = task_text
            keyboard = [
                [InlineKeyboardButton("Терміново", callback_data='urgent')],
                [InlineKeyboardButton("Середній", callback_data='medium')],
                [InlineKeyboardButton("Низький", callback_data='low')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Оберіть пріоритет завдання:", reply_markup=reply_markup)
            context.user_data['state'] = STATE_SELECT_PRIORITY
        elif user_state == STATE_CANNOT_COMPLETE:
            reason = update.message.text
            task_index = context.user_data.get('cannot_complete_task_index')
            if task_index is not None:
                user_id = update.effective_user.id
                if user_id in tasks and 0 <= task_index < len(tasks[user_id]):
                    del tasks[user_id][task_index]
                    update_data()
                    await update.message.reply_text("Завдання видалено через неможливість виконання.")
                    context.user_data['state'] = None

# Обробник кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("complete_"):
        task_index = int(query.data.split("_")[1])
        user_id = query.from_user.id
        if user_id in tasks and 0 <= task_index < len(tasks[user_id]):
            del tasks[user_id][task_index]
            update_data()
            await query.edit_message_text(text="Завдання успішно завершено!")
    elif query.data.startswith("cannot_complete_"):
        task_index = int(query.data.split("_")[1])
        user_id = query.from_user.id
        if user_id in tasks and 0 <= task_index < len(tasks[user_id]):
            del tasks[user_id][task_index]
            update_data()
            await query.edit_message_text(text="Завдання видалено через неможливість виконання.")
    elif query.data in ['urgent', 'medium', 'low']:
        user_id = query.from_user.id
        task_text = context.user_data.get('task_text')
        assigned_by = user_data[user_id]['username']
        priority = query.data
        if user_id not in tasks:
            tasks[user_id] = []
        tasks[user_id].append({
            'task_text': task_text,
            'priority': priority,
            'assigned_by': assigned_by
        })
        update_data()
        await query.edit_message_text(text=f"Завдання додано з пріоритетом: {priority_translation[priority]}")

# Функція нагадування
async def remind_task(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().time()
    start_time = time(7, 0, 0)
    end_time = time(19, 59, 59)

    if start_time <= now <= end_time:
        for user_id, user_tasks in tasks.items():
            for task in user_tasks:
                priority = task['priority']
                if priority == 'urgent' and now.minute % 60 == 0:  # Кожні 1 годину
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ Нагадування: {task['task_text']} ({priority_translation[priority]})"
                    )
                elif priority == 'medium' and now.hour % 6 == 0:  # Кожні 6 годин
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ Нагадування: {task['task_text']} ({priority_translation[priority]})"
                    )
                elif priority == 'low' and now.hour == 7 and now.minute == 0:  # Щодня о 7:00
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⏰ Нагадування: {task['task_text']} ({priority_translation[priority]})"
                    )

# Обробник помилок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# Ініціалізація бота
def initialize_bot():
    global application
    TOKEN = "7911352883:AAHiZP7RuhiwCz_ItdMakiQqo23WVxAV_Zw"
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .post_init(lambda app: app.job_queue.start())
        .build()
    )

    # Додавання обробників команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button))

    # Встановлення JobQueue
    if application.job_queue:
        application.job_queue.run_repeating(callback=remind_task, interval=3600, first=0)

    # Обробник помилок
    application.add_error_handler(error_handler)

    # Встановлення вебхука
    application.run_webhook(
        listen='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        url_path=TOKEN,
        webhook_url=f'https://reminder-bot-m6pm.onrender.com/{TOKEN}'
    )

# Ініціалізація бота при запуску додатку
initialize_bot()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))