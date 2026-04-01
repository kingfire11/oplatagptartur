FROM python:3.11-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов
COPY . .

# Создаём директорию для данных
RUN mkdir -p /app/data && chmod 777 /app/data

ENV DATA_DIR=/app/data

# Запускаем бота + webhook сервер
CMD ["python", "main.py"]
