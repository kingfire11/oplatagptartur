import os
import json
import hashlib
import hmac
import asyncio
import time
import re
import logging
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F
from dotenv import load_dotenv
from html import escape as html_escape

load_dotenv()

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
LAVA_SHOP_ID = os.getenv('LAVA_SHOP_ID')
LAVA_SECRET_KEY = os.getenv('LAVA_SECRET_KEY')
LAVA_ADDITIONAL_KEY = os.getenv('LAVA_ADDITIONAL_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '').rstrip('/')
if not WEBHOOK_URL:
    WEBHOOK_URL = "https://placeholder.bothost.ru"
ADMIN_ID = int(os.getenv('ADMIN_ID', '6499414636'))
LAVA_API_URL = "https://api.lava.ru/business/invoice/create"

_bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
_last_request_time: dict[int, float] = {}
RATE_LIMIT_SECONDS = 30

# Защита от дублирования webhook
_processed_orders: set = set()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==================== LAVA WEBHOOK ====================

def verify_lava_sign(data: dict) -> bool:
    """Проверяет подпись Lava: md5("invoice_id:amount:pay_time:secret_key_2")"""
    sign = data.get('sign')
    if not sign:
        logger.warning("Webhook received without sign")
        return True  # Если secret_key_2 не задан, Lava не шлёт sign

    expected = hashlib.md5(
        f"{data.get('invoice_id')}:{data.get('amount')}:{data.get('pay_time')}:{LAVA_ADDITIONAL_KEY}".encode()
    ).hexdigest()
    return hmac.compare_digest(expected.lower(), sign.lower())


async def handle_lava_webhook(request):
    try:
        raw = await request.read()
        logger.info(f"Webhook raw body: {raw.decode('utf-8', errors='replace')}")

        data = json.loads(raw)
        logger.info(f"Webhook parsed: {data}")

        if not verify_lava_sign(data):
            logger.warning("Invalid webhook sign")
            return web.json_response({'error': 'Invalid sign'}, status=403)

        webhook_type = data.get('type')
        order_id = data.get('order_id')
        amount = data.get('amount')
        status = data.get('status')
        credited = data.get('credited')
        invoice_id = data.get('invoice_id')

        logger.info(f"Webhook fields: type={webhook_type}, order_id={order_id}, invoice_id={invoice_id}, status={status}, amount={amount}")

        # type=1 (счёт) или без type + статус "success"/"paid"
        if status in ('success', 'paid') and (webhook_type is None or webhook_type == 1):
            if order_id in _processed_orders:
                logger.info(f"Duplicate webhook for order {order_id}, skipping")
                return web.json_response({'status': 'ok'})

            _processed_orders.add(order_id)
            text = (
                f"✅ <b>Оплата прошла успешно!</b>\n\n"
                f"📦 Заказ: {order_id}\n"
                f"🆔 Инвойс: {invoice_id}\n"
                f"💰 Сумма: {amount} ₽"
            )
            if credited:
                text += f"\n📥 Зачислено: {credited} ₽"

            await bot.send_message(
                chat_id=ADMIN_ID,
                text=text,
                parse_mode="HTML"
            )

            logger.info(f"Payment success: order={order_id}, amount={amount}, credited={credited}")
        else:
            logger.info(f"Payment not success: order={order_id}, status={status}")

        return web.json_response({'status': 'ok'})
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return web.json_response({'error': 'Internal server error'}, status=500)


async def handle_health(request):
    return web.json_response({'status': 'ok'})


# ==================== TELEGRAM BOT ====================

def get_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Купить API", callback_data="shop_main")],
        [InlineKeyboardButton(text="🛠 Техподдержка", url="https://t.me/claudxeseller")],
        [InlineKeyboardButton(text="📄 Публичная оферта", callback_data="docs_offer")],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data="docs_privacy")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="docs_contacts")],
        [InlineKeyboardButton(text="↩️ Политика возврата", callback_data="docs_refund")],
    ])
    return keyboard


def get_products_keyboard() -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💻 Claude Code API 3000$", callback_data="product_3000")],
        [InlineKeyboardButton(text="💻 Claude Code API 5000$", callback_data="product_5000")],
        [InlineKeyboardButton(text="💻 Claude Code API 10000$", callback_data="product_10000")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
    ])
    return keyboard


def get_buy_keyboard(product_id: str) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Купить", callback_data=f"buy_{product_id}")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
    ])
    return keyboard


