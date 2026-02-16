"""
Объединенный скрипт для полного цикла обучения и тестирования MTF моделей.

Выполняет:
1. Обучение 15m моделей (с MTF фичами)
2. Обучение 1h моделей (с/без MTF фичей)
3. Тестирование отдельных моделей
4. Тестирование MTF комбинаций
5. Выбор лучших комбинаций по каждому инструменту

Использование:
    # Полный цикл для всех активных инструментов
    python train_and_test_all.py
    
    # Пропустить обучение, только тестирование
    python train_and_test_all.py --skip-training
    
    # Только обучение, без тестирования
    python train_and_test_all.py --skip-testing
    
    # Кастомные параметры
    python train_and_test_all.py --mtf-1h --days 60 --conf-1h 0.60
"""
import argparse
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from bot.config import load_settings
from bot.state import BotState


def safe_print(*args, **kwargs):
    """Безопасный print."""
    try:
        print(*args, **kwargs)
        sys.stdout.flush()
    except (UnicodeEncodeError, IOError):
        text = ' '.join(str(arg) for arg in args)
        print(text, **kwargs)


def train_models_15m(tickers: List[str], use_mtf: bool = True, skip_update: bool = False, update_days: int = 180):
    """Обучает 15m модели для всех тикеров."""
    safe_print("\n" + "=" * 80)
    safe_print("📊 ОБУЧЕНИЕ 15M МОДЕЛЕЙ")
    safe_print("=" * 80)
    
    python_exe = sys.executable
    env = os.environ.copy()
    
    for ticker in tickers:
        safe_print(f"\n📈 Обучение 15m моделей для {ticker}...")
        
        cmd = [python_exe, "train_models.py", "--ticker", ticker, "--interval", "15min"]
        
        if use_mtf:
            cmd.append("--mtf")
        else:
            cmd.append("--no-mtf")
        
        if skip_update:
            cmd.append("--skip-update")
        
        if update_days:
            cmd.append("--update-days")
            cmd.append(str(update_days))
        
        try:
            result = subprocess.run(
                cmd,
                check=True,
                cwd=Path(__file__).parent,
                env=env,
                encoding='utf-8',
                errors='replace'
            )
            safe_print(f"✅ 15m модели для {ticker} успешно обучены")
        except subprocess.CalledProcessError as e:
            safe_print(f"❌ Ошибка при обучении 15m моделей для {ticker}: {e}")
            continue
        except KeyboardInterrupt:
            safe_print(f"\n⚠️ Прервано пользователем")
            sys.exit(1)
    
    safe_print("\n✅ Обучение 15m моделей завершено\n")


def train_models_1h(tickers: List[str], use_mtf: bool = False, skip_update: bool = False, update_days: int = 180):
    """Обучает 1h модели для всех тикеров."""
    safe_print("\n" + "=" * 80)
    safe_print("📊 ОБУЧЕНИЕ 1H МОДЕЛЕЙ")
    safe_print("=" * 80)
    
    python_exe = sys.executable
    env = os.environ.copy()
    
    for ticker in tickers:
        safe_print(f"\n📈 Обучение 1h моделей для {ticker}...")
        
        cmd = [python_exe, "train_1h_models.py", "--ticker", ticker]
        
        if use_mtf:
            cmd.append("--mtf")
        else:
            cmd.append("--no-mtf")
        
        if skip_update:
            cmd.append("--skip-update")
        
        if update_days:
            cmd.append("--update-days")
            cmd.append(str(update_days))
        
        try:
            result = subprocess.run(
                cmd,
                check=True,
                cwd=Path(__file__).parent,
                env=env,
                encoding='utf-8',
                errors='replace'
            )
            safe_print(f"✅ 1h модели для {ticker} успешно обучены")
        except subprocess.CalledProcessError as e:
            safe_print(f"❌ Ошибка при обучении 1h моделей для {ticker}: {e}")
            continue
        except KeyboardInterrupt:
            safe_print(f"\n⚠️ Прервано пользователем")
            sys.exit(1)
    
    safe_print("\n✅ Обучение 1h моделей завершено\n")


