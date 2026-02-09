# Инструкция по деплою на сервер

## Подготовка сервера

### 1. Установка зависимостей

```bash
# Обновляем систему
sudo apt update && sudo apt upgrade -y

# Устанавливаем Python и Git
sudo apt install -y python3 python3-pip python3-venv git

# Устанавливаем systemd (обычно уже установлен)
sudo systemctl --version
```

### 2. Клонирование репозитория

```bash
# Создаем директорию для проекта
sudo mkdir -p /opt/moex_bot2
sudo chown $USER:$USER /opt/moex_bot2

# Клонируем репозиторий
cd /opt
git clone https://github.com/YOUR_USERNAME/moex_bot2.git
# или если репозиторий приватный:
# git clone git@github.com:YOUR_USERNAME/moex_bot2.git
```

### 3. Настройка окружения

```bash
cd /opt/moex_bot2

# Создаем виртуальное окружение
python3 -m venv venv
source venv/bin/activate

# Устанавливаем зависимости
pip install --upgrade pip
pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
pip install -r requirements.txt

# Создаем необходимые директории
mkdir -p logs ml_data ml_models
```

### 4. Настройка .env файла

```bash
# Создаем .env файл с вашими настройками
nano .env
```

Содержимое `.env`:
```env
# Tinkoff Invest API
TINKOFF_TOKEN=your_token_here
TINKOFF_SANDBOX=true

# Telegram Bot
TELEGRAM_TOKEN=your_telegram_bot_token
ALLOWED_USER_ID=your_telegram_user_id

# Trading settings
TRADING_INSTRUMENTS=VBH6,SRH6,GLDRUBF
TIMEFRAME=15min

# ML Strategy
ML_CONFIDENCE_THRESHOLD=0.35
ML_MIN_SIGNAL_STRENGTH=слабое
```

### 5. Настройка systemd service

```bash
# Копируем service файл
sudo cp deploy/moex_bot.service /etc/systemd/system/

# Редактируем файл, заменив YOUR_USER и YOUR_GROUP на ваши значения
sudo nano /etc/systemd/system/moex_bot.service

# Обновляем systemd
sudo systemctl daemon-reload

# Включаем автозапуск
sudo systemctl enable moex_bot

# Запускаем бота
sudo systemctl start moex_bot

# Проверяем статус
sudo systemctl status moex_bot
```

### 6. Просмотр логов

```bash
# Логи systemd
sudo journalctl -u moex_bot -f

# Логи приложения
tail -f /opt/moex_bot2/logs/bot.log
tail -f /opt/moex_bot2/logs/errors.log
```

## Настройка GitHub Actions

### 1. Создание SSH ключа для деплоя

На сервере:
```bash
# Генерируем SSH ключ (если еще нет)
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_actions_deploy

# Добавляем публичный ключ в authorized_keys
cat ~/.ssh/github_actions_deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 2. Настройка GitHub Secrets

В репозитории GitHub перейдите в:
**Settings → Secrets and variables → Actions**

Добавьте следующие secrets:

- `SSH_PRIVATE_KEY` - приватный ключ для SSH (содержимое `~/.ssh/github_actions_deploy` на сервере)
- `SERVER_USER` - пользователь для SSH подключения (например, `ubuntu` или `root`)
- `SERVER_HOST` - IP адрес или домен сервера
- `SERVER_PORT` - порт SSH (обычно `22`, можно не указывать)
- `DEPLOY_PATH` - путь к проекту на сервере (по умолчанию `/opt/moex_bot2`)

### 3. Получение приватного ключа

На сервере:
```bash
cat ~/.ssh/github_actions_deploy
```

Скопируйте вывод (включая `-----BEGIN OPENSSH PRIVATE KEY-----` и `-----END OPENSSH PRIVATE KEY-----`) и вставьте в GitHub Secret `SSH_PRIVATE_KEY`.

## Ручной деплой

Если нужно задеплоить вручную:

```bash
# Делаем скрипт исполняемым
chmod +x deploy.sh

# Запускаем деплой
./deploy.sh user@example.com /opt/moex_bot2
```

Или вручную на сервере:

```bash
cd /opt/moex_bot2
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart moex_bot
```

## Управление ботом

```bash
# Запуск
sudo systemctl start moex_bot

# Остановка
sudo systemctl stop moex_bot

# Перезапуск
sudo systemctl restart moex_bot

# Статус
sudo systemctl status moex_bot

# Просмотр логов
sudo journalctl -u moex_bot -f

# Отключить автозапуск
sudo systemctl disable moex_bot

# Включить автозапуск
sudo systemctl enable moex_bot
```

## Устранение проблем

### Бот не запускается

1. Проверьте логи:
```bash
sudo journalctl -u moex_bot -n 50
```

2. Проверьте .env файл:
```bash
cd /opt/moex_bot2
cat .env
```

3. Проверьте права доступа:
```bash
ls -la /opt/moex_bot2
```

### Проблемы с зависимостями

```bash
cd /opt/moex_bot2
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt --force-reinstall
```

### Проблемы с SSH в GitHub Actions

1. Проверьте, что SSH ключ правильно добавлен в secrets
2. Убедитесь, что публичный ключ добавлен в `authorized_keys` на сервере
3. Проверьте, что пользователь имеет права на выполнение команд в директории проекта