def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    last_time = _last_request_time.get(user_id, 0)
    if now - last_time < RATE_LIMIT_SECONDS:
        return False
    _last_request_time[user_id] = now
    return True


def sanitize_html(text: str) -> str:
    return html_escape(str(text))


async def create_lava_invoice(amount: float, order_id: str, username: str = None) -> str:
    hook_url = f"{WEBHOOK_URL}/lava/webhook"
    logger.info(f"Hook URL for Lava: {hook_url}")
    body = {
        "shopId": LAVA_SHOP_ID,
        "sum": float(amount),
        "orderId": order_id,
        "hookUrl": hook_url,
    }
    if username:
        body["comment"] = f"Order from @{username}"

    body_json = json.dumps(body)
    signature = hmac.new(LAVA_SECRET_KEY.encode(), body_json.encode(), hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Signature": signature
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(LAVA_API_URL, json=body, headers=headers) as response:
            result = await response.json()
            if result.get("status") == 200 or result.get("status_check") == True:
                return result.get("data", {}).get("url")
            else:
                raise Exception(f"Lava API error: {result.get('error', 'Unknown error')}")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот магазина Claude Code API.\n\n"
        "Нажмите кнопку 💳 Купить, чтобы выбрать товар,\n"
        "или обратитесь в техподдержку за помощью.",
        reply_markup=get_main_keyboard()
    )


PRODUCTS = {
    "3000": {"name": "Claude Code API 3000$", "amount": 3000, "price_rub": 3000, "description": "Доступ к API Claude Code для разработки.\n\nПодходит для:\n• Telegram-ботов\n• VS Code / Cursor / IDE\n• AI-ассистентов\n• автоматизации и генерации кода\n\nВы получаете API ключ с кредитами.\n\nКредиты не имеют срока действия и могут использоваться в любое время.\n\nДоступны модели:\n• Claude sonnet 4.6\n• Claude sonnet 4.5\n• Claude Opus 4.5\n• Claude Opus 4.6"},
    "5000": {"name": "Claude Code API 5000$", "amount": 5000, "price_rub": 4500, "description": "Доступ к API Claude Code для разработки.\n\nПодходит для:\n• Telegram-ботов\n• VS Code / Cursor / IDE\n• AI-ассистентов\n• автоматизации и генерации кода\n\nВы получаете API ключ с кредитами.\n\nКредиты не имеют срока действия и могут использоваться в любое время.\n\nДоступны модели:\n• Claude sonnet 4.6\n• Claude sonnet 4.5\n• Claude Opus 4.5\n• Claude Opus 4.6"},
    "10000": {"name": "Claude Code API 10000$", "amount": 10000, "price_rub": 8000, "description": "Доступ к API Claude Code для разработки.\n\nПодходит для:\n• Telegram-ботов\n• VS Code / Cursor / IDE\n• AI-ассистентов\n• автоматизации и генерации кода\n\nВы получаете API ключ с кредитами.\n\nКредиты не имеют срока действия и могут использоваться в любое время.\n\nДоступны модели:\n• Claude sonnet 4.6\n• Claude sonnet 4.5\n• Claude Opus 4.5\n• Claude Opus 4.6"}
}


@dp.message(F.text)
async def handle_text(message: types.Message):
    pattern = r'^@?(\w+)\s+(\d+)$'
    match = re.match(pattern, message.text)

    if match:
        username = match.group(1)
        amount = int(match.group(2))

        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0.")
            return
        if amount > 100000:
            await message.answer("❌ Максимальная сумма — 100 000 ₽.")
            return

        if not check_rate_limit(message.from_user.id):
            await message.answer("⏳ Подождите 30 секунд между запросами.")
            return

        order_id = f"order_{int(time.time())}"

        try:
            payment_link = await create_lava_invoice(amount, order_id, username)
            buyer = message.from_user
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🛒 <b>Новый заказ!</b>\n\n"
                    f"👤 Покупатель: @{sanitize_html(buyer.username or 'нет username')}\n"
                    f"📝 Имя: {sanitize_html(buyer.full_name)}\n"
                    f"🆔 ID: {buyer.id}\n"
                    f"💰 Сумма: {amount} ₽"
                ),
                parse_mode="HTML"
            )
            logger.info(f"Order created by {buyer.id}: {order_id}, {amount}₽")
        except Exception as e:
            logger.error(f"Failed to create invoice: {e}")
            await message.answer(f"❌ Ошибка создания счёта: {str(e)}")
            return

        await message.answer(
            f"💰 <b>Ссылка для оплаты создана</b>\n\n"
            f"👤 Пользователь: {sanitize_html(username)}\n"
            f"💵 Сумма: <b>{amount} ₽</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Оплатить", url=payment_link)]
            ])
        )
    else:
        await message.answer("❌ Для покупки товаров используйте кнопку 💳 Купить в меню.")


