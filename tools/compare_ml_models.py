"""
Скрипт для массового тестирования ВСЕХ ML моделей по каждому инструменту.

Запускает бэктест для всех моделей в директории ml_models и формирует сводную таблицу.
"""
import argparse
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from functools import partial
import concurrent.futures
import traceback

import pandas as pd
import numpy as np
from tqdm import tqdm

try:
    from backtest_ml_strategy import run_exact_backtest, BacktestMetrics
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    sys.exit(1)


def find_all_tickers(models_dir: Path) -> List[str]:
    """Автоматически находит все тикеры из имен файлов моделей."""
    if not models_dir.exists():
        return []
    
    tickers = set()
    
    for model_file in models_dir.glob("*.pkl"):
        name = model_file.stem
        parts = name.split("_")
        
        if len(parts) >= 2:
            for part in parts[1:]:
                part_upper = part.upper()
                if len(part_upper) >= 3 and part_upper.isalnum():
                    tickers.add(part_upper)
                    break
    
    return sorted(list(tickers))


def find_models_for_ticker(models_dir: Path, ticker: str) -> List[Path]:
    """Ищет все ML модели для указанного тикера."""
    if not models_dir.exists():
        return []
    
    patterns = [
        f"*_{ticker}_*.pkl",
        f"*{ticker}*.pkl",
    ]
    
    results: List[Path] = []
    for pattern in patterns:
        for f in models_dir.glob(pattern):
            if f.is_file() and f not in results:
                results.append(f)
    
    return sorted(list({f.resolve() for f in results}))


def extract_interval_from_model(model_path: Path) -> str:
    """Извлекает интервал из имени файла модели."""
    name = model_path.stem
    parts = name.split("_")
    
    for part in parts:
        if part in ["15", "60", "240", "D"]:
            return part
    
    return "15"


def metrics_to_dict(m: BacktestMetrics, model_path: Path) -> Dict[str, Any]:
    """Преобразует BacktestMetrics в словарь."""
    if m is None:
        return {}
    
    filename = model_path.name
    name_no_ext = filename.replace(".pkl", "")
    parts = name_no_ext.split("_")
    
    model_type = parts[0] if parts else "unknown"
    mode_suffix = None
    if len(parts) >= 4:
        mode_suffix = parts[-1]
    
    result = {
        "ticker": m.ticker,
        "model_name": m.model_name,
        "model_filename": filename,
        "model_path": str(model_path),
        "model_type": model_type,
        "mode_suffix": mode_suffix or "",
        "total_trades": m.total_trades,
        "winning_trades": m.winning_trades,
        "losing_trades": m.losing_trades,
        "win_rate_pct": m.win_rate,
        "total_pnl_rub": m.total_pnl,
        "total_pnl_pct": m.total_pnl_pct,
        "profit_factor": m.profit_factor,
        "max_drawdown_rub": m.max_drawdown,
        "max_drawdown_pct": m.max_drawdown_pct,
        "sharpe_ratio": m.sharpe_ratio,
        "long_trades": m.long_signals,
        "short_trades": m.short_signals,
        "avg_win_rub": m.avg_win,
        "avg_loss_rub": m.avg_loss,
        "best_trade_rub": m.best_trade_pnl,
        "worst_trade_rub": m.worst_trade_pnl,
        "avg_confidence": m.avg_confidence,
        "avg_tp_distance_pct": m.avg_tp_distance_pct,
        "avg_sl_distance_pct": m.avg_sl_distance_pct,
        "avg_rr_ratio": m.avg_rr_ratio,
        "signals_with_tp_sl_pct": m.signals_with_tp_sl_pct,
        "signals_with_correct_sl_pct": m.signals_with_correct_sl_pct,
    }
    
    return result


def test_single_model(args_tuple: Tuple) -> Optional[Dict[str, Any]]:
    """Функция для тестирования одной модели (для параллельного выполнения)."""
    model_path, ticker, days, interval, initial_balance, risk_per_trade, leverage = args_tuple
    
    try:
        import matplotlib
        matplotlib.use('Agg')
        
        from backtest_ml_strategy import run_exact_backtest
        
        model_interval = extract_interval_from_model(model_path)
        test_interval = interval.replace("min", "").replace("hour", "60").replace("day", "D")
        if test_interval == "15" and model_interval != "15":
            test_interval = model_interval
        
        metrics = run_exact_backtest(
            model_path=str(model_path),
            ticker=ticker,
            days_back=days,
            interval=test_interval,
            initial_balance=initial_balance,
            risk_per_trade=risk_per_trade,
            leverage=leverage,
        )
        
        if metrics is None:
            return None
        
        return metrics_to_dict(metrics, model_path)
        
    except Exception as e:
        return {"error": True, "model": model_path.name, "message": str(e)[:100]}


