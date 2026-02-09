"""Проверка конфигурации .env файла."""
import os
from pathlib import Path
from dotenv import load_dotenv

def check_env():
    """Проверяет наличие и содержимое .env файла."""
    project_root = Path(__file__).parent
    env_path = project_root / ".env"
    
    print("=" * 60)
    print("ПРОВЕРКА .env ФАЙЛА")
    print("=" * 60)
    print(f"\nПуть к .env: {env_path}")
    print(f"Файл существует: {env_path.exists()}")
    
    if env_path.exists():
        print(f"Размер файла: {env_path.stat().st_size} байт")
        
        # Загружаем .env
        result = load_dotenv(dotenv_path=env_path, override=True)
        print(f"Загрузка переменных: {'✅ Успешно' if result else '⚠️ Не удалось загрузить'}")
        
        # Проверяем переменные
        print("\n" + "=" * 60)
        print("ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ")
        print("=" * 60)
        
        # TINKOFF_TOKEN
        tinkoff_token = os.getenv("TINKOFF_TOKEN", "").strip()
        if tinkoff_token:
            print(f"✅ TINKOFF_TOKEN: {'*' * min(20, len(tinkoff_token))}... (длина: {len(tinkoff_token)})")
        else:
            print("❌ TINKOFF_TOKEN: НЕ НАЙДЕН")
            print("   Добавьте в .env: TINKOFF_TOKEN=ваш_токен")
        
        # TINKOFF_SANDBOX
        sandbox = os.getenv("TINKOFF_SANDBOX", "").strip().lower()
        print(f"{'✅' if sandbox else 'ℹ️'} TINKOFF_SANDBOX: {sandbox or 'не установлен (по умолчанию: false)'}")
        
        # TELEGRAM_TOKEN
        telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
        if telegram_token:
            print(f"✅ TELEGRAM_TOKEN: {'*' * min(20, len(telegram_token))}... (длина: {len(telegram_token)})")
            print(f"   Начинается с: {telegram_token[:10]}...")
        else:
            print("❌ TELEGRAM_TOKEN: НЕ НАЙДЕН")
            print("   Добавьте в .env: TELEGRAM_TOKEN=ваш_токен_от_BotFather")
            print("   Получить токен: @BotFather в Telegram -> /newbot")
        
        # ALLOWED_USER_ID
        allowed_user_id = os.getenv("ALLOWED_USER_ID", "").strip()
        if allowed_user_id:
            try:
                user_id = int(allowed_user_id)
                print(f"✅ ALLOWED_USER_ID: {user_id}")
            except ValueError:
                print(f"⚠️ ALLOWED_USER_ID: '{allowed_user_id}' (неверный формат, должен быть число)")
        else:
            print("⚠️ ALLOWED_USER_ID: НЕ УСТАНОВЛЕН")
            print("   Добавьте в .env: ALLOWED_USER_ID=ваш_telegram_user_id")
            print("   Узнать ID: @userinfobot в Telegram")
        
        # TRADING_INSTRUMENTS
        instruments = os.getenv("TRADING_INSTRUMENTS", "").strip()
        if instruments:
            instruments_list = [s.strip() for s in instruments.split(",") if s.strip()]
            print(f"✅ TRADING_INSTRUMENTS: {', '.join(instruments_list)} ({len(instruments_list)} инструментов)")
        else:
            print("⚠️ TRADING_INSTRUMENTS: НЕ УСТАНОВЛЕН")
            print("   Добавьте в .env: TRADING_INSTRUMENTS=VBH6,SRH6,GLDRUBF")
        
        # Показываем первые строки .env (без секретов)
        print("\n" + "=" * 60)
        print("СОДЕРЖИМОЕ .env (первые 20 строк, скрыты секреты)")
        print("=" * 60)
        try:
            with open(env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()[:20]
                for i, line in enumerate(lines, 1):
                    line = line.rstrip()
                    # Скрываем значения токенов
                    if 'TOKEN' in line or 'PASSWORD' in line or 'SECRET' in line:
                        if '=' in line:
                            key, _ = line.split('=', 1)
                            print(f"{i:3d}: {key}=***СКРЫТО***")
                        else:
                            print(f"{i:3d}: {line}")
                    else:
                        print(f"{i:3d}: {line}")
        except Exception as e:
            print(f"Ошибка чтения файла: {e}")
    else:
        print("\n❌ Файл .env не найден!")
        print("\nСоздайте файл .env в корне проекта со следующим содержимым:")
        print("\n" + "-" * 60)
        print("# Tinkoff Invest API")
        print("TINKOFF_TOKEN=ваш_токен_тинькофф")
        print("TINKOFF_SANDBOX=true")
        print("")
        print("# Telegram Bot")
        print("TELEGRAM_TOKEN=ваш_токен_от_BotFather")
        print("ALLOWED_USER_ID=ваш_telegram_user_id")
        print("")
        print("# Trading Instruments")
        print("TRADING_INSTRUMENTS=VBH6,SRH6,GLDRUBF")
        print("-" * 60)
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    check_env()
