import telebot
import logging
import sqlite3
import csv
from telebot import types
from datetime import datetime, timedelta, timezone
import requests
import json
import uuid
import threading
import time

BOT_TOKEN = '7172315946:AAE6LSdd3nA4MI2NAkcQ52noxp-mG2u57aE'
CONTACTS_DATABASE_FILE = r"D:\MYPROJECT\OSNOVA\BD\contacts.db"
USER_DATABASE_FILE = r"D:\MYPROJECT\OSNOVA\BD\users.db"
TRANSACTIONS_DATABASE_FILE = r"D:\MYPROJECT\OSNOVA\BD\transactions.db"
ERROR_LOG_FILE = r"D:\MYPROJECT\OSNOVA\BD\error_log.txt"
FOUND_CONTACTS_FILE = r"D:\MYPROJECT\OSNOVA\BD\found_contacts.csv"

USDT_WALLET = 'TP63bgLMcgQFBbiFhGTy2REqMxeg7KrtTH'
USDT_RATE = 100
COST_PER_SEARCH = 2  # Стоимость одного пробива контакта в рублях

logging.basicConfig(level=logging.INFO)

bot = telebot.TeleBot(BOT_TOKEN)
bot.user_data = {}

search_queue = []
queue_lock = threading.Lock()

def create_user_database():
    conn = sqlite3.connect(USER_DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        balance REAL DEFAULT 0.0,
                        is_admin INTEGER DEFAULT 0,
                        free_searches INTEGER DEFAULT 0
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_sessions (
                        user_id INTEGER,
                        telegram_user_id INTEGER,
                        PRIMARY KEY (user_id, telegram_user_id),
                        FOREIGN KEY (user_id) REFERENCES users(id)
                      )''')
    conn.commit()
    conn.close()

def create_transactions_database():
    conn = sqlite3.connect(TRANSACTIONS_DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        txid TEXT NOT NULL UNIQUE,
                        amount REAL NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS pending_transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        amount REAL NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        expires_at TEXT,
                        UNIQUE(user_id, amount)
                      )''')
    conn.commit()
    conn.close()

create_user_database()
create_transactions_database()

def log_error(error_message):
    with open(ERROR_LOG_FILE, 'a', encoding='utf-8') as file:
        file.write(f"{datetime.now()}: {error_message}\n")

def format_date(date_str):
    try:
        day, month, year = map(int, date_str.split('.'))
        return f"{day:02d}.{month:02d}.{year}"
    except Exception as e:
        log_error(f"Ошибка форматирования даты: {str(e)}")
        return None

def get_telegram_contacts(name, birthday):
    try:
        conn = sqlite3.connect(CONTACTS_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT phone FROM contacts WHERE name = ? AND birthday = ?",
                       (name.lower(), format_date(birthday)))
        phones = cursor.fetchall()
        conn.close()
        return [f"https://t.me/+{phone[0]}" for phone in phones]
    except Exception as e:
        log_error(f"Ошибка запроса контактов: {str(e)}")
        return []

def split_message(message, chunk_size=4096):
    return [message[i:i + chunk_size] for i in range(0, len(message), chunk_size)]

def register_user(username, password):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        conn.close()
        return "Регистрация прошла успешно!"
    except sqlite3.IntegrityError:
        return "Пользователь с таким именем уже существует."
    except Exception as e:
        log_error(f"Ошибка регистрации пользователя: {str(e)}")
        return "Ошибка регистрации."

def authenticate_user(username, password):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE username = ? AND password = ?", (username, password))
        user = cursor.fetchone()
        conn.close()
        return user
    except Exception as e:
        log_error(f"Ошибка аутентификации пользователя: {str(e)}")
        return None

def get_user_balance(user_id):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
        balance = cursor.fetchone()
        conn.close()
        if balance:
            return balance[0]
        else:
            return 0
    except Exception as e:
        log_error(f"Ошибка получения баланса: {str(e)}")
        return 0

def get_user_free_searches(user_id):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT free_searches FROM users WHERE id = ?", (user_id,))
        free_searches = cursor.fetchone()
        conn.close()
        if free_searches:
            return free_searches[0]
        else:
            return 0
    except Exception as e:
        log_error(f"Ошибка получения количества бесплатных пробивов: {str(e)}")
        return 0