def compare_models(
    tickers: List[str],
    models_dir: Path,
    days: int = 30,
    interval: str = "15min",
    initial_balance: float = 10000.0,
    risk_per_trade: float = 0.02,
    leverage: int = 1,
    workers: int = 4,
) -> pd.DataFrame:
    """Запускает бэктест для всех моделей и возвращает DataFrame с результатами."""
    all_results: List[Dict[str, Any]] = []
    
    print("=" * 80)
    print("🚀 ML MODELS COMPARISON BACKTEST (TINKOFF)")
    print("=" * 80)
    print(f"📊 Tickers: {', '.join(tickers)}")
    print(f"📁 Models dir: {models_dir}")
    print(f"⚙️  Days: {days}, Interval: {interval}")
    print(f"💰 Initial balance: {initial_balance:.2f} руб")
    print(f"🎯 Risk per trade: {risk_per_trade*100:.1f}%, Leverage: {leverage}x")
    print(f"⚡ Workers: {workers}")
    print("=" * 80)
    
    all_models: List[Tuple[Path, str]] = []
    for ticker in tickers:
        models = find_models_for_ticker(models_dir, ticker)
        for model in models:
            all_models.append((model, ticker))
    
    if not all_models:
        print(f"❌ Не найдено моделей для тестирования")
        return pd.DataFrame()
    
    print(f"\n📦 Найдено {len(all_models)} моделей для тестирования")
    
    test_args = [
        (model_path, ticker, days, interval, initial_balance, risk_per_trade, leverage)
        for model_path, ticker in all_models
    ]
    
    print(f"\n🚀 Запуск параллельного тестирования ({workers} workers)...")
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        results = list(tqdm(
            executor.map(test_single_model, test_args),
            total=len(test_args),
            desc="Testing models"
        ))
    
    for result in results:
        if result and not result.get("error", False):
            all_results.append(result)
        elif result and result.get("error", False):
            print(f"⚠️  Ошибка в модели {result.get('model', 'unknown')}: {result.get('message', 'Unknown error')}")
    
    if not all_results:
        print(f"❌ Нет результатов для отображения")
        return pd.DataFrame()
    
    df_results = pd.DataFrame(all_results)
    
    if "sharpe_ratio" in df_results.columns:
        df_results = df_results.sort_values("sharpe_ratio", ascending=False)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = f"ml_models_comparison_{timestamp}.csv"
    df_results.to_csv(output_file, index=False)
    print(f"\n✅ Результаты сохранены в: {output_file}")
    
    print(f"\n🏆 ТОП-10 МОДЕЛЕЙ (по Sharpe Ratio):")
    print("=" * 80)
    top_models = df_results.head(10)
    for idx, row in top_models.iterrows():
        print(f"{idx+1:2d}. {row['model_filename']:40s} | "
              f"Sharpe: {row['sharpe_ratio']:6.2f} | "
              f"PnL: {row['total_pnl_pct']:7.2f}% | "
              f"Trades: {row['total_trades']:4d} | "
              f"WR: {row['win_rate_pct']:5.1f}%")
    
    # Генерируем анализ и рекомендации
    print(f"\n📊 Генерация анализа и рекомендаций...")
    analysis_text = generate_analysis_and_recommendations(df_results, output_file)
    print(analysis_text)
    
    return df_results


