import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from datetime import datetime
import requests

BOT_TOKEN = '7172315946:AAE6LSdd3nA4MI2NAkcQ52noxp-mG2u57aE'

CONTACTS_DATABASE_FILE = r"D:\MYPROJECT\OSNOVA\BD\contacts.db"
USER_DATABASE_FILE = r"D:\MYPROJECT\OSNOVA\BD\users.db"
TRANSACTIONS_DATABASE_FILE = r"D:\MYPROJECT\OSNOVA\BD\transactions.db"
ERROR_LOG_FILE = r"D:\MYPROJECT\OSNOVA\BD\error_log.txt"

USDT_WALLET = 'TPoDU5YgGRfUUc79Ax378ENpWnm2LxhEK5'
TRON_API_TOKEN = '81d41398-348f-4711-af67-7e8ed36d5cdd'
USDT_RATE = 100

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())

user_data = {}

class RegisterForm(StatesGroup):
    username = State()
    password = State()

class LoginForm(StatesGroup):
    username = State()
    password = State()

class Form(StatesGroup):
    usdt_amount = State()
    txid = State()
    target_username = State()
    transfer_amount = State()

def create_user_database():
    conn = sqlite3.connect(USER_DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL,
                        balance REAL DEFAULT 0.0,
                        is_admin INTEGER DEFAULT 0,
                        free_searches INTEGER DEFAULT 0,
                        bot_token TEXT
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
        cursor.execute("SELECT phone FROM contacts WHERE name = ? AND birthday = ?", (name.lower(), format_date(birthday)))
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
    if user_id in user_data:
        user_data[user_id]['balance'] = get_user_balance(user_id)
        user_data[user_id]['free_searches'] = get_user_free_searches(user_id)

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
        cursor.execute("INSERT INTO pending_transactions (user_id, amount) VALUES (?, ?)", (user_id, amount))
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

def check_transaction(txid):
    try:
        url = f"https://api.trongrid.io/v1/transactions/{txid}"
        headers = {'TRON-PRO-API-KEY': TRON_API_TOKEN}
        response = requests.get(url, headers=headers)
        return response.json()
    except Exception as e:
        log_error(f"Ошибка проверки транзакции: {str(e)}")
        return None

def start_menu(user_id):
    markup = types.InlineKeyboardMarkup()
    if user_id in user_data:
        markup.add(types.InlineKeyboardButton("Баланс", callback_data="balance"))
        markup.add(types.InlineKeyboardButton("Пополнить баланс", callback_data="addbalance"))
        markup.add(types.InlineKeyboardButton("Проверить транзакцию", callback_data="checktransaction"))
        markup.add(types.InlineKeyboardButton("Перевод средств", callback_data="transfer"))
        markup.add(types.InlineKeyboardButton("Выйти", callback_data="logout"))
        if is_admin(user_id):
            markup.add(types.InlineKeyboardButton("Добавить баланс пользователю", callback_data="adminaddbalance"))
            markup.add(types.InlineKeyboardButton("Предоставить бесплатные пробивы", callback_data="grantfree"))
    else:
        markup.add(types.InlineKeyboardButton("Регистрация", callback_data="register"))
        markup.add(types.InlineKeyboardButton("Вход", callback_data="login"))
    markup.add(types.InlineKeyboardButton("Помощь", callback_data="help"))
    return markup

@dp.message_handler(commands=['start'])
async def handle_start(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data:
        username = user_data[user_id].get('username', 'неизвестный пользователь')
        balance = get_user_balance(user_id)
        free_searches = get_user_free_searches(user_id)
        await message.answer(
            f"Привет, {username}!\nВаш баланс: {balance} руб.\nБесплатные пробивы: {free_searches}",
            reply_markup=start_menu(user_id)
        )
    else:
        await message.answer(
            "Добро пожаловать! Выберите действие:",
            reply_markup=start_menu(user_id)
        )

@dp.callback_query_handler(lambda c: c.data == 'help')
async def handle_help(callback_query: types.CallbackQuery):
    help_text = (
        "Список доступных команд:\n"
        "Регистрация - Зарегистрировать новый аккаунт\n"
        "Вход - Войти в существующий аккаунт\n"
        "Баланс - Показать баланс\n"
        "Пополнить баланс - Пополнить баланс\n"
        "Проверить транзакцию - Проверить транзакцию\n"
        "Перевод средств - Перевести средства другому пользователю\n"
        "Команды администратора - Доступные команды для администраторов\n"
        "Помощь - Показать это сообщение\n"
    )
    await bot.send_message(callback_query.from_user.id, help_text, reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'register')
async def handle_register(callback_query: types.CallbackQuery):
    await RegisterForm.username.set()
    await bot.send_message(callback_query.from_user.id, "Введите имя пользователя:")
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=RegisterForm.username)
async def process_register_username(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['username'] = message.text
    await RegisterForm.next()
    await message.reply("Введите пароль:")

@dp.message_handler(state=RegisterForm.password)
async def process_register_password(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        username = data['username']
        password = message.text
    response = register_user(username, password)
    await message.reply(response, reply_markup=start_menu(message.from_user.id))
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'login')
async def handle_login(callback_query: types.CallbackQuery):
    await LoginForm.username.set()
    await bot.send_message(callback_query.from_user.id, "Введите имя пользователя:")
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=LoginForm.username)
async def process_login_username(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['username'] = message.text
    await LoginForm.next()
    await message.reply("Введите пароль:")

@dp.message_handler(state=LoginForm.password)
async def process_login_password(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        username = data['username']
        password = message.text
    user = authenticate_user(username, password)
    if user:
        user_id = user[0]
        user_data[message.from_user.id] = {
            'user_id': user_id,
            'username': user[1],
        }
        add_telegram_user_id(user_id, message.from_user.id)
        await message.reply(f"Вход выполнен успешно!\nПривет, {user[1]}!", reply_markup=start_menu(message.from_user.id))
    else:
        await message.reply("Неверное имя пользователя или пароль.", reply_markup=start_menu(message.from_user.id))
    await state.finish()

@dp.callback_query_handler(lambda c: c.data == 'balance')
async def handle_balance(callback_query: types.CallbackQuery):
    if callback_query.from_user.id in user_data:
        user_id = user_data[callback_query.from_user.id]['user_id']
        balance = get_user_balance(user_id)
        free_searches = get_user_free_searches(user_id)
        await bot.send_message(callback_query.from_user.id, f"Ваш баланс: {balance} руб.\nБесплатные пробивы: {free_searches}", reply_markup=start_menu(callback_query.from_user.id))
    else:
        await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.", reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'addbalance')
async def handle_add_balance(callback_query: types.CallbackQuery):
    if callback_query.from_user.id in user_data:
        markup = types.InlineKeyboardMarkup()
        usdt_button = types.InlineKeyboardButton(text="USDT (TRC20)", callback_data="usdt_trc20")
        cryptomus_button = types.InlineKeyboardButton(text="Cryptomus (В разработке)", callback_data="cryptomus")
        markup.add(usdt_button, cryptomus_button)
        await bot.send_message(callback_query.from_user.id, f"Выберите платежную систему:\nКурс: 1 USDT = {USDT_RATE} руб.", reply_markup=markup)
    else:
        await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.", reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'usdt_trc20')
async def handle_usdt_selection(callback_query: types.CallbackQuery):
    await Form.usdt_amount.set()
    await bot.send_message(callback_query.from_user.id, f"Отправьте точную сумму на адрес кошелька USDT (TRC20): {USDT_WALLET}\nВведите сумму для пополнения:")
    await bot.answer_callback_query(callback_query.id)

@dp.message_handler(state=Form.usdt_amount)
async def process_usdt_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.reply("Сумма должна быть положительной. Попробуйте еще раз.")
            return
        user_id = user_data[message.from_user.id]['user_id']
        add_pending_transaction(user_id, amount)
        await message.reply(f"Заявка на пополнение на сумму {amount} USDT создана.\nОтправьте точную сумму на адрес кошелька USDT (TRC20): {USDT_WALLET}\nПосле отправки транзакции используйте команду Проверить транзакцию.", reply_markup=start_menu(message.from_user.id))
    except ValueError:
        await message.reply("Неверная сумма. Попробуйте еще раз.")
    except Exception as e:
        log_error(f"Ошибка в обработке суммы USDT: {str(e)}")
        await message.reply("Ошибка обработки суммы. Пожалуйста, попробуйте еще раз позже.",
                            reply_markup=start_menu(message.from_user.id))
    finally:
        await state.finish()

    @dp.callback_query_handler(lambda c: c.data == 'checktransaction')
    async def handle_checktransaction(callback_query: types.CallbackQuery):
        await Form.txid.set()
        await bot.send_message(callback_query.from_user.id, "Введите идентификатор транзакции (txid):")
        await bot.answer_callback_query(callback_query.id)

    @dp.message_handler(state=Form.txid)
    async def process_txid(message: types.Message, state: FSMContext):
        try:
            txid = message.text
            transaction = check_transaction(txid)
            if transaction and 'raw_data' in transaction and 'contract' in transaction['raw_data']:
                for contract in transaction['raw_data']['contract']:
                    if 'parameter' in contract and 'value' in contract['parameter'] and 'to_address' in \
                            contract['parameter']['value']:
                        to_address = contract['parameter']['value']['to_address']
                        if to_address == USDT_WALLET:
                            amount = contract['parameter']['value']['amount'] / 1000000  # сумма в TRX, переводим в USDT
                            rub_amount = amount * USDT_RATE
                            user_id = user_data[message.from_user.id]['user_id']
                            add_balance(user_id, rub_amount)
                            add_transaction(user_id, txid, rub_amount)
                            remove_pending_transaction(user_id, amount)
                            await message.reply(f"Транзакция подтверждена! Ваш баланс пополнен на {rub_amount} руб.",
                                                reply_markup=start_menu(message.from_user.id))
                            return
            await message.reply("Транзакция не найдена или неверный идентификатор транзакции.",
                                reply_markup=start_menu(message.from_user.id))
        except Exception as e:
            log_error(f"Ошибка в обработке txid: {str(e)}")
            await message.reply("Ошибка обработки идентификатора. Пожалуйста, попробуйте еще раз позже.",
                                reply_markup=start_menu(message.from_user.id))
        finally:
            await state.finish()

    @dp.callback_query_handler(lambda c: c.data == 'transfer')
    async def handle_transfer(callback_query: types.CallbackQuery):
        if callback_query.from_user.id in user_data:
            await Form.target_username.set()
            await bot.send_message(callback_query.from_user.id,
                                   "Введите имя пользователя, которому хотите перевести средства:")
        else:
            await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                                   reply_markup=start_menu(callback_query.from_user.id))
        await bot.answer_callback_query(callback_query.id)

    @dp.message_handler(state=Form.target_username)
    async def process_target_username(message: types.Message, state: FSMContext):
        async with state.proxy() as data:
            data['target_username'] = message.text
        await Form.next()
        await message.reply("Введите сумму для перевода:")

    @dp.message_handler(state=Form.transfer_amount)
    async def process_transfer_amount(message: types.Message, state: FSMContext):
        try:
            amount = float(message.text)
            if amount <= 0:
                await message.reply("Сумма должна быть положительной. Попробуйте еще раз.")
                return
            async with state.proxy() as data:
                target_username = data['target_username']
            target_user_id = get_user_id_by_username(target_username)
            if target_user_id:
                user_id = user_data[message.from_user.id]['user_id']
                if get_user_balance(user_id) >= amount:
                    deduct_balance(user_id, amount)
                    add_balance(target_user_id, amount)
                    await message.reply(f"Вы успешно перевели {amount} руб. пользователю {target_username}.",
                                        reply_markup=start_menu(message.from_user.id))
                else:
                    await message.reply("Недостаточно средств для перевода.",
                                        reply_markup=start_menu(message.from_user.id))
            else:
                await message.reply("Пользователь не найден.", reply_markup=start_menu(message.from_user.id))
        except ValueError:
            await message.reply("Неверная сумма. Попробуйте еще раз.", reply_markup=start_menu(message.from_user.id))
        except Exception as e:
            log_error(f"Ошибка в обработке перевода: {str(e)}")
            await message.reply("Ошибка обработки перевода. Пожалуйста, попробуйте еще раз позже.",
                                reply_markup=start_menu(message.from_user.id))
        finally:
            await state.finish()

    @dp.callback_query_handler(lambda c: c.data == 'logout')
    async def handle_logout(callback_query: types.CallbackQuery):
        if callback_query.from_user.id in user_data:
            user_id = user_data[callback_query.from_user.id]['user_id']
            remove_telegram_user_id(user_id, callback_query.from_user.id)
            del user_data[callback_query.from_user.id]
            await bot.send_message(callback_query.from_user.id, "Вы вышли из системы.",
                                   reply_markup=start_menu(callback_query.from_user.id))
        await bot.answer_callback_query(callback_query.id)

    @dp.callback_query_handler(lambda c: c.data == 'admin')
    async def handle_admin(callback_query: types.CallbackQuery):
        if callback_query.from_user.id in user_data:
            user_id = user_data[callback_query.from_user.id]['user_id']
            if is_admin(user_id):
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("Добавить баланс пользователю", callback_data="adminaddbalance"))
                markup.add(types.InlineKeyboardButton("Предоставить бесплатные пробивы", callback_data="grantfree"))
                await bot.send_message(callback_query.from_user.id, "Выберите действие:", reply_markup=markup)
            else:
                await bot.send_message(callback_query.from_user.id, "У вас нет прав администратора.")
        else:
            await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                                   reply_markup=start_menu(callback_query.from_user.id))
        await bot.answer_callback_query(callback_query.id)

    @dp.callback_query_handler(lambda c: c.data == 'adminaddbalance')
    async def handle_admin_add_balance(callback_query: types.CallbackQuery):
        if callback_query.from_user.id in user_data:
            user_id = user_data[callback_query.from_user.id]['user_id']
            if is_admin(user_id):
                await Form.target_username.set()
                await bot.send_message(callback_query.from_user.id,
                                       "Введите имя пользователя, которому хотите добавить баланс:")
            else:
                await bot.send_message(callback_query.from_user.id, "У вас нет прав администратора.")
        else:
            await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                                   reply_markup=start_menu(callback_query.from_user.id))
        await bot.answer_callback_query(callback_query.id)

    @dp.message_handler(state=Form.target_username)
    async def process_admin_target_username(message: types.Message, state: FSMContext):
        async with state.proxy() as data:
            data['target_username'] = message.text
        await Form.next()
        await message.reply("Введите сумму для добавления баланса:")

    @dp.message_handler(state=Form.transfer_amount)
    async def process_admin_add_balance_amount(message: types.Message, state: FSMContext):
        try:
            amount = float(message.text)
            if amount <= 0:
                await message.reply("Сумма должна быть положительной. Попробуйте еще раз.")
                return
            async with state.proxy() as data:
                target_username = data['target_username']
            target_user_id = get_user_id_by_username(target_username)
            if target_user_id:
                add_balance(target_user_id, amount)
                await message.reply(f"Баланс пользователя {target_username} пополнен на {amount} руб.",
                                    reply_markup=start_menu(message.from_user.id))
            else:
                await message.reply("Пользователь не найден.", reply_markup=start_menu(message.from_user.id))
        except ValueError:
            await message.reply("Неверная сумма. Попробуйте еще раз.", reply_markup=start_menu(message.from_user.id))
        except Exception as e:
            log_error(f"Ошибка в добавлении баланса администратором: {str(e)}")
            await message.reply("Ошибка добавления баланса. Пожалуйста, попробуйте еще раз позже.",
                                reply_markup=start_menu(message.from_user.id))
        finally:
            await state.finish()

    @dp.callback_query_handler(lambda c: c.data == 'grantfree')
    async def handle_grant_free_searches(callback_query: types.CallbackQuery):
        if callback_query.from_user.id in user_data:
            user_id = user_data[callback_query.from_user.id]['user_id']
            if is_admin(user_id):
                await Form.target_username.set()
                await bot.send_message(callback_query.from_user.id,
                                       "Введите имя пользователя, которому хотите предоставить бесплатные пробивы:")
            else:
                await bot.send_message(callback_query.from_user.id, "У вас нет прав администратора.")
        else:
            await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                                   reply_markup=start_menu(callback_query.from_user.id))
        await bot.answer_callback_query(callback_query.id)

    @dp.message_handler(state=Form.target_username)
    async def process_grant_free_target_username(message: types.Message, state: FSMContext):
        async with state.proxy() as data:
            data['target_username'] = message.text
        await Form.next()
        await message.reply("Введите количество бесплатных пробивов:")

        await message.reply("Ошибка обработки суммы. Пожалуйста, попробуйте еще раз позже.",
                            reply_markup=start_menu(message.from_user.id))

    finally:
    await state.finish()


