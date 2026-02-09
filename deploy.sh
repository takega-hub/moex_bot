#!/bin/bash
# Скрипт для ручного деплоя на сервер
# Использование: ./deploy.sh [user@host] [path]

set -e

# Параметры по умолчанию
SERVER="${1:-user@example.com}"
DEPLOY_PATH="${2:-/opt/moex_bot2}"

echo "🚀 Начинаем деплой на $SERVER:$DEPLOY_PATH"

# Проверяем подключение
echo "Проверяем подключение к серверу..."
ssh $SERVER "echo '✅ Подключение установлено'"

# Выполняем деплой
ssh $SERVER << ENDSSH
  set -e
  
  echo "📦 Переходим в директорию проекта..."
  cd $DEPLOY_PATH || { echo "❌ Директория $DEPLOY_PATH не существует!"; exit 1; }
  
  echo "🛑 Останавливаем бота..."
  sudo systemctl stop moex_bot || echo "⚠️ Бот не был запущен"
  
  echo "💾 Сохраняем состояние..."
  if [ -f runtime_state.json ]; then
    cp runtime_state.json runtime_state.json.backup
    echo "✅ Состояние сохранено"
  fi
  
  echo "🔄 Обновляем код из GitHub..."
  git fetch origin
  CURRENT_BRANCH=\$(git branch --show-current)
  git reset --hard origin/\$CURRENT_BRANCH || git reset --hard origin/main || git reset --hard origin/master
  
  echo "🐍 Настраиваем виртуальное окружение..."
  if [ ! -d "venv" ]; then
    echo "Создаем новое виртуальное окружение..."
    python3 -m venv venv
  fi
  
  source venv/bin/activate
  pip install --upgrade pip
  
  echo "📚 Устанавливаем зависимости..."
  pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
  pip install -r requirements.txt
  
  echo "📁 Создаем необходимые директории..."
  mkdir -p logs ml_data ml_models
  chmod 755 logs
  
  echo "🔄 Восстанавливаем состояние..."
  if [ -f runtime_state.json.backup ]; then
    mv runtime_state.json.backup runtime_state.json
  fi
  
  echo "▶️ Запускаем бота..."
  sudo systemctl start moex_bot
  
  echo "⏳ Ждем запуска..."
  sleep 3
  
  echo "✅ Проверяем статус..."
  sudo systemctl status moex_bot --no-pager || true
  
  echo "🎉 Деплой завершен!"
ENDSSH

echo "✅ Деплой успешно выполнен!"
