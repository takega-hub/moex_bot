"""
Скрипт для тестирования всех комбинаций MTF стратегий (1h + 15m) для MOEX бота.

Использование:
    # Тестирование всех комбинаций для всех активных инструментов
    python test_mtf_combinations.py
    
    # Тестирование для конкретного инструмента
    python test_mtf_combinations.py --ticker VBH6
    
    # Тестирование с кастомными параметрами
    python test_mtf_combinations.py --conf-1h 0.60 --conf-15m 0.45
"""
import argparse
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from bot.config import load_settings
from bot.state import BotState
from data.storage import DataStorage
from bot.ml.mtf_strategy import MultiTimeframeMLStrategy

try:
    from backtest_ml_strategy import run_exact_backtest, BacktestMetrics, MLBacktestSimulator
except ImportError as e:
    print(f"❌ Ошибка импорта backtest_ml_strategy: {e}")
    sys.exit(1)


def find_all_models_for_ticker(ticker: str) -> Tuple[List[str], List[str]]:
    """
    Находит ВСЕ модели 1h и 15m для инструмента.
    
    Returns:
        (list_1h_models, list_15m_models)
    """
    models_dir = Path("ml_models")
    if not models_dir.exists():
        return [], []
    
    ticker_upper = ticker.upper()
    
    # Ищем 1h модели (интервал 60 или 1h в имени)
    models_1h = []
    for pattern in [f"*_{ticker_upper}_60_*.pkl", f"*_{ticker_upper}_*1h*.pkl"]:
        models_1h.extend(models_dir.glob(pattern))
    
    # Ищем 15m модели (интервал 15 или 15m в имени)
    models_15m = []
    for pattern in [f"*_{ticker_upper}_15_*.pkl", f"*_{ticker_upper}_*15m*.pkl"]:
        models_15m.extend(models_dir.glob(pattern))
    
    # Сортируем по имени (для стабильности)
    models_1h = sorted([str(m) for m in models_1h])
    models_15m = sorted([str(m) for m in models_15m])
    
    return models_1h, models_15m


