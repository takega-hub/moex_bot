"""
Скрипт для автоматического запуска бэктестов всех моделей по тикеру.
"""
import argparse
import subprocess
import sys
import os
from pathlib import Path
from typing import List, Dict
import pandas as pd
from datetime import datetime


def find_models_for_ticker(ticker: str, models_dir: str = "ml_models") -> List[str]:
    """Находит все модели для указанного тикера."""
    models_path = Path(models_dir)
    if not models_path.exists():
        print(f"❌ Директория {models_dir} не найдена")
        return []
    
    ticker_upper = ticker.upper()
    models = []
    
    for model_file in models_path.glob("*.pkl"):
        model_name = model_file.name
        if ticker_upper in model_name.upper():
            models.append(str(model_file))
    
    models.sort()
    return models


def run_backtest(
    model_path: str,
    ticker: str,
    days: int = 30,
    interval: str = "15min",
    balance: float = 100000.0,
    risk: float = 0.02,
    leverage: int = 1
) -> Dict:
    """Запускает бэктест для одной модели."""
    cmd = [
        sys.executable,
        "backtest_ml_strategy.py",
        "--model", model_path,
        "--ticker", ticker,
        "--days", str(days),
        "--interval", interval,
        "--balance", str(balance),
        "--risk", str(risk),
        "--leverage", str(leverage),
    ]
    
    print(f"\n{'='*80}")
    print(f"🚀 Запуск бэктеста: {Path(model_path).name}")
    print(f"{'='*80}")
    
    try:
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=3600,
            env=env
        )
        
        if result.returncode != 0:
            print(f"❌ Ошибка при запуске бэктеста:")
            print(result.stderr)
            return None
        
        output = result.stdout
        
        metrics = {}
        for line in output.split('\n'):
            if 'Общий PnL:' in line:
                try:
                    parts = line.split()
                    pnl_idx = parts.index('PnL:')
                    metrics['total_pnl'] = float(parts[pnl_idx + 1])
                except:
                    pass
            elif 'Win Rate:' in line:
                try:
                    parts = line.split()
                    wr_idx = parts.index('Rate:')
                    metrics['win_rate'] = float(parts[wr_idx + 1].replace('%', ''))
                except:
                    pass
            elif 'Sharpe Ratio:' in line:
                try:
                    parts = line.split()
                    sharpe_idx = parts.index('Ratio:')
                    metrics['sharpe_ratio'] = float(parts[sharpe_idx + 1])
                except:
                    pass
        
        return metrics
        
    except subprocess.TimeoutExpired:
        print(f"❌ Бэктест превысил лимит времени (1 час)")
        return None
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description='Автоматический запуск бэктестов всех моделей для Tinkoff бота')
    parser.add_argument('--ticker', type=str, required=True, help='Тикер инструмента')
    parser.add_argument('--days', type=int, default=30, help='Количество дней для бэктеста')
    parser.add_argument('--interval', type=str, default='15min', help='Интервал свечей')
    parser.add_argument('--balance', type=float, default=100000.0, help='Начальный баланс в рублях')
    parser.add_argument('--risk', type=float, default=0.02, help='Риск на сделку')
    parser.add_argument('--leverage', type=int, default=1, help='Плечо')
    parser.add_argument('--output', type=str, help='Путь к файлу для сохранения результатов (CSV)')
    
    args = parser.parse_args()
    
    models = find_models_for_ticker(args.ticker)
    
    if not models:
        print(f"❌ Не найдено моделей для {args.ticker}")
        sys.exit(1)
    
    print(f"📦 Найдено {len(models)} моделей для {args.ticker}")
    
    results = []
    for model_path in models:
        metrics = run_backtest(
            model_path=model_path,
            ticker=args.ticker,
            days=args.days,
            interval=args.interval,
            balance=args.balance,
            risk=args.risk,
            leverage=args.leverage,
        )
        
        if metrics:
            metrics['model_path'] = model_path
            metrics['model_name'] = Path(model_path).name
            results.append(metrics)
    
    if not results:
        print(f"\n❌ Нет результатов")
        sys.exit(1)
    
    df_results = pd.DataFrame(results)
    
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"backtest_results_{args.ticker}_{timestamp}.csv")
    
    df_results.to_csv(output_path, index=False)
    print(f"\n✅ Результаты сохранены в: {output_path}")
    
    if 'sharpe_ratio' in df_results.columns:
        df_results = df_results.sort_values('sharpe_ratio', ascending=False)
        print(f"\n🏆 ТОП-5 МОДЕЛЕЙ:")
        for idx, row in df_results.head(5).iterrows():
            print(f"   {row['model_name']:40s} | Sharpe: {row.get('sharpe_ratio', 0):.2f}")


if __name__ == "__main__":
    main()