def generate_analysis_and_recommendations(df_results: pd.DataFrame, output_file: str) -> str:
    """Генерирует детальный анализ и рекомендации по улучшению прибыльности."""
    if df_results.empty:
        return ""
    
    analysis_lines = []
    analysis_lines.append("=" * 80)
    analysis_lines.append("📊 ДЕТАЛЬНЫЙ АНАЛИЗ РЕЗУЛЬТАТОВ МОДЕЛЕЙ")
    analysis_lines.append("=" * 80)
    analysis_lines.append("")
    
    # 1. Общая статистика
    analysis_lines.append("1. ОБЩАЯ СТАТИСТИКА")
    analysis_lines.append("-" * 80)
    total_models = len(df_results)
    profitable_models = len(df_results[df_results['total_pnl_pct'] > 0])
    avg_sharpe = df_results['sharpe_ratio'].mean()
    avg_win_rate = df_results['win_rate_pct'].mean()
    avg_pnl = df_results['total_pnl_pct'].mean()
    
    analysis_lines.append(f"   Всего моделей: {total_models}")
    analysis_lines.append(f"   Прибыльных моделей: {profitable_models} ({profitable_models/total_models*100:.1f}%)")
    analysis_lines.append(f"   Средний Sharpe Ratio: {avg_sharpe:.2f}")
    analysis_lines.append(f"   Средний Win Rate: {avg_win_rate:.1f}%")
    analysis_lines.append(f"   Средний PnL: {avg_pnl:.2f}%")
    analysis_lines.append("")
    
    # 2. Анализ по типам моделей
    analysis_lines.append("2. АНАЛИЗ ПО ТИПАМ МОДЕЛЕЙ")
    analysis_lines.append("-" * 80)
    model_type_stats = df_results.groupby('model_type').agg({
        'sharpe_ratio': ['mean', 'max', 'count'],
        'total_pnl_pct': ['mean', 'max'],
        'win_rate_pct': 'mean',
        'total_trades': 'mean'
    }).round(2)
    
    for model_type in df_results['model_type'].unique():
        type_df = df_results[df_results['model_type'] == model_type]
        if len(type_df) > 0:
            analysis_lines.append(f"   {model_type.upper()}:")
            analysis_lines.append(f"      Количество: {len(type_df)}")
            analysis_lines.append(f"      Средний Sharpe: {type_df['sharpe_ratio'].mean():.2f}")
            analysis_lines.append(f"      Лучший Sharpe: {type_df['sharpe_ratio'].max():.2f}")
            analysis_lines.append(f"      Средний PnL: {type_df['total_pnl_pct'].mean():.2f}%")
            analysis_lines.append(f"      Средний Win Rate: {type_df['win_rate_pct'].mean():.1f}%")
            analysis_lines.append(f"      Среднее кол-во сделок: {type_df['total_trades'].mean():.0f}")
            analysis_lines.append("")
    
    # 3. Анализ по инструментам
    analysis_lines.append("3. АНАЛИЗ ПО ИНСТРУМЕНТАМ")
    analysis_lines.append("-" * 80)
    for ticker in df_results['ticker'].unique():
        ticker_df = df_results[df_results['ticker'] == ticker]
        if len(ticker_df) > 0:
            best_model = ticker_df.loc[ticker_df['sharpe_ratio'].idxmax()]
            analysis_lines.append(f"   {ticker}:")
            analysis_lines.append(f"      Моделей: {len(ticker_df)}")
            analysis_lines.append(f"      Лучшая модель: {best_model['model_filename']}")
            analysis_lines.append(f"      Лучший Sharpe: {best_model['sharpe_ratio']:.2f}")
            analysis_lines.append(f"      Лучший PnL: {best_model['total_pnl_pct']:.2f}%")
            analysis_lines.append(f"      Средний Win Rate: {ticker_df['win_rate_pct'].mean():.1f}%")
            analysis_lines.append("")
    
    # 4. Выявление проблем
    analysis_lines.append("4. ВЫЯВЛЕННЫЕ ПРОБЛЕМЫ")
    analysis_lines.append("-" * 80)
    
    # Проблема: низкий Win Rate
    low_wr = df_results[df_results['win_rate_pct'] < 50]
    if len(low_wr) > 0:
        analysis_lines.append(f"   ⚠️  Низкий Win Rate (<50%): {len(low_wr)} моделей")
        for _, row in low_wr.iterrows():
            analysis_lines.append(f"      - {row['model_filename']}: WR={row['win_rate_pct']:.1f}%")
        analysis_lines.append("")
    
    # Проблема: отрицательный PnL
    negative_pnl = df_results[df_results['total_pnl_pct'] < 0]
    if len(negative_pnl) > 0:
        analysis_lines.append(f"   ❌ Убыточные модели: {len(negative_pnl)}")
        for _, row in negative_pnl.iterrows():
            analysis_lines.append(f"      - {row['model_filename']}: PnL={row['total_pnl_pct']:.2f}%")
        analysis_lines.append("")
    
    # Проблема: мало сделок
    few_trades = df_results[df_results['total_trades'] < 10]
    if len(few_trades) > 0:
        analysis_lines.append(f"   ⚠️  Мало сделок (<10): {len(few_trades)} моделей")
        for _, row in few_trades.iterrows():
            analysis_lines.append(f"      - {row['model_filename']}: {row['total_trades']} сделок")
        analysis_lines.append("")
    
    # Проблема: низкий Profit Factor
    low_pf = df_results[df_results['profit_factor'] < 1.5]
    if len(low_pf) > 0:
        analysis_lines.append(f"   ⚠️  Низкий Profit Factor (<1.5): {len(low_pf)} моделей")
        analysis_lines.append("")
    
    # Проблема: соотношение TP/SL
    if 'avg_rr_ratio' in df_results.columns:
        wrong_rr = df_results[df_results['avg_rr_ratio'] < 2.0]
        if len(wrong_rr) > 0:
            analysis_lines.append(f"   ⚠️  Неправильное соотношение TP/SL (<2.0): {len(wrong_rr)} моделей")
            analysis_lines.append(f"      Рекомендуется соотношение 2.5:1")
            analysis_lines.append("")
    
    # 5. Рекомендации по улучшению
    analysis_lines.append("5. РЕКОМЕНДАЦИИ ПО УЛУЧШЕНИЮ ПРИБЫЛЬНОСТИ")
    analysis_lines.append("-" * 80)
    
    # Лучшие модели для использования
    top_3 = df_results.head(3)
    analysis_lines.append("   ✅ РЕКОМЕНДУЕМЫЕ МОДЕЛИ ДЛЯ ПРОДАКШЕНА:")
    for idx, (_, row) in enumerate(top_3.iterrows(), 1):
        analysis_lines.append(f"      {idx}. {row['model_filename']}")
        analysis_lines.append(f"         Sharpe: {row['sharpe_ratio']:.2f}, PnL: {row['total_pnl_pct']:.2f}%, WR: {row['win_rate_pct']:.1f}%")
    analysis_lines.append("")
    
    # Рекомендации по типам моделей
    best_type = df_results.groupby('model_type')['sharpe_ratio'].mean().idxmax()
    analysis_lines.append(f"   📈 ЛУЧШИЙ ТИП МОДЕЛИ: {best_type.upper()}")
    analysis_lines.append(f"      Средний Sharpe: {df_results[df_results['model_type'] == best_type]['sharpe_ratio'].mean():.2f}")
    analysis_lines.append("")
    
    # Рекомендации по оптимизации
    analysis_lines.append("   🔧 РЕКОМЕНДАЦИИ ПО ОПТИМИЗАЦИИ:")
    
    # Проверка соотношения TP/SL
    if 'avg_rr_ratio' in df_results.columns:
        avg_rr = df_results['avg_rr_ratio'].mean()
        if avg_rr < 2.0:
            analysis_lines.append(f"      • Увеличить соотношение TP/SL до 2.5:1 (текущее среднее: {avg_rr:.2f})")
    
    # Проверка Win Rate
    if avg_win_rate < 60:
        analysis_lines.append(f"      • Улучшить фильтрацию сигналов для повышения Win Rate (текущий: {avg_win_rate:.1f}%)")
        analysis_lines.append(f"        - Увеличить confidence_threshold")
        analysis_lines.append(f"        - Добавить дополнительные фильтры (тренд, волатильность)")
    
    # Проверка количества сделок
    avg_trades = df_results['total_trades'].mean()
    if avg_trades < 20:
        analysis_lines.append(f"      • Увеличить количество сигналов (текущее среднее: {avg_trades:.0f} сделок)")
        analysis_lines.append(f"        - Смягчить параметры создания таргета при обучении")
        analysis_lines.append(f"        - Снизить confidence_threshold")
    
    # Проверка Profit Factor
    avg_pf = df_results['profit_factor'].mean()
    if avg_pf < 2.0:
        analysis_lines.append(f"      • Улучшить соотношение прибыль/убыток (текущий PF: {avg_pf:.2f})")
        analysis_lines.append(f"        - Улучшить управление рисками")
        analysis_lines.append(f"        - Использовать trailing stop")
    
    # Рекомендации по конкретным моделям
    analysis_lines.append("")
    analysis_lines.append("   🎯 КОНКРЕТНЫЕ ДЕЙСТВИЯ:")
    
    # Для убыточных моделей
    if len(negative_pnl) > 0:
        analysis_lines.append(f"      • Переобучить {len(negative_pnl)} убыточных моделей:")
        analysis_lines.append(f"        - Увеличить количество данных для обучения")
        analysis_lines.append(f"        - Настроить параметры таргета (forward_periods, threshold_pct)")
        analysis_lines.append(f"        - Попробовать другие типы моделей")
    
    # Для моделей с низким Win Rate
    if len(low_wr) > 0:
        analysis_lines.append(f"      • Улучшить {len(low_wr)} моделей с низким Win Rate:")
        analysis_lines.append(f"        - Повысить confidence_threshold")
        analysis_lines.append(f"        - Добавить фильтры по тренду и волатильности")
        analysis_lines.append(f"        - Использовать ансамбли вместо одиночных моделей")
    
    # Рекомендации по ансамблям
    ensemble_models = df_results[df_results['model_type'].isin(['ensemble', 'triple', 'quad'])]
    single_models = df_results[~df_results['model_type'].isin(['ensemble', 'triple', 'quad'])]
    
    if len(ensemble_models) > 0 and len(single_models) > 0:
        ensemble_avg_sharpe = ensemble_models['sharpe_ratio'].mean()
        single_avg_sharpe = single_models['sharpe_ratio'].mean()
        
        if ensemble_avg_sharpe > single_avg_sharpe:
            analysis_lines.append(f"      • Ансамбли показывают лучшие результаты (Sharpe: {ensemble_avg_sharpe:.2f} vs {single_avg_sharpe:.2f})")
            analysis_lines.append(f"        - Рекомендуется использовать ансамбли для продакшена")
        else:
            analysis_lines.append(f"      • Одиночные модели показывают лучшие результаты")
            analysis_lines.append(f"        - Рассмотреть оптимизацию весов ансамблей")
    
    analysis_lines.append("")
    analysis_lines.append("=" * 80)
    
    # Сохраняем анализ в файл
    analysis_text = "\n".join(analysis_lines)
    analysis_file = output_file.replace('.csv', '_analysis.txt')
    with open(analysis_file, 'w', encoding='utf-8') as f:
        f.write(analysis_text)
    
    return analysis_text


