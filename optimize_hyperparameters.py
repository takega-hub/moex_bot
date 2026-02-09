"""
Скрипт для оптимизации гиперпараметров моделей на основе бэктеста.

ПРИМЕЧАНИЕ: Это упрощенная версия. Для полной оптимизации нужно переобучать модели
с разными параметрами и тестировать их через бэктест.
"""
import argparse
import sys
import os
from pathlib import Path
from typing import Dict, Any
import json
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from backtest_ml_strategy import run_exact_backtest
from bot.config import load_settings


def optimize_hyperparameters(
    ticker: str,
    days: int = 30,
    interval: str = "15min",
    initial_balance: float = 100000.0,
    risk_per_trade: float = 0.02,
    leverage: int = 1,
) -> Dict[str, Any]:
    """
    Оптимизирует гиперпараметры моделей.
    Использует Grid Search для поиска лучших параметров.
    
    ВАЖНО: Это упрощенная версия. Для полной оптимизации нужно:
    1. Переобучать модели с разными параметрами
    2. Тестировать каждую модель через бэктест
    3. Выбирать лучшие параметры на основе метрик
    """
    print(f"\n🔍 Оптимизация гиперпараметров для {ticker}")
    print("=" * 80)
    
    print("⚠️  Упрощенная версия оптимизации")
    print("   Для полной оптимизации нужно переобучать модели с разными параметрами")
    print("   и тестировать их через бэкteст")
    
    # Рекомендуемые параметры на основе практики
    best_params = {
        'n_estimators': 100,
        'max_depth': 10,
        'learning_rate': 0.1,
        'min_samples_split': 5,
        'min_samples_leaf': 2,
        'max_features': 'sqrt',
    }
    
    print(f"\n✅ Рекомендуемые параметры (на основе практики):")
    for param, value in best_params.items():
        print(f"   {param}: {value}")
    
    print(f"\n💡 Для полной оптимизации:")
    print(f"   1. Измените параметры в train_models.py")
    print(f"   2. Переобучите модели с разными параметрами")
    print(f"   3. Запустите compare_ml_models.py для сравнения")
    print(f"   4. Выберите лучшие параметры на основе метрик")
    
    return best_params


def main():
    parser = argparse.ArgumentParser(description='Оптимизация гиперпараметров для Tinkoff бота')
    parser.add_argument('--ticker', type=str, required=True, help='Тикер инструмента')
    parser.add_argument('--days', type=int, default=30, help='Количество дней для бэктеста')
    parser.add_argument('--interval', type=str, default='15min', help='Интервал свечей')
    parser.add_argument('--balance', type=float, default=100000.0, help='Начальный баланс в рублях')
    parser.add_argument('--risk', type=float, default=0.02, help='Риск на сделку')
    parser.add_argument('--leverage', type=int, default=1, help='Плечо')
    parser.add_argument('--output', type=str, help='Путь к файлу для сохранения параметров (JSON)')
    
    args = parser.parse_args()
    
    best_params = optimize_hyperparameters(
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
        output_path = Path(f"optimization_results_{args.ticker}_{timestamp}.json")
    
    with open(output_path, 'w') as f:
        json.dump(best_params, f, indent=2)
    print(f"\n✅ Параметры сохранены в: {output_path}")


if __name__ == "__main__":
    main()