def get_user_id_by_username(username):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user_id = cursor.fetchone()
        conn.close()
        if user_id:
            return user_id[0]
        else:
            return None
    except Exception as e:
        log_error(f"Ошибка получения ID пользователя по имени: {str(e)}")
        return None

def update_user_data(user_id):
    if user_id in bot.user_data:
        bot.user_data[user_id]['balance'] = get_user_balance(user_id)
        bot.user_data[user_id]['free_searches'] = get_user_free_searches(user_id)

def refresh_user_data(telegram_user_id):
    if telegram_user_id in bot.user_data:
        user_id = bot.user_data[telegram_user_id]['user_id']
        bot.user_data[telegram_user_id].update({
            'balance': get_user_balance(user_id),
            'free_searches': get_user_free_searches(user_id)
        })
    else:
        log_error(f"Данные пользователя не инициализированы для telegram_user_id: {telegram_user_id}")

def deduct_balance(user_id, amount):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance - ? WHERE id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        update_user_data(user_id)
    except Exception as e:
        log_error(f"Ошибка списания баланса: {str(e)}")

def is_admin(user_id):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,))
        admin = cursor.fetchone()
        conn.close()
        if admin:
            return admin[0] == 1
        else:
            return False
    except Exception as e:
        log_error(f"Ошибка проверки прав администратора: {str(e)}")
        return False

def add_balance(user_id, amount):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user_id))
        conn.commit()
        conn.close()
        update_user_data(user_id)
    except Exception as e:
        log_error(f"Ошибка пополнения баланса: {str(e)}")

def grant_free_searches(user_id, count):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET free_searches = free_searches + ? WHERE id = ?", (count, user_id))
        conn.commit()
        conn.close()
        update_user_data(user_id)
    except Exception as e:
        log_error(f"Ошибка предоставления бесплатных пробивов: {str(e)}")

