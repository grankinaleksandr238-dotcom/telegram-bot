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
from aiohttp import web

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "8336035363:AAGRP57xOcUNjgmbSNs6TnQ1uNtCbe2ryhU")
SUPER_ADMINS = [8127013147]  # Полные права
DB_PATH = 'database.db'

# ===== ИНИЦИАЛИЗАЦИЯ =====
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===== БАЗА ДАННЫХ =====
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Пользователи
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_date TEXT,
                balance INTEGER DEFAULT 0,
                last_bonus TEXT,
                theft_attempts INTEGER DEFAULT 0,
                theft_success INTEGER DEFAULT 0,
                theft_failed INTEGER DEFAULT 0,
                theft_protected INTEGER DEFAULT 0,
                protection_item TEXT DEFAULT 'none',
                tool_item TEXT DEFAULT 'none'
            )
        ''')
        # Каналы
        await db.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT UNIQUE,
                title TEXT,
                invite_link TEXT
            )
        ''')
        # Товары магазина
        await db.execute('''
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price INTEGER,
                category TEXT DEFAULT 'gift',
                effect TEXT
            )
        ''')
        # Покупки
        await db.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                item_id INTEGER,
                purchase_date TEXT,
                status TEXT DEFAULT 'pending',
                admin_comment TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(item_id) REFERENCES shop_items(id)
            )
        ''')
        # Промокоды
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promocodes (
                code TEXT PRIMARY KEY,
                reward INTEGER,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0
            )
        ''')
        # Розыгрыши
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
        # Участники розыгрышей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                user_id INTEGER,
                giveaway_id INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(giveaway_id) REFERENCES giveaways(id)
            )
        ''')
        # Младшие админы
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_date TEXT
            )
        ''')
        # Добавляем начальные товары, если их нет
        cur = await db.execute("SELECT COUNT(*) FROM shop_items")
        count = await cur.fetchone()
        if count[0] == 0:
            # Подарки
            await db.execute("INSERT INTO shop_items (name, description, price, category) VALUES (?, ?, ?, ?)",
                             ("🎁 Стикерпак MALBORO", "Эксклюзивные стикеры", 50, "gift"))
            await db.execute("INSERT INTO shop_items (name, description, price, category) VALUES (?, ?, ?, ?)",
                             ("🍫 Шоколадка", "Виртуальная, но очень вкусная", 30, "gift"))
            # Криминал: инструменты
            await db.execute("INSERT INTO shop_items (name, description, price, category, effect) VALUES (?, ?, ?, ?, ?)",
                             ("🔧 Фомка", "+10% к шансу кражи", 100, "crime", "tool+10"))
            await db.execute("INSERT INTO shop_items (name, description, price, category, effect) VALUES (?, ?, ?, ?, ?)",
                             ("🔨 Отмычки", "+20% к шансу кражи", 180, "crime", "tool+20"))
            # Криминал: защита
            await db.execute("INSERT INTO shop_items (name, description, price, category, effect) VALUES (?, ?, ?, ?, ?)",
                             ("🚨 Сигнализация", "-15% к шансу кражи грабителя", 150, "crime", "protect-15"))
            await db.execute("INSERT INTO shop_items (name, description, price, category, effect) VALUES (?, ?, ?, ?, ?)",
                             ("🛡️ Бронестекло", "-30% к шансу кражи грабителя", 250, "crime", "protect-30"))
        await db.commit()

# ===== СОСТОЯНИЯ FSM =====
class CreateGiveaway(StatesGroup):
    prize = State()
    end_date = State()
    media = State()

class AddChannel(StatesGroup):
    chat_id = State()
    title = State()
    invite_link = State()

class RemoveChannel(StatesGroup):
    chat_id = State()

class AddShopItem(StatesGroup):
    name = State()
    description = State()
    price = State()
    category = State()
    effect = State()

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

class Theft(StatesGroup):
    target = State()

class FindUser(StatesGroup):
    query = State()

class AddJuniorAdmin(StatesGroup):
    user_id = State()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====
async def is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMINS

async def is_junior_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM admins WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
    return row is not None

async def is_admin(user_id: int) -> bool:
    return await is_super_admin(user_id) or await is_junior_admin(user_id)

