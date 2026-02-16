import asyncio
import logging
import sqlite3
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===== НАСТРОЙКИ =====
BOT_TOKEN = "8336035363:AAElYUVwWI2Le3tg35mLLiJBk8VeCqro6n0"
ADMINS = [8127013147]

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TEXT,
            balance INTEGER DEFAULT 0,
            last_bonus TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT UNIQUE,
            title TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            price INTEGER
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            purchase_date TEXT,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(item_id) REFERENCES shop_items(id)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward INTEGER,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prize TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active',
            winner_id INTEGER
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            user_id INTEGER,
            giveaway_id INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(user_id),
            FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
        )
    ''')
    conn.commit()
    conn.close()

# ===== СОСТОЯНИЯ =====
class CreateGiveaway(StatesGroup):
    prize = State()
    end_date = State()

class AddChannel(StatesGroup):
    chat_id = State()
    title = State()

class RemoveChannel(StatesGroup):
    chat_id = State()

class AddShopItem(StatesGroup):
    name = State()
    description = State()
    price = State()

class RemoveShopItem(StatesGroup):
    item_id = State()

class CreatePromocode(StatesGroup):
    code = State()
    reward = State()
    max_uses = State()

class Broadcast(StatesGroup):
    message = State()

class AddBalance(StatesGroup):
    user_id = State()
    amount = State()

class CasinoBet(StatesGroup):
    amount = State()

class PromoActivate(StatesGroup):
    code = State()

class CompleteGiveaway(StatesGroup):
    giveaway_id = State()

class PickWinner(StatesGroup):
    giveaway_id = State()

# ===== ИНИЦИАЛИЗАЦИЯ =====
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===== ПРОВЕРКА АДМИНА =====
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# ===== ПРОВЕРКА ПОДПИСКИ =====
async def check_subscription(user_id: int) -> bool:
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT chat_id FROM channels")
    channels = cur.fetchall()
    conn.close()
    if not channels:
        return True
    for ch in channels:
        chat_id = ch[0]
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception:
            return False
    return True

def subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")]
    ])

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🎁 Бонус", callback_data="bonus")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop"),
         InlineKeyboardButton(text="🎰 Казино", callback_data="casino")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="promo"),
         InlineKeyboardButton(text="🎲 Розыгрыши", callback_data="giveaways")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать розыгрыш", callback_data="admin_create")],
        [InlineKeyboardButton(text="📋 Активные розыгрыши", callback_data="admin_list")],
        [InlineKeyboardButton(text="✅ Завершить розыгрыш", callback_data="admin_complete")],
        [InlineKeyboardButton(text="🏆 Выбрать победителя", callback_data="admin_pick_winner")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💰 Начислить монеты", callback_data="admin_add_balance")],
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="admin_add_channel")],
        [InlineKeyboardButton(text="➖ Удалить канал", callback_data="admin_remove_channel")],
        [InlineKeyboardButton(text="📦 Управление магазином", callback_data="admin_shop_menu")],
        [InlineKeyboardButton(text="🎫 Управление промокодами", callback_data="admin_promo_menu")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")]
    ])

def back_to_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад в админку", callback_data="admin_back")]
    ])

def shop_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_shop_add")],
        [InlineKeyboardButton(text="➖ Удалить товар", callback_data="admin_shop_remove")],
        [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_shop_list")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
    ])

def promo_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_promo_create")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="admin_promo_list")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
    ])

# ===== СТАРТ =====
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, joined_date, balance) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0))
    conn.commit()
    conn.close()
    if not await check_subscription(user_id):
        await message.answer("❗️ Для доступа к боту нужно подписаться на наши каналы.\nПосле подписки нажми кнопку ниже.", reply_markup=subscription_keyboard())
        return
    await message.answer(f"Привет, {first_name}!\nДобро пожаловать в бота!", reply_markup=main_keyboard())

# ===== ПРОВЕРКА ПОДПИСКИ =====
@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await check_subscription(callback.from_user.id):
        await callback.message.edit_text("✅ Подписка подтверждена! Добро пожаловать.", reply_markup=main_keyboard())
    else:
        await callback.answer("❌ Вы ещё не подписались на все каналы!", show_alert=True)

# ===== ПРОФИЛЬ =====
@dp.callback_query(lambda c: c.data == "profile")
async def profile_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT balance, joined_date FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        balance, joined = row
        text = f"👤 Ваш профиль:\n💰 Баланс: {balance} монет\n📅 Зарегистрирован: {joined}"
    else:
        text = "Профиль не найден"
    await callback.message.edit_text(text, reply_markup=main_keyboard())

# ===== БОНУС =====
@dp.callback_query(lambda c: c.data == "bonus")
async def bonus_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT last_bonus FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    last_bonus_str = row[0] if row else None
    now = datetime.now()
    if last_bonus_str:
        last_bonus = datetime.strptime(last_bonus_str, "%Y-%m-%d %H:%M:%S")
        if now - last_bonus < timedelta(days=1):
            remaining = timedelta(days=1) - (now - last_bonus)
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds // 60) % 60
            await callback.answer(f"Бонус можно будет получить через {hours} ч {minutes} мин", show_alert=True)
            conn.close()
            return
    bonus = random.randint(5, 15)
    cur.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id=?", (bonus, now.strftime("%Y-%m-%d %H:%M:%S"), user_id))
    conn.commit()
    conn.close()
    await callback.message.edit_text(f"🎉 Вы получили бонус {bonus} монет!", reply_markup=main_keyboard())

# ===== МАГАЗИН =====
@dp.callback_query(lambda c: c.data == "shop")
async def shop_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, price FROM shop_items")
    items = cur.fetchall()
    conn.close()
    if not items:
        await callback.message.edit_text("🛒 В магазине пока нет товаров.", reply_markup=main_keyboard())
        return
    text = "🛒 Магазин:\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for item in items:
        item_id, name, desc, price = item
        text += f"🔹 {name}\n{desc}\n💰 {price} монет\n\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"Купить {name}", callback_data=f"buy_{item_id}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="« Назад", callback_data="back_main")])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def buy_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    item_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT name, price FROM shop_items WHERE id=?", (item_id,))
    item = cur.fetchone()
    if not item:
        await callback.answer("Товар не найден", show_alert=True)
        conn.close()
        return
    name, price = item
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    balance = cur.fetchone()[0]
    if balance < price:
        await callback.answer("Недостаточно монет!", show_alert=True)
        conn.close()
        return
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (price, user_id))
    cur.execute("INSERT INTO purchases (user_id, item_id, purchase_date) VALUES (?, ?, ?)",
                (user_id, item_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    await callback.answer(f"✅ Вы купили {name}! Скоро админ свяжется с вами.", show_alert=True)
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, f"🛒 Покупка: пользователь {user_id} купил {name} за {price} монет.")
        except:
            pass
    await callback.message.edit_text(f"✅ Покупка совершена!", reply_markup=main_keyboard())

# ===== КАЗИНО =====
@dp.callback_query(lambda c: c.data == "casino")
async def casino_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    await callback.message.edit_text("🎰 Введите сумму ставки (целое число):")
    await state.set_state(CasinoBet.amount)

@dp.message(CasinoBet.amount)
async def casino_bet_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    if amount <= 0:
        await message.answer("Ставка должна быть положительной.")
        return
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        await state.clear()
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    balance = cur.fetchone()[0]
    if amount > balance:
        await message.answer("Недостаточно монет.")
        conn.close()
        await state.clear()
        return
    win = random.random() < 0.3
    if win:
        cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        result_text = f"🎉 Вы выиграли! Ваш выигрыш: {amount*2} монет (чистый выигрыш {amount})"
    else:
        cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
        result_text = f"😢 Вы проиграли {amount} монет."
    conn.commit()
    cur.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    new_balance = cur.fetchone()[0]
    conn.close()
    await message.answer(f"{result_text}\n💰 Текущий баланс: {new_balance}")
    await state.clear()

# ===== ПРОМОКОД =====
@dp.callback_query(lambda c: c.data == "promo")
async def promo_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    await callback.message.edit_text("Введите промокод:")
    await state.set_state(PromoActivate.code)

@dp.message(PromoActivate.code)
async def promo_activate(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        await state.clear()
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT reward, max_uses, used_count FROM promocodes WHERE code=?", (code,))
    row = cur.fetchone()
    if not row:
        await message.answer("❌ Промокод не найден.")
        await state.clear()
        conn.close()
        return
    reward, max_uses, used = row
    if used >= max_uses:
        await message.answer("❌ Промокод уже использован максимальное количество раз.")
        await state.clear()
        conn.close()
        return
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, user_id))
    cur.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code=?", (code,))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Промокод активирован! Вы получили {reward} монет.")
    await state.clear()

# ===== РОЗЫГРЫШИ =====
@dp.callback_query(lambda c: c.data == "giveaways")
async def giveaways_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT id, prize, end_date FROM giveaways WHERE status='active'")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await callback.message.edit_text("Сейчас нет активных розыгрышей.", reply_markup=main_keyboard())
        return
    text = "🎁 Активные розыгрыши:\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for row in rows:
        gid, prize, end = row
        text += f"ID: {gid} | {prize} | до {end}\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"Участвовать в {prize}", callback_data=f"part_{gid}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="« Назад", callback_data="back_main")])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("part_"))
async def participate_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    giveaway_id = int(callback.data.split("_")[1])
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT status FROM giveaways WHERE id=?", (giveaway_id,))
    row = cur.fetchone()
    if not row or row[0] != 'active':
        await callback.answer("Розыгрыш не активен", show_alert=True)
        conn.close()
        return
    cur.execute("SELECT * FROM participants WHERE user_id=? AND giveaway_id=?", (user_id, giveaway_id))
    if cur.fetchone():
        await callback.answer("Вы уже участвуете", show_alert=True)
        conn.close()
        return
    cur.execute("INSERT INTO participants (user_id, giveaway_id) VALUES (?, ?)", (user_id, giveaway_id))
    conn.commit()
    conn.close()
    await callback.answer("✅ Вы участвуете в розыгрыше!", show_alert=True)

# ===== НАЗАД В ГЛАВНОЕ МЕНЮ =====
@dp.callback_query(lambda c: c.data == "back_main")
async def back_main_callback(callback: CallbackQuery):
    await callback.message.edit_text("Главное меню:", reply_markup=main_keyboard())

# ===== АДМИНКА =====
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У вас нет прав администратора.")
        return
    await message.answer("Панель администратора:", reply_markup=admin_keyboard())

# ===== ОБРАБОТЧИК АДМИН-КОЛБЭКОВ =====
@dp.callback_query(lambda c: c.data.startswith("admin_"))
async def admin_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    action = callback.data.split('_')[1]
    if action == "back":
        await callback.message.edit_text("Панель администратора:", reply_markup=admin_keyboard())
    elif action == "create":
        await callback.message.edit_text("Введите название приза:", reply_markup=back_to_admin_keyboard())
        await state.set_state(CreateGiveaway.prize)
    elif action == "list":
        conn = sqlite3.connect('database.db')
        cur = conn.cursor()
        cur.execute("SELECT id, prize, end_date FROM giveaways WHERE status='active'")
        rows = cur.fetchall()
        conn.close()
        if not rows:
            await callback.message.edit_text("Нет активных розыгрышей.", reply_markup=back_to_admin_keyboard())
        else:
            text = "Активные розыгрыши:\n"
            for row in rows:
                text += f"ID: {row[0]} | {row[1]} | до {row[2]}\n"
            await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())
    elif action == "complete":
        await callback.message.edit_text("Введите ID розыгрыша для завершения:", reply_markup=back_to_admin_keyboard())
        await state.set_state(CompleteGiveaway.giveaway_id)
    elif action == "pick_winner":
        await callback.message.edit_text("Введите ID розыгрыша для выбора победителя:", reply_markup=back_to_admin_keyboard())
        await state.set_state(PickWinner.giveaway_id)
    elif action == "broadcast":
        await callback.message.edit_text("Введите сообщение для рассылки:", reply_markup=back_to_admin_keyboard())
        await state.set_state(Broadcast.message)
    elif action == "add_balance":
        await callback.message.edit_text("Введите ID пользователя и сумму через пробел (пример: 123456789 100):", reply_markup=back_to_admin_keyboard())
        await state.set_state(AddBalance.user_id)
    elif action == "add_channel":
        await callback.message.edit_text("Введите chat_id канала (например @channel или -100123456789):", reply_markup=back_to_admin_keyboard())
        await state.set_state(AddChannel.chat_id)
    elif action == "remove_channel":
        await callback.message.edit_text("Введите chat_id канала для удаления:", reply_markup=back_to_admin_keyboard())
        await state.set_state(RemoveChannel.chat_id)
    elif action == "shop_menu":
        await callback.message.edit_text("Управление магазином:", reply_markup=shop_admin_keyboard())
    elif action == "promo_menu":
        await callback.message.edit_text("Управление промокодами:", reply_markup=promo_admin_keyboard())
    elif action == "stats":
        conn = sqlite3.connect('database.db')
        cur = conn.cursor()
        users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_balance = cur.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
        active_giveaways = cur.execute("SELECT COUNT(*) FROM giveaways WHERE status='active'").fetchone()[0]
        shop_items = cur.execute("SELECT COUNT(*) FROM shop_items").fetchone()[0]
        conn.close()
        text = f"📊 Статистика:\n👥 Пользователей: {users}\n💰 Всего монет: {total_balance}\n🎁 Активных розыгрышей: {active_giveaways}\n🛒 Товаров в магазине: {shop_items}"
        await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())

# ===== СОЗДАНИЕ РОЗЫГРЫША =====
@dp.message(CreateGiveaway.prize)
async def create_prize(message: Message, state: FSMContext):
    await state.update_data(prize=message.text)
    await message.answer("Введите дату окончания в формате ДД.ММ.ГГГГ (например, 31.12.2025):", reply_markup=back_to_admin_keyboard())
    await state.set_state(CreateGiveaway.end_date)

@dp.message(CreateGiveaway.end_date)
async def create_end_date(message: Message, state: FSMContext):
    data = await state.get_data()
    prize = data['prize']
    end_date = message.text
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("INSERT INTO giveaways (prize, end_date) VALUES (?, ?)", (prize, end_date))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Розыгрыш '{prize}' создан до {end_date}.")
    await state.clear()

# ===== ЗАВЕРШЕНИЕ РОЗЫГРЫША =====
@dp.message(CompleteGiveaway.giveaway_id)
async def complete_giveaway(message: Message, state: FSMContext):
    try:
        gid = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("UPDATE giveaways SET status='completed' WHERE id=? AND status='active'", (gid,))
    if cur.rowcount:
        await message.answer(f"✅ Розыгрыш ID {gid} завершён.")
    else:
        await message.answer("❌ Розыгрыш не найден или уже завершён.")
    conn.commit()
    conn.close()
    await state.clear()

# ===== ВЫБОР ПОБЕДИТЕЛЯ =====
@dp.message(PickWinner.giveaway_id)
async def pick_winner(message: Message, state: FSMContext):
    try:
        gid = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT prize FROM giveaways WHERE id=? AND status='active'", (gid,))
    row = cur.fetchone()
    if not row:
        await message.answer("❌ Активный розыгрыш не найден.")
        conn.close()
        await state.clear()
        return
    prize = row[0]
    cur.execute("SELECT user_id FROM participants WHERE giveaway_id=?", (gid,))
    participants = cur.fetchall()
    if not participants:
        await message.answer("❌ В розыгрыше нет участников.")
        conn.close()
        await state.clear()
        return
    winner_id = random.choice(participants)[0]
    cur.execute("UPDATE giveaways SET status='completed', winner_id=? WHERE id=?", (winner_id, gid))
    conn.commit()
    conn.close()
    await message.answer(f"🏆 Победитель розыгрыша '{prize}': {winner_id}")
    try:
        await bot.send_message(winner_id, f"🎉 Поздравляем! Вы победили в розыгрыше '{prize}'! Свяжитесь с админом для получения приза.")
    except:
        pass
    await state.clear()

# ===== РАССЫЛКА =====
@dp.message(Broadcast.message)
async def broadcast_message(message: Message, state: FSMContext):
    text = message.text
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = cur.fetchall()
    conn.close()
    success = 0
    for user in users:
        try:
            await bot.send_message(user[0], text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            pass
    await message.answer(f"✅ Рассылка завершена. Отправлено {success} пользователям.")
    await state.clear()

# ===== НАЧИСЛЕНИЕ МОНЕТ =====
@dp.message(AddBalance.user_id)
async def add_balance_user(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Введите ID и сумму через пробел.")
        return
    try:
        target_id = int(parts[0])
        amount = int(parts[1])
    except:
        await message.answer("Неверный формат.")
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, target_id))
    if cur.rowcount:
        await message.answer(f"✅ Пользователю {target_id} начислено {amount} монет.")
    else:
        await message.answer("❌ Пользователь не найден.")
    conn.commit()
    conn.close()
    await state.clear()

# ===== ДОБАВЛЕНИЕ КАНАЛА =====
@dp.message(AddChannel.chat_id)
async def add_channel_id(message: Message, state: FSMContext):
    await state.update_data(chat_id=message.text.strip())
    await message.answer("Введите название канала (для отображения):")
    await state.set_state(AddChannel.title)

@dp.message(AddChannel.title)
async def add_channel_title(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data['chat_id']
    title = message.text
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO channels (chat_id, title) VALUES (?, ?)", (chat_id, title))
        conn.commit()
        await message.answer(f"✅ Канал {title} добавлен.")
    except sqlite3.IntegrityError:
        await message.answer("❌ Такой канал уже есть.")
    conn.close()
    await state.clear()

# ===== УДАЛЕНИЕ КАНАЛА =====
@dp.message(RemoveChannel.chat_id)
async def remove_channel(message: Message, state: FSMContext):
    chat_id = message.text.strip()
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    if cur.rowcount:
        await message.answer("✅ Канал удалён.")
    else:
        await message.answer("❌ Канал не найден.")
    conn.commit()
    conn.close()
    await state.clear()

# ===== УПРАВЛЕНИЕ МАГАЗИНОМ (АДМИН) =====
@dp.callback_query(lambda c: c.data == "admin_shop_add")
async def shop_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название товара:", reply_markup=back_to_admin_keyboard())
    await state.set_state(AddShopItem.name)

@dp.message(AddShopItem.name)
async def shop_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите описание товара:")
    await state.set_state(AddShopItem.description)

@dp.message(AddShopItem.description)
async def shop_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Введите цену (целое число монет):")
    await state.set_state(AddShopItem.price)

@dp.message(AddShopItem.price)
async def shop_add_price(message: Message, state: FSMContext):
    try:
        price = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    data = await state.get_data()
    name = data['name']
    desc = data['description']
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("INSERT INTO shop_items (name, description, price) VALUES (?, ?, ?)", (name, desc, price))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Товар '{name}' добавлен с ценой {price}.")
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_shop_remove")
async def shop_remove(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите ID товара для удаления:", reply_markup=back_to_admin_keyboard())
    await state.set_state(RemoveShopItem.item_id)

@dp.message(RemoveShopItem.item_id)
async def shop_remove_id(message: Message, state: FSMContext):
    try:
        item_id = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("DELETE FROM shop_items WHERE id=?", (item_id,))
    if cur.rowcount:
        await message.answer("✅ Товар удалён.")
    else:
        await message.answer("❌ Товар не найден.")
    conn.commit()
    conn.close()
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_shop_list")
async def shop_list_admin(callback: CallbackQuery):
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT id, name, description, price FROM shop_items")
    items = cur.fetchall()
    conn.close()
    if not items:
        await callback.message.edit_text("Товаров нет.", reply_markup=shop_admin_keyboard())
        return
    text = "📦 Товары в магазине:\n"
    for item in items:
        text += f"ID: {item[0]} | {item[1]} | {item[2]} | {item[3]} монет\n"
    await callback.message.edit_text(text, reply_markup=shop_admin_keyboard())

# ===== УПРАВЛЕНИЕ ПРОМОКОДАМИ =====
@dp.callback_query(lambda c: c.data == "admin_promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите код промокода (латиница, цифры):", reply_markup=back_to_admin_keyboard())
    await state.set_state(CreatePromocode.code)

@dp.message(CreatePromocode.code)
async def promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.update_data(code=code)
    await message.answer("Введите количество монет:")
    await state.set_state(CreatePromocode.reward)

@dp.message(CreatePromocode.reward)
async def promo_reward(message: Message, state: FSMContext):
    try:
        reward = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    await state.update_data(reward=reward)
    await message.answer("Введите максимальное количество использований:")
    await state.set_state(CreatePromocode.max_uses)

@dp.message(CreatePromocode.max_uses)
async def promo_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    data = await state.get_data()
    code = data['code']
    reward = data['reward']
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO promocodes (code, reward, max_uses) VALUES (?, ?, ?)", (code, reward, max_uses))
        conn.commit()
        await message.answer(f"✅ Промокод {code} создан: {reward} монет, {max_uses} использований.")
    except sqlite3.IntegrityError:
        await message.answer("❌ Промокод с таким кодом уже существует.")
    conn.close()
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_promo_list")
async def promo_list_admin(callback: CallbackQuery):
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT code, reward, max_uses, used_count FROM promocodes")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await callback.message.edit_text("Промокодов нет.", reply_markup=promo_admin_keyboard())
        return
    text = "🎫 Промокоды:\n"
    for row in rows:
        text += f"{row[0]}: {row[1]} монет, использовано {row[3]}/{row[2]}\n"
    await callback.message.edit_text(text, reply_markup=promo_admin_keyboard())

# ===== ЗАПУСК =====
async def main():
    init_db()
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