@dp.callback_query_handler(lambda c: c.data == 'checktransaction')
async def handle_checktransaction(callback_query: types.CallbackQuery):
    await Form.txid.set()
    await bot.send_message(callback_query.from_user.id, "Введите идентификатор транзакции (txid):")
    await bot.answer_callback_query(callback_query.id)


@dp.message_handler(state=Form.txid)
async def process_txid(message: types.Message, state: FSMContext):
    try:
        txid = message.text
        transaction = check_transaction(txid)
        if transaction and 'raw_data' in transaction and 'contract' in transaction['raw_data']:
            for contract in transaction['raw_data']['contract']:
                if 'parameter' in contract and 'value' in contract['parameter'] and 'to_address' in \
                        contract['parameter']['value']:
                    to_address = contract['parameter']['value']['to_address']
                    if to_address == USDT_WALLET:
                        amount = contract['parameter']['value']['amount'] / 1000000  # сумма в TRX, переводим в USDT
                        rub_amount = amount * USDT_RATE
                        user_id = user_data[message.from_user.id]['user_id']
                        add_balance(user_id, rub_amount)
                        add_transaction(user_id, txid, rub_amount)
                        remove_pending_transaction(user_id, amount)
                        await message.reply(f"Транзакция подтверждена! Ваш баланс пополнен на {rub_amount} руб.",
                                            reply_markup=start_menu(message.from_user.id))
                        return
        await message.reply("Транзакция не найдена или неверный идентификатор транзакции.",
                            reply_markup=start_menu(message.from_user.id))
    except Exception as e:
        log_error(f"Ошибка в обработке txid: {str(e)}")
        await message.reply("Ошибка обработки идентификатора. Пожалуйста, попробуйте еще раз позже.",
                            reply_markup=start_menu(message.from_user.id))
    finally:
        await state.finish()