def main():
    parser = argparse.ArgumentParser(description='Сравнение всех ML моделей для Tinkoff бота')
    parser.add_argument('--tickers', type=str, default='auto', help='Тикеры для тестирования (auto для автопоиска)')
    parser.add_argument('--models-dir', type=str, default='ml_models', help='Директория с моделями')
    parser.add_argument('--days', type=int, default=30, help='Количество дней для бэктеста')
    parser.add_argument('--interval', type=str, default='15min', help='Интервал свечей')
    parser.add_argument('--balance', type=float, default=10000.0, help='Начальный баланс в рублях')
    parser.add_argument('--risk', type=float, default=0.02, help='Риск на сделку')
    parser.add_argument('--leverage', type=int, default=1, help='Плечо')
    parser.add_argument('--workers', type=int, default=4, help='Количество параллельных процессов')
    
    args = parser.parse_args()
    
    models_dir = Path(args.models_dir)
    
    if args.tickers.lower() == 'auto':
        tickers = find_all_tickers(models_dir)
        if not tickers:
            print("❌ Не найдено тикеров. Укажите --tickers вручную.")
            sys.exit(1)
        print(f"🔍 Автоматически найдены тикеры: {', '.join(tickers)}")
    else:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    
    df_results = compare_models(
        tickers=tickers,
        models_dir=models_dir,
        days=args.days,
        interval=args.interval,
        initial_balance=args.balance,
        risk_per_trade=args.risk,
        leverage=args.leverage,
        workers=args.workers,
    )
    
    if df_results.empty:
        print(f"\n❌ Нет результатов для отображения")
        sys.exit(1)
    
    print(f"\n✅ Сравнение завершено!")
    print(f"   Протестировано моделей: {len(df_results)}")
    print(f"   Лучшая модель: {df_results.iloc[0]['model_filename']}")


if __name__ == "__main__":
    main()