def add_transaction(user_id, txid, amount):
    try:
        conn = sqlite3.connect(TRANSACTIONS_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO transactions (user_id, txid, amount) VALUES (?, ?, ?)", (user_id, txid, amount))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"Ошибка добавления транзакции: {str(e)}")

def add_pending_transaction(user_id, amount):
    try:
        conn = sqlite3.connect(TRANSACTIONS_DATABASE_FILE)
        cursor = conn.cursor()
        expires_at = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("INSERT INTO pending_transactions (user_id, amount, expires_at) VALUES (?, ?, ?)",
                       (user_id, amount, expires_at))
        conn.commit()
        conn.close()
    except sqlite3.IntegrityError:
        raise ValueError("Заявка на данную сумму уже существует.")
    except Exception as e:
        log_error(f"Ошибка добавления ожидаемой транзакции: {str(e)}")

def remove_pending_transaction(user_id, amount):
    try:
        conn = sqlite3.connect(TRANSACTIONS_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_transactions WHERE user_id = ? AND amount = ?", (user_id, amount))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"Ошибка удаления ожидаемой транзакции: {str(e)}")

def get_trc20_transactions(address):
    base_url = "https://api.trongrid.io/v1/accounts/"
    endpoint = f"{address}/transactions/trc20"

    params = {
        "limit": 200
    }

    response = requests.get(base_url + endpoint, params=params)
    if response.status_code != 200:
        log_error(f"Error fetching data: {response.status_code}")
        return None

    data = response.json()
    transactions = data.get('data', [])

    usdt_transactions = [tx for tx in transactions if tx.get('token_info', {}).get('symbol') == 'USDT']

    return usdt_transactions

def search_people(people):
    api_token = "eyJhbGciOiJodHRwOi8vd3d3LnczLm9yZy8yMDAxLzA0L3htbGRzaWctbW9yZSNobWFjLXNoYTI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI1MDU5MTg1MzY4IiwianRpIjoiNjY0M2FkODBlZjIyNzYwOWM0ZjNhMjdkIiwiZXhwIjoyMDMxMzEyMDkxLCJpc3MiOiJMT0xhcHAiLCJhdWQiOiJMT0xzZWFyc2gifQ.ishFA_Hr_7R86nINekCuazuMotdVv60JJoYI9QF3yi0"
    client_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {api_token}",
        "X-ClientId": client_id
    }
    url = "https://quickosintapi.com/api/v1/search/agregate"

    payload = {
        "Items": people,
        "CountryCode": "RU"
    }
    response = requests.post(url, headers=headers, json=payload)
    if response.status_code == 200:
        return response.json()
    else:
        log_error(f"Ошибка API запроса: {response.status_code}, {response.text}")
        return None

def append_to_csv(fio, birthday, phone):
    try:
        with open(FOUND_CONTACTS_FILE, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file, delimiter='|')
            writer.writerow([fio, birthday, phone])
    except Exception as e:
        log_error(f"Ошибка записи в CSV: {str(e)}")

@bot.message_handler(commands=['start'])
def handle_start(message):
    refresh_user_data(message.from_user.id)
    if message.from_user.id in bot.user_data:
        user_data = bot.user_data[message.from_user.id]
        username = user_data.get('username', 'неизвестный пользователь')
        balance = user_data.get('balance', 0)
        free_searches = user_data.get('free_searches', 0)
        bot.send_message(message.chat.id,
                         f"Привет, {username}!\nВаш баланс: {balance} руб.\nБесплатные пробивы: {free_searches}")
    else:
        bot.send_message(message.chat.id,
                         "Добро пожаловать! Введите команду /login для входа или /register для регистрации.")

@bot.message_handler(commands=['help'])
def handle_help(message):
    help_text = (
        "Список доступных команд:\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать это сообщение\n"
        "/register <имя пользователя> <пароль> - Зарегистрировать новый аккаунт\n"
        "/login <имя пользователя> <пароль> - Войти в существующий аккаунт\n"
        "/logout - Выйти из аккаунта\n"
        "/balance - Показать баланс\n"
        "/addbalance - Пополнить баланс\n"
        "/checktransaction - Проверить транзакции на кошельке\n"
        "/transfer <имя пользователя> <сумма> - Перевести средства другому пользователю\n"
    )
    user_id = message.from_user.id
    if user_id in bot.user_data and is_admin(bot.user_data[user_id]['user_id']):
        help_text += (
            "/adminaddbalance <имя пользователя> <сумма> - Добавить баланс пользователю (только для администраторов)\n"
            "/grantfree <имя пользователя> <количество> - Предоставить бесплатные пробивы пользователю (только для администраторов)\n"
        )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['register'])
def handle_register(message):
    try:
        _, username, password = message.text.split()
        response = register_user(username, password)
        bot.reply_to(message, response)
    except ValueError:
        bot.reply_to(message, "Использование: /register <имя пользователя> <пароль>")

@bot.message_handler(commands=['login'])
def handle_login(message):
    try:
        _, username, password = message.text.split()
        user = authenticate_user(username, password)
        if user:
            user_id = user[0]
            if message.from_user.id not in bot.user_data:
                bot.user_data[message.from_user.id] = {
                    'user_id': user_id,
                    'username': user[1],
                }
            add_telegram_user_id(user_id, message.from_user.id)
            refresh_user_data(message.from_user.id)
            bot.reply_to(message, f"Вход выполнен успешно!\nПривет, {user[1]}!")
        else:
            bot.reply_to(message, "Неверное имя пользователя или пароль.")
    except ValueError:
        bot.reply_to(message, "Использование: /login <имя пользователя> <пароль>")

@bot.message_handler(commands=['logout'])
def handle_logout(message):
    if message.from_user.id in bot.user_data:
        user_id = bot.user_data[message.from_user.id]['user_id']
        remove_telegram_user_id(user_id, message.from_user.id)
        del bot.user_data[message.from_user.id]
        bot.reply_to(message, "Вы успешно вышли из системы.")
    else:
        bot.reply_to(message, "Вы не были авторизованы.")

@bot.message_handler(commands=['balance'])
def handle_balance(message):
    refresh_user_data(message.from_user.id)
    if message.from_user.id in bot.user_data:
        user_data = bot.user_data[message.from_user.id]
        balance = user_data.get('balance', 0)
        free_searches = user_data.get('free_searches', 0)
        bot.reply_to(message, f"Ваш баланс: {balance} руб.\nБесплатные пробивы: {free_searches}")
    else:
        bot.reply_to(message, "Сначала выполните вход с помощью команды /login.")

