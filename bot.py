import asyncio
import logging
import sqlite3
import random
from datetime import datetime
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
    # Таблица пользователей
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TEXT
        )
    ''')
    # Таблица розыгрышей
    cur.execute('''
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prize TEXT,
            end_date TEXT,
            status TEXT DEFAULT 'active',
            winner_id INTEGER
        )
    ''')
    # Таблица участников
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

# ===== СОСТОЯНИЯ ДЛЯ СОЗДАНИЯ РОЗЫГРЫША =====
class CreateGiveaway(StatesGroup):
    prize = State()
    end_date = State()

# ===== ИНИЦИАЛИЗАЦИЯ =====
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ===== ПРОВЕРКА АДМИНА =====
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

# ===== КЛАВИАТУРЫ =====
def admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать розыгрыш", callback_data="admin_create")],
        [InlineKeyboardButton(text="📋 Активные розыгрыши", callback_data="admin_list")],
        [InlineKeyboardButton(text="✅ Завершить розыгрыш", callback_data="admin_complete")],
        [InlineKeyboardButton(text="🏆 Выбрать победителя", callback_data="admin_pick_winner")]
    ])
    return keyboard

def back_to_admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад в админку", callback_data="admin_back")]
    ])
    return keyboard

# ===== ХЭНДЛЕРЫ =====

# Старт
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, joined_date) VALUES (?, ?, ?, ?)",
                (user_id, username, first_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()
    await message.answer(f"Привет, {first_name}!\nЯ бот для розыгрышей. Используй /admin, если ты админ.")

# Админка
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет прав администратора.")
        return
    await message.answer("Панель администратора:", reply_markup=admin_keyboard())

# Обработка кнопок админки
@dp.callback_query(lambda c: c.data.startswith('admin_'))
async def admin_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer("Нет прав", show_alert=True)
        return
    
    action = callback.data.split('_')[1]
    
    if action == "back":
        await callback.message.edit_text("Панель администратора:", reply_markup=admin_keyboard())
    
    elif action == "create":
        await callback.message.edit_text("Введи название приза (например: iPhone 15):", reply_markup=back_to_admin_keyboard())
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
            text = "🎁 Активные розыгрыши:\n\n"
            for row in rows:
                text += f"ID: {row[0]} | Приз: {row[1]} | до {row[2]}\n"
            await callback.message.edit_text(text, reply_markup=back_to_admin_keyboard())
    
    elif action == "complete":
        await callback.message.edit_text("Введи ID розыгрыша, который нужно завершить:", reply_markup=back_to_admin_keyboard())
        # Здесь можно добавить логику через FSM, пока просто уведомление
        await callback.message.answer("Эта функция будет добавлена позже.")
    
    elif action == "pick_winner":
        await callback.message.edit_text("Введи ID розыгрыша для выбора победителя:", reply_markup=back_to_admin_keyboard())
        await callback.message.answer("Эта функция будет добавлена позже.")

# Состояния создания розыгрыша
@dp.message(CreateGiveaway.prize)
async def create_prize(message: Message, state: FSMContext):
    await state.update_data(prize=message.text)
    await message.answer("Введи дату окончания в формате ДД.ММ.ГГГГ (например: 31.12.2025):", reply_markup=back_to_admin_keyboard())
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
    giveaway_id = cur.lastrowid
    conn.close()
    
    await message.answer(f"✅ Розыгрыш создан!\nID: {giveaway_id}\nПриз: {prize}\nОкончание: {end_date}")
    await state.clear()

# Участие в розыгрыше
@dp.message(Command("participate"))
async def cmd_participate(message: Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Используй: /participate <ID_розыгрыша>")
        return
    
    try:
        giveaway_id = int(args[1])
    except:
        await message.answer("ID должен быть числом.")
        return
    
    user_id = message.from_user.id
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    
    # Проверяем активен ли розыгрыш
    cur.execute("SELECT status FROM giveaways WHERE id=?", (giveaway_id,))
    row = cur.fetchone()
    if not row or row[0] != 'active':
        await message.answer("Розыгрыш не найден или уже завершён.")
        conn.close()
        return
    
    # Проверяем не участвует ли уже
    cur.execute("SELECT * FROM participants WHERE user_id=? AND giveaway_id=?", (user_id, giveaway_id))
    if cur.fetchone():
        await message.answer("Ты уже участвуешь в этом розыгрыше!")
        conn.close()
        return
    
    # Добавляем участника
    cur.execute("INSERT INTO participants (user_id, giveaway_id) VALUES (?, ?)", (user_id, giveaway_id))
    conn.commit()
    conn.close()
    
    await message.answer("✅ Ты успешно участвуешь в розыгрыше! Удачи!")

# Просмотр активных розыгрышей
@dp.message(Command("giveaways"))
async def cmd_giveaways(message: Message):
    conn = sqlite3.connect('database.db')
    cur = conn.cursor()
    cur.execute("SELECT id, prize, end_date FROM giveaways WHERE status='active'")
    rows = cur.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("Сейчас нет активных розыгрышей.")
    else:
        text = "🎁 Активные розыгрыши:\n\n"
        for row in rows:
            text += f"ID: {row[0]} | {row[1]} | до {row[2]}\n"
        text += "\nУчаствуй: /participate ID"
        await message.answer(text)

# ===== ЗАПУСК =====
async def main():
    init_db()
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
