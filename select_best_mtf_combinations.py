"""
Скрипт для выбора лучших комбинаций MTF стратегий на основе результатов сравнения моделей.
"""
import pandas as pd
import json
from pathlib import Path
from typing import Dict, List, Tuple

def load_comparison_data(csv_path: str) -> pd.DataFrame:
    """Загрузить данные сравнения моделей из CSV."""
    df = pd.read_csv(csv_path)
    return df

def calculate_score(row: pd.Series) -> float:
    """
    Рассчитать комплексный score для модели.
    Учитывает: win_rate, total_pnl_pct, sharpe_ratio, profit_factor, max_drawdown_pct
    """
    # Нормализуем метрики (чем больше, тем лучше, кроме drawdown)
    win_rate_score = row['win_rate_pct'] / 100.0  # 0-1
    pnl_score = min(row['total_pnl_pct'] / 200.0, 1.0)  # Нормализуем до 200%
    sharpe_score = min(row['sharpe_ratio'] / 10.0, 1.0)  # Нормализуем до 10
    profit_factor_score = min(row['profit_factor'] / 5.0, 1.0)  # Нормализуем до 5
    drawdown_penalty = max(0, 1.0 - row['max_drawdown_pct'] / 20.0)  # Штраф за drawdown > 20%
    
    # Взвешенная сумма
    score = (
        win_rate_score * 0.25 +
        pnl_score * 0.30 +
        sharpe_score * 0.20 +
        profit_factor_score * 0.15 +
        drawdown_penalty * 0.10
    )
    
    return score

def select_best_models(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    Выбрать лучшие модели для каждого инструмента и таймфрейма.
    
    Returns:
        Dict с ключами: ticker -> {'1h': best_1h_model, '15min': best_15min_model}
    """
    results = {}
    
    # Получаем список всех инструментов
    tickers = df['ticker'].unique()
    
    for ticker in tickers:
        ticker_data = df[df['ticker'] == ticker].copy()
        
        # Рассчитываем score для каждой модели
        ticker_data['score'] = ticker_data.apply(calculate_score, axis=1)
        
        # Разделяем по таймфреймам
        models_1h = ticker_data[ticker_data['mode_suffix'] == '1h'].copy()
        models_15min = ticker_data[ticker_data['mode_suffix'] == '15min'].copy()
        
        # Выбираем лучшие модели
        best_1h = None
        best_15min = None
        
        if not models_1h.empty:
            best_1h = models_1h.loc[models_1h['score'].idxmax()]
        
        if not models_15min.empty:
            best_15min = models_15min.loc[models_15min['score'].idxmax()]
        
        results[ticker] = {
            '1h': best_1h.to_dict() if best_1h is not None else None,
            '15min': best_15min.to_dict() if best_15min is not None else None
        }
    
    return results

def print_recommendations(results: Dict[str, Dict]):
    """Вывести рекомендации по лучшим комбинациям."""
    print("=" * 80)
    print("РЕКОМЕНДУЕМЫЕ КОМБИНАЦИИ MTF СТРАТЕГИЙ")
    print("=" * 80)
    print()
    
    for ticker in sorted(results.keys()):
        print(f"📊 {ticker}")
        print("-" * 80)
        
        model_1h = results[ticker]['1h']
        model_15min = results[ticker]['15min']
        
        if model_1h is not None:
            print(f"  ✅ 1h модель (тренд/фильтр):")
            print(f"     Название: {model_1h['model_name']}")
            print(f"     Файл: {model_1h['model_filename']}")
            print(f"     Win Rate: {model_1h['win_rate_pct']:.2f}%")
            print(f"     PnL: {model_1h['total_pnl_pct']:.2f}%")
            print(f"     Sharpe: {model_1h['sharpe_ratio']:.2f}")
            print(f"     Profit Factor: {model_1h['profit_factor']:.2f}")
            print(f"     Max Drawdown: {model_1h['max_drawdown_pct']:.2f}%")
            print(f"     Score: {model_1h.get('score', 0):.4f}")
        else:
            print(f"  ⚠️  1h модель: не найдена")
        
        print()
        
        if model_15min is not None:
            print(f"  ✅ 15min модель (точка входа):")
            print(f"     Название: {model_15min['model_name']}")
            print(f"     Файл: {model_15min['model_filename']}")
            print(f"     Win Rate: {model_15min['win_rate_pct']:.2f}%")
            print(f"     PnL: {model_15min['total_pnl_pct']:.2f}%")
            print(f"     Sharpe: {model_15min['sharpe_ratio']:.2f}")
            print(f"     Profit Factor: {model_15min['profit_factor']:.2f}")
            print(f"     Max Drawdown: {model_15min['max_drawdown_pct']:.2f}%")
            print(f"     Score: {model_15min.get('score', 0):.4f}")
        else:
            print(f"  ⚠️  15min модель: не найдена")
        
        print()
        
        if model_1h is not None and model_15min is not None:
            print(f"  🎯 Комбинированная MTF стратегия:")
            print(f"     1h: {model_1h['model_filename']}")
            print(f"     15min: {model_15min['model_filename']}")
            print()
        
        print()

def save_recommendations_to_json(results: Dict[str, Dict], output_path: str):
    """Сохранить рекомендации в JSON файл."""
    # Преобразуем в формат, удобный для использования
    output = {}
    
    for ticker, models in results.items():
        output[ticker] = {}
        
        if models['1h'] is not None:
            output[ticker]['model_1h'] = {
                'filename': models['1h']['model_filename'],
                'name': models['1h']['model_name'],
                'path': models['1h']['model_path']
            }
        
        if models['15min'] is not None:
            output[ticker]['model_15m'] = {
                'filename': models['15min']['model_filename'],
                'name': models['15min']['model_name'],
                'path': models['15min']['model_path']
            }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Рекомендации сохранены в: {output_path}")

def main():
    """Основная функция."""
    csv_path = "ml_models_comparison_20260216_233323.csv"
    
    if not Path(csv_path).exists():
        print(f"❌ Файл {csv_path} не найден!")
        return
    
    print(f"📊 Загрузка данных из {csv_path}...")
    df = load_comparison_data(csv_path)
    
    print(f"✅ Загружено {len(df)} записей")
    print()
    
    print("🔍 Анализ моделей и выбор лучших комбинаций...")
    results = select_best_models(df)
    
    print()
    print_recommendations(results)
    
    # Сохраняем в JSON
    output_path = "best_mtf_combinations.json"
    save_recommendations_to_json(results, output_path)
    
    print()
    print("=" * 80)
    print("АНАЛИЗ ЗАВЕРШЕН")
    print("=" * 80)

if __name__ == "__main__":
    main()