@dp.callback_query_handler(lambda c: c.data == 'transfer')
async def handle_transfer(callback_query: types.CallbackQuery):
    if callback_query.from_user.id in user_data:
        await Form.target_username.set()
        await bot.send_message(callback_query.from_user.id,
                               "Введите имя пользователя, которому хотите перевести средства:")
    else:
        await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                               reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)


@dp.message_handler(state=Form.target_username)
async def process_target_username(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['target_username'] = message.text
    await Form.next()
    await message.reply("Введите сумму для перевода:")


@dp.message_handler(state=Form.transfer_amount)
async def process_transfer_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.reply("Сумма должна быть положительной. Попробуйте еще раз.")
            return
        async with state.proxy() as data:
            target_username = data['target_username']
        target_user_id = get_user_id_by_username(target_username)
        if target_user_id:
            user_id = user_data[message.from_user.id]['user_id']
            if get_user_balance(user_id) >= amount:
                deduct_balance(user_id, amount)
                add_balance(target_user_id, amount)
                await message.reply(f"Вы успешно перевели {amount} руб. пользователю {target_username}.",
                                    reply_markup=start_menu(message.from_user.id))
            else:
                await message.reply("Недостаточно средств для перевода.", reply_markup=start_menu(message.from_user.id))
        else:
            await message.reply("Пользователь не найден.", reply_markup=start_menu(message.from_user.id))
    except ValueError:
        await message.reply("Неверная сумма. Попробуйте еще раз.", reply_markup=start_menu(message.from_user.id))
    except Exception as e:
        log_error(f"Ошибка в обработке перевода: {str(e)}")
        await message.reply("Ошибка обработки перевода. Пожалуйста, попробуйте еще раз позже.",
                            reply_markup=start_menu(message.from_user.id))
    finally:
        await state.finish()


@dp.callback_query_handler(lambda c: c.data == 'logout')
async def handle_logout(callback_query: types.CallbackQuery):
    if callback_query.from_user.id in user_data:
        user_id = user_data[callback_query.from_user.id]['user_id']
        remove_telegram_user_id(user_id, callback_query.from_user.id)
        del user_data[callback_query.from_user.id]
        await bot.send_message(callback_query.from_user.id, "Вы вышли из системы.",
                               reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == 'admin')
async def handle_admin(callback_query: types.CallbackQuery):
    if callback_query.from_user.id in user_data:
        user_id = user_data[callback_query.from_user.id]['user_id']
        if is_admin(user_id):
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("Добавить баланс пользователю", callback_data="adminaddbalance"))
            markup.add(types.InlineKeyboardButton("Предоставить бесплатные пробивы", callback_data="grantfree"))
            await bot.send_message(callback_query.from_user.id, "Выберите действие:", reply_markup=markup)
        else:
            await bot.send_message(callback_query.from_user.id, "У вас нет прав администратора.")
    else:
        await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                               reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)


