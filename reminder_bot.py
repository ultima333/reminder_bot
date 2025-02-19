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
import psycopg2.pool  # Для пулу підключень до PostgreSQL

# Налаштування логування
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Створення Flask додатку
app = Flask(__name__)

# Глобальна змінна для Application
application = None

# Ініціалізація пулу підключень до PostgreSQL
db_pool = psycopg2.pool.SimpleConnectionPool(1, 10,
    dbname=os.getenv("DB_NAME", "your_db_name"),
    user=os.getenv("DB_USER", "your_db_user"),
    password=os.getenv("DB_PASSWORD", "your_db_password"),
    host=os.getenv("DB_HOST", "your_db_host"),
    port=os.getenv("DB_PORT", "5432")
)

def get_connection():
    return db_pool.getconn()

def release_connection(conn):
    db_pool.putconn(conn)

# Словник для перекладу пріоритетів
priority_translation = {
    'urgent': 'Терміново',
    'medium': 'Середній',
    'low': 'Низький'
}

# Стани бота
STATE_ENTER_TASK = "enter_task"
STATE_SELECT_PRIORITY = "select_priority"
STATE_CANNOT_COMPLETE = "cannot_complete"

# Ініціалізація таблиць у PostgreSQL
def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            chat_id BIGINT UNIQUE
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(id),
            task_text TEXT,
            priority TEXT,
            assigned_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed BOOLEAN DEFAULT FALSE,
            cannot_complete_reason TEXT
        );
    """)
    conn.commit()
    cursor.close()
    release_connection(conn)

# Функція для додавання користувача до бази даних
def add_user(user_id, username, chat_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (id, username, chat_id) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (id) 
        DO UPDATE SET username = EXCLUDED.username, chat_id = EXCLUDED.chat_id;
    """, (user_id, username, chat_id))
    conn.commit()
    cursor.close()
    release_connection(conn)

# Функція для додавання завдання до бази даних
def add_task_to_db(user_id, task_text, priority, assigned_by):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tasks (user_id, task_text, priority, assigned_by)
        VALUES (%s, %s, %s, %s);
    """, (user_id, task_text, priority, assigned_by))
    conn.commit()
    cursor.close()
    release_connection(conn)

# Функція для отримання всіх активних завдань користувача
def get_active_tasks(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, task_text, priority FROM tasks WHERE user_id = %s AND completed = FALSE;
    """, (user_id,))
    tasks = cursor.fetchall() or []  # Запобігаємо помилці
    cursor.close()
    release_connection(conn)
    return tasks

# Функція для завершення завдання
def complete_task_in_db(task_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE tasks SET completed = TRUE WHERE id = %s;", (task_id,))
    conn.commit()
    cursor.close()
    release_connection(conn)

# Функція для позначення завдання як "не можу виконати"
def mark_task_cannot_complete(task_id, reason):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE tasks 
        SET cannot_complete_reason = %s, completed = TRUE 
        WHERE id = %s;
    """, (reason, task_id))
    conn.commit()
    cursor.close()
    release_connection(conn)

# Функція для нагадувань про завдання
async def remind_task(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT task_text, priority FROM tasks 
        WHERE user_id = %s AND completed = FALSE;
    """, (user_id,))
    tasks = cursor.fetchall()
    cursor.close()
    release_connection(conn)
    if tasks:
        for task_text, priority in tasks:
            await context.bot.send_message(
                chat_id=user_id, 
                text=f"🔔 Нагадування!\n📝 Завдання: {task_text}\n🚦 Пріоритет: {priority_translation.get(priority, 'Невідомий')}"
            )

# Головне меню
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ['📝 Додати завдання', '✅ Завершити завдання'],
        ['📋 Мої завдання', '🚫 Не можу виконати']
    ], resize_keyboard=True)

# Обробник помилок
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення.")
        return

    user = update.effective_user
    add_user(user.id, user.username if user.username else f"Користувач {user.id}", user.id)

    await update.message.reply_text(
        "Вітаю! Оберіть дію:",
        reply_markup=main_menu_keyboard()
    )

# Функція для додавання завдання
async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['state'] = STATE_ENTER_TASK
    await update.message.reply_text("Введіть текст завдання:")

# Команда "Завершити завдання"
async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tasks = get_active_tasks(user_id)
    if not tasks:
        await update.message.reply_text("У вас немає активних завдань.")
        return
    keyboard = [
        [InlineKeyboardButton(f"{task[1]} ({priority_translation.get(task[2], 'Невідомий')})", callback_data=f"complete_{task[0]}")]
        for task in tasks
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Оберіть завдання для завершення:", reply_markup=reply_markup)

# Команда "Не можу виконати"
async def cannot_complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення.")
        return

    user_id = update.effective_user.id
    tasks = get_active_tasks(user_id)
    if not tasks:
        await update.message.reply_text("У вас немає активних завдань.")
        return

    keyboard = []
    for task in tasks:
        keyboard.append([InlineKeyboardButton(f"{task[1]} ({priority_translation.get(task[2], 'Невідомий')})", callback_data=f"cannot_complete_{task[0]}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Оберіть завдання, яке ви не можете виконати:", reply_markup=reply_markup)

# Обробник кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data.startswith("complete_"):
        task_id = int(query.data.split("_")[1])
        complete_task_in_db(task_id)
        await query.edit_message_text(text="Завдання успішно завершено!")
    elif query.data.startswith("cannot_complete_"):
        task_id = int(query.data.split("_")[1])  # Виправлено індекс [2] на [1]
        context.user_data['cannot_complete_task_id'] = task_id
        await query.edit_message_text(text="Будь ласка, поясніть, чому ви не можете виконати це завдання:")
        context.user_data['state'] = STATE_CANNOT_COMPLETE

# Обробник текстових повідомлень
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
    elif context.user_data.get('state', None) == STATE_ENTER_TASK:
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
    elif context.user_data.get('state', None) == STATE_CANNOT_COMPLETE:
        reason = update.message.text
        task_id = context.user_data.get('cannot_complete_task_id')
        if task_id is not None:
            mark_task_cannot_complete(task_id, reason)
            await update.message.reply_text("Причина не виконання завдання зафіксована.")
            context.user_data.pop('cannot_complete_task_id', None)
            context.user_data.pop('state', None)

# Команда /tasks
async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення.")
        return

    user_id = update.effective_user.id
    tasks = get_active_tasks(user_id)
    if not tasks:
        await update.message.reply_text("У вас немає активних завдань.")
        return

    tasks_list = []
    for task in tasks:
        tasks_list.append(f"📝 {task[1]} ({priority_translation.get(task[2], 'Невідомий')})")
    await update.message.reply_text("Ваші активні завдання:\n\n" + "\n".join(tasks_list))

# Ініціалізація бота
def initialize_bot():
    global application
    TOKEN = "7911352883:AAHiZP7RuhiwCz_ItdMakiQqo23WVxAV_Zw"
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .post_init(lambda app: app.job_queue.start())  # Ініціалізація JobQueue
        .build()
    )

    # Додавання обробників команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button))

    # Встановлення JobQueue
    if application.job_queue and not any(job.name == "remind_task" for job in application.job_queue.jobs()):
        application.job_queue.run_repeating(callback=remind_task, interval=3600, first=0, name="remind_task")

    # Обробник помилок
    application.add_error_handler(error_handler)

    # Встановлення вебхука
    WEBHOOK_URL = os.getenv("RENDER_EXTERNAL_URL", "https://reminder-bot-m6pm.onrender.com")
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )

# Ініціалізація бази даних та бота
initialize_database()
initialize_bot()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))