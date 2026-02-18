"""
Скрипт для оптимизации весов ансамблей на основе Sharpe ratio.
"""
import argparse
import sys
import os
from pathlib import Path
from typing import Dict, List
import json
from datetime import datetime
import numpy as np
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest_ml_strategy import run_exact_backtest
from bot.config import load_settings


def calculate_sharpe_from_backtest(metrics) -> float:
    """Вычисляет Sharpe ratio из метрик бэктеста."""
    if metrics is None or metrics.total_trades == 0:
        return 0.0
    return metrics.sharpe_ratio if hasattr(metrics, 'sharpe_ratio') else 0.0


def optimize_ensemble_weights(
    model_paths: List[str],
    ticker: str,
    days: int = 30,
    interval: str = "15min",
    initial_balance: float = 100000.0,
    risk_per_trade: float = 0.02,
    leverage: int = 1,
) -> Dict[str, float]:
    """Оптимизирует веса ансамбля на основе Sharpe ratio."""
    print(f"\nТестирование {len(model_paths)} моделей...")
    
    model_sharpes = {}
    for model_path in model_paths:
        try:
            metrics = run_exact_backtest(
                model_path=model_path,
                ticker=ticker,
                days_back=days,
                interval=interval,
                initial_balance=initial_balance,
                risk_per_trade=risk_per_trade,
                leverage=leverage,
            )
            sharpe = calculate_sharpe_from_backtest(metrics)
            model_sharpes[model_path] = sharpe
            print(f"   {Path(model_path).name}: Sharpe = {sharpe:.2f}")
        except Exception as e:
            print(f"   [WARNING] Ошибка для {Path(model_path).name}: {e}")
            model_sharpes[model_path] = 0.0
    
    def objective(weights):
        weighted_sharpe = sum(w * model_sharpes[path] for w, path in zip(weights, model_paths))
        penalty = 0.1 * sum((w - 1/len(weights))**2 for w in weights)
        return -(weighted_sharpe - penalty)
    
    constraints = {'type': 'eq', 'fun': lambda w: sum(w) - 1.0}
    bounds = [(0.0, 1.0) for _ in model_paths]
    initial_weights = [1.0 / len(model_paths)] * len(model_paths)
    
    print(f"\nОптимизация весов...")
    result = minimize(
        objective,
        initial_weights,
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
        options={'maxiter': 1000}
    )
    
    if not result.success:
        print(f"[WARNING] Оптимизация не сошлась, используем равномерные веса")
        optimal_weights = initial_weights
    else:
        optimal_weights = result.x
    
    weights_dict = {
        Path(path).name: float(weight)
        for path, weight in zip(model_paths, optimal_weights)
    }
    
    print(f"\n✅ Оптимизированные веса:")
    for model_name, weight in weights_dict.items():
        print(f"   {model_name}: {weight:.4f}")
    
    return weights_dict


def main():
    parser = argparse.ArgumentParser(description='Оптимизация весов ансамблей для Tinkoff бота')
    parser.add_argument('--ticker', type=str, required=True, help='Тикер инструмента')
    parser.add_argument('--models', type=str, required=True, help='Пути к моделям через запятую')
    parser.add_argument('--days', type=int, default=30, help='Количество дней для бэктеста')
    parser.add_argument('--interval', type=str, default='15min', help='Интервал свечей')
    parser.add_argument('--balance', type=float, default=100000.0, help='Начальный баланс в рублях')
    parser.add_argument('--risk', type=float, default=0.02, help='Риск на сделку')
    parser.add_argument('--leverage', type=int, default=1, help='Плечо')
    parser.add_argument('--output', type=str, help='Путь к файлу для сохранения весов (JSON)')
    
    args = parser.parse_args()
    
    model_paths = [p.strip() for p in args.models.split(",")]
    
    weights = optimize_ensemble_weights(
        model_paths=model_paths,
        ticker=args.ticker,
        days=args.days,
        interval=args.interval,
        initial_balance=args.balance,
        risk_per_trade=args.risk,
        leverage=args.leverage,
    )
    
    if args.output:
        output_path = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path(f"ensemble_weights_{args.ticker}_{timestamp}.json")
    
    with open(output_path, 'w') as f:
        json.dump(weights, f, indent=2)
    print(f"\n✅ Веса сохранены в: {output_path}")


if __name__ == "__main__":
    main()
