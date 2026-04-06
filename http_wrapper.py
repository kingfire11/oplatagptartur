import os
import json
import hashlib
import hmac
from aiohttp import web
import aiohttp

# Настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
LAVA_SHOP_ID = os.getenv('LAVA_SHOP_ID')
LAVA_SECRET_KEY = os.getenv('LAVA_SECRET_KEY')
LAVA_ADDITIONAL_KEY = os.getenv('LAVA_ADDITIONAL_KEY')
ADMIN_ID = int(os.getenv('ADMIN_ID', '6499414636'))

bot_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def verify_lava_signature(body: bytes, signature: str) -> bool:
    """Проверяет подпись webhook от Lava"""
    # Lava подписывает тело запроса через HMAC-SHA256 с Secret Key
    expected_signature = hmac.new(
        LAVA_SECRET_KEY.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


async def handle_lava_webhook(request):
    """Обработчик webhook от Lava"""
    try:
        # Получаем тело запроса
        body = await request.read()

        # Подпись может быть в заголовке Authorization или Signature
        signature = request.headers.get('Authorization', '') or request.headers.get('Signature', '')

        # Убираем префикс "Bearer " если есть
        if signature.startswith('Bearer '):
            signature = signature[7:]

        # Проверяем подпись (опционально, но рекомендуется)
        if signature and not verify_lava_signature(body, signature):
            print(f"Invalid signature: {signature}")
            return web.json_response({'error': 'Invalid signature'}, status=403)

        # Парсим JSON
        data = json.loads(body)

        print(f"Webhook received: {data}")

        order_id = data.get('orderId')
        amount = data.get('sum')
        status = data.get('status')  # 1 = успешно, 0 = ожидает
        shop_id = data.get('shopId')
        type_event = data.get('type')  # 1 = счет, 2 = выплата

        # Проверяем статус оплаты (status=1 означает успешно оплачено)
        if status == 1:
            async with aiohttp.ClientSession() as session:
                await session.post(bot_url, json={
                    'chat_id': ADMIN_ID,
                    'text': (
                        f"✅ <b>Оплата прошла успешно!</b>\n\n"
                        f"📦 Заказ: {order_id}\n"
                        f"💰 Сумма: {amount} ₽\n"
                        f"🏪 Shop ID: {shop_id}"
                    ),
                    'parse_mode': 'HTML'
                })
            print(f"Payment success: order={order_id}, amount={amount}")
        else:
            print(f"Payment pending: order={order_id}, status={status}")

        return web.json_response({'status': 'ok'})

    except Exception as e:
        print(f"Webhook error: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def handle_health(request):
    """Проверка работоспособности"""
    return web.json_response({'status': 'ok'})


def create_app():
    app = web.Application()
    app.router.add_post('/lava/webhook', handle_lava_webhook)
    app.router.add_get('/lava/health', handle_health)
    return app


if __name__ == '__main__':
    import subprocess
    import threading

    app = create_app()

    def run_bot():
        """Запускает бот как subprocess"""
        try:
            import time
            time.sleep(2)  # Даем серверу время запуститься
            print("Starting bot.py...")
            process = subprocess.Popen(
                ["python", "bot.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            # Логируем вывод бота
            def log_output(pipe, prefix):
                for line in iter(pipe.readline, ""):
                    if line:
                        print(f"[{prefix}] {line.rstrip()}")
            threading.Thread(target=lambda: log_output(process.stdout, "BOT"), daemon=True).start()
            threading.Thread(target=lambda: log_output(process.stderr, "BOT-ERR"), daemon=True).start()
            print("Bot started successfully")
        except Exception as e:
            print(f"Failed to start bot: {e}")

    # Запускаем бот в отдельном потоке
    threading.Thread(target=run_bot, daemon=True).start()

    print("Starting webhook server on port 8080...")
    web.run_app(app, host='0.0.0.0', port=8080)
