"""
Скрипт для обучения всех моделей (15m и 1h) по активным символам.

Использование:
    # Обучение всех моделей для всех активных инструментов
    python train_all_models.py
    
    # Обучение только 15m моделей
    python train_all_models.py --only-15m
    
    # Обучение только 1h моделей
    python train_all_models.py --only-1h
"""
import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bot.config import load_settings
from bot.state import BotState


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Обучение всех моделей (15m и 1h) по активным символам",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Обучение всех моделей для всех активных инструментов
  python train_all_models.py
  
  # Обучение только 15m моделей
  python train_all_models.py --only-15m
  
  # Обучение только 1h моделей
  python train_all_models.py --only-1h
  
  # Обучение с MTF фичами
  python train_all_models.py --mtf
  
  # Обучение без MTF фичей
  python train_all_models.py --no-mtf
        """
    )
    parser.add_argument("--only-15m", action="store_true", help="Обучать только 15m модели")
    parser.add_argument("--only-1h", action="store_true", help="Обучать только 1h модели")
    parser.add_argument("--mtf", action="store_true", help="Использовать MTF фичи")
    parser.add_argument("--no-mtf", action="store_true", help="НЕ использовать MTF фичи")
    parser.add_argument("--skip-update", action="store_true", help="Пропустить обновление исторических данных")
    parser.add_argument("--update-days", type=int, default=180, help="Количество дней исторических данных для обновления")
    
    args = parser.parse_args()
    
    # Загружаем настройки и состояние
    settings = load_settings()
    state = BotState()
    
    # Определяем инструменты для обучения
    tickers = list(state.active_instruments) if state.active_instruments else list(settings.instruments)
    if not tickers:
        print("❌ Нет активных инструментов для обучения!")
        print("   Добавьте инструменты через Telegram бота или .env файл")
        return
    
    # Определяем, какие модели обучать
    train_15m = not args.only_1h
    train_1h = not args.only_15m
    
    if args.only_15m and args.only_1h:
        print("❌ Нельзя указать одновременно --only-15m и --only-1h")
        return
    
    python_exe = sys.executable
    env = os.environ.copy()
    
    print("=" * 80)
    print("🚀 ОБУЧЕНИЕ ВСЕХ МОДЕЛЕЙ ПО АКТИВНЫМ СИМВОЛАМ")
    print("=" * 80)
    print(f"📊 Инструменты: {', '.join(tickers)}")
    print(f"⏰ Модели: {'15m' if train_15m else ''}{' + ' if train_15m and train_1h else ''}{'1h' if train_1h else ''}")
    print(f"🔧 MTF: {'Включено' if args.mtf else 'Выключено' if args.no_mtf else 'По умолчанию'}")
    print("=" * 80)
    print()
    
    # Обучаем 15m модели
    if train_15m:
        print("=" * 80)
        print("📊 ОБУЧЕНИЕ 15M МОДЕЛЕЙ")
        print("=" * 80)
        
        for ticker in tickers:
            print(f"\n📈 Обучение 15m моделей для {ticker}...")
            
            cmd = [python_exe, "train_models.py", "--ticker", ticker, "--interval", "15min"]
            
            if args.mtf:
                cmd.append("--mtf")
            elif args.no_mtf:
                cmd.append("--no-mtf")
            
            if args.skip_update:
                cmd.append("--skip-update")
            
            if args.update_days:
                cmd.append("--update-days")
                cmd.append(str(args.update_days))
            
            try:
                result = subprocess.run(
                    cmd,
                    check=True,
                    cwd=Path(__file__).parent,
                    env=env,
                    encoding='utf-8',
                    errors='replace'
                )
                print(f"✅ 15m модели для {ticker} успешно обучены")
            except subprocess.CalledProcessError as e:
                print(f"❌ Ошибка при обучении 15m моделей для {ticker}: {e}")
                continue
            except KeyboardInterrupt:
                print(f"\n⚠️ Прервано пользователем")
                sys.exit(1)
        
        print("\n✅ Обучение 15m моделей завершено\n")
    
    # Обучаем 1h модели
    if train_1h:
        print("=" * 80)
        print("📊 ОБУЧЕНИЕ 1H МОДЕЛЕЙ")
        print("=" * 80)
        
        for ticker in tickers:
            print(f"\n📈 Обучение 1h моделей для {ticker}...")
            
            cmd = [python_exe, "train_1h_models.py", "--ticker", ticker]
            
            if args.mtf:
                cmd.append("--mtf")
            elif args.no_mtf:
                cmd.append("--no-mtf")
            
            if args.skip_update:
                cmd.append("--skip-update")
            
            if args.update_days:
                cmd.append("--update-days")
                cmd.append(str(args.update_days))
            
            try:
                result = subprocess.run(
                    cmd,
                    check=True,
                    cwd=Path(__file__).parent,
                    env=env,
                    encoding='utf-8',
                    errors='replace'
                )
                print(f"✅ 1h модели для {ticker} успешно обучены")
            except subprocess.CalledProcessError as e:
                print(f"❌ Ошибка при обучении 1h моделей для {ticker}: {e}")
                continue
            except KeyboardInterrupt:
                print(f"\n⚠️ Прервано пользователем")
                sys.exit(1)
        
        print("\n✅ Обучение 1h моделей завершено\n")
    
    print("=" * 80)
    print("✅ ОБУЧЕНИЕ ВСЕХ МОДЕЛЕЙ ЗАВЕРШЕНО")
    print("=" * 80)
    print("\n💡 Следующие шаги:")
    print("   1. Сравнить модели:")
    print(f"      python compare_ml_models.py --tickers {','.join(tickers)}")
    print("   2. Протестировать MTF комбинации:")
    print(f"      python test_mtf_combinations.py --tickers {','.join(tickers)}")
    print("   3. Выбрать лучшие модели для продакшена")


if __name__ == "__main__":
    main()
