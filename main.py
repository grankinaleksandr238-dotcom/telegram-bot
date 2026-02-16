import asyncio
import logging
import random
import os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiosqlite

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "8336035363:AAElYUVwWI2Le3tg35mLLiJBk8VeCqro6n0")  # Токен из переменных окружения
ADMINS = [8127013147]  # ID админов можно тоже вынести в переменные позже

# ===== БАЗА ДАННЫХ =====
DB_PATH = 'database.db'

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_date TEXT,
                balance INTEGER DEFAULT 0,
                last_bonus TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE,
                title TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price INTEGER
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id INTEGER,
                purchase_date TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(item_id) REFERENCES shop_items(id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                reward INTEGER,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prize TEXT,
                end_date TEXT,
                media_file_id TEXT,
                media_type TEXT,
                status TEXT DEFAULT 'active',
                winner_id INTEGER
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                user_id INTEGER,
                giveaway_id INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
            )
        ''')
        await db.commit()

# ===== СОСТОЯНИЯ =====
class CreateGiveaway(StatesGroup):
    prize = State()
    end_date = State()
    media = State()

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

class BroadcastConfirm(StatesGroup):
    waiting = State()

class AddBalance(StatesGroup):
    user_id = State()
    amount = State()

class CasinoBet(StatesGroup):
    amount = State()

class PromoActivate(StatesGroup):
    code = State()

class CompleteGiveaway(StatesGroup):
    giveaway_id = State()

class SelectWinner(StatesGroup):
    giveaway_id = State()

# ===== ИНИЦИАЛИЗАЦИЯ =====
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

async def check_subscription(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM channels") as cursor:
            channels = await cursor.fetchall()
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

def user_main_keyboard(is_admin_user=False):
    kb = [
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎰 Казино")],
        [KeyboardButton(text="🎟 Промокод"), KeyboardButton(text="🎲 Розыгрыши")]
    ]
    if is_admin_user:
        kb.append([KeyboardButton(text="⚙️ Админ панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_main_keyboard():
    kb = [
        [KeyboardButton(text="➕ Создать розыгрыш")],
        [KeyboardButton(text="📋 Активные розыгрыши")],
        [KeyboardButton(text="✅ Завершить розыгрыш")],
        [KeyboardButton(text="🏆 Выбрать победителя")],
        [KeyboardButton(text="📢 Рассылка")],
        [KeyboardButton(text="💰 Начислить монеты")],
        [KeyboardButton(text="➕ Добавить канал")],
        [KeyboardButton(text="➖ Удалить канал")],
        [KeyboardButton(text="📦 Управление магазином")],
        [KeyboardButton(text="🎫 Управление промокодами")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="◀️ Назад в главное меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def back_to_admin_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад в админку", callback_data="admin_back")]
    ])

def shop_admin_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin_shop_add")],
        [InlineKeyboardButton(text="➖ Удалить товар", callback_data="admin_shop_remove")],
        [InlineKeyboardButton(text="📋 Список товаров", callback_data="admin_shop_list")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
    ])

def promo_admin_inline():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin_promo_create")],
        [InlineKeyboardButton(text="📋 Список промокодов", callback_data="admin_promo_list")],
        [InlineKeyboardButton(text="« Назад", callback_data="admin_back")]
    ])

def participate_confirm_keyboard(giveaway_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить участие", callback_data=f"confirm_part_{giveaway_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="giveaways")]
    ])

# ===== ИГРОВЫЕ ФРАЗЫ =====
BONUS_PHRASES = [
    "🎉 Удача на твоей стороне! +{bonus} монет!",
    "💰 Клад найден! +{bonus} монет!",
    "🌟 Ты сорвал джекпот! +{bonus} монет!",
    "🍀 Бонус активирован! +{bonus} монет!",
    "🎁 Держи подарок! +{bonus} монет!"
]

CASINO_WIN_PHRASES = [
    "🎰 Джекпот! Ты выиграл {win} монет (чистыми {profit})!",
    "🍒 Комбинация удачи! +{profit} монет!",
    "💫 Фортуна улыбнулась! Твой выигрыш: {win} монет!",
    "🎲 Кости показали {profit} монет прибыли!",
    "✨ Ты обыграл казино! +{profit} монет!"
]

CASINO_LOSE_PHRASES = [
    "😢 В этот раз не повезло... Потеряно {loss} монет.",
    "💔 Казино забирает {loss} монет.",
    "📉 Неудача! Минус {loss} монет.",
    "🍂 Повезёт в следующий раз. -{loss} монет.",
    "⚡️ Проигрыш: {loss} монет."
]

PURCHASE_PHRASES = [
    "✅ Покупка совершена! Админ уже в курсе.",
    "🛒 Товар твой! Скоро админ свяжется.",
    "🎁 Приятного использования! Ожидай сообщения от админа.",
    "💎 Отличный выбор! Админ уведомлён."
]

# ===== СТАРТ =====
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, joined_date, balance) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 0)
        )
        await db.commit()
    if not await check_subscription(user_id):
        await message.answer("❗️ Для доступа к боту нужно подписаться на наши каналы.\nПосле подписки нажми кнопку ниже.",
                             reply_markup=subscription_keyboard())
        return
    admin_flag = is_admin(user_id)
    await message.answer(f"Привет, {first_name}!\nДобро пожаловать в игровой бот!",
                         reply_markup=user_main_keyboard(admin_flag))

# ===== ПРОВЕРКА ПОДПИСКИ =====
@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    if await check_subscription(callback.from_user.id):
        admin_flag = is_admin(callback.from_user.id)
        await callback.message.edit_text("✅ Подписка подтверждена! Добро пожаловать.")
        await callback.message.answer("Главное меню:", reply_markup=user_main_keyboard(admin_flag))
    else:
        await callback.answer("❌ Вы ещё не подписались на все каналы!", show_alert=True)

# ===== ПРОФИЛЬ =====
@dp.message(F.text == "👤 Профиль")
async def profile_text(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, joined_date FROM users WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
    if row:
        balance, joined = row
        text = f"👤 Твой профиль:\n💰 Баланс: {balance} монет\n📅 Зарегистрирован: {joined}"
    else:
        text = "Профиль не найден"
    await message.answer(text, reply_markup=user_main_keyboard(is_admin(user_id)))

# ===== БОНУС =====
@dp.message(F.text == "🎁 Бонус")
async def bonus_text(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT last_bonus FROM users WHERE user_id=?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        last_bonus_str = row[0] if row else None
    now = datetime.now()
    if last_bonus_str:
        last_bonus = datetime.strptime(last_bonus_str, "%Y-%m-%d %H:%M:%S")
        if now - last_bonus < timedelta(days=1):
            remaining = timedelta(days=1) - (now - last_bonus)
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds // 60) % 60
            await message.answer(f"⏳ Бонус можно будет получить через {hours} ч {minutes} мин")
            return
    bonus = random.randint(5, 15)
    phrase = random.choice(BONUS_PHRASES).format(bonus=bonus)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id=?",
                         (bonus, now.strftime("%Y-%m-%d %H:%M:%S"), user_id))
        await db.commit()
    await message.answer(phrase, reply_markup=user_main_keyboard(is_admin(user_id)))

# ===== МАГАЗИН =====
@dp.message(F.text == "🛒 Магазин")
async def shop_text(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, description, price FROM shop_items") as cursor:
            items = await cursor.fetchall()
    if not items:
        await message.answer("🛒 В магазине пока нет товаров.", reply_markup=user_main_keyboard(is_admin(user_id)))
        return
    text = "🛒 Магазин:\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for item in items:
        item_id, name, desc, price = item
        text += f"🔹 {name}\n{desc}\n💰 {price} монет\n\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"Купить {name}", callback_data=f"buy_{item_id}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="« Назад", callback_data="back_main")])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def buy_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    item_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, price FROM shop_items WHERE id=?", (item_id,)) as cursor:
            item = await cursor.fetchone()
        if not item:
            await callback.answer("Товар не найден", show_alert=True)
            return
        name, price = item
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cursor:
            balance = (await cursor.fetchone())[0]
        if balance < price:
            await callback.answer("Недостаточно монет!", show_alert=True)
            return
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (price, user_id))
        await db.execute("INSERT INTO purchases (user_id, item_id, purchase_date) VALUES (?, ?, ?)",
                         (user_id, item_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await db.commit()
    phrase = random.choice(PURCHASE_PHRASES)
    await callback.answer(f"✅ Ты купил {name}! {phrase}", show_alert=True)
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, f"🛒 Покупка: пользователь {user_id} купил {name} за {price} монет.")
        except:
            pass
    await callback.message.edit_text(f"✅ Покупка совершена!", reply_markup=user_main_keyboard(is_admin(user_id)))

# ===== КАЗИНО =====
@dp.message(F.text == "🎰 Казино")
async def casino_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    await message.answer("🎰 Введи сумму ставки (целое число):")
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
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cursor:
            balance = (await cursor.fetchone())[0]
        if amount > balance:
            await message.answer("Недостаточно монет.")
            await state.clear()
            return
        win = random.random() < 0.3
        if win:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            profit = amount
            win_amount = amount * 2
            phrase = random.choice(CASINO_WIN_PHRASES).format(win=win_amount, profit=profit)
        else:
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (amount, user_id))
            phrase = random.choice(CASINO_LOSE_PHRASES).format(loss=amount)
        await db.commit()
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cursor:
            new_balance = (await cursor.fetchone())[0]
    await message.answer(f"{phrase}\n💰 Текущий баланс: {new_balance}")
    await state.clear()

# ===== ПРОМОКОД =====
@dp.message(F.text == "🎟 Промокод")
async def promo_text(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    await message.answer("Введи промокод:")
    await state.set_state(PromoActivate.code)

@dp.message(PromoActivate.code)
async def promo_activate(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        await state.clear()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT reward, max_uses, used_count FROM promocodes WHERE code=?", (code,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            await message.answer("❌ Промокод не найден.")
            await state.clear()
            return
        reward, max_uses, used = row
        if used >= max_uses:
            await message.answer("❌ Промокод уже использован максимальное количество раз.")
            await state.clear()
            return
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (reward, user_id))
        await db.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code=?", (code,))
        await db.commit()
    await message.answer(f"✅ Промокод активирован! Ты получил {reward} монет.")
    await state.clear()

# ===== РОЗЫГРЫШИ =====
@dp.message(F.text == "🎲 Розыгрыши")
async def giveaways_text(message: Message):
    user_id = message.from_user.id
    if not await check_subscription(user_id):
        await message.answer("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, prize, end_date FROM giveaways WHERE status='active'") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await message.answer("Сейчас нет активных розыгрышей.", reply_markup=user_main_keyboard(is_admin(user_id)))
        return
    text = "🎁 Активные розыгрыши:\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for row in rows:
        gid, prize, end = row
        text += f"ID: {gid} | {prize} | до {end}\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"🔍 Подробнее о {prize}", callback_data=f"detail_{gid}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="« Назад", callback_data="back_main")])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data.startswith("detail_"))
async def giveaway_detail(callback: CallbackQuery):
    giveaway_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT prize, end_date, media_file_id, media_type FROM giveaways WHERE id=? AND status='active'",
                              (giveaway_id,)) as cursor:
            row = await cursor.fetchone()
    if not row:
        await callback.answer("Розыгрыш не найден или завершён.", show_alert=True)
        return
    prize, end_date, media_file_id, media_type = row
    caption = f"🎁 Розыгрыш: {prize}\n📅 Окончание: {end_date}\n\nЖелаешь участвовать?"
    if media_file_id and media_type:
        if media_type == 'photo':
            await callback.message.answer_photo(photo=media_file_id, caption=caption,
                                                reply_markup=participate_confirm_keyboard(giveaway_id))
        elif media_type == 'video':
            await callback.message.answer_video(video=media_file_id, caption=caption,
                                                reply_markup=participate_confirm_keyboard(giveaway_id))
        elif media_type == 'document':
            await callback.message.answer_document(document=media_file_id, caption=caption,
                                                   reply_markup=participate_confirm_keyboard(giveaway_id))
    else:
        await callback.message.answer(caption, reply_markup=participate_confirm_keyboard(giveaway_id))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_part_"))
async def confirm_participation(callback: CallbackQuery):
    giveaway_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    if not await check_subscription(user_id):
        await callback.message.edit_text("❗️ Сначала подпишитесь на каналы.", reply_markup=subscription_keyboard())
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT status FROM giveaways WHERE id=?", (giveaway_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or row[0] != 'active':
                await callback.answer("Розыгрыш не активен", show_alert=True)
                return
        async with db.execute("SELECT * FROM participants WHERE user_id=? AND giveaway_id=?", (user_id, giveaway_id)) as cursor:
            if await cursor.fetchone():
                await callback.answer("Ты уже участвуешь!", show_alert=True)
                return
        await db.execute("INSERT INTO participants (user_id, giveaway_id) VALUES (?, ?)", (user_id, giveaway_id))
        await db.commit()
    await callback.answer("✅ Ты участвуешь в розыгрыше!", show_alert=True)
    await giveaways_text(callback.message)

# ===== ВОЗВРАТ В ГЛАВНОЕ МЕНЮ =====
@dp.callback_query(lambda c: c.data == "back_main")
async def back_main_callback(callback: CallbackQuery):
    admin_flag = is_admin(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=user_main_keyboard(admin_flag))

# ===== АДМИН ПАНЕЛЬ =====
@dp.message(F.text == "⚙️ Админ панель")
async def admin_panel_entry(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав администратора.")
        return
    await message.answer("Панель администратора:", reply_markup=admin_main_keyboard())

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав администратора.")
        return
    await message.answer("Панель администратора:", reply_markup=admin_main_keyboard())

# ===== АДМИНСКИЕ ОБРАБОТЧИКИ =====
@dp.message(F.text == "➕ Создать розыгрыш")
async def admin_create_giveaway(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите название приза:", reply_markup=back_to_admin_inline())
    await state.set_state(CreateGiveaway.prize)

@dp.message(F.text == "📋 Активные розыгрыши")
async def admin_list_giveaways(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, prize, end_date FROM giveaways WHERE status='active'") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await message.answer("Нет активных розыгрышей.", reply_markup=admin_main_keyboard())
    else:
        text = "Активные розыгрыши:\n"
        for row in rows:
            text += f"ID: {row[0]} | {row[1]} | до {row[2]}\n"
        await message.answer(text, reply_markup=admin_main_keyboard())

@dp.message(F.text == "✅ Завершить розыгрыш")
async def admin_complete_giveaway(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите ID розыгрыша для завершения:", reply_markup=back_to_admin_inline())
    await state.set_state(CompleteGiveaway.giveaway_id)

@dp.message(CompleteGiveaway.giveaway_id)
async def complete_giveaway(message: Message, state: FSMContext):
    try:
        gid = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE giveaways SET status='completed' WHERE id=? AND status='active'", (gid,))
        await db.commit()
        if db.total_changes:
            await message.answer(f"✅ Розыгрыш ID {gid} завершён.")
        else:
            await message.answer("❌ Розыгрыш не найден или уже завершён.")
    await state.clear()

@dp.message(F.text == "🏆 Выбрать победителя")
async def admin_pick_winner(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите ID розыгрыша для выбора победителя:", reply_markup=back_to_admin_inline())
    await state.set_state(SelectWinner.giveaway_id)

@dp.message(SelectWinner.giveaway_id)
async def select_winner(message: Message, state: FSMContext):
    try:
        gid = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT prize FROM giveaways WHERE id=? AND status='active'", (gid,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            await message.answer("❌ Активный розыгрыш не найден.")
            await state.clear()
            return
        prize = row[0]
        async with db.execute("SELECT user_id FROM participants WHERE giveaway_id=?", (gid,)) as cursor:
            participants = await cursor.fetchall()
        if not participants:
            await message.answer("❌ В розыгрыше нет участников.")
            await state.clear()
            return
        winner_id = random.choice(participants)[0]
        await db.execute("UPDATE giveaways SET status='completed', winner_id=? WHERE id=?", (winner_id, gid))
        await db.commit()
    await message.answer(f"🏆 Победитель розыгрыша '{prize}': {winner_id}")
    try:
        await bot.send_message(winner_id, f"🎉 Поздравляем! Ты победил в розыгрыше '{prize}'! Свяжись с админом для получения приза.")
    except:
        pass
    await state.clear()

@dp.message(F.text == "📢 Рассылка")
async def admin_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Отправьте сообщение для рассылки (можно с фото, видео, документом).",
                         reply_markup=back_to_admin_inline())
    await state.set_state(Broadcast.message)

@dp.message(Broadcast.message)
async def broadcast_message(message: Message, state: FSMContext):
    content_type = message.content_type
    data = {}
    if content_type == 'text':
        data['text'] = message.text
    elif content_type == 'photo':
        data['photo'] = message.photo[-1].file_id
        data['caption'] = message.caption
    elif content_type == 'video':
        data['video'] = message.video.file_id
        data['caption'] = message.caption
    elif content_type == 'document':
        data['document'] = message.document.file_id
        data['caption'] = message.caption
    else:
        await message.answer("Неподдерживаемый тип сообщения. Отправь текст, фото, видео или документ.")
        return
    await state.update_data(content=data, content_type=content_type)
    await message.answer("Запустить рассылку? (да/нет)", reply_markup=back_to_admin_inline())
    await state.set_state(BroadcastConfirm.waiting)

@dp.message(BroadcastConfirm.waiting)
async def broadcast_confirm(message: Message, state: FSMContext):
    if message.text.lower() == 'да':
        data = await state.get_data()
        content = data['content']
        content_type = data['content_type']
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id FROM users") as cursor:
                users = await cursor.fetchall()
        success = 0
        for user in users:
            try:
                if content_type == 'text':
                    await bot.send_message(user[0], content['text'])
                elif content_type == 'photo':
                    await bot.send_photo(user[0], photo=content['photo'], caption=content.get('caption', ''))
                elif content_type == 'video':
                    await bot.send_video(user[0], video=content['video'], caption=content.get('caption', ''))
                elif content_type == 'document':
                    await bot.send_document(user[0], document=content['document'], caption=content.get('caption', ''))
                success += 1
                await asyncio.sleep(0.05)
            except:
                pass
        await message.answer(f"✅ Рассылка завершена. Отправлено {success} пользователям.")
    else:
        await message.answer("Рассылка отменена.")
    await state.clear()

@dp.message(F.text == "💰 Начислить монеты")
async def admin_add_balance(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите ID пользователя и сумму через пробел (пример: 123456789 100):",
                         reply_markup=back_to_admin_inline())
    await state.set_state(AddBalance.user_id)

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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, target_id))
        await db.commit()
        if db.total_changes:
            await message.answer(f"✅ Пользователю {target_id} начислено {amount} монет.")
        else:
            await message.answer("❌ Пользователь не найден.")
    await state.clear()

@dp.message(F.text == "➕ Добавить канал")
async def admin_add_channel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите chat_id канала (например @channel или -100123456789):",
                         reply_markup=back_to_admin_inline())
    await state.set_state(AddChannel.chat_id)

@dp.message(AddChannel.chat_id)
async def add_channel_id(message: Message, state: FSMContext):
    await state.update_data(chat_id=message.text.strip())
    await message.answer("Введите название канала (для отображения):", reply_markup=back_to_admin_inline())
    await state.set_state(AddChannel.title)

@dp.message(AddChannel.title)
async def add_channel_title(message: Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data['chat_id']
    title = message.text
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO channels (chat_id, title) VALUES (?, ?)", (chat_id, title))
            await db.commit()
            await message.answer(f"✅ Канал {title} добавлен.")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Такой канал уже есть.")
    await state.clear()

@dp.message(F.text == "➖ Удалить канал")
async def admin_remove_channel(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Введите chat_id канала для удаления:", reply_markup=back_to_admin_inline())
    await state.set_state(RemoveChannel.chat_id)

@dp.message(RemoveChannel.chat_id)
async def remove_channel(message: Message, state: FSMContext):
    chat_id = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
        await db.commit()
        if db.total_changes:
            await message.answer("✅ Канал удалён.")
        else:
            await message.answer("❌ Канал не найден.")
    await state.clear()

@dp.message(F.text == "📦 Управление магазином")
async def admin_shop_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Управление магазином:", reply_markup=shop_admin_inline())

@dp.message(F.text == "🎫 Управление промокодами")
async def admin_promo_menu(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Управление промокодами:", reply_markup=promo_admin_inline())

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        users = await db.execute_fetchone("SELECT COUNT(*) FROM users")
        total_balance = await db.execute_fetchone("SELECT SUM(balance) FROM users")
        active_giveaways = await db.execute_fetchone("SELECT COUNT(*) FROM giveaways WHERE status='active'")
        shop_items = await db.execute_fetchone("SELECT COUNT(*) FROM shop_items")
    text = (f"📊 Статистика:\n👥 Пользователей: {users[0]}\n"
            f"💰 Всего монет: {total_balance[0] or 0}\n"
            f"🎁 Активных розыгрышей: {active_giveaways[0]}\n"
            f"🛒 Товаров в магазине: {shop_items[0]}")
    await message.answer(text, reply_markup=admin_main_keyboard())

@dp.message(F.text == "◀️ Назад в главное меню")
async def admin_back_to_main(message: Message):
    admin_flag = is_admin(message.from_user.id)
    await message.answer("Главное меню:", reply_markup=user_main_keyboard(admin_flag))

# ===== INLINE-АДМИНКА =====
@dp.callback_query(lambda c: c.data == "admin_back")
async def admin_back_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.message.answer("Панель администратора:", reply_markup=admin_main_keyboard())

@dp.callback_query(lambda c: c.data == "admin_shop_add")
async def shop_add(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите название товара:", reply_markup=back_to_admin_inline())
    await state.set_state(AddShopItem.name)

@dp.message(AddShopItem.name)
async def shop_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите описание товара:", reply_markup=back_to_admin_inline())
    await state.set_state(AddShopItem.description)

@dp.message(AddShopItem.description)
async def shop_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("Введите цену (целое число монет):", reply_markup=back_to_admin_inline())
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
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO shop_items (name, description, price) VALUES (?, ?, ?)", (name, desc, price))
        await db.commit()
    await message.answer(f"✅ Товар '{name}' добавлен с ценой {price}.")
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_shop_remove")
async def shop_remove(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите ID товара для удаления:", reply_markup=back_to_admin_inline())
    await state.set_state(RemoveShopItem.item_id)

@dp.message(RemoveShopItem.item_id)
async def shop_remove_id(message: Message, state: FSMContext):
    try:
        item_id = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM shop_items WHERE id=?", (item_id,))
        await db.commit()
        if db.total_changes:
            await message.answer("✅ Товар удалён.")
        else:
            await message.answer("❌ Товар не найден.")
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_shop_list")
async def shop_list_admin(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, description, price FROM shop_items") as cursor:
            items = await cursor.fetchall()
    if not items:
        await callback.message.edit_text("Товаров нет.", reply_markup=shop_admin_inline())
        return
    text = "📦 Товары в магазине:\n"
    for item in items:
        text += f"ID: {item[0]} | {item[1]} | {item[2]} | {item[3]} монет\n"
    await callback.message.edit_text(text, reply_markup=shop_admin_inline())

@dp.callback_query(lambda c: c.data == "admin_promo_create")
async def promo_create(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введите код промокода (латиница, цифры):", reply_markup=back_to_admin_inline())
    await state.set_state(CreatePromocode.code)

@dp.message(CreatePromocode.code)
async def promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.update_data(code=code)
    await message.answer("Введите количество монет:", reply_markup=back_to_admin_inline())
    await state.set_state(CreatePromocode.reward)

@dp.message(CreatePromocode.reward)
async def promo_reward(message: Message, state: FSMContext):
    try:
        reward = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    await state.update_data(reward=reward)
    await message.answer("Введите максимальное количество использований:", reply_markup=back_to_admin_inline())
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
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO promocodes (code, reward, max_uses) VALUES (?, ?, ?)", (code, reward, max_uses))
            await db.commit()
            await message.answer(f"✅ Промокод {code} создан: {reward} монет, {max_uses} использований.")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Промокод с таким кодом уже существует.")
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_promo_list")
async def promo_list_admin(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code, reward, max_uses, used_count FROM promocodes") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await callback.message.edit_text("Промокодов нет.", reply_markup=promo_admin_inline())
        return
    text = "🎫 Промокоды:\n"
    for row in rows:
        text += f"{row[0]}: {row[1]} монет, использовано {row[3]}/{row[2]}\n"
    await callback.message.edit_text(text, reply_markup=promo_admin_inline())

# ===== СОЗДАНИЕ РОЗЫГРЫША (ПРОДОЛЖЕНИЕ) =====
@dp.message(CreateGiveaway.prize)
async def giveaway_prize(message: Message, state: FSMContext):
    await state.update_data(prize=message.text)
    await message.answer("Введите дату окончания в формате ДД.ММ.ГГГГ (например, 31.12.2025):",
                         reply_markup=back_to_admin_inline())
    await state.set_state(CreateGiveaway.end_date)

@dp.message(CreateGiveaway.end_date)
async def giveaway_end_date(message: Message, state: FSMContext):
    await state.update_data(end_date=message.text)
    await message.answer("Теперь отправьте медиа для розыгрыша (фото, видео, документ) или отправьте 'пропустить', если медиа не нужно.",
                         reply_markup=back_to_admin_inline())
    await state.set_state(CreateGiveaway.media)

@dp.message(CreateGiveaway.media)
async def giveaway_media(message: Message, state: FSMContext):
    data = await state.get_data()
    prize = data['prize']
    end_date = data['end_date']
    media_file_id = None
    media_type = None
    if message.text and message.text.lower() == 'пропустить':
        pass
    elif message.photo:
        media_file_id = message.photo[-1].file_id
        media_type = 'photo'
    elif message.video:
        media_file_id = message.video.file_id
        media_type = 'video'
    elif message.document:
        media_file_id = message.document.file_id
        media_type = 'document'
    else:
        await message.answer("Пожалуйста, отправьте фото, видео, документ или напишите 'пропустить'.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO giveaways (prize, end_date, media_file_id, media_type) VALUES (?, ?, ?, ?)",
            (prize, end_date, media_file_id, media_type)
        )
        await db.commit()
    await message.answer(f"✅ Розыгрыш '{prize}' создан до {end_date}.")
    await state.clear()

# ===== ЗАПУСК =====
async def main():
    await init_db()
    print("🤖 Бот запущен и готов к работе!")
    print(f"👑 Админы: {ADMINS}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