@bot.message_handler(commands=['addbalance'])
def handle_add_balance(message):
    refresh_user_data(message.from_user.id)
    if message.from_user.id in bot.user_data:
        try:
            bot.reply_to(message, "Введите сумму для пополнения:")
            bot.register_next_step_handler(message, handle_balance_amount)
        except Exception as e:
            log_error(f"Ошибка в команде /addbalance: {str(e)}")
            bot.reply_to(message, "Ошибка. Попробуйте еще раз.")
    else:
        bot.reply_to(message, "Сначала выполните вход с помощью команды /login.")

def handle_balance_amount(message):
    try:
        amount = float(message.text)
        if amount <= 0:
            bot.reply_to(message, "Сумма должна быть положительной. Попробуйте еще раз.")
            return

        user_id = bot.user_data[message.from_user.id]['user_id']
        try:
            add_pending_transaction(user_id, amount)
            markup = types.InlineKeyboardMarkup()
            usdt_button = types.InlineKeyboardButton(text="USDT (TRC20)", callback_data=f"usdt_trc20|{amount}")
            cryptomus_button = types.InlineKeyboardButton(text="Cryptomus (В разработке)", callback_data="cryptomus")
            markup.add(usdt_button, cryptomus_button)
            bot.reply_to(message, f"Выберите платежную систему:\nКурс: 1 USDT = {USDT_RATE} руб.\nУ вас есть 1 час для оплаты, иначе заказ будет аннулирован. Убедитесь, что на кошель поступает точная сумма.", reply_markup=markup)
        except ValueError:
            bot.reply_to(message, "Заявка на данную сумму уже существует. Подождите пока предыдущая транзакция завершится или выберите другую сумму.")
    except ValueError:
        bot.reply_to(message, "Неверная сумма. Попробуйте еще раз.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("usdt_trc20"))
def handle_usdt_trc20_selection(call):
    refresh_user_data(call.from_user.id)
    if call.from_user.id in bot.user_data:
        try:
            _, amount = call.data.split('|')
            bot.reply_to(call.message, f"Отправьте точную сумму {amount} USDT на адрес кошелька USDT (TRC20): {USDT_WALLET}\nПосле отправки транзакции используйте команду /checktransaction для проверки.")
        except Exception as e:
            log_error(f"Ошибка в обработке выбора платежной системы: {str(e)}")
            bot.reply_to(call.message, "Ошибка. Попробуйте еще раз.")
    else:
        bot.reply_to(call.message, "Сначала выполните вход с помощью команды /login.")

@bot.message_handler(commands=['checktransaction'])
def handle_check_transaction(message):
    refresh_user_data(message.from_user.id)
    if message.from_user.id in bot.user_data:
        try:
            user_id = bot.user_data[message.from_user.id]['user_id']
            transactions = get_trc20_transactions(USDT_WALLET)
            pending_transactions = []

            conn = sqlite3.connect(TRANSACTIONS_DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT amount FROM pending_transactions WHERE user_id = ?", (user_id,))
            pending_transactions = cursor.fetchall()
            conn.close()

            pending_amounts = [amount[0] for amount in pending_transactions]

            if transactions:
                for tx in transactions:
                    from_address = tx.get('from')
                    to_address = tx.get('to')
                    amount = int(tx.get('value', 0)) / 1e6
                    transaction_id = tx.get('transaction_id')
                    timestamp = tx.get('block_timestamp')

                    if to_address == USDT_WALLET and amount in pending_amounts:
                        add_balance(user_id, amount * USDT_RATE)
                        add_transaction(user_id, transaction_id, amount * USDT_RATE)
                        remove_pending_transaction(user_id, amount)
                        bot.reply_to(message, f"Транзакция подтверждена! Ваш баланс пополнен на {amount * USDT_RATE} руб.")
                        return
                bot.reply_to(message, "Нет новых транзакций на вашем кошельке.")
            else:
                bot.reply_to(message, "Транзакции не найдены.")
        except Exception as e:
            log_error(f"Ошибка в команде /checktransaction: {str(e)}")
            bot.reply_to(message, "Ошибка проверки транзакции. Пожалуйста, попробуйте еще раз позже.")
    else:
        bot.reply_to(message, "Сначала выполните вход с помощью команды /login.")

@bot.message_handler(commands=['transfer'])
def handle_transfer(message):
    refresh_user_data(message.from_user.id)
    if message.from_user.id in bot.user_data:
        try:
            _, target_username, amount = message.text.split()
            target_user_id = get_user_id_by_username(target_username)
            if target_user_id:
                amount = float(amount)
                user_id = bot.user_data[message.from_user.id]['user_id']
                if get_user_balance(user_id) >= amount:
                    deduct_balance(user_id, amount)
                    add_balance(target_user_id, amount)
                    bot.reply_to(message, f"Вы успешно перевели {amount} руб. пользователю {target_username}.")
                else:
                    bot.reply_to(message, "Недостаточно средств для перевода.")
            else:
                bot.reply_to(message, "Пользователь не найден.")
        except ValueError:
            bot.reply_to(message, "Использование: /transfer <имя пользователя> <сумма>")
        except Exception as e:
            log_error(f"Ошибка в команде /transfer: {str(e)}")
            bot.reply_to(message, "Ошибка. Попробуйте еще раз.")
    else:
        bot.reply_to(message, "Сначала выполните вход с помощью команды /login.")

@bot.message_handler(commands=['adminaddbalance'])
def handle_admin_add_balance(message):
    refresh_user_data(message.from_user.id)
    if message.from_user.id in bot.user_data:
        user_id = bot.user_data[message.from_user.id]['user_id']
        if is_admin(user_id):
            try:
                _, target_username, amount = message.text.split()
                target_user_id = get_user_id_by_username(target_username)
                if target_user_id:
                    add_balance(target_user_id, float(amount))
                    bot.reply_to(message, f"Баланс пользователя {target_username} пополнен на {amount} руб.")
                else:
                    bot.reply_to(message, "Пользователь не найден.")
            except ValueError:
                bot.reply_to(message, "Использование: /adminaddbalance <имя пользователя> <сумма>")
            except Exception as e:
                log_error(f"Ошибка в команде /adminaddbalance: {str(e)}")
                bot.reply_to(message, "Ошибка. Попробуйте еще раз.")
        else:
            bot.reply_to(message, "У вас нет прав администратора.")
    else:
        bot.reply_to(message, "Сначала выполните вход с помощью команды /login.")

@bot.message_handler(commands=['grantfree'])
def handle_grant_free_searches(message):
    refresh_user_data(message.from_user.id)
    if message.from_user.id in bot.user_data:
        user_id = bot.user_data[message.from_user.id]['user_id']
        if is_admin(user_id):
            try:
                _, target_username, count = message.text.split()
                target_user_id = get_user_id_by_username(target_username)
                if target_user_id:
                    grant_free_searches(target_user_id, int(count))
                    bot.reply_to(message, f"Пользователю {target_username} предоставлено {count} бесплатных пробивов.")
                else:
                    bot.reply_to(message, "Пользователь не найден.")
            except ValueError:
                bot.reply_to(message, "Использование: /grantfree <имя пользователя> <количество>")
            except Exception as e:
                log_error(f"Ошибка в команде /grantfree: {str(e)}")
                bot.reply_to(message, "Ошибка. Попробуйте еще раз.")
        else:
            bot.reply_to(message, "У вас нет прав администратора.")
    else:
        bot.reply_to(message, "Сначала выполните вход с помощью команды /login.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    if message.from_user.id in bot.user_data:
        user_id = bot.user_data[message.from_user.id]['user_id']
        refresh_user_data(message.from_user.id)
        try:
            with queue_lock:
                search_queue.append((message, user_id))

        except Exception as e:
            log_error(f"Ошибка в обработке сообщения: {str(e)}")
            bot.reply_to(message, "Ошибка обработки запроса. Пожалуйста, попробуйте еще раз позже.")
    else:
        bot.reply_to(message, "Сначала выполните вход с помощью команды /login.")

def process_search_queue():
    while True:
        if search_queue:
            with queue_lock:
                message, user_id = search_queue.pop(0)

            try:
                lines = message.text.split('\n')
                total_contacts = len(lines)
                free_searches = get_user_free_searches(user_id)
                balance = get_user_balance(user_id)
                required_balance = max(0, total_contacts - free_searches) * COST_PER_SEARCH

                if balance < required_balance:
                    bot.reply_to(message,
                                f"У вас недостаточно средств на балансе. Вам нужно {required_balance} руб. Пополните баланс с помощью команды /addbalance.")
                    return

                found_contacts = []
                not_found_contacts = []

                for line in lines:
                    parts = line.split()
                    if len(parts) >= 5:
                        name = ' '.join(parts[:3])
                        birthday = parts[3]
                        other_values = "".join(parts[4:])
                        contacts_phones = get_telegram_contacts(name, birthday)
                        contact_info = f"{name} {birthday} {other_values}\n"

                        if contacts_phones:
                            for phone in contacts_phones:
                                phone_numbers = phone.split(',')
                                for number in phone_numbers:
                                    contact_info += f"{number}\n"
                            found_contacts.append(contact_info)
                        else:
                            not_found_contacts.append(f"RU|{name} {birthday} {other_values}\n")

                # Обработка API-запроса для не найденных контактов
                if not_found_contacts:
                    people = [f"RU|{line.strip()}" for line in not_found_contacts]
                    api_response = search_people(people)

                    if api_response and 'itemsGood' in api_response:
                        for person in api_response['itemsGood']:
                            query = person['query']
                            phones = []
                            for item in person['items']:
                                phones.extend(item.get('phones', []))
                            filtered_phones = [phone for phone in phones if phone.startswith('79')]
                            fio, birthday, score = query.split(' ', 2)
                            if filtered_phones:
                                for phone in filtered_phones:
                                    append_to_csv(fio, birthday, phone)
                                    found_contacts.append(f"{fio} {birthday} {score}\n{phone}\n")
                            else:
                                found_contacts.append(f"{fio} {birthday} {score}\nNo phones found.\n")
                    else:
                        bot.reply_to(message, "Ошибка при запросе к API.")

                combined_response = ''.join(found_contacts)
                messages = split_message(combined_response)
                for msg in messages:
                    bot.reply_to(message, msg)

                if free_searches >= total_contacts:
                    grant_free_searches(user_id, -total_contacts)
                else:
                    if free_searches > 0:
                        grant_free_searches(user_id, -free_searches)
                    deduct_balance(user_id, required_balance)

            except Exception as e:
                log_error(f"Ошибка в обработке сообщения: {str(e)}")
                bot.reply_to(message, "Ошибка обработки запроса. Пожалуйста, попробуйте еще раз позже.")
        time.sleep(1)  # Wait for 1 second before processing the next request

def load_user_sessions():
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, telegram_user_id FROM user_sessions")
        users = cursor.fetchall()
        for user_id, telegram_user_id in users:
            if telegram_user_id not in bot.user_data:
                bot.user_data[telegram_user_id] = {
                    'user_id': user_id,
                    'username': get_username(user_id),
                }
        conn.close()
    except Exception as e:
        log_error(f"Ошибка загрузки сессий пользователей: {str(e)}")

def get_username(user_id):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
        username = cursor.fetchone()[0]
        conn.close()
        return username
    except Exception as e:
        log_error(f"Ошибка получения имени пользователя: {str(e)}")
        return "неизвестный пользователь"

def add_telegram_user_id(user_id, telegram_user_id):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_sessions (user_id, telegram_user_id) VALUES (?, ?)",
                       (user_id, telegram_user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"Ошибка добавления telegram_user_id: {str(e)}")

def remove_telegram_user_id(user_id, telegram_user_id):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE user_id = ? AND telegram_user_id = ?",
                       (user_id, telegram_user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"Ошибка удаления telegram_user_id: {str(e)}")

load_user_sessions()

# Start the queue processing thread
queue_thread = threading.Thread(target=process_search_queue)
queue_thread.start()

bot.polling(none_stop=True)
