import os
import sqlite3
import json
import re
import asyncio
import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Проверка директории /opt/data
try:
    if not os.path.exists('/opt/data'):
        os.makedirs('/opt/data')
        logger.info("Created directory /opt/data")
    with open('/opt/data/test_write', 'w') as f:
        f.write('test')
    os.remove('/opt/data/test_write')
    logger.info("Write permissions in /opt/data confirmed")
except Exception as e:
    logger.error(f"Cannot access or write to /opt/data: {e}")
    raise

# Инициализация базы данных SQLite
def init_db():
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS orders
                     (user_id INTEGER, uc_amount TEXT, price TEXT, player_id TEXT, status TEXT, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, language TEXT, bonuses INTEGER, referral_code TEXT, referred_by TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS promos
                     (code TEXT PRIMARY KEY, discount REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute("INSERT OR IGNORE INTO promos (code, discount) VALUES ('SUMMER10', 0.1)")
        c.execute("INSERT OR IGNORE INTO promos (code, discount) VALUES ('WELCOME', 0.05)")
        conn.commit()
        logger.info("Database initialized successfully at /opt/data/bot.db")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        conn.close()

init_db()

# Загрузка цен из JSON
PRICES = {
    "60": "90.06 ₽", "325": "450.31 ₽", "660": "900.61 ₽",
    "1800": "2251.53 ₽", "3850": "4503.05 ₽", "8100": "9006.10 ₽"
}
try:
    with open('/opt/data/prices.json', 'w') as f:
        json.dump(PRICES, f)
    logger.info("prices.json created successfully at /opt/data/prices.json")
except Exception as e:
    logger.error(f"Failed to create prices.json: {e}")

def load_prices():
    try:
        with open('/opt/data/prices.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load prices.json: {e}")
        return PRICES

# Проверка валидности ID игрока
def is_valid_player_id(player_id):
    return bool(re.match(r'^\d{8,12}$', player_id))

# Переводы для мультиязычности
TRANSLATIONS = {
    'ru': {
        'welcome': "Здравствуйте, это бот от TopUp UC (BETA)\nЯ буду сопровождать Вас.\n\n"
                  "Доступные команды:\n"
                  "/buy_uc — Купить UC\n"
                  "/promo — Ввести промокод (например, SUMMER10)\n"
                  "/history — Показать список заказов\n"
                  "/bonuses — Показать бонусы\n"
                  "/custom — Калькулятор UC\n"
                  "/referral — Получить реферальную ссылку\n"
                  "/language — Сменить язык",
        'choose_uc': "Вы покупаете UC, укажите сумму:",
        'order_details': "⭐️ Здравствуйте, это пополнение от TopUp UC.\n"
                        "💎 В оставленной заявке на пополнение UC фигурировал Ваш Telegram-ник: @{username}.\n"
                        "👉🏻 Перевод осуществляется только на карту @azcoin456, обязательно спросите куда идут деньги!\n"
                        "🛒 Уточним детали:\n"
                        "✍️ Ваша покупка: {uc_amount} UC ✍️\n"
                        "☺️ Сумма к оплате: {price}\n\n"
                        "🤍🤍🤍🤍🤍🤍🤍🤍🤍🤍🤍🤍\n\n"
                        "✨ После оплаты отправьте скриншот платежа в ответ на это сообщение.\n"
                        "⏳ Срок зачисления: UC будут зачислены в течение 10-30 минут после подтверждения платежа.\n\n"
                        "🤍🤍🤍🤍🤍🤍🤍🤍\n"
                        "📢 Бонус: Пополняйте UC и участвуйте в нашей системе достижений! "
                        "Узнайте подробности в канале (https://t.me/ucbuypubgmobile/10).",
        'enter_id': "Введите ID игрока для PUBG Mobile:",
        'invalid_id': "Некорректный ID. Введите 8-12 цифр.",
        'id_saved': "ID игрока сохранен: {player_id}\nТеперь выберите 'Оплатить' для продолжения.",
        'payment': "Оплата {uc_amount} UC\nPlayerID: {player_id}",
        'screenshot_received': "Скриншот платежа получен! Мы проверим и зачислим UC в течение 10-30 минут.",
        'promo_prompt': "Введите промокод:",
        'promo_success': "Промокод применен! Скидка: {discount}%",
        'promo_invalid': "Неверный промокод.",
        'history': "Ваши заказы:\n{history}",
        'bonuses': "Ваши бонусы: {bonuses} UC",
        'custom_uc': "Введите количество UC для расчета цены:",
        'custom_result': "{uc_amount} UC = {price} ₽",
        'referral': "Ваша реферальная ссылка: {link}\nПриглашайте друзей и получайте 5% бонусов от их покупок!",
        'reminder': "Вы выбрали {uc_amount} UC, но не завершили заказ. Продолжить?",
        'banned': "Ваш аккаунт заблокирован."
    },
    'en': {
        'welcome': "Hello, this is the TopUp UC bot (BETA)\nI'll assist you.\n\n"
                  "Available commands:\n"
                  "/buy_uc — Buy UC\n"
                  "/promo — Enter promo code (e.g., SUMMER10)\n"
                  "/history — Show order history\n"
                  "/bonuses — Show bonuses\n"
                  "/custom — UC calculator\n"
                  "/referral — Get referral link\n"
                  "/language — Change language",
        'choose_uc': "You are buying UC, select an amount:",
        'order_details': "⭐️ Hello, this is a TopUp UC replenishment.\n"
                        "💎 Your Telegram username was mentioned in the UC replenishment request: @{username}.\n"
                        "👉🏻 Payment is made only to the card @azcoin456, always ask where the money is going!\n"
                        "🛒 Let's clarify the details:\n"
                        "✍️ Your purchase: {uc_amount} UC ✍️\n"
                        "☺️ Amount to pay: {price}\n\n"
                        "🤍🤍🤍🤍🤍🤍🤍🤍🤍🤍🤍🤍\n\n"
                        "✨ After payment, send a screenshot of the payment in reply to this message.\n"
                        "⏳ Processing time: UC will be credited within 10-30 minutes after payment confirmation.\n\n"
                        "🤍🤍🤍🤍🤍🤍🤍🤍\n"
                        "📢 Bonus: Top up UC and participate in our achievement system! "
                        "Learn more in the channel (https://t.me/ucbuypubgmobile/10).",
        'enter_id': "Enter your PUBG Mobile player ID:",
        'invalid_id': "Invalid ID. Enter 8-12 digits.",
        'id_saved': "Player ID saved: {player_id}\nNow select 'Pay' to continue.",
        'payment': "Payment for {uc_amount} UC\nPlayerID: {player_id}",
        'screenshot_received': "Payment screenshot received! We will verify and credit UC within 10-30 minutes.",
        'promo_prompt': "Enter promo code:",
        'promo_success': "Promo code applied! Discount: {discount}%",
        'promo_invalid': "Invalid promo code.",
        'history': "Your orders:\n{history}",
        'bonuses': "Your bonuses: {bonuses} UC",
        'custom_uc': "Enter the amount of UC to calculate the price:",
        'custom_result': "{uc_amount} UC = {price} USD",
        'referral': "Your referral link: {link}\nInvite friends and get 5% bonuses from their purchases!",
        'reminder': "You selected {uc_amount} UC but didn't complete the order. Continue?",
        'banned': "Your account is banned."
    }
}

# ID админа
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # Замени через переменную окружения в Render

async def check_ban(update: Update, context):
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
        if c.fetchone():
            await update.message.reply_text(TRANSLATIONS['ru']['banned'])
            return True
        return False
    except Exception as e:
        logger.error(f"Check ban failed: {e}")
        return False
    finally:
        conn.close()

async def start(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, language, bonuses) VALUES (?, 'ru', 0)", (user_id,))
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.commit()

        if context.args and context.args[0].startswith('ref'):
            referred_by = context.args[0].replace('ref', '')
            c.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referred_by, user_id))
            conn.commit()

        await update.message.reply_text(TRANSLATIONS[lang]['welcome'])
        context.job_queue.run_once(reminder, 600, data={'user_id': user_id}, name=str(user_id))
    except Exception as e:
        logger.error(f"Start command failed: {e}")
    finally:
        conn.close()

async def buy_uc(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()

        prices = load_prices()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"60 UC: {prices['60']}", callback_data="60uc")],
            [InlineKeyboardButton(f"325 UC: {prices['325']}", callback_data="325uc")],
            [InlineKeyboardButton(f"660 UC: {prices['660']}", callback_data="660uc")],
            [InlineKeyboardButton(f"1800 UC: {prices['1800']}", callback_data="1800uc")],
            [InlineKeyboardButton(f"3850 UC: {prices['3850']}", callback_data="3850uc")],
            [InlineKeyboardButton(f"8100 UC: {prices['8100']}", callback_data="8100uc")]
        ])
        await update.message.reply_text(TRANSLATIONS[lang]['choose_uc'], reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Buy UC command failed: {e}")

async def button_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()

        if query.data in ["60uc", "325uc", "660uc", "1800uc", "3850uc", "8100uc"]:
            context.user_data['selected_uc'] = query.data.replace("uc", "")
            uc_amount = context.user_data['selected_uc']
            prices = load_prices()
            price = prices.get(uc_amount, "неизвестно")
            discount = context.user_data.get('discount', 0)
            if discount:
                price_value = float(price.replace(" ₽", ""))
                price = f"{price_value * (1 - discount):.2f} ₽ (скидка {discount*100}%)"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("Ввести ID" if lang == 'ru' else "Enter ID", callback_data="enter_id")],
                [InlineKeyboardButton("Оплатить" if lang == 'ru' else "Pay", callback_data="pay")]
            ])
            await query.message.reply_text(
                TRANSLATIONS[lang]['order_details'].format(
                    username=query.from_user.username or 'не указан',
                    uc_amount=uc_amount,
                    price=price
                ),
                reply_markup=keyboard
            )

            conn = sqlite3.connect('/opt/data/bot.db')
            c = conn.cursor()
            c.execute("INSERT INTO orders (user_id, uc_amount, price, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                      (user_id, uc_amount, price, 'pending', datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()

            price_value = float(price.split()[0])
            bonuses = int(price_value // 1000)
            c.execute("UPDATE users SET bonuses = bonuses + ? WHERE user_id = ?", (bonuses, user_id))
            conn.commit()

            await context.bot.send_message(
                ADMIN_ID,
                f"Новый заказ:\nПользователь: @{query.from_user.username or 'не указан'}\nUC: {uc_amount}\nЦена: {price}"
            )

        elif query.data == "enter_id":
            await query.message.reply_text(TRANSLATIONS[lang]['enter_id'])
            context.user_data['waiting_for_id'] = True

        elif query.data == "pay":
            player_id = context.user_data.get('player_id', 'не указан')
            uc_amount = context.user_data.get('selected_uc', 'неизвестно')
            await query.message.reply_text(
                TRANSLATIONS[lang]['payment'].format(uc_amount=uc_amount, player_id=player_id)
            )

            price = float(load_prices().get(uc_amount, "0").replace(" ₽", ""))
            bonus = int(price * 0.05)
            conn = sqlite3.connect('/opt/data/bot.db')
            c = conn.cursor()
            c.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
            referred_by = c.fetchone()
            if referred_by and referred_by[0]:
                c.execute("UPDATE users SET bonuses = bonuses + ? WHERE user_id = ?", (bonus, int(referred_by[0])))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Button callback failed: {e}")

async def handle_player_id(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()

        if context.user_data.get('waiting_for_id', False):
            player_id = update.message.text
            if not is_valid_player_id(player_id):
                await update.message.reply_text(TRANSLATIONS[lang]['invalid_id'])
                return
            context.user_data['player_id'] = player_id
            context.user_data['waiting_for_id'] = False
            await update.message.reply_text(TRANSLATIONS[lang]['id_saved'].format(player_id=player_id))

            conn = sqlite3.connect('/opt/data/bot.db')
            c = conn.cursor()
            c.execute("UPDATE orders SET player_id = ? WHERE user_id = ? AND status = 'pending'",
                      (player_id, user_id))
            conn.commit()
            conn.close()
    except Exception as e:
        logger.error(f"Handle player ID failed: {e}")

async def handle_screenshot(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()

        if update.message.photo:
            await update.message.reply_text(TRANSLATIONS[lang]['screenshot_received'])
            await context.bot.send_photo(
                ADMIN_ID,
                update.message.photo[-1].file_id,
                caption=f"Скриншот платежа от @{update.effective_user.username or 'не указан'}"
            )
    except Exception as e:
        logger.error(f"Handle screenshot failed: {e}")

async def promo(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()

        await update.message.reply_text(TRANSLATIONS[lang]['promo_prompt'])
        context.user_data['waiting_for_promo'] = True
    except Exception as e:
        logger.error(f"Promo command failed: {e}")

async def handle_promo(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]

        if context.user_data.get('waiting_for_promo', False):
            promo_code = update.message.text.upper()
            c.execute("SELECT discount FROM promos WHERE code = ?", (promo_code,))
            result = c.fetchone()
            if result:
                context.user_data['discount'] = result[0]
                await update.message.reply_text(
                    TRANSLATIONS[lang]['promo_success'].format(discount=result[0]*100)
                )
            else:
                await update.message.reply_text(TRANSLATIONS[lang]['promo_invalid'])
            context.user_data['waiting_for_promo'] = False
        conn.close()
    except Exception as e:
        logger.error(f"Handle promo failed: {e}")

async def history(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        c.execute("SELECT uc_amount, price, status, timestamp FROM orders WHERE user_id = ?", (user_id,))
        orders = c.fetchall()
        conn.close()

        if not orders:
            await update.message.reply_text("У вас пока нет заказов." if lang == 'ru' else "You have no orders yet.")
            return
        history_text = "\n".join([f"{o[3]}: {o[0]} UC, {o[1]}, {o[2]}" for o in orders])
        await update.message.reply_text(TRANSLATIONS[lang]['history'].format(history=history_text))
    except Exception as e:
        logger.error(f"History command failed: {e}")

async def bonuses(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language, bonuses FROM users WHERE user_id = ?", (user_id,))
        lang, bonuses = c.fetchone()
        conn.close()
        await update.message.reply_text(TRANSLATIONS[lang]['bonuses'].format(bonuses=bonuses))
    except Exception as e:
        logger.error(f"Bonuses command failed: {e}")

async def custom_uc(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()
        await update.message.reply_text(TRANSLATIONS[lang]['custom_uc'])
        context.user_data['waiting_for_custom_uc'] = True
    except Exception as e:
        logger.error(f"Custom UC command failed: {e}")

async def handle_custom_uc(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()

        if context.user_data.get('waiting_for_custom_uc', False):
            try:
                uc_amount = int(update.message.text)
                if uc_amount <= 0:
                    raise ValueError
                price = uc_amount * 1.5
                await update.message.reply_text(
                    TRANSLATIONS[lang]['custom_result'].format(uc_amount=uc_amount, price=price)
                )
            except ValueError:
                await update.message.reply_text("Введите положительное число.")
            context.user_data['waiting_for_custom_uc'] = False
    except Exception as e:
        logger.error(f"Handle custom UC failed: {e}")

async def referral(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language, referral_code FROM users WHERE user_id = ?", (user_id,))
        lang, referral_code = c.fetchone()
        if not referral_code:
            referral_code = f"ref{user_id}"
            c.execute("UPDATE users SET referral_code = ? WHERE user_id = ?", (referral_code, user_id))
            conn.commit()
        conn.close()
        link = f"t.me/YourBot?start={referral_code}"
        await update.message.reply_text(TRANSLATIONS[lang]['referral'].format(link=link))
    except Exception as e:
        logger.error(f"Referral command failed: {e}")

async def language(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Русский", callback_data="lang_ru")],
            [InlineKeyboardButton("English", callback_data="lang_en")]
        ])
        await update.message.reply_text("Выберите язык / Select language:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Language command failed: {e}")

async def set_language(update: Update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        lang = 'ru' if query.data == "lang_ru" else 'en'
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
        conn.commit()
        conn.close()
        await query.message.reply_text("Язык изменен / Language changed.")
    except Exception as e:
        logger.error(f"Set language failed: {e}")

async def admin(update: Update, context):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("Доступ запрещен.")
        return
    try:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Просмотреть заказы", callback_data="admin_orders")],
            [InlineKeyboardButton("Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("Заблокировать пользователя", callback_data="admin_ban")]
        ])
        await update.message.reply_text("Админ-панель:", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Admin command failed: {e}")

async def admin_callback(update: Update, context):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.message.reply_text("Доступ запрещен.")
        return
    try:
        if query.data == "admin_orders":
            conn = sqlite3.connect('/opt/data/bot.db')
            c = conn.cursor()
            c.execute("SELECT user_id, uc_amount, price, status, timestamp FROM orders")
            orders = c.fetchall()
            conn.close()
            if not orders:
                await query.message.reply_text("Заказов нет.")
                return
            orders_text = "\n".join([f"ID: {o[0]}, UC: {o[1]}, Цена: {o[2]}, Статус: {o[3]}, Время: {o[4]}" for o in orders])
            await query.message.reply_text(f"Заказы:\n{orders_text}")

        elif query.data == "admin_stats":
            conn = sqlite3.connect('/opt/data/bot.db')
            c = conn.cursor()
            c.execute("SELECT COUNT(*), SUM(CAST(REPLACE(price, ' ₽', '') AS REAL)) FROM orders")
            count, total = c.fetchone()
            c.execute("SELECT uc_amount, COUNT(*) FROM orders GROUP BY uc_amount ORDER BY COUNT(*) DESC LIMIT 1")
            popular = c.fetchone()
            conn.close()
            stats = f"Заказов: {count}\nОбщая выручка: {total or 0:.2f} ₽\nПопулярный пакет: {popular[0]} UC ({popular[1]} заказов)"
            await query.message.reply_text(stats)

        elif query.data == "admin_ban":
            await query.message.reply_text("Введите ID пользователя для блокировки:")
            context.user_data['waiting_for_ban'] = True
    except Exception as e:
        logger.error(f"Admin callback failed: {e}")

async def handle_admin_ban(update: Update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Доступ запрещен.")
        return
    try:
        if context.user_data.get('waiting_for_ban', False):
            try:
                ban_id = int(update.message.text)
                conn = sqlite3.connect('/opt/data/bot.db')
                c = conn.cursor()
                c.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (ban_id,))
                conn.commit()
                conn.close()
                await update.message.reply_text(f"Пользователь {ban_id} заблокирован.")
            except ValueError:
                await update.message.reply_text("Введите корректный ID.")
            context.user_data['waiting_for_ban'] = False
    except Exception as e:
        logger.error(f"Handle admin ban failed: {e}")

async def reminder(context):
    job = context.job
    user_id = job.data['user_id']
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        c.execute("SELECT uc_amount FROM orders WHERE user_id = ? AND status = 'pending' ORDER BY timestamp DESC LIMIT 1", (user_id,))
        result = c.fetchone()
        conn.close()
        if result:
            await context.bot.send_message(user_id, TRANSLATIONS[lang]['reminder'].format(uc_amount=result[0]))
    except Exception as e:
        logger.error(f"Reminder failed: {e}")

async def simple_chatbot(update: Update, context):
    if await check_ban(update, context):
        return
    user_id = update.effective_user.id
    try:
        conn = sqlite3.connect('/opt/data/bot.db')
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        lang = c.fetchone()[0]
        conn.close()

        text = update.message.text.lower()
        responses = {
            'ru': {
                'как долго ждать': "UC будут зачислены в течение 10-30 минут после подтверждения платежа.",
                'где мой заказ': "Проверьте статус заказа с помощью команды /history.",
                'как оплатить': "Используйте команду /buy_uc, выберите пакет UC, введите ID игрока и следуйте инструкциям."
            },
            'en': {
                'how long to wait': "UC will be credited within 10-30 minutes after payment confirmation.",
                'where is my order': "Check your order status with the /history command.",
                'how to pay': "Use the /buy_uc command, select a UC package, enter your player ID, and follow the instructions."
            }
        }
        response = responses[lang].get(text, "Извините, я не понял. Используйте /start для списка команд." if lang == 'ru' else "Sorry, I didn't understand. Use /start for a list of commands.")
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Simple chatbot failed: {e}")

async def main():
    try:
        token = os.environ.get("TOKEN")
        if not token:
            logger.error("No TOKEN environment variable set")
            raise ValueError("No TOKEN environment variable set")

        application = Application.builder().token(token).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("buy_uc", buy_uc))
        application.add_handler(CommandHandler("promo", promo))
        application.add_handler(CommandHandler("history", history))
        application.add_handler(CommandHandler("bonuses", bonuses))
        application.add_handler(CommandHandler("custom", custom_uc))
        application.add_handler(CommandHandler("referral", referral))
        application.add_handler(CommandHandler("language", language))
        application.add_handler(CommandHandler("admin", admin))
        application.add_handler(CallbackQueryHandler(button_callback, pattern="^(60uc|325uc|660uc|1800uc|3850uc|8100uc|enter_id|pay)$"))
        application.add_handler(CallbackQueryHandler(set_language, pattern="^lang_"))
        application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r'^\d{8,12}$'), handle_player_id))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_promo))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_uc))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_ban))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, simple_chatbot))
        application.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))

        logger.info("Starting webhook")
        await application.initialize()
        await application.start()
        await application.updater.start_webhook(
            listen="0.0.0.0",
            port=8443,
            url_path="/webhook",
            webhook_url="https://topup-uc-bot.onrender.com/webhook"
        )
        logger.info("Webhook started successfully")
    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        raise

if __name__ == '__main__':
    asyncio.run(main())