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
                    task = tasks[user_id][task_index]
                    assigned_by_id = task['assigned_by_id']
                    try:
                        await context.bot.send_message(
                            chat_id=assigned_by_id,
                            text=f"🚫 Користувач @{update.effective_user.username if update.effective_user.username else update.effective_user.id} не може виконати завдання:\n\n"
                                 f"📝 Завдання: {task['task_text']}\n"
                                 f"🚦 Пріоритет: {priority_translation[task['priority']]}\n"
                                 f"📌 Причина: {reason}"
                        )
                    except Exception as e:
                        logger.error(f"Не вдалося надіслати повідомлення користувачу {assigned_by_id}: {e}")
                    tasks[user_id].pop(task_index)
                    update_data()  # Оновлення даних у файлі
                    await update.message.reply_text("Завдання видалено через неможливість виконання.")
                else:
                    await update.message.reply_text("Помилка: завдання не знайдено.")
            else:
                await update.message.reply_text("Помилка: не вдалося обробити завдання.")
            context.user_data.clear()

# Команда /addtask
async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        await update.message.reply_text("Будь ласка, напишіть мені в приватні повідомлення, щоб додати завдання.")
        return
    # Додавання користувача до user_data, якщо його там немає
    user = update.effective_user
    if user.id not in user_data:
        user_data[user.id] = {
            'username': user.username if user.username else f"Користувач {user.id}",
            'chat_id': user.id
        }
        update_data()  # Оновлення даних у файлі
    keyboard = [
        [InlineKeyboardButton("Собі", callback_data=f"assign_{update.effective_user.id}")]
    ]
    for user_id, data in user_data.items():
        if user_id != update.effective_user.id:
            username = data['username'] if data['username'] else f"Користувач {user_id}"
            keyboard.append([InlineKeyboardButton(username, callback_data=f"assign_{user_id}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Оберіть користувача, якому хочете призначити завдання:", reply_markup=reply_markup)
    context.user_data['state'] = STATE_SELECT_USER

# Функція для очищення старих нагадувань
def clear_old_jobs(job_queue, chat_id, name):
    for job in job_queue.get_jobs_by_name(name):
        if job.chat_id == chat_id:
            job.schedule_removal()

# Обробник вибору користувача, пріоритету або завершення завдання
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("assign_"):
        assigned_user_id = int(query.data.split("_")[1])
        context.user_data['assigned_user'] = assigned_user_id
        await query.edit_message_text(text="Введіть текст завдання:")
        context.user_data['state'] = STATE_ENTER_TASK
    elif query.data.startswith("complete_"):
        index = int(query.data.split("_")[1])
        user_id = query.from_user.id
        if user_id in tasks and 0 <= index < len(tasks[user_id]):
            completed_task = tasks[user_id].pop(index)
            update_data()  # Оновлення даних у файлі
            await query.edit_message_text(text=f"Завдання завершено: {completed_task['task_text']} ({priority_translation[completed_task['priority']]})")
            assigned_by_id = completed_task['assigned_by_id']
            if assigned_by_id in user_data:
                assigned_by_username = user_data[assigned_by_id]['username']
                try:
                    await context.bot.send_message(
                        chat_id=assigned_by_id,
                        text=f"✅ Завдання, яке ви призначили для @{query.from_user.username if query.from_user.username else query.from_user.id}, виконано:\n\n"
                             f"📝 Завдання: {completed_task['task_text']}\n"
                             f"🚦 Пріоритет: {priority_translation[completed_task['priority']]}"
                    )
                except Exception as e:
                    logger.error(f"Не вдалося надіслати повідомлення користувачу {assigned_by_id}: {e}")
        else:
            await query.edit_message_text(text="Помилка: завдання не знайдено.")
    elif query.data.startswith("cannot_complete_"):
        index = int(query.data.split("_")[2])
        user_id = query.from_user.id
        if user_id in tasks and 0 <= index < len(tasks[user_id]):
            context.user_data['cannot_complete_task_index'] = index
            await query.edit_message_text(text="Будь ласка, введіть причину, чому ви не можете виконати це завдання:")
            context.user_data['state'] = STATE_CANNOT_COMPLETE
        else:
            await query.edit_message_text(text="Помилка: завдання не знайдено.")
    else:
        priority = query.data
        context.user_data['priority'] = priority
        assigned_user = context.user_data['assigned_user']
        task_text = context.user_data['task_text']
        # Перевірка, чи існує користувач у user_data
        if assigned_user not in user_data:
            user_data[assigned_user] = {
                'username': f"Користувач {assigned_user}",  # Замінне значення, якщо username недоступний
                'chat_id': assigned_user
            }
            update_data()  # Оновлення даних у файлі
        if assigned_user not in tasks:
            tasks[assigned_user] = []
        tasks[assigned_user].append({
            'task_text': task_text,
            'priority': priority,
            'assigned_by': f"@{query.from_user.username}" if query.from_user.username else f"Користувач {query.from_user.id}",
            'assigned_by_id': query.from_user.id
        })
        update_data()  # Оновлення даних у файлі
        try:
            await context.bot.send_message(
                chat_id=assigned_user,
                text=f"🎯 Вам призначено нове завдання:\n\n"
                     f"📝 Завдання: {task_text}\n"
                     f"🚦 Пріоритет: {priority_translation[priority]}\n"
                     f"👤 Призначено: @{query.from_user.username if query.from_user.username else query.from_user.id}\n\n"
                     f"Нагадування будуть надходити у приватні повідомлення."
            )
        except Exception as e:
            logger.error(f"Не вдалося надіслати повідомлення користувачу: {e}")
        # Додавання нагадувань з очищенням старих
        if priority == 'urgent':
            clear_old_jobs(context.job_queue, assigned_user, 'urgent')  # Очищення старих нагадувань
            context.job_queue.run_repeating(remind_task, interval=3600, first=0, chat_id=assigned_user, data=assigned_user, name='urgent')
        elif priority == 'medium':
            clear_old_jobs(context.job_queue, assigned_user, 'medium')  # Очищення старих нагадувань
            context.job_queue.run_repeating(remind_task, interval=21600, first=0, chat_id=assigned_user, data=assigned_user, name='medium')
        elif priority == 'low':
            clear_old_jobs(context.job_queue, assigned_user, 'low')  # Очищення старих нагадувань
            reminder_time = time(7, 0, 0)
            context.job_queue.run_daily(remind_task, time=reminder_time, chat_id=assigned_user, data=assigned_user, name='low')
        # Використання username з user_data
        await query.edit_message_text(text=f"Завдання додано для {user_data[assigned_user]['username']} з пріоритетом {priority_translation[priority]}!")
        context.user_data.clear()

# Функція для нагадування
async def remind_task(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    assigned_user = job.data
    priority = job.name
    # Поточний час
    now = datetime.now().time()
    # Робочий час: з 7:00 до 20:00
    start_time = time(7, 0, 0)
    end_time = time(19, 59, 59)
    # Перевірка, чи поточний час знаходиться в робочому діапазоні
    if start_time <= now <= end_time:
        if assigned_user in tasks and tasks[assigned_user]:
            for task in tasks[assigned_user]:
                if task['priority'] == priority:
                    await context.bot.send_message(
                        chat_id=context.job.chat_id,
                        text=f"⏰ Нагадування для {user_data[assigned_user]['username']}:\n\n"
                             f"📝 Завдання: {task['task_text']}\n"
                             f"🚦 Пріоритет: {priority_translation[task['priority']]}\n"
                             f"👤 Призначено: {task['assigned_by']}"
                    )
    else:
        logger.info(f"Нагадування не відправлено, бо зараз поза робочим часом: {now}")

# Ендпоінт для вебхуків
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return 'ok'

# Новий ендпоінт для пінгування
@app.route('/ping', methods=['GET'])
def ping():
    return 'Pong!', 200

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def initialize_bot():
    global application
    TOKEN = "8197063148:AAHu3grk5UOnUqqjuTBmqAPvy-7TYfId4qk"
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