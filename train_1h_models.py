"""
Скрипт для обучения ML моделей на 1-часовом таймфрейме для MOEX бота.

Использование:
    # Обучение всех моделей для всех активных инструментов на 1h без MTF
    python train_1h_models.py --no-mtf
    
    # Обучение всех моделей для всех активных инструментов на 1h с MTF (4h)
    python train_1h_models.py --mtf
    
    # Обучение для конкретного инструмента
    python train_1h_models.py --ticker VBH6 --no-mtf
"""
import subprocess
import sys
import os
from pathlib import Path

# Импортируем настройки для получения активных инструментов
sys.path.insert(0, str(Path(__file__).parent))
from bot.config import load_settings
from bot.state import BotState


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Обучение ML моделей на 1-часовом таймфрейме для MOEX бота",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Обучение всех моделей на 1h без MTF
  python train_1h_models.py --no-mtf
  
  # Обучение всех моделей на 1h с MTF
  python train_1h_models.py --mtf
  
  # Обучение для конкретного инструмента
  python train_1h_models.py --ticker VBH6 --no-mtf
        """
    )
    parser.add_argument("--ticker", type=str, help="Тикер инструмента (если не указано, обучаются все активные)")
    parser.add_argument("--mtf", action="store_true", help="Использовать MTF фичи (4h)")
    parser.add_argument("--no-mtf", action="store_true", help="НЕ использовать MTF фичи (только 1h)")
    parser.add_argument("--skip-update", action="store_true", help="Пропустить обновление исторических данных")
    parser.add_argument("--update-days", type=int, default=180, help="Количество дней исторических данных для обновления")
    
    args = parser.parse_args()
    
    # Загружаем настройки и состояние
    settings = load_settings()
    state = BotState()
    
    # Определяем инструменты для обучения
    if args.ticker:
        tickers = [args.ticker.upper()]
    else:
        # Используем активные инструменты из state
        tickers = list(state.active_instruments) if state.active_instruments else list(settings.instruments)
        if not tickers:
            print("❌ Нет активных инструментов для обучения!")
            print("   Добавьте инструменты через Telegram бота или .env файл")
            return
    
    # Формируем команду
    python_exe = sys.executable
    cmd = [python_exe, "train_models.py", "--interval", "1hour"]
    
    if args.mtf:
        cmd.append("--mtf")
    elif args.no_mtf:
        cmd.append("--no-mtf")
    
    if args.skip_update:
        cmd.append("--skip-update")
    
    if args.update_days:
        cmd.append("--update-days")
        cmd.append(str(args.update_days))
    
    print("=" * 80)
    print("🚀 ОБУЧЕНИЕ МОДЕЛЕЙ НА 1-ЧАСОВОМ ТАЙМФРЕЙМЕ")
    print("=" * 80)
    print(f"📊 Инструменты: {', '.join(tickers)}")
    print(f"⏰ Таймфрейм: 1h")
    print(f"🔧 MTF: {'Включено (4h)' if args.mtf else 'Выключено' if args.no_mtf else 'По умолчанию'}")
    print("=" * 80)
    
    # Обучаем для каждого инструмента
    for ticker in tickers:
        print(f"\n📈 Обучение моделей для {ticker}...")
        ticker_cmd = cmd + ["--ticker", ticker]
        
        try:
            env = os.environ.copy()
            result = subprocess.run(
                ticker_cmd, 
                check=True, 
                cwd=Path(__file__).parent,
                env=env,
                encoding='utf-8',
                errors='replace'
            )
            print(f"✅ Модели для {ticker} успешно обучены")
        except subprocess.CalledProcessError as e:
            print(f"❌ Ошибка при обучении моделей для {ticker}: {e}")
            if hasattr(e, 'stdout') and e.stdout:
                print(f"   Вывод: {e.stdout[-500:]}")
            if hasattr(e, 'stderr') and e.stderr:
                print(f"   Ошибки: {e.stderr[-500:]}")
            continue
        except KeyboardInterrupt:
            print(f"\n⚠️ Прервано пользователем")
            sys.exit(1)
    
    print("\n" + "=" * 80)
    print("✅ ОБУЧЕНИЕ ЗАВЕРШЕНО")
    print("=" * 80)
    print("\n💡 Следующие шаги:")
    print("   1. Протестировать модели:")
    print("      python compare_ml_models.py --tickers " + ",".join(tickers))
    print("   2. Протестировать MTF комбинации:")
    print("      python test_mtf_combinations.py --tickers " + ",".join(tickers))
    print("   3. Выбрать лучшие модели для продакшена")


if __name__ == "__main__":
    main()