@dp.callback_query(F.data == "docs_back")
async def handle_back(callback: types.CallbackQuery):
    await callback.message.answer(
        "👋 Привет! Я бот магазина Claude Code API.\n\n"
        "Нажмите кнопку 💳 Купить, чтобы выбрать товар,\n"
        "или обратитесь в техподдержку за помощью.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "shop_main")
async def handle_shop_main(callback: types.CallbackQuery):
    await callback.message.answer(
        "💎 <b>Магазин Claude Code API</b>\n\n"
        "Выберите товар для покупки:",
        parse_mode="HTML",
        reply_markup=get_products_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data == "main_menu")
async def handle_main_menu(callback: types.CallbackQuery):
    await callback.message.answer(
        "👋 Привет! Я бот магазина Claude Code API.\n\n"
        "Нажмите кнопку 💳 Купить, чтобы выбрать товар,\n"
        "или обратитесь в техподдержку за помощью.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("product_"))
async def handle_product(callback: types.CallbackQuery):
    product_id = callback.data.split("_")[1]
    product = PRODUCTS.get(product_id)
    if product:
        await callback.message.answer(
            f"💻 <b>{product['name']}</b>\n\n"
            f"{product['description']}\n\n"
            f"💵 Цена: <b>{product['price_rub']} ₽</b>",
            parse_mode="HTML",
            reply_markup=get_buy_keyboard(product_id)
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("buy_"))
async def handle_buy(callback: types.CallbackQuery):
    product_id = callback.data.split("_")[1]
    product = PRODUCTS.get(product_id)
    if product:
        amount_rub = product['price_rub']
        order_id = f"order_{int(time.time())}"
        username = callback.from_user.username
        buyer = callback.from_user

        if not check_rate_limit(buyer.id):
            await callback.answer("Подождите 30 секунд между запросами", show_alert=False)
            return

        try:
            payment_link = await create_lava_invoice(amount_rub, order_id, username)
            await bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🛒 <b>Новая покупка!</b>\n\n"
                    f"👤 Покупатель: @{sanitize_html(buyer.username or 'нет username')}\n"
                    f"📝 Имя: {sanitize_html(buyer.full_name)}\n"
                    f"🆔 ID: {buyer.id}\n"
                    f"📦 Товар: {sanitize_html(product['name'])}\n"
                    f"💰 Цена: {amount_rub} ₽"
                ),
                parse_mode="HTML"
            )
            logger.info(f"Purchase by {buyer.id}: {product['name']}, {amount_rub}₽")
        except Exception as e:
            logger.error(f"Failed to create invoice for buy: {e}")
            await callback.message.answer(f"❌ Ошибка создания счёта: {str(e)}")
            await callback.answer()
            return

        await callback.message.answer(
            f"🛒 <b>Оформление заказа</b>\n\n"
            f"Товар: {sanitize_html(product['name'])}\n"
            f"Сумма к оплате: <b>{amount_rub:.2f} ₽</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💰 Оплатить", url=payment_link)],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
            ])
        )
    await callback.answer()