def test_individual_models(tickers: List[str], days: int = 30, workers: int = 4):
    """Тестирует отдельные модели через compare_ml_models.py."""
    safe_print("\n" + "=" * 80)
    safe_print("🧪 ТЕСТИРОВАНИЕ ОТДЕЛЬНЫХ МОДЕЛЕЙ")
    safe_print("=" * 80)
    
    python_exe = sys.executable
    env = os.environ.copy()
    
    tickers_str = ",".join(tickers)
    
    cmd = [
        python_exe, "compare_ml_models.py",
        "--tickers", tickers_str,
        "--days", str(days),
        "--workers", str(workers)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            check=True,
            cwd=Path(__file__).parent,
            env=env,
            encoding='utf-8',
            errors='replace'
        )
        safe_print("\n✅ Тестирование отдельных моделей завершено\n")
    except subprocess.CalledProcessError as e:
        safe_print(f"❌ Ошибка при тестировании отдельных моделей: {e}")
        return False
    except KeyboardInterrupt:
        safe_print(f"\n⚠️ Прервано пользователем")
        sys.exit(1)
    
    return True


def test_mtf_combinations(
    tickers: List[str],
    days: int = 30,
    balance: float = 10000.0,
    risk: float = 0.02,
    leverage: int = 1,
    conf_1h: float = 0.50,
    conf_15m: float = 0.35,
    alignment_mode: str = "strict",
    require_alignment: bool = True
):
    """Тестирует MTF комбинации через test_mtf_combinations.py."""
    safe_print("\n" + "=" * 80)
    safe_print("🧪 ТЕСТИРОВАНИЕ MTF КОМБИНАЦИЙ")
    safe_print("=" * 80)
    
    python_exe = sys.executable
    env = os.environ.copy()
    
    tickers_str = ",".join(tickers)
    
    cmd = [
        python_exe, "test_mtf_combinations.py",
        "--tickers", tickers_str,
        "--days", str(days),
        "--balance", str(balance),
        "--risk", str(risk),
        "--leverage", str(leverage),
        "--conf-1h", str(conf_1h),
        "--conf-15m", str(conf_15m),
        "--alignment-mode", alignment_mode,
    ]
    
    if not require_alignment:
        cmd.append("--no-require-alignment")
    
    try:
        result = subprocess.run(
            cmd,
            check=True,
            cwd=Path(__file__).parent,
            env=env,
            encoding='utf-8',
            errors='replace'
        )
        safe_print("\n✅ Тестирование MTF комбинаций завершено\n")
    except subprocess.CalledProcessError as e:
        safe_print(f"❌ Ошибка при тестировании MTF комбинаций: {e}")
        return False
    except KeyboardInterrupt:
        safe_print(f"\n⚠️ Прервано пользователем")
        sys.exit(1)
    
    return True


def find_best_combinations(tickers: List[str]) -> Dict[str, Dict]:
    """Находит лучшие MTF комбинации для каждого тикера из CSV файлов."""
    safe_print("\n" + "=" * 80)
    safe_print("🏆 ВЫБОР ЛУЧШИХ КОМБИНАЦИЙ")
    safe_print("=" * 80)
    
    best_combinations = {}
    
    # Ищем CSV файлы с результатами MTF комбинаций
    csv_files = sorted(Path(".").glob("mtf_combinations_*.csv"), reverse=True)
    
    if not csv_files:
        safe_print("⚠️ Не найдено CSV файлов с результатами MTF комбинаций")
        return best_combinations
    
    # Берем последний файл (самый свежий)
    latest_file = csv_files[0]
    safe_print(f"📄 Используем файл: {latest_file.name}")
    
    try:
        df = pd.read_csv(latest_file)
        
        # Для каждого тикера находим лучшую комбинацию по Sharpe Ratio
        for ticker in tickers:
            ticker_data = df[df['ticker'] == ticker.upper()]
            
            if ticker_data.empty:
                safe_print(f"⚠️ Нет данных для {ticker}")
                continue
            
            # Сортируем по Sharpe Ratio (лучший первый)
            best = ticker_data.nlargest(1, 'sharpe_ratio').iloc[0]
            
            best_combinations[ticker] = {
                'model_1h': best['model_1h'],
                'model_15m': best['model_15m'],
                'sharpe_ratio': best['sharpe_ratio'],
                'total_pnl_pct': best['total_pnl_pct'],
                'win_rate': best['win_rate'],
                'profit_factor': best['profit_factor'],
                'max_drawdown_pct': best['max_drawdown_pct'],
            }
            
            safe_print(f"\n✅ {ticker}:")
            safe_print(f"   1h: {best['model_1h']}")
            safe_print(f"   15m: {best['model_15m']}")
            safe_print(f"   Sharpe: {best['sharpe_ratio']:.2f}")
            safe_print(f"   PnL: {best['total_pnl_pct']:.2f}%")
            safe_print(f"   WR: {best['win_rate']:.1f}%")
            safe_print(f"   PF: {best['profit_factor']:.2f}")
        
        # Сохраняем результаты
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_file = f"best_mtf_combinations_{timestamp}.txt"
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("🏆 ЛУЧШИЕ MTF КОМБИНАЦИИ ПО ИНСТРУМЕНТАМ\n")
            f.write("=" * 80 + "\n\n")
            
            for ticker, combo in best_combinations.items():
                f.write(f"{ticker}:\n")
                f.write(f"  1h модель: {combo['model_1h']}\n")
                f.write(f"  15m модель: {combo['model_15m']}\n")
                f.write(f"  Sharpe Ratio: {combo['sharpe_ratio']:.2f}\n")
                f.write(f"  Total PnL: {combo['total_pnl_pct']:.2f}%\n")
                f.write(f"  Win Rate: {combo['win_rate']:.1f}%\n")
                f.write(f"  Profit Factor: {combo['profit_factor']:.2f}\n")
                f.write(f"  Max Drawdown: {combo['max_drawdown_pct']:.2f}%\n")
                f.write("\n")
        
        safe_print(f"\n✅ Результаты сохранены в {summary_file}")
        
    except Exception as e:
        safe_print(f"❌ Ошибка при обработке результатов: {e}")
        import traceback
        traceback.print_exc()
    
    return best_combinations