def test_mtf_combination(
    ticker: str,
    model_1h_path: str,
    model_15m_path: str,
    days_back: int = 30,
    initial_balance: float = 10000.0,
    risk_per_trade: float = 0.02,
    leverage: int = 1,
    confidence_threshold_1h: float = 0.50,
    confidence_threshold_15m: float = 0.35,
    alignment_mode: str = "strict",
    require_alignment: bool = True,
) -> Optional[BacktestMetrics]:
    """
    Тестирует одну комбинацию MTF стратегии.
    
    Returns:
        BacktestMetrics или None при ошибке
    """
    from datetime import datetime, timedelta
    from bot.strategy import Action, Bias, Signal
    
    try:
        print(f"   Загрузка данных и подготовка стратегии...")
        
        # Загружаем настройки
        settings = load_settings()
        storage = DataStorage()
        
        # Получаем информацию об инструменте
        instrument_info = storage.get_instrument_by_ticker(ticker)
        if not instrument_info:
            print(f"   ❌ Инструмент {ticker} не найден в базе")
            return None
        
        figi = instrument_info["figi"]
        
        # Загружаем данные для 15m (основной таймфрейм)
        to_date = datetime.now()
        from_date = to_date - timedelta(days=days_back)
        
        df_15m = storage.get_candles(
            figi=figi,
            from_date=from_date,
            to_date=to_date,
            interval="15min",
            limit=10000
        )
        
        if df_15m.empty:
            print(f"   ❌ Нет 15m данных для {ticker}")
            return None
        
        # Загружаем данные для 1h (если есть отдельные данные)
        df_1h = storage.get_candles(
            figi=figi,
            from_date=from_date,
            to_date=to_date,
            interval="1hour",
            limit=10000
        )
        
        # Преобразуем индексы
        if "time" in df_15m.columns:
            df_15m["timestamp"] = pd.to_datetime(df_15m["time"])
            df_15m = df_15m.set_index("timestamp")
        
        if not df_1h.empty and "time" in df_1h.columns:
            df_1h["timestamp"] = pd.to_datetime(df_1h["time"])
            df_1h = df_1h.set_index("timestamp")
        
        # Создаем MTF стратегию
        mtf_strategy = MultiTimeframeMLStrategy(
            model_1h_path=model_1h_path,
            model_15m_path=model_15m_path,
            confidence_threshold_1h=confidence_threshold_1h,
            confidence_threshold_15m=confidence_threshold_15m,
            alignment_mode=alignment_mode,
            require_alignment=require_alignment,
        )
        
        # Создаем фичи для 15m данных
        df_15m_with_features = mtf_strategy.strategy_15m.feature_engineer.create_technical_indicators(df_15m.copy())
        
        # Создаем симулятор
        lot_size = 1
        simulator = MLBacktestSimulator(
            initial_balance=initial_balance,
            risk_per_trade=risk_per_trade,
            leverage=leverage,
            max_position_hours=48.0,
            lot_size=lot_size,
        )
        simulator._base_order_rub = getattr(settings.risk, 'base_order_usd', 10000.0)
        
        # Запускаем бэктест
        min_window_size = 200
        total_bars = len(df_15m_with_features)
        
        for idx in range(min_window_size, total_bars):
            try:
                current_time = df_15m_with_features.index[idx]
                row = df_15m_with_features.iloc[idx]
                current_price = float(row['close'])
                high = float(row['high'])
                low = float(row['low'])
            except Exception as e:
                continue
            
            df_15m_window = df_15m_with_features.iloc[:idx+1]
            
            # Подготавливаем 1h данные для текущего окна (если есть)
            df_1h_window = None
            if not df_1h.empty:
                # Берем 1h данные до текущего момента
                df_1h_window = df_1h[df_1h.index <= current_time]
            else:
                # Агрегируем из 15m данных (MTF стратегия сделает это сама)
                df_1h_window = None
            
            has_position = None
            if simulator.current_position is not None:
                has_position = Bias.LONG if simulator.current_position.action == Action.LONG else Bias.SHORT
            
            try:
                signal = mtf_strategy.generate_signal(
                    row=row,
                    df_15m=df_15m_window,
                    df_1h=df_1h_window,
                    has_position=has_position,
                    current_price=current_price,
                    leverage=leverage,
                )
            except Exception as e:
                signal = Signal(
                    timestamp=current_time,
                    action=Action.HOLD,
                    reason=f"mtf_error_{str(e)[:30]}",
                    price=current_price
                )
            
            # Анализируем сигнал
            simulator.analyze_signal(signal, current_price)
            
            if simulator.current_position is not None:
                exited = simulator.check_exit(current_time, current_price, high, low)
                if exited:
                    continue
            
            # Открываем позицию только если сигнал не None и это LONG/SHORT
            if simulator.current_position is None and signal is not None and signal.action in (Action.LONG, Action.SHORT):
                simulator.open_position(signal, current_time, ticker)
        
        # Закрываем открытые позиции в конце
        if simulator.current_position is not None:
            final_price = float(df_15m_with_features['close'].iloc[-1])
            final_time = df_15m_with_features.index[-1]
            simulator.close_all_positions(final_time, final_price)
        
        # Рассчитываем метрики
        model_name = f"MTF_{Path(model_1h_path).stem}_{Path(model_15m_path).stem}"
        metrics = simulator.calculate_metrics(ticker, model_name, days_back=days_back)
        
        return metrics
        
    except Exception as e:
        print(f"   ❌ Ошибка при тестировании комбинации: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_all_combinations(
    ticker: str,
    days_back: int = 30,
    initial_balance: float = 10000.0,
    risk_per_trade: float = 0.02,
    leverage: int = 1,
    confidence_threshold_1h: float = 0.50,
    confidence_threshold_15m: float = 0.35,
    alignment_mode: str = "strict",
    require_alignment: bool = True,
) -> pd.DataFrame:
    """
    Тестирует ВСЕ комбинации моделей 1h и 15m для инструмента.
    
    Returns:
        DataFrame с результатами всех комбинаций
    """
    print("=" * 80)
    print("🚀 ТЕСТИРОВАНИЕ ВСЕХ КОМБИНАЦИЙ MTF СТРАТЕГИИ")
    print("=" * 80)
    print(f"Инструмент: {ticker}")
    print(f"Период: {days_back} дней")
    print()
    
    # Находим все модели
    models_1h, models_15m = find_all_models_for_ticker(ticker)
    
    if not models_1h:
        print(f"❌ Не найдено 1h моделей для {ticker}")
        return pd.DataFrame()
    if not models_15m:
        print(f"❌ Не найдено 15m моделей для {ticker}")
        return pd.DataFrame()
    
    print(f"📦 Найдено моделей:")
    print(f"   1h: {len(models_1h)}")
    for m in models_1h:
        print(f"      - {Path(m).name}")
    print(f"   15m: {len(models_15m)}")
    for m in models_15m:
        print(f"      - {Path(m).name}")
    print()
    print(f"🎯 Всего комбинаций: {len(models_1h) * len(models_15m)}")
    print()
    
    # Результаты
    results = []
    
    # Тестируем все комбинации
    for i, model_1h in enumerate(models_1h, 1):
        for j, model_15m in enumerate(models_15m, 1):
            combo_num = (i - 1) * len(models_15m) + j
            total_combos = len(models_1h) * len(models_15m)
            
            print("=" * 80)
            print(f"📊 Комбинация {combo_num}/{total_combos}:")
            print(f"   1h: {Path(model_1h).name}")
            print(f"   15m: {Path(model_15m).name}")
            print("-" * 80)
            
            metrics = test_mtf_combination(
                ticker=ticker,
                model_1h_path=model_1h,
                model_15m_path=model_15m,
                days_back=days_back,
                initial_balance=initial_balance,
                risk_per_trade=risk_per_trade,
                leverage=leverage,
                confidence_threshold_1h=confidence_threshold_1h,
                confidence_threshold_15m=confidence_threshold_15m,
                alignment_mode=alignment_mode,
                require_alignment=require_alignment,
            )
            
            if metrics:
                results.append({
                    "model_1h": Path(model_1h).name,
                    "model_15m": Path(model_15m).name,
                    "ticker": ticker,
                    "total_trades": metrics.total_trades,
                    "winning_trades": metrics.winning_trades,
                    "losing_trades": metrics.losing_trades,
                    "win_rate": metrics.win_rate,
                    "total_pnl": metrics.total_pnl,
                    "total_pnl_pct": metrics.total_pnl_pct,
                    "avg_win": metrics.avg_win,
                    "avg_loss": metrics.avg_loss,
                    "profit_factor": metrics.profit_factor,
                    "max_drawdown_pct": metrics.max_drawdown_pct,
                    "sharpe_ratio": metrics.sharpe_ratio,
                })
                print(f"✅ Результат: {metrics.total_trades} сделок, PnL: {metrics.total_pnl_pct:.2f}%, WR: {metrics.win_rate:.1f}%")
            else:
                print(f"⚠️  Пропущено (бэктест MTF пока не реализован)")
            
            print()
    
    # Создаем DataFrame с результатами
    if results:
        df_results = pd.DataFrame(results)
        df_results = df_results.sort_values('total_pnl_pct', ascending=False)
        
        print("=" * 80)
        print("🏆 ЛУЧШИЕ КОМБИНАЦИИ")
        print("=" * 80)
        print(df_results.head(10).to_string(index=False))
        print()
        
        # Сохраняем результаты
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mtf_combinations_{ticker}_{timestamp}.csv"
        df_results.to_csv(filename, index=False)
        print(f"✅ Результаты сохранены в {filename}")
        
        return df_results
    else:
        print("❌ Нет результатов для отображения")
        return pd.DataFrame()


