import logging
import os
import psycopg2
from psycopg2 import pool
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

# Параметри підключення до PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL')

# Перевірка DATABASE_URL та створення пулу підключень
if not DATABASE_URL:
    logger.error("❌ DATABASE_URL не встановлено. Перевірте змінні середовища.")
    exit(1)

try:
    db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, dsn=DATABASE_URL)
except Exception as e:
    logger.error(f"❌ Помилка підключення до PostgreSQL: {e}")
    exit(1)

def get_connection():
    return db_pool.getconn()

def release_connection(conn):
    db_pool.putconn(conn)

# Ініціалізація бази даних
def initialize_database():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Таблиця для користувачів
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                chat_id BIGINT UNIQUE
            )
        ''')

        # Таблиця для завдань
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                task_text TEXT,
                priority TEXT,
                assigned_by TEXT,
                created_at TIMESTAMP,
                last_reminder_sent TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
        ''')
        conn.commit()
    finally:
        cursor.close()
        release_connection(conn)

# Додавання користувача до бази даних
def add_user_to_db(user_id, username, chat_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO users (user_id, username, chat_id) VALUES (%s, %s, %s) ON CONFLICT (chat_id) DO NOTHING', (user_id, username, chat_id))
        conn.commit()
    finally:
        cursor.close()
        release_connection(conn)

# Додавання завдання до бази даних
def add_task_to_db(user_id, task_text, priority, assigned_by):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        created_at = datetime.now()
        cursor.execute('''
            INSERT INTO tasks (user_id, task_text, priority, assigned_by, created_at, last_reminder_sent)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (user_id, task_text, priority, assigned_by, created_at, None))
        conn.commit()
    finally:
        cursor.close()
        release_connection(conn)

# Отримання завдань користувача
def get_user_tasks_from_db(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id, task_text, priority, assigned_by FROM tasks WHERE user_id = %s', (user_id,))
        tasks = cursor.fetchall()
        return tasks
    finally:
        cursor.close()
        release_connection(conn)

# Видалення завдання
def delete_task_from_db(task_id):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('DELETE FROM tasks WHERE id = %s', (task_id,))
        conn.commit()
    finally:
        cursor.close()
        release_connection(conn)

# Відновлення нагадувань при запуску бота
def restore_reminders(application):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id, user_id, task_text, priority, created_at, last_reminder_sent FROM tasks')
        tasks_list = cursor.fetchall()

        if not tasks_list:
            logger.info("🔹 Немає завдань для відновлення нагадувань.")
            return

        for task in tasks_list:
            task_id, user_id, task_text, priority, created_at, last_reminder_sent = task
            now = datetime.now()

            if priority == 'urgent':
                interval = 3600  # Кожні 1 годину
            elif priority == 'medium':
                interval = 21600  # Кожні 6 годин
            elif priority == 'low':
                reminder_time = time(7, 0, 0)  # Щодня о 7:00
                application.job_queue.run_daily(remind_task, time=reminder_time, chat_id=user_id, data=user_id, name='low')
                continue

            # Перевірка, чи настав час для нагадування
            if last_reminder_sent and (now - last_reminder_sent).total_seconds() < interval:
                continue  # Пропускаємо, якщо ще не настав час нагадування

            application.job_queue.run_repeating(
                remind_task,
                interval=interval,
                first=0,
                chat_id=user_id,
                data=user_id,
                name=priority
            )
    finally:
        cursor.close()
        release_connection(conn)

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

    # Додавання користувача до бази даних, якщо його там немає
    add_user_to_db(user.id, user.username if user.username else f"Користувач {user.id}", user.id)

    await update.message.reply_text(
        "Вітаю! Оберіть дію:",
        reply_markup=main_menu_keyboard()
    )

# Функція нагадування
async def remind_task(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    assigned_user = job.data
    priority = job.name
    now = datetime.now().time()
    start_time = time(7, 0, 0)
    end_time = time(19, 59, 59)

    if start_time <= now <= end_time:
        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT task_text, priority, assigned_by FROM tasks WHERE user_id = %s AND priority = %s', (assigned_user, priority))
            tasks_list = cursor.fetchall()

            for task in tasks_list:
                task_text, _, assigned_by = task
                priority_text = priority_translation.get(priority, "Невідомий")  # За замовчуванням
                await context.bot.send_message(
                    chat_id=assigned_user,
                    text=f"⏰ Нагадування для {assigned_by}:\n\n"
                         f"📝 Завдання: {task_text}\n"
                         f"🚦 Пріоритет: {priority_text}"
                )

                # Оновлення часу останнього нагадування
                cursor.execute('UPDATE tasks SET last_reminder_sent = %s WHERE user_id = %s AND priority = %s', (datetime.now(), assigned_user, priority))
                conn.commit()
        finally:
            cursor.close()
            release_connection(conn)
    else:
        logger.info(f"Нагадування не відправлено, бо зараз поза робочим часом: {now}")

# Ініціалізація бота
def initialize_bot():
    global application
    TOKEN = "8197063148:AAHu3grk5UOnUqqjuTBmqAPvy-7TYfId4qk"
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .post_init(lambda app: app.job_queue.start())
        .build()
    )

    # Відновлення нагадувань
    restore_reminders(application)

    # Додавання обробників команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button))

    # Обробник помилок
    application.add_error_handler(error_handler)

    # Встановлення вебхука
    application.run_webhook(
        listen='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        url_path=TOKEN,
        webhook_url=f'https://reminder-bot-m6pm.onrender.com/{TOKEN}'
    )

# Ініціалізація бази даних та бота при запуску додатку
initialize_database()
initialize_bot()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))