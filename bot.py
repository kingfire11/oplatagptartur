import os
import hashlib
import time
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F
from dotenv import load_dotenv

load_dotenv()

# Настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
LAVA_SHOP_ID = os.getenv('LAVA_SHOP_ID')
LAVA_SECRET_KEY = os.getenv('LAVA_SECRET_KEY')
LAVA_API_URL = "https://business.lava.ru/api/v1/bill/create"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def get_main_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с основными кнопками"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Публичная оферта", callback_data="docs_offer")],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data="docs_privacy")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="docs_contacts")],
        [InlineKeyboardButton(text="↩️ Политика возврата", callback_data="docs_refund")],
    ])
    return keyboard


def generate_lava_link(amount: float, description: str = "Оплата заказа") -> str:
    """Генерирует ссылку на оплату Lava"""
    order_id = f"order_{int(time.time())}"

    # Параметры для подписи
    params = {
        "shopId": LAVA_SHOP_ID,
        "orderId": order_id,
        "amount": amount,
        "description": description,
    }

    # Создаем подпись (SHA256 от shopId:orderId:amount:secretKey)
    sign_string = f"{LAVA_SHOP_ID}:{order_id}:{amount}:{LAVA_SECRET_KEY}"
    signature = hashlib.sha256(sign_string.encode()).hexdigest()

    # Формируем ссылку
    link = f"{LAVA_API_URL}?shopId={LAVA_SHOP_ID}&orderId={order_id}&amount={amount}&description={description}&signature={signature}"

    return link


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для оплаты.\n\n"
        "Отправьте мне сумму для оплаты (например: 1000 или 500.50), "
        "и я сгенерирую ссылку на оплату.",
        reply_markup=get_main_keyboard()
    )


@dp.callback_query(F.data == "docs_back")
async def handle_back(callback: types.CallbackQuery):
    """Кнопка назад - показывает главное меню"""
    await callback.message.answer(
        "👋 Привет! Я бот для оплаты.\n\n"
        "Отправьте мне сумму для оплаты (например: 1000 или 500.50), "
        "и я сгенерирую ссылку на оплату.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("docs_"))
async def handle_docs(callback: types.CallbackQuery):
    """Обработчик кнопок с документами - показывает текст внутри бота"""
    doc_type = callback.data.split("_")[1]

    docs = {
        "offer": {
            "title": "📄 ПУБЛИЧНАЯ ОФЕРТА",
            "text":
                "1. ОБЩИЕ ПОЛОЖЕНИЯ\n"
                "1.1. Настоящая публичная оферта является официальным предложением исполнителя заключить договор возмездного оказания услуг.\n"
                "1.2. В соответствии с п. 2 ст. 437 ГК РФ, в случае принятия условий оферты и оплаты услуг, физическое лицо становится Заказчиком.\n"
                "1.3. Акцептом оферты является факт оплаты услуг Заказчиком.\n\n"
                "2. ПРЕДМЕТ ОФЕРТЫ\n"
                "2.1. Исполнитель обязуется оказать услуги по обработке платежей через платежный сервис LAVA.\n"
                "2.2. Услуги считаются оказанными с момента успешного проведения платежа.\n\n"
                "3. ПОРЯДОК РАСЧЕТОВ\n"
                "3.1. Оплата производится через платежный сервис LAVA.\n"
                "3.2. Комиссия платежной системы оплачивается Заказчиком дополнительно.\n\n"
                "4. ОТВЕТСТВЕННОСТЬ СТОРОН\n"
                "4.1. Исполнитель не несет ответственности за технические сбои в работе LAVA.\n"
                "4.2. Заказчик несет ответственность за достоверность платежных данных.\n\n"
                "5. РЕКВИЗИТЫ\n"
                "ИНН: 612204854706\n"
                "Email: arytyn.babayan@mail.ru"
        },
        "privacy": {
            "title": "🔒 ПОЛИТИКА КОНФИДЕНЦИАЛЬНОСТИ",
            "text":
                "1. ОБЩИЕ ПОЛОЖЕНИЯ\n"
                "1.1. Политика определяет порядок обработки и защиты персональных данных.\n"
                "1.2. Разработана в соответствии с ФЗ-152 «О персональных данных».\n\n"
                "2. КАКИЕ ДАННЫЕ МЫ СОБИРАЕМ\n"
                "- ID пользователя в Telegram\n"
                "- Имя и фамилия\n"
                "- Данные о транзакциях (сумма, время, статус)\n\n"
                "3. ЦЕЛИ ОБРАБОТКИ ДАННЫХ\n"
                "- Обработка платежей через LAVA\n"
                "- Идентификация пользователя\n"
                "- Предоставление услуг\n\n"
                "4. ПЕРЕДАЧА ДАННЫХ\n"
                "Мы не передаем данные третьим лицам, кроме случаев обработки платежей через LAVA.\n\n"
                "5. ЗАЩИТА ДАННЫХ\n"
                "Данные хранятся в зашифрованном виде.\n\n"
                "6. КОНТАКТЫ\n"
                "По вопросам: arytyn.babayan@mail.ru"
        },
        "contacts": {
            "title": "📞 КОНТАКТЫ",
            "text":
                "📧 Email: arytyn.babayan@mail.ru\n"
                "📱 Телефон: +7 (993) 555-51-61\n"
                "⏰ Режим работы: Пн-Пт 10:00-19:00 (МСК)\n\n"
                "📄 Реквизиты:\n"
                "ИНН: 612204854706"
        },
        "refund": {
            "title": "↩️ ПОЛИТИКА ВОЗВРАТА",
            "text":
                "1. ОСНОВАНИЯ ДЛЯ ВОЗВРАТА\n"
                "- Технический сбой при проведении платежа\n"
                "- Двойное списание средств\n"
                "- Ошибочно введенная сумма\n"
                "- Отказ от услуги до момента оказания\n\n"
                "2. ПОРЯДОК ВОЗВРАТА\n"
                "2.1. Отправьте заявку на email: arytyn.babayan@mail.ru\n"
                "2.2. Укажите: ID в Telegram, сумму, дату, причину\n"
                "2.3. Срок рассмотрения: до 10 рабочих дней\n"
                "2.4. Срок возврата: до 30 дней\n\n"
                "3. СЛУЧАИ ОТКАЗА\n"
                "- Услуга оказана надлежащим образом\n"
                "- Прошло более 90 дней с оплаты\n\n"
                "📧 Email для вопросов: arytyn.babayan@mail.ru"
        }
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


@dp.message(F.text)
async def handle_amount(message: types.Message):
    try:
        amount = float(message.text.replace(',', '.'))

        if amount <= 0:
            await message.answer("❌ Сумма должна быть больше 0")
            return

        if amount > 1000000:
            await message.answer("❌ Сумма слишком большая (макс. 1 000 000)")
            return

        # Генерируем ссылку
        payment_link = generate_lava_link(amount)

        await message.answer(
            f"💳 Сумма к оплате: <b>{amount:.2f} ₽</b>\n\n"
            f"Нажмите на ссылку для оплаты:\n"
            f"<a href='{payment_link}'>💰 Оплатить</a>",
            parse_mode="HTML"
        )

    except ValueError:
        await message.answer(
            "❌ Неверный формат суммы.\n"
            "Отправьте число (например: 1000 или 500.50)"
        )


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