def main():
    parser = argparse.ArgumentParser(
        description="Тестирование всех комбинаций MTF стратегий (1h + 15m)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Тестирование всех комбинаций для всех активных инструментов
  python test_mtf_combinations.py
  
  # Тестирование для конкретного инструмента
  python test_mtf_combinations.py --ticker VBH6
  
  # Тестирование с кастомными параметрами
  python test_mtf_combinations.py --conf-1h 0.60 --conf-15m 0.45
        """
    )
    parser.add_argument("--tickers", type=str, help="Тикеры для тестирования (через запятую, или 'auto' для автопоиска)")
    parser.add_argument("--ticker", type=str, help="Один тикер для тестирования (устаревший, используйте --tickers)")
    parser.add_argument("--days", type=int, default=30, help="Количество дней для бэктеста")
    parser.add_argument("--balance", type=float, default=10000.0, help="Начальный баланс в рублях")
    parser.add_argument("--risk", type=float, default=0.02, help="Риск на сделку")
    parser.add_argument("--leverage", type=int, default=1, help="Плечо")
    parser.add_argument("--conf-1h", type=float, default=0.50, help="Порог уверенности для 1h модели")
    parser.add_argument("--conf-15m", type=float, default=0.35, help="Порог уверенности для 15m модели")
    parser.add_argument("--alignment-mode", type=str, default="strict", choices=["strict", "weighted"],
                       help="Режим выравнивания")
    parser.add_argument("--no-require-alignment", action="store_true", help="Не требовать совпадение направлений")
    
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
    elif args.ticker:
        tickers = [args.ticker.upper()]
    else:
        tickers = list(state.active_instruments) if state.active_instruments else list(settings.instruments)
    
    if not tickers:
        print("❌ Нет инструментов для тестирования!")
        print("   Добавьте инструменты через Telegram бота или .env файл")
        return
    
    print("=" * 80)
    print("🚀 ТЕСТИРОВАНИЕ MTF КОМБИНАЦИЙ")
    print("=" * 80)
    print(f"📊 Инструменты: {', '.join(tickers)}")
    print(f"⏰ Период: {args.days} дней")
    print(f"💰 Баланс: {args.balance:.2f} руб")
    print(f"📈 Риск: {args.risk*100:.1f}%")
    print(f"⚡ Плечо: {args.leverage}x")
    print(f"🎯 Пороги: 1h={args.conf_1h}, 15m={args.conf_15m}")
    print(f"🔧 Режим: {args.alignment_mode}, require_alignment={not args.no_require_alignment}")
    print("=" * 80)
    print()
    
    # Тестируем для каждого инструмента
    all_results = []
    for ticker in tickers:
        print(f"\n{'='*80}")
        print(f"📊 Тестирование {ticker}")
        print(f"{'='*80}\n")
        
        df_results = test_all_combinations(
            ticker=ticker,
            days_back=args.days,
            initial_balance=args.balance,
            risk_per_trade=args.risk,
            leverage=args.leverage,
            confidence_threshold_1h=args.conf_1h,
            confidence_threshold_15m=args.conf_15m,
            alignment_mode=args.alignment_mode,
            require_alignment=not args.no_require_alignment,
        )
        
        if not df_results.empty:
            all_results.append(df_results)
    
    # Объединяем результаты
    if all_results:
        df_all = pd.concat(all_results, ignore_index=True)
        df_all = df_all.sort_values('total_pnl_pct', ascending=False)
        
        print("\n" + "=" * 80)
        print("🏆 ОБЩИЕ РЕЗУЛЬТАТЫ (ЛУЧШИЕ КОМБИНАЦИИ)")
        print("=" * 80)
        print(df_all.head(20).to_string(index=False))
        print()
        
        # Сохраняем общие результаты
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mtf_combinations_all_{timestamp}.csv"
        df_all.to_csv(filename, index=False)
        print(f"✅ Общие результаты сохранены в {filename}")
    else:
        print("❌ Нет результатов для отображения")


if __name__ == "__main__":
    main()