def main():
    parser = argparse.ArgumentParser(
        description="Полный цикл обучения и тестирования MTF моделей",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Полный цикл для всех активных инструментов
  python train_and_test_all.py
  
  # Пропустить обучение, только тестирование
  python train_and_test_all.py --skip-training
  
  # Только обучение, без тестирования
  python train_and_test_all.py --skip-testing
  
  # Кастомные параметры
  python train_and_test_all.py --mtf-1h --days 60 --conf-1h 0.60
        """
    )
    
    # Параметры обучения
    parser.add_argument("--skip-training", action="store_true", help="Пропустить обучение моделей")
    parser.add_argument("--skip-testing", action="store_true", help="Пропустить тестирование моделей")
    parser.add_argument("--skip-mtf-testing", action="store_true", help="Пропустить тестирование MTF комбинаций")
    parser.add_argument("--skip-individual-testing", action="store_true", help="Пропустить тестирование отдельных моделей")
    parser.add_argument("--mtf-15m", action="store_true", help="Использовать MTF фичи для 15m моделей")
    parser.add_argument("--no-mtf-15m", action="store_true", help="НЕ использовать MTF фичи для 15m моделей")
    parser.add_argument("--mtf-1h", action="store_true", help="Использовать MTF фичи для 1h моделей")
    parser.add_argument("--no-mtf-1h", action="store_true", help="НЕ использовать MTF фичи для 1h моделей")
    parser.add_argument("--skip-update", action="store_true", help="Пропустить обновление исторических данных")
    parser.add_argument("--update-days", type=int, default=180, help="Количество дней исторических данных для обновления")
    
    # Параметры тестирования
    parser.add_argument("--days", type=int, default=30, help="Количество дней для бэктеста")
    parser.add_argument("--balance", type=float, default=10000.0, help="Начальный баланс в рублях")
    parser.add_argument("--risk", type=float, default=0.02, help="Риск на сделку")
    parser.add_argument("--leverage", type=int, default=1, help="Плечо")
    parser.add_argument("--conf-1h", type=float, default=0.50, help="Порог уверенности для 1h модели")
    parser.add_argument("--conf-15m", type=float, default=0.35, help="Порог уверенности для 15m модели")
    parser.add_argument("--alignment-mode", type=str, default="strict", choices=["strict", "weighted"],
                       help="Режим выравнивания")
    parser.add_argument("--no-require-alignment", action="store_true", help="Не требовать совпадение направлений")
    parser.add_argument("--workers", type=int, default=4, help="Количество процессов для тестирования")
    
    # Параметры инструментов
    parser.add_argument("--tickers", type=str, help="Тикеры для обработки (через запятую, или 'auto' для автопоиска)")
    
    args = parser.parse_args()
    
    # Загружаем настройки и состояние
    settings = load_settings()
    state = BotState()
    
    # Определяем инструменты
    if args.tickers:
        if args.tickers.lower() == "auto":
            tickers = list(state.active_instruments) if state.active_instruments else list(settings.instruments)
        else:
            tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = list(state.active_instruments) if state.active_instruments else list(settings.instruments)
    
    if not tickers:
        safe_print("❌ Нет активных инструментов для обработки!")
        safe_print("   Добавьте инструменты через Telegram бота или .env файл")
        return
    
    # Определяем MTF режимы
    # По умолчанию: 15m с MTF, 1h без MTF
    use_mtf_15m = True  # По умолчанию включено
    use_mtf_1h = False  # По умолчанию выключено
    
    if args.mtf_15m:
        use_mtf_15m = True
    elif args.no_mtf_15m:
        use_mtf_15m = False
    
    if args.mtf_1h:
        use_mtf_1h = True
    elif args.no_mtf_1h:
        use_mtf_1h = False
    
    # Выводим информацию
    safe_print("=" * 80)
    safe_print("🚀 ПОЛНЫЙ ЦИКЛ ОБУЧЕНИЯ И ТЕСТИРОВАНИЯ MTF МОДЕЛЕЙ")
    safe_print("=" * 80)
    safe_print(f"📊 Инструменты: {', '.join(tickers)}")
    safe_print(f"🔧 MTF для 15m: {'Включено' if use_mtf_15m else 'Выключено'}")
    safe_print(f"🔧 MTF для 1h: {'Включено' if use_mtf_1h else 'Выключено'}")
    safe_print(f"⏰ Период тестирования: {args.days} дней")
    safe_print(f"💰 Баланс: {args.balance:.2f} руб")
    safe_print(f"📈 Риск: {args.risk*100:.1f}%")
    safe_print(f"🎯 Пороги: 1h={args.conf_1h}, 15m={args.conf_15m}")
    safe_print("=" * 80)
    safe_print()
    
    # 1. Обучение моделей
    if not args.skip_training:
        train_models_15m(tickers, use_mtf_15m, args.skip_update, args.update_days)
        train_models_1h(tickers, use_mtf_1h, args.skip_update, args.update_days)
    else:
        safe_print("⏭️  Пропущено обучение моделей")
    
    # 2. Тестирование отдельных моделей
    if not args.skip_testing and not args.skip_individual_testing:
        test_individual_models(tickers, args.days, args.workers)
    else:
        safe_print("⏭️  Пропущено тестирование отдельных моделей")
    
    # 3. Тестирование MTF комбинаций
    if not args.skip_testing and not args.skip_mtf_testing:
        test_mtf_combinations(
            tickers,
            args.days,
            args.balance,
            args.risk,
            args.leverage,
            args.conf_1h,
            args.conf_15m,
            args.alignment_mode,
            not args.no_require_alignment
        )
    else:
        safe_print("⏭️  Пропущено тестирование MTF комбинаций")
    
    # 4. Выбор лучших комбинаций
    if not args.skip_testing and not args.skip_mtf_testing:
        best_combinations = find_best_combinations(tickers)
        
        if best_combinations:
            safe_print("\n" + "=" * 80)
            safe_print("✅ ВСЕ ЭТАПЫ ЗАВЕРШЕНЫ")
            safe_print("=" * 80)
            safe_print("\n💡 Следующие шаги:")
            safe_print("   1. Проверьте файл best_mtf_combinations_*.txt")
            safe_print("   2. Примените лучшие комбинации через Telegram бота")
            safe_print("   3. Настройте параметры MTF стратегии в ml_settings.json")
        else:
            safe_print("\n⚠️ Не удалось определить лучшие комбинации")
    else:
        safe_print("\n" + "=" * 80)
        safe_print("✅ ОБУЧЕНИЕ ЗАВЕРШЕНО")
        safe_print("=" * 80)
        safe_print("\n💡 Следующие шаги:")
        safe_print("   1. Запустите тестирование:")
        safe_print(f"      python train_and_test_all.py --skip-training --tickers {','.join(tickers)}")
        safe_print("   2. Проверьте результаты в CSV файлах")


if __name__ == "__main__":
    main()