@dp.callback_query(F.data.startswith("docs_"))
async def handle_docs(callback: types.CallbackQuery):
    doc_type = callback.data.split("_")[1]
    docs = {
        "offer": {"title": "📄 ПУБЛИЧНАЯ ОФЕРТА", "text": "1. ОБЩИЕ ПОЛОЖЕНИЯ\n1.1. Настоящая публичная оферта является официальным предложением заключить договор возмездного оказания услуг по предоставлению доступа к API Claude Code.\n1.2. В соответствии с п. 2 ст. 437 ГК РФ, в случае принятия условий оферты и оплаты услуг, физическое лицо становится Заказчиком.\n1.3. Акцептом оферты является факт оплаты услуг Заказчиком.\n\n2. ПРЕДМЕТ ОФЕРТЫ\n2.1. Исполнитель обязуется предоставить Заказчику доступ к API Claude Code с кредитами на сумму, соответствующую оплаченному тарифу.\n2.2. Услуги считаются оказанными с момента предоставления API ключа после успешного проведения платежа.\n2.3. API ключ предоставляет доступ к моделям: Claude sonnet 4.6, Claude sonnet 4.5, Claude Opus 4.5, Claude Opus 4.6.\n\n3. ПОРЯДОК РАСЧЕТОВ\n3.1. Оплата производится через платежный сервис LAVA.\n3.2. Комиссия платежной системы оплачивается Заказчиком дополнительно.\n3.3. Кредиты не имеют срока действия и могут использоваться в любое время.\n\n4. ОТВЕТСТВЕННОСТЬ СТОРОН\n4.1. Исполнитель не несет ответственности за технические сбои в работе LAVA и API провайдера.\n4.2. Заказчик несет ответственность за сохранность API ключа.\n4.3. Исполнитель не гарантирует бесперебойную работу API сторонних сервисов.\n\n5. РЕКВИЗИТЫ\nИНН: 612204854706\nEmail: arytyn.babayan@mail.ru"},
        "privacy": {"title": "🔒 ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ", "text": "1. ОБЩИЕ ПОЛОЖЕНИЯ\n1.1. Политика определяет порядок обработки и защиты персональных данных пользователей бота по продаже API Claude Code.\n1.2. Разработана в соответствии с ФЗ-152 «О персональных данных».\n\n2. КАКИЕ ДАННЫЕ МЫ СОБИРАЕМ\n- ID пользователя в Telegram\n- Имя и фамилия\n- Username (@ник)\n- Данные о транзакциях (сумма, время, статус, ID заказа)\n- Выданные API ключи\n\n3. ЦЕЛИ ОБРАБОТКИ ДАННЫХ\n- Обработка платежей через LAVA\n- Идентификация пользователя\n- Выдача API ключей\n- Техническая поддержка\n\n4. ПЕРЕДАЧА ДАННЫХ\nМы не передаем данные третьим лицам, кроме случаев:\n- Обработки платежей через LAVA\n- Предоставления API доступа провайдеру\n\n5. ЗАЩИТА ДАННЫХ\nAPI ключи и персональные данные хранятся в зашифрованном виде.\n\n6. КОНТАКТЫ\nПо вопросам: arytyn.babayan@mail.ru"},
        "contacts": {"title": "📞 КОНТАКТЫ", "text": "📧 Email: arytyn.babayan@mail.ru\n📱 Телефон: +7 (993) 555-51-61\n⏰ Режим работы: Пн-Пт 10:00-19:00 (МСК)\n\n🤖 Техподдержка: @claudxeseller\n\n📄 Реквизиты:\nИНН: 612204854706"},
        "refund": {"title": "↩️ ПОЛИТИКА ВОЗВРАТА", "text": "1. ОСНОВАНИЯ ДЛЯ ВОЗВРАТА\n- Технический сбой при проведении платежа\n- Двойное списание средств\n- API ключ не был выдан после оплаты\n- Техническая невозможность использования API\n\n2. ПОРЯДОК ВОЗВРАТА\n2.1. Отправьте заявку на email: arytyn.babayan@mail.ru\n2.2. Укажите: ID в Telegram, сумму, дату, причину возврата\n2.3. Срок рассмотрения: до 10 рабочих дней\n2.4. Срок возврата: до 30 дней\n2.5. Возврат денежных средств осуществляется на реквизиты пользователя, с которых производилась оплата.\n\n3. СЛУЧАИ ОТКАЗА В ВОЗВРАТЕ\n- API ключ был выдан и активирован\n- Кредиты были частично или полностью использованы\n- Прошло более 90 дней с момента оплаты\n\n📧 Email для вопросов: arytyn.babayan@mail.ru"}
    }
    doc = docs.get(doc_type)
    if doc:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="docs_back")]
        ])
        await callback.message.answer(
            f"<b>{doc['title']}</b>\n\n"
            f"<code>{doc['text']}</code>",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    await callback.answer()


# ==================== ЗАПУСК ====================

async def start_bot():
    logger.info("Starting Telegram bot polling...")
    await dp.start_polling(bot)


async def start_web():
    port = int(os.getenv('PORT', '8080'))
    app = web.Application()
    app.router.add_post('/lava/webhook', handle_lava_webhook)
    app.router.add_get('/lava/health', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Webhook server started on port {port}")


async def main():
    await asyncio.gather(
        start_bot(),
        start_web()
    )


if __name__ == "__main__":
    asyncio.run(main())