@dp.callback_query_handler(lambda c: c.data == 'adminaddbalance')
async def handle_admin_add_balance(callback_query: types.CallbackQuery):
    if callback_query.from_user.id in user_data:
        user_id = user_data[callback_query.from_user.id]['user_id']
        if is_admin(user_id):
            await Form.target_username.set()
            await bot.send_message(callback_query.from_user.id,
                                   "Введите имя пользователя, которому хотите добавить баланс:")
        else:
            await bot.send_message(callback_query.from_user.id, "У вас нет прав администратора.")
    else:
        await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                               reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)


@dp.message_handler(state=Form.target_username)
async def process_admin_target_username(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['target_username'] = message.text
    await Form.next()
    await message.reply("Введите сумму для добавления баланса:")


@dp.message_handler(state=Form.transfer_amount)
async def process_admin_add_balance_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        if amount <= 0:
            await message.reply("Сумма должна быть положительной. Попробуйте еще раз.")
            return
        async with state.proxy() as data:
            target_username = data['target_username']
        target_user_id = get_user_id_by_username(target_username)
        if target_user_id:
            add_balance(target_user_id, amount)
            await message.reply(f"Баланс пользователя {target_username} пополнен на {amount} руб.",
                                reply_markup=start_menu(message.from_user.id))
        else:
            await message.reply("Пользователь не найден.", reply_markup=start_menu(message.from_user.id))
    except ValueError:
        await message.reply("Неверная сумма. Попробуйте еще раз.", reply_markup=start_menu(message.from_user.id))
    except Exception as e:
        log_error(f"Ошибка в добавлении баланса администратором: {str(e)}")
        await message.reply("Ошибка добавления баланса. Пожалуйста, попробуйте еще раз позже.",
                            reply_markup=start_menu(message.from_user.id))
    finally:
        await state.finish()


@dp.callback_query_handler(lambda c: c.data == 'grantfree')
async def handle_grant_free_searches(callback_query: types.CallbackQuery):
    if callback_query.from_user.id in user_data:
        user_id = user_data[callback_query.from_user.id]['user_id']
        if is_admin(user_id):
            await Form.target_username.set()
            await bot.send_message(callback_query.from_user.id,
                                   "Введите имя пользователя, которому хотите предоставить бесплатные пробивы:")
        else:
            await bot.send_message(callback_query.from_user.id, "У вас нет прав администратора.")
    else:
        await bot.send_message(callback_query.from_user.id, "Сначала выполните вход с помощью команды Вход.",
                               reply_markup=start_menu(callback_query.from_user.id))
    await bot.answer_callback_query(callback_query.id)


@dp.message_handler(state=Form.target_username)
async def process_grant_free_target_username(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        data['target_username'] = message.text
    await Form.next()
    await message.reply("Введите количество бесплатных пробивов:")


@dp.message_handler(state=Form.transfer_amount)
async def process_grant_free_amount(message: types.Message, state: FSMContext):
    try:
        count = int(message.text)
        if count <= 0:
            await message.reply("Количество должно быть положительным. Попробуйте еще раз.")
            return
        async with state.proxy() as data:
            target_username = data['target_username']
        target_user_id = get_user_id_by_username(target_username)
        if target_user_id:
            grant_free_searches(target_user_id, count)
            await message.reply(f"Пользователю {target_username} предоставлено {count} бесплатных пробивов.", reply_markup=start_menu(message.from_user.id))
        else:
            await message.reply("Пользователь не найден.", reply_markup=start_menu(message.from_user.id))
    except ValueError:
        await message.reply("Неверное количество. Попробуйте еще раз.", reply_markup=start_menu(message.from_user.id))
    except Exception as e:
        log_error(f"Ошибка в предоставлении бесплатных пробивов: {str(e)}")
        await message.reply("Ошибка предоставления бесплатных пробивов. Пожалуйста, попробуйте еще раз позже.", reply_markup=start_menu(message.from_user.id))
    finally:
        await state.finish()

def load_user_sessions():
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, telegram_user_id FROM user_sessions")
        users = cursor.fetchall()
        for user_id, telegram_user_id in users:
            if telegram_user_id not in user_data:
                user_data[telegram_user_id] = {
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
        cursor.execute("INSERT OR IGNORE INTO user_sessions (user_id, telegram_user_id) VALUES (?, ?)", (user_id, telegram_user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"Ошибка добавления telegram_user_id: {str(e)}")

def remove_telegram_user_id(user_id, telegram_user_id):
    try:
        conn = sqlite3.connect(USER_DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE user_id = ? AND telegram_user_id = ?", (user_id, telegram_user_id))
        conn.commit()
        conn.close()
    except Exception as e:
        log_error(f"Ошибка удаления telegram_user_id: {str(e)}")

load_user_sessions()
executor.start_polling(dp, skip_updates=True)