async def check_subscription(user_id: int) -> tuple[bool, list]:
    """Возвращает (подписан_ли, список_неподписанных_каналов с ссылками)"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id, title, invite_link FROM channels") as cursor:
            channels = await cursor.fetchall()
    if not channels:
        return True, []
    not_subscribed = []
    for ch in channels:
        chat_id, title, invite_link = ch
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                not_subscribed.append((title, invite_link))
        except Exception:
            not_subscribed.append((title, invite_link))
    return len(not_subscribed) == 0, not_subscribed

# ===== КЛАВИАТУРЫ =====
def subscription_inline(not_subscribed):
    kb = []
    for title, link in not_subscribed:
        if link:
            kb.append([InlineKeyboardButton(text=f"📢 {title}", url=link)])
        else:
            kb.append([InlineKeyboardButton(text=f"📢 {title}", callback_data="no_link")])
    kb.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def user_main_keyboard(is_admin_user=False):
    buttons = [
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🎁 Бонус")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="🎰 Казино")],
        [KeyboardButton(text="🎟 Промокод"), KeyboardButton(text="🎲 Розыгрыши")],
        [KeyboardButton(text="💰 Мои покупки"), KeyboardButton(text="🔫 Ограбить")]
    ]
    if is_admin_user:
        buttons.append([KeyboardButton(text="⚙️ Админ панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def admin_main_keyboard(is_super):
    buttons = [
        [KeyboardButton(text="🎁 Управление розыгрышами")],
        [KeyboardButton(text="📢 Рассылка"), KeyboardButton(text="💰 Начислить монеты")],
        [KeyboardButton(text="📺 Управление каналами")],
        [KeyboardButton(text="🛒 Управление магазином")],
        [KeyboardButton(text="🎫 Управление промокодами")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="👥 Найти пользователя")],
        [KeyboardButton(text="🛍️ Список покупок")],
    ]
    if is_super:
        buttons.append([KeyboardButton(text="➕ Добавить админа")])
        buttons.append([KeyboardButton(text="🔄 Сброс статистики")])
    buttons.append([KeyboardButton(text="◀️ Назад в главное меню")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def giveaway_admin_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Создать розыгрыш")],
        [KeyboardButton(text="📋 Активные розыгрыши")],
        [KeyboardButton(text="✅ Завершить розыгрыш")],
        [KeyboardButton(text="🏆 Выбрать победителя")],
        [KeyboardButton(text="◀️ Назад в админку")]
    ], resize_keyboard=True)

def channel_admin_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Добавить канал")],
        [KeyboardButton(text="➖ Удалить канал")],
        [KeyboardButton(text="📋 Список каналов")],
        [KeyboardButton(text="◀️ Назад в админку")]
    ], resize_keyboard=True)

def shop_admin_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Добавить товар")],
        [KeyboardButton(text="➖ Удалить товар")],
        [KeyboardButton(text="📋 Список товаров")],
        [KeyboardButton(text="◀️ Назад в админку")]
    ], resize_keyboard=True)

def promo_admin_keyboard():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="➕ Создать промокод")],
        [KeyboardButton(text="📋 Список промокодов")],
        [KeyboardButton(text="◀️ Назад в админку")]
    ], resize_keyboard=True)

def back_keyboard():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="◀️ Назад")]], resize_keyboard=True)

def shop_category_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Подарки", callback_data="shop_gift")],
        [InlineKeyboardButton(text="🔫 Криминал", callback_data="shop_crime")]
    ])

def purchase_action_keyboard(purchase_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"purchase_done_{purchase_id}"),
         InlineKeyboardButton(text="❌ Отказ", callback_data=f"purchase_reject_{purchase_id}")]
    ])

# ===== ИГРОВЫЕ ФРАЗЫ (с молодёжным сленгом) =====
BONUS_PHRASES = [
    "🎉 Красава, лови +{bonus} монет!",
    "💰 Зашкварно богатенький стал! +{bonus}",
    "🌟 Хайпанули? +{bonus} монет в карман!",
    "🍀 Удача крашеная, держи +{bonus}",
    "🎁 Ты в тренде, +{bonus} монет!"
]

CASINO_WIN_PHRASES = [
    "🎰 Краш! Ты выиграл {win} монет (чистыми {profit})!",
    "🍒 Хайповая комбинация! +{profit} монет!",
    "💫 Фортуна крашеная, твой выигрыш: {win} монет!",
    "🎲 Изи-катка, {profit} монет твои!",
    "✨ Ты красавчик, обыграл казино! +{profit} монет!"
]

CASINO_LOSE_PHRASES = [
    "😢 Обидно, потерял {loss} монет.",
    "💔 Зашкварно, минус {loss}.",
    "📉 Не фортануло, -{loss} монет.",
    "🍂 В следующий раз краш будет твоим, а пока -{loss}.",
    "⚡️ Лузернулся на {loss} монет."
]

PURCHASE_PHRASES = [
    "✅ Купил! Админ скоро в личку прилетит.",
    "🛒 Товар твой! Жди админа, бро.",
    "🎁 Крутая покупка! Админ уже в курсе.",
    "💎 Ты краш! Админ свяжется."
]

THEFT_SUCCESS_PHRASES = [
    "🔫 Красава! Ты украл {amount} монет у {target}!",
    "💰 Хайпанул, {amount} монет у {target} теперь твои!",
    "🦹‍♂️ Удачная кража! +{amount} от {target}",
    "😈 Ты краш, {target} даже не понял! +{amount}"
]

THEFT_FAIL_PHRASES = [
    "😢 Облом, тебя спалили! Ничего не украл.",
    "🚨 Треск, {target} оказался с защитой!",
    "👮‍♂️ Мусора? Пришлось сваливать, 0 монет.",
    "💔 Не фортануло, {target} слишком крутой."
]

THEFT_PROTECT_PHRASES = [
    "🛡️ Твоя защита сработала! {attacker} ничего не украл.",
    "🚨 Сигналка заорала, грабитель сбежал!",
    "😎 Ты краш, защита отбила атаку {attacker}.",
    "💪 Бронестекло выдержало! {attacker} ушёл ни с чем."
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
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer(
            "❗️ Для доступа к боту нужно подписаться на наши каналы.\nПосле подписки нажми кнопку ниже.",
            reply_markup=subscription_inline(not_subscribed)
        )
        return
    admin_flag = await is_admin(user_id)
    await message.answer(
        f"Привет, {first_name}!\n"
        f"Добро пожаловать в **Malboro GAME**! 🚬\n"
        f"Тут ты найдёшь: казино, розыгрыши, магазин с подарками и криминал.\n"
        f"Грабить друзей — это зашкварно, но весело! 🔫\n\n"
        f"Канал: @MALBORO (подпишись, чтобы быть в теме)",
        reply_markup=user_main_keyboard(admin_flag)
    )

# ===== ПРОВЕРКА ПОДПИСКИ =====
@dp.callback_query(lambda c: c.data == "check_sub")
async def check_sub_callback(callback: CallbackQuery):
    ok, not_subscribed = await check_subscription(callback.from_user.id)
    if ok:
        admin_flag = await is_admin(callback.from_user.id)
        await callback.message.edit_text("✅ Подписка подтверждена! Добро пожаловать.")
        await callback.message.answer("Главное меню:", reply_markup=user_main_keyboard(admin_flag))
    else:
        await callback.answer("❌ Ты ещё не подписался на все каналы!", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=subscription_inline(not_subscribed))

@dp.callback_query(lambda c: c.data == "no_link")
async def no_link(callback: CallbackQuery):
    await callback.answer("Ссылка временно недоступна, найди канал вручную", show_alert=True)

# ===== ПРОФИЛЬ =====
@dp.message(F.text == "👤 Профиль")
async def profile_handler(message: Message):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT balance, joined_date, theft_attempts, theft_success, theft_failed, theft_protected, protection_item FROM users WHERE user_id=?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
    if row:
        balance, joined, attempts, success, failed, protected, protection = row
        prot_text = "Нет" if protection == 'none' else protection.replace('protect-', '🛡️ Уровень ')
        text = (
            f"👤 Твой профиль:\n"
            f"💰 Баланс: {balance} монет\n"
            f"📅 Зарегистрирован: {joined}\n"
            f"🔫 Ограблений: {attempts} (успешно: {success}, провал: {failed})\n"
            f"🛡️ Защита: {prot_text}\n"
            f"⚔️ Отбито атак: {protected}"
        )
    else:
        text = "Профиль не найден"
    await message.answer(text, reply_markup=user_main_keyboard(await is_admin(user_id)))

# ===== БОНУС =====
@dp.message(F.text == "🎁 Бонус")
async def bonus_handler(message: Message):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
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
        await db.execute(
            "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE user_id=?",
            (bonus, now.strftime("%Y-%m-%d %H:%M:%S"), user_id)
        )
        await db.commit()
    await message.answer(phrase, reply_markup=user_main_keyboard(await is_admin(user_id)))

# ===== МАГАЗИН =====
@dp.message(F.text == "🛒 Магазин")
async def shop_handler(message: Message):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    await message.answer("Выбери раздел магазина:", reply_markup=shop_category_keyboard())

@dp.callback_query(lambda c: c.data.startswith("shop_"))
async def shop_category(callback: CallbackQuery):
    category = callback.data.split("_")[1]  # gift or crime
    async with aiosqlite.connect(DB_PATH) as db:
        if category == 'gift':
            async with db.execute("SELECT id, name, description, price FROM shop_items WHERE category='gift'") as cursor:
                items = await cursor.fetchall()
        else:
            async with db.execute("SELECT id, name, description, price FROM shop_items WHERE category='crime'") as cursor:
                items = await cursor.fetchall()
    if not items:
        await callback.message.edit_text("В этом разделе пока нет товаров.")
        return
    text = f"{'🎁 Подарки' if category=='gift' else '🔫 Криминал'}:\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for item in items:
        item_id, name, desc, price = item
        text += f"🔹 {name}\n{desc}\n💰 {price} монет\n\n"
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"Купить {name}", callback_data=f"buy_{item_id}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="« Назад", callback_data="back_to_shop_cat")])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "back_to_shop_cat")
async def back_to_shop_cat(callback: CallbackQuery):
    await callback.message.edit_text("Выбери раздел магазина:", reply_markup=shop_category_keyboard())

@dp.callback_query(lambda c: c.data.startswith("buy_"))
async def buy_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await callback.message.edit_text("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    item_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT name, price, category, effect FROM shop_items WHERE id=?", (item_id,)) as cursor:
            item = await cursor.fetchone()
        if not item:
            await callback.answer("Товар не найден", show_alert=True)
            return
        name, price, category, effect = item
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cursor:
            balance = (await cursor.fetchone())[0]
        if balance < price:
            await callback.answer("Не хватает монет!", show_alert=True)
            return
        # Обновляем баланс и, если нужно, специальные поля
        if category == 'crime' and effect:
            if effect.startswith('protect-'):
                # Защита: заменяем текущую защиту (можно накопление, но для простоты заменим)
                await db.execute("UPDATE users SET protection_item = ? WHERE user_id=?", (effect, user_id))
            elif effect.startswith('tool+'):
                # Инструмент: заменяем (или можно добавить позже накопление)
                await db.execute("UPDATE users SET tool_item = ? WHERE user_id=?", (effect, user_id))
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (price, user_id))
        await db.execute(
            "INSERT INTO purchases (user_id, item_id, purchase_date) VALUES (?, ?, ?)",
            (user_id, item_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        await db.commit()
    phrase = random.choice(PURCHASE_PHRASES)
    await callback.answer(f"✅ Ты купил {name}! {phrase}", show_alert=True)
    # Уведомление админам
    admins = SUPER_ADMINS.copy()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM admins") as cur:
            rows = await cur.fetchall()
            for row in rows:
                admins.append(row[0])
    for admin_id in admins:
        try:
            await bot.send_message(
                admin_id,
                f"🛒 Покупка: пользователь {callback.from_user.full_name} (@{callback.from_user.username})\n"
                f"[Ссылка](tg://user?id={user_id}) купил {name} за {price} монет.",
                parse_mode="Markdown"
            )
        except:
            pass
    await callback.message.edit_text(f"✅ Покупка совершена!", reply_markup=user_main_keyboard(await is_admin(user_id)))

# ===== МОИ ПОКУПКИ =====
@dp.message(F.text == "💰 Мои покупки")
async def my_purchases(message: Message):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT p.id, s.name, p.purchase_date, p.status, p.admin_comment FROM purchases p JOIN shop_items s ON p.item_id = s.id WHERE p.user_id=? ORDER BY p.purchase_date DESC",
            (user_id,)
        ) as cursor:
            purchases = await cursor.fetchall()
    if not purchases:
        await message.answer("У тебя пока нет покупок.", reply_markup=user_main_keyboard(await is_admin(user_id)))
        return
    text = "📦 Твои покупки:\n"
    for pid, name, date, status, comment in purchases:
        status_emoji = "⏳" if status == 'pending' else "✅" if status == 'completed' else "❌"
        text += f"{status_emoji} {name} от {date}\n"
        if comment:
            text += f"   Комментарий: {comment}\n"
    await message.answer(text, reply_markup=user_main_keyboard(await is_admin(user_id)))

# ===== КАЗИНО =====
@dp.message(F.text == "🎰 Казино")
async def casino_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    await message.answer("🎰 Введи сумму ставки (целое число):", reply_markup=back_keyboard())
    await state.set_state(CasinoBet.amount)

@dp.message(CasinoBet.amount)
async def casino_bet_amount(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await message.answer("Главное меню:", reply_markup=user_main_keyboard(await is_admin(message.from_user.id)))
        return
    try:
        amount = int(message.text)
    except:
        await message.answer("Введите число.")
        return
    if amount <= 0:
        await message.answer("Ставка должна быть положительной.")
        return
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
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
    await message.answer(
        f"{phrase}\n💰 Текущий баланс: {new_balance}",
        reply_markup=user_main_keyboard(await is_admin(user_id))
    )
    await state.clear()

# ===== ПРОМОКОД =====
@dp.message(F.text == "🎟 Промокод")
async def promo_handler(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    await message.answer("Введи промокод:", reply_markup=back_keyboard())
    await state.set_state(PromoActivate.code)

@dp.message(PromoActivate.code)
async def promo_activate(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await message.answer("Главное меню:", reply_markup=user_main_keyboard(await is_admin(message.from_user.id)))
        return
    code = message.text.strip().upper()
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
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
    await message.answer(
        f"✅ Промокод активирован! Ты получил {reward} монет.",
        reply_markup=user_main_keyboard(await is_admin(user_id))
    )
    await state.clear()

# ===== РОЗЫГРЫШИ =====
@dp.message(F.text == "🎲 Розыгрыши")
async def giveaways_handler(message: Message):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, prize, end_date FROM giveaways WHERE status='active'") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await message.answer(
            "Сейчас нет активных розыгрышей.",
            reply_markup=user_main_keyboard(await is_admin(user_id))
        )
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
        async with db.execute(
            "SELECT prize, end_date, media_file_id, media_type FROM giveaways WHERE id=? AND status='active'",
            (giveaway_id,)
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        await callback.answer("Розыгрыш не найден или завершён.", show_alert=True)
        return
    prize, end_date, media_file_id, media_type = row
    caption = f"🎁 Розыгрыш: {prize}\n📅 Окончание: {end_date}\n\nЖелаешь участвовать?"
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, участвую", callback_data=f"confirm_part_{giveaway_id}")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_detail")]
    ])
    if media_file_id and media_type:
        if media_type == 'photo':
            await callback.message.answer_photo(photo=media_file_id, caption=caption, reply_markup=confirm_kb)
        elif media_type == 'video':
            await callback.message.answer_video(video=media_file_id, caption=caption, reply_markup=confirm_kb)
        elif media_type == 'document':
            await callback.message.answer_document(document=media_file_id, caption=caption, reply_markup=confirm_kb)
    else:
        await callback.message.answer(caption, reply_markup=confirm_kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("confirm_part_"))
async def confirm_participation(callback: CallbackQuery):
    giveaway_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await callback.message.edit_text("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
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
    await giveaways_handler(callback.message)

@dp.callback_query(lambda c: c.data == "cancel_detail")
async def cancel_detail(callback: CallbackQuery):
    await callback.message.delete()
    await giveaways_handler(callback.message)

@dp.callback_query(lambda c: c.data == "back_main")
async def back_main_callback(callback: CallbackQuery):
    admin_flag = await is_admin(callback.from_user.id)
    await callback.message.delete()
    await callback.message.answer("Главное меню:", reply_markup=user_main_keyboard(admin_flag))

# ===== ОГРАБЛЕНИЕ =====
@dp.message(F.text == "🔫 Ограбить")
async def theft_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    ok, not_subscribed = await check_subscription(user_id)
    if not ok:
        await message.answer("❗️ Сначала подпишись на каналы.", reply_markup=subscription_inline(not_subscribed))
        return
    await message.answer("Введи @username или ID того, кого хочешь ограбить:", reply_markup=back_keyboard())
    await state.set_state(Theft.target)

@dp.message(Theft.target)
async def theft_target(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await message.answer("Главное меню:", reply_markup=user_main_keyboard(await is_admin(message.from_user.id)))
        return
    target_input = message.text.strip()
    user_id = message.from_user.id
    # Определяем, ID или юзернейм
    if target_input.startswith('@'):
        target_username = target_input[1:]
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id FROM users WHERE username=?", (target_username,)) as cursor:
                row = await cursor.fetchone()
        if not row:
            await message.answer("❌ Пользователь с таким юзернеймом не найден в боте.")
            return
        target_id = row[0]
    else:
        try:
            target_id = int(target_input)
        except:
            await message.answer("❌ Некорректный ID или юзернейм.")
            return
    if target_id == user_id:
        await message.answer("Сам себя не ограбишь, бро! 😆")
        return
    # Получаем данные грабителя и жертвы
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance, tool_item FROM users WHERE user_id=?", (user_id,)) as cursor:
            robber = await cursor.fetchone()
        async with db.execute("SELECT balance, protection_item FROM users WHERE user_id=?", (target_id,)) as cursor:
            victim = await cursor.fetchone()
        if not robber or not victim:
            await message.answer("❌ Один из пользователей не найден.")
            return
        robber_balance, robber_tool = robber
        victim_balance, victim_protection = victim
        if victim_balance <= 0:
            await message.answer("У этого пользователя нет монет. Нечего грабить.")
            return
        # Рассчитываем базовый шанс 50%
        chance = 50
        if robber_tool and robber_tool.startswith('tool+'):
            chance += int(robber_tool.split('+')[1])
        if victim_protection and victim_protection.startswith('protect-'):
            chance -= int(victim_protection.split('-')[1])
        chance = max(10, min(90, chance))  # ограничим 10-90%
        # Розыгрыш
        success = random.randint(1, 100) <= chance
        # Обновляем статистику
        await db.execute("UPDATE users SET theft_attempts = theft_attempts + 1 WHERE user_id=?", (user_id,))
        if success:
            # Кража 10-30% от баланса жертвы
            steal_percent = random.uniform(0.1, 0.3)
            steal_amount = int(victim_balance * steal_percent)
            if steal_amount < 1:
                steal_amount = 1
            await db.execute("UPDATE users SET balance = balance - ? WHERE user_id=?", (steal_amount, target_id))
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (steal_amount, user_id))
            await db.execute("UPDATE users SET theft_success = theft_success + 1 WHERE user_id=?", (user_id,))
            # Фраза успеха
            phrase = random.choice(THEFT_SUCCESS_PHRASES).format(amount=steal_amount, target=f"@{target_input}")
        else:
            steal_amount = 0
            await db.execute("UPDATE users SET theft_failed = theft_failed + 1 WHERE user_id=?", (user_id,))
            if victim_protection != 'none':
                await db.execute("UPDATE users SET theft_protected = theft_protected + 1 WHERE user_id=?", (target_id,))
                phrase = random.choice(THEFT_PROTECT_PHRASES).format(attacker=message.from_user.first_name)
                # Уведомим жертву о защите
                try:
                    await bot.send_message(target_id, phrase)
                except:
                    pass
            else:
                phrase = random.choice(THEFT_FAIL_PHRASES).format(target=target_input)
        await db.commit()
    await message.answer(phrase, reply_markup=user_main_keyboard(await is_admin(user_id)))
    await state.clear()

# ===== АДМИН ПАНЕЛЬ =====
@dp.message(F.text == "⚙️ Админ панель")
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("У тебя нет прав администратора.")
        return
    super_admin = await is_super_admin(message.from_user.id)
    await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("У тебя нет прав администратора.")
        return
    super_admin = await is_super_admin(message.from_user.id)
    await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))

# ===== УПРАВЛЕНИЕ РОЗЫГРЫШАМИ =====
@dp.message(F.text == "🎁 Управление розыгрышами")
async def admin_giveaway_menu(message: Message):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Управление розыгрышами:", reply_markup=giveaway_admin_keyboard())

@dp.message(F.text == "➕ Создать розыгрыш")
async def create_giveaway_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введите название приза:", reply_markup=back_keyboard())
    await state.set_state(CreateGiveaway.prize)

@dp.message(CreateGiveaway.prize)
async def create_giveaway_prize(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_giveaway_menu(message)
        return
    await state.update_data(prize=message.text)
    await message.answer("Введите дату окончания в формате ДД.ММ.ГГГГ (например, 31.12.2025):", reply_markup=back_keyboard())
    await state.set_state(CreateGiveaway.end_date)

@dp.message(CreateGiveaway.end_date)
async def create_giveaway_end_date(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_giveaway_menu(message)
        return
    await state.update_data(end_date=message.text)
    await message.answer(
        "Теперь отправьте медиа для розыгрыша (фото, видео, документ) или отправьте 'пропустить', если медиа не нужно.",
        reply_markup=back_keyboard()
    )
    await state.set_state(CreateGiveaway.media)

@dp.message(CreateGiveaway.media)
async def create_giveaway_media(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_giveaway_menu(message)
        return
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
    await admin_giveaway_menu(message)

@dp.message(F.text == "📋 Активные розыгрыши")
async def admin_list_giveaways(message: Message):
    if not await is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, prize, end_date FROM giveaways WHERE status='active'") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await message.answer("Нет активных розыгрышей.", reply_markup=giveaway_admin_keyboard())
    else:
        text = "Активные розыгрыши:\n"
        for row in rows:
            text += f"ID: {row[0]} | {row[1]} | до {row[2]}\n"
        await message.answer(text, reply_markup=giveaway_admin_keyboard())

@dp.message(F.text == "✅ Завершить розыгрыш")
async def complete_giveaway_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введите ID розыгрыша для завершения:", reply_markup=back_keyboard())
    await state.set_state(CompleteGiveaway.giveaway_id)

@dp.message(CompleteGiveaway.giveaway_id)
async def complete_giveaway(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_giveaway_menu(message)
        return
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
    await admin_giveaway_menu(message)

@dp.message(F.text == "🏆 Выбрать победителя")
async def select_winner_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введите ID розыгрыша для выбора победителя:", reply_markup=back_keyboard())
    await state.set_state(SelectWinner.giveaway_id)

@dp.message(SelectWinner.giveaway_id)
async def select_winner(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_giveaway_menu(message)
        return
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
            await admin_giveaway_menu(message)
            return
        prize = row[0]
        async with db.execute("SELECT user_id FROM participants WHERE giveaway_id=?", (gid,)) as cursor:
            participants = await cursor.fetchall()
        if not participants:
            await message.answer("❌ В розыгрыше нет участников.")
            await state.clear()
            await admin_giveaway_menu(message)
            return
        winner_id = random.choice(participants)[0]
        await db.execute("UPDATE giveaways SET status='completed', winner_id=? WHERE id=?", (winner_id, gid))
        await db.commit()
    await message.answer(f"🏆 Победитель розыгрыша '{prize}': {winner_id}")
    try:
        await bot.send_message(
            winner_id,
            f"🎉 Поздравляем! Ты победил в розыгрыше '{prize}'! Свяжись с админом для получения приза."
        )
    except:
        pass
    await state.clear()
    await admin_giveaway_menu(message)

# ===== РАССЫЛКА =====
@dp.message(F.text == "📢 Рассылка")
async def broadcast_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer(
        "Отправьте сообщение для рассылки (можно с фото, видео, документом).",
        reply_markup=back_keyboard()
    )
    await state.set_state(Broadcast.message)

@dp.message(Broadcast.message)
async def broadcast_message(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        super_admin = await is_super_admin(message.from_user.id)
        await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))
        return
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
    await message.answer("Запустить рассылку? (да/нет)", reply_markup=back_keyboard())
    await state.set_state(BroadcastConfirm.waiting)

@dp.message(BroadcastConfirm.waiting)
async def broadcast_confirm(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        super_admin = await is_super_admin(message.from_user.id)
        await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))
        return
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
    super_admin = await is_super_admin(message.from_user.id)
    await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))

# ===== НАЧИСЛЕНИЕ МОНЕТ =====
@dp.message(F.text == "💰 Начислить монеты")
async def add_balance_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer(
        "Введите ID пользователя и сумму через пробел (пример: 123456789 100):",
        reply_markup=back_keyboard()
    )
    await state.set_state(AddBalance.user_id)

@dp.message(AddBalance.user_id)
async def add_balance(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        super_admin = await is_super_admin(message.from_user.id)
        await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))
        return
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
    super_admin = await is_super_admin(message.from_user.id)
    await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))

# ===== УПРАВЛЕНИЕ КАНАЛАМИ =====
@dp.message(F.text == "📺 Управление каналами")
async def admin_channel_menu(message: Message):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Управление каналами:", reply_markup=channel_admin_keyboard())

@dp.message(F.text == "➕ Добавить канал")
async def add_channel_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer(
        "Введите chat_id канала (например @channel или -100123456789):",
        reply_markup=back_keyboard()
    )
    await state.set_state(AddChannel.chat_id)

@dp.message(AddChannel.chat_id)
async def add_channel_id(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_channel_menu(message)
        return
    await state.update_data(chat_id=message.text.strip())
    await message.answer("Введите название канала (для отображения):", reply_markup=back_keyboard())
    await state.set_state(AddChannel.title)

@dp.message(AddChannel.title)
async def add_channel_title(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_channel_menu(message)
        return
    await state.update_data(title=message.text)
    await message.answer("Введите ссылку-приглашение (например https://t.me/... или @channel):", reply_markup=back_keyboard())
    await state.set_state(AddChannel.invite_link)

@dp.message(AddChannel.invite_link)
async def add_channel_link(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_channel_menu(message)
        return
    data = await state.get_data()
    chat_id = data['chat_id']
    title = data['title']
    invite_link = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO channels (chat_id, title, invite_link) VALUES (?, ?, ?)",
                             (chat_id, title, invite_link))
            await db.commit()
            await message.answer(f"✅ Канал {title} добавлен.")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Такой канал уже есть.")
    await state.clear()
    await admin_channel_menu(message)

@dp.message(F.text == "➖ Удалить канал")
async def remove_channel_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введите chat_id канала для удаления:", reply_markup=back_keyboard())
    await state.set_state(RemoveChannel.chat_id)

@dp.message(RemoveChannel.chat_id)
async def remove_channel(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_channel_menu(message)
        return
    chat_id = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
        await db.commit()
        if db.total_changes:
            await message.answer("✅ Канал удалён.")
        else:
            await message.answer("❌ Канал не найден.")
    await state.clear()
    await admin_channel_menu(message)

@dp.message(F.text == "📋 Список каналов")
async def list_channels(message: Message):
    if not await is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id, title, invite_link FROM channels") as cursor:
            channels = await cursor.fetchall()
    if not channels:
        await message.answer("Нет добавленных каналов.", reply_markup=channel_admin_keyboard())
    else:
        text = "📺 Список каналов:\n"
        for ch in channels:
            text += f"• {ch[1]} ({ch[0]}) – ссылка: {ch[2] or 'нет'}\n"
        await message.answer(text, reply_markup=channel_admin_keyboard())

# ===== УПРАВЛЕНИЕ МАГАЗИНОМ =====
@dp.message(F.text == "🛒 Управление магазином")
async def admin_shop_menu(message: Message):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Управление магазином:", reply_markup=shop_admin_keyboard())

@dp.message(F.text == "➕ Добавить товар")
async def add_shop_item_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введите название товара:", reply_markup=back_keyboard())
    await state.set_state(AddShopItem.name)

@dp.message(AddShopItem.name)
async def add_shop_item_name(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_shop_menu(message)
        return
    await state.update_data(name=message.text)
    await message.answer("Введите описание товара:", reply_markup=back_keyboard())
    await state.set_state(AddShopItem.description)

@dp.message(AddShopItem.description)
async def add_shop_item_desc(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_shop_menu(message)
        return
    await state.update_data(description=message.text)
    await message.answer("Введите цену (целое число монет):", reply_markup=back_keyboard())
    await state.set_state(AddShopItem.price)

@dp.message(AddShopItem.price)
async def add_shop_item_price(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_shop_menu(message)
        return
    try:
        price = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    await state.update_data(price=price)
    await message.answer("Выберите категорию (gift - подарок, crime - криминал):", reply_markup=back_keyboard())
    await state.set_state(AddShopItem.category)

@dp.message(AddShopItem.category)
async def add_shop_item_category(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_shop_menu(message)
        return
    cat = message.text.strip().lower()
    if cat not in ['gift', 'crime']:
        await message.answer("Категория должна быть 'gift' или 'crime'.")
        return
    await state.update_data(category=cat)
    if cat == 'crime':
        await message.answer("Введите эффект (например tool+10, protect-15) или 'none':", reply_markup=back_keyboard())
        await state.set_state(AddShopItem.effect)
    else:
        # Для подарков эффект не нужен
        data = await state.get_data()
        name = data['name']
        desc = data['description']
        price = data['price']
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO shop_items (name, description, price, category) VALUES (?, ?, ?, ?)",
                             (name, desc, price, cat))
            await db.commit()
        await message.answer(f"✅ Товар '{name}' добавлен в категорию {cat}.")
        await state.clear()
        await admin_shop_menu(message)

@dp.message(AddShopItem.effect)
async def add_shop_item_effect(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_shop_menu(message)
        return
    effect = message.text.strip()
    data = await state.get_data()
    name = data['name']
    desc = data['description']
    price = data['price']
    category = data['category']
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO shop_items (name, description, price, category, effect) VALUES (?, ?, ?, ?, ?)",
                         (name, desc, price, category, effect))
        await db.commit()
    await message.answer(f"✅ Товар '{name}' добавлен в категорию {category} с эффектом {effect}.")
    await state.clear()
    await admin_shop_menu(message)

@dp.message(F.text == "➖ Удалить товар")
async def remove_shop_item_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введите ID товара для удаления:", reply_markup=back_keyboard())
    await state.set_state(RemoveShopItem.item_id)

@dp.message(RemoveShopItem.item_id)
async def remove_shop_item(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_shop_menu(message)
        return
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
    await admin_shop_menu(message)

@dp.message(F.text == "📋 Список товаров")
async def list_shop_items(message: Message):
    if not await is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, name, description, price, category, effect FROM shop_items") as cursor:
            items = await cursor.fetchall()
    if not items:
        await message.answer("Товаров нет.", reply_markup=shop_admin_keyboard())
        return
    text = "📦 Товары в магазине:\n"
    for item in items:
        text += f"ID: {item[0]} | {item[1]} | {item[2]} | {item[3]} монет | {item[4]}"
        if item[5]:
            text += f" | эффект: {item[5]}"
        text += "\n"
    await message.answer(text, reply_markup=shop_admin_keyboard())

# ===== УПРАВЛЕНИЕ ПРОМОКОДАМИ =====
@dp.message(F.text == "🎫 Управление промокодами")
async def admin_promo_menu(message: Message):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Управление промокодами:", reply_markup=promo_admin_keyboard())

@dp.message(F.text == "➕ Создать промокод")
async def create_promocode_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введите код промокода (латиница, цифры):", reply_markup=back_keyboard())
    await state.set_state(CreatePromocode.code)

@dp.message(CreatePromocode.code)
async def create_promocode_code(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_promo_menu(message)
        return
    code = message.text.strip().upper()
    await state.update_data(code=code)
    await message.answer("Введите количество монет:", reply_markup=back_keyboard())
    await state.set_state(CreatePromocode.reward)

@dp.message(CreatePromocode.reward)
async def create_promocode_reward(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_promo_menu(message)
        return
    try:
        reward = int(message.text)
    except:
        await message.answer("Введите целое число.")
        return
    await state.update_data(reward=reward)
    await message.answer("Введите максимальное количество использований:", reply_markup=back_keyboard())
    await state.set_state(CreatePromocode.max_uses)

@dp.message(CreatePromocode.max_uses)
async def create_promocode_max_uses(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        await admin_promo_menu(message)
        return
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
    await admin_promo_menu(message)

@dp.message(F.text == "📋 Список промокодов")
async def list_promocodes(message: Message):
    if not await is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code, reward, max_uses, used_count FROM promocodes") as cursor:
            rows = await cursor.fetchall()
    if not rows:
        await message.answer("Промокодов нет.", reply_markup=promo_admin_keyboard())
        return
    text = "🎫 Промокоды:\n"
    for row in rows:
        text += f"{row[0]}: {row[1]} монет, использовано {row[3]}/{row[2]}\n"
    await message.answer(text, reply_markup=promo_admin_keyboard())

# ===== СТАТИСТИКА =====
@dp.message(F.text == "📊 Статистика")
async def stats_handler(message: Message):
    if not await is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        users = await db.execute_fetchone("SELECT COUNT(*) FROM users")
        total_balance = await db.execute_fetchone("SELECT SUM(balance) FROM users")
        active_giveaways = await db.execute_fetchone("SELECT COUNT(*) FROM giveaways WHERE status='active'")
        shop_items = await db.execute_fetchone("SELECT COUNT(*) FROM shop_items")
        purchases_pending = await db.execute_fetchone("SELECT COUNT(*) FROM purchases WHERE status='pending'")
        purchases_completed = await db.execute_fetchone("SELECT COUNT(*) FROM purchases WHERE status='completed'")
        total_thefts = await db.execute_fetchone("SELECT SUM(theft_attempts) FROM users")
        total_thefts_success = await db.execute_fetchone("SELECT SUM(theft_success) FROM users")
    text = (
        f"📊 Статистика:\n"
        f"👥 Пользователей: {users[0]}\n"
        f"💰 Всего монет: {total_balance[0] or 0}\n"
        f"🎁 Активных розыгрышей: {active_giveaways[0]}\n"
        f"🛒 Товаров в магазине: {shop_items[0]}\n"
        f"🛍️ Ожидающих покупок: {purchases_pending[0]}\n"
        f"✅ Выполненных покупок: {purchases_completed[0]}\n"
        f"🔫 Всего ограблений: {total_thefts[0] or 0} (успешно: {total_thefts_success[0] or 0})"
    )
    await message.answer(text, reply_markup=admin_main_keyboard(await is_super_admin(message.from_user.id)))

# ===== НАЙТИ ПОЛЬЗОВАТЕЛЯ =====
@dp.message(F.text == "👥 Найти пользователя")
async def find_user_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return
    await message.answer("Введи ID или @username пользователя:", reply_markup=back_keyboard())
    await state.set_state(FindUser.query)

@dp.message(FindUser.query)
async def find_user_result(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        super_admin = await is_super_admin(message.from_user.id)
        await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))
        return
    query = message.text.strip()
    if query.startswith('@'):
        username = query[1:]
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id, first_name, balance, joined_date, theft_attempts, theft_success, theft_failed, theft_protected, protection_item FROM users WHERE username=?", (username,)) as cur:
                row = await cur.fetchone()
    else:
        try:
            uid = int(query)
        except:
            await message.answer("❌ Некорректный формат. Введи ID или @username.")
            return
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT user_id, first_name, balance, joined_date, theft_attempts, theft_success, theft_failed, theft_protected, protection_item FROM users WHERE user_id=?", (uid,)) as cur:
                row = await cur.fetchone()
    if not row:
        await message.answer("❌ Пользователь не найден.")
        return
    uid, name, bal, joined, attempts, success, failed, protected, prot = row
    prot_text = "Нет" if prot == 'none' else prot.replace('protect-', '🛡️ Уровень ')
    text = (
        f"👤 Пользователь: {name} (ID: {uid})\n"
        f"💰 Баланс: {bal}\n"
        f"📅 Регистрация: {joined}\n"
        f"🔫 Ограблений: {attempts} (успешно: {success}, провал: {failed})\n"
        f"🛡️ Защита: {prot_text}\n"
        f"⚔️ Отбито атак: {protected}"
    )
    await message.answer(text)
    await state.clear()

# ===== СПИСОК ПОКУПОК (АДМИН) =====
@dp.message(F.text == "🛍️ Список покупок")
async def admin_purchases(message: Message):
    if not await is_admin(message.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT p.id, u.user_id, u.username, s.name, p.purchase_date, p.status FROM purchases p JOIN users u ON p.user_id = u.user_id JOIN shop_items s ON p.item_id = s.id WHERE p.status='pending' ORDER BY p.purchase_date"
        ) as cursor:
            purchases = await cursor.fetchall()
    if not purchases:
        await message.answer("Нет необработанных покупок.")
        return
    for pid, uid, username, item_name, date, status in purchases:
        text = f"🆔 {pid}\nПользователь: {uid} (@{username})\nТовар: {item_name}\nДата: {date}"
        await message.answer(text, reply_markup=purchase_action_keyboard(pid))

@dp.callback_query(lambda c: c.data.startswith("purchase_done_"))
async def purchase_done(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    purchase_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE purchases SET status='completed' WHERE id=?", (purchase_id,))
        await db.commit()
        async with db.execute("SELECT user_id FROM purchases WHERE id=?", (purchase_id,)) as cur:
            row = await cur.fetchone()
            if row:
                user_id = row[0]
                try:
                    await bot.send_message(user_id, "✅ Твоя покупка обработана! Админ выслал подарок.")
                except:
                    pass
    await callback.answer("Покупка отмечена как выполненная")
    await callback.message.delete()

@dp.callback_query(lambda c: c.data.startswith("purchase_reject_"))
async def purchase_reject(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Недостаточно прав", show_alert=True)
        return
    purchase_id = int(callback.data.split("_")[2])
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE purchases SET status='rejected' WHERE id=?", (purchase_id,))
        await db.commit()
        async with db.execute("SELECT user_id FROM purchases WHERE id=?", (purchase_id,)) as cur:
            row = await cur.fetchone()
            if row:
                user_id = row[0]
                try:
                    await bot.send_message(user_id, "❌ К сожалению, твоя покупка не может быть выполнена. Свяжись с админом.")
                except:
                    pass
    await callback.answer("Покупка отклонена")
    await callback.message.delete()

# ===== ДОБАВЛЕНИЕ МЛАДШЕГО АДМИНА =====
@dp.message(F.text == "➕ Добавить админа")
async def add_admin_start(message: Message, state: FSMContext):
    if not await is_super_admin(message.from_user.id):
        await message.answer("Только суперадмин может добавлять админов.")
        return
    await message.answer("Введи ID пользователя, которого хочешь сделать младшим админом:", reply_markup=back_keyboard())
    await state.set_state(AddJuniorAdmin.user_id)

@dp.message(AddJuniorAdmin.user_id)
async def add_admin_finish(message: Message, state: FSMContext):
    if message.text == "◀️ Назад":
        await state.clear()
        super_admin = await is_super_admin(message.from_user.id)
        await message.answer("Панель администратора:", reply_markup=admin_main_keyboard(super_admin))
        return
    try:
        uid = int(message.text)
    except:
        await message.answer("❌ Введи числовой ID.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        # Проверим, есть ли пользователь в БД
        async with db.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)) as cur:
            if not await cur.fetchone():
                await message.answer("❌ Пользователь с таким ID не найден в боте.")
                return
        # Добавляем в таблицу admins
        try:
            await db.execute("INSERT INTO admins (user_id, added_by, added_date) VALUES (?, ?, ?)",
                             (uid, message.from_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            await db.commit()
            await message.answer(f"✅ Пользователь {uid} теперь младший админ.")
        except aiosqlite.IntegrityError:
            await message.answer("❌ Этот пользователь уже админ.")
    await state.clear()

# ===== СБРОС СТАТИСТИКИ =====
@dp.message(F.text == "🔄 Сброс статистики")
async def reset_stats(message: Message):
    if not await is_super_admin(message.from_user.id):
        return
    # Запрашиваем подтверждение
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, сбросить всё", callback_data="reset_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="reset_cancel")]
    ])
    await message.answer("⚠️ Ты уверен? Это действие безвозвратно обнулит балансы, покупки и статистику всех пользователей.", reply_markup=confirm_kb)

@dp.callback_query(lambda c: c.data == "reset_confirm")
async def reset_confirm(callback: CallbackQuery):
    if not await is_super_admin(callback.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        # Обнуляем балансы и статистику пользователей
        await db.execute("UPDATE users SET balance=0, theft_attempts=0, theft_success=0, theft_failed=0, theft_protected=0, protection_item='none', tool_item='none'")
        # Очищаем покупки
        await db.execute("DELETE FROM purchases")
        await db.commit()
    await callback.message.edit_text("✅ Статистика сброшена.")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "reset_cancel")
async def reset_cancel(callback: CallbackQuery):
    await callback.message.edit_text("Сброс отменён.")
    await callback.answer()

# ===== НАЗАД В ГЛАВНОЕ МЕНЮ ИЗ АДМИНКИ =====
@dp.message(F.text == "◀️ Назад в главное меню")
async def back_to_main_from_admin(message: Message):
    admin_flag = await is_admin(message.from_user.id)
    await message.answer("Главное меню:", reply_markup=user_main_keyboard(admin_flag))

# ===== ОБРАБОТКА НЕИЗВЕСТНЫХ СООБЩЕНИЙ =====
@dp.message()
async def unknown_message(message: Message):
    admin_flag = await is_admin(message.from_user.id)
    await message.answer("Я не понимаю эту команду. Используй кнопки меню.", reply_markup=user_main_keyboard(admin_flag))

# ===== ВЕБ-СЕРВЕР ДЛЯ RAILWAY =====
async def handle(request):
    return web.Response(text="Bot is running")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started on port {port}")

# ===== ЗАПУСК =====
async def main():
    await init_db()
    # Запускаем веб-сервер для Railway
    asyncio.create_task(start_web_server())
    logging.info("🤖 Бот запущен и готов к работе!")
    logging.info(f"👑 Суперадмины: {SUPER_ADMINS}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
