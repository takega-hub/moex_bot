"""
Скрипт для выбора лучших комбинаций MTF стратегий из новых данных.
Сравнивает модели с MTF фичами и без них.
"""
import pandas as pd
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional

def load_comparison_data(csv_path: str) -> pd.DataFrame:
    """Загрузить данные сравнения моделей из CSV."""
    df = pd.read_csv(csv_path)
    return df

def calculate_composite_score(row: pd.Series) -> float:
    """
    Рассчитать комплексный score для модели.
    Учитывает: win_rate, total_pnl_pct, sharpe_ratio, profit_factor, max_drawdown_pct
    """
    # Нормализуем метрики
    win_rate_score = row['win_rate_pct'] / 100.0  # 0-1
    pnl_score = min(row['total_pnl_pct'] / 200.0, 1.0)  # Нормализуем до 200%
    sharpe_score = min(row['sharpe_ratio'] / 10.0, 1.0)  # Нормализуем до 10
    profit_factor_score = min(row['profit_factor'] / 5.0, 1.0)  # Нормализуем до 5
    drawdown_penalty = max(0, 1.0 - row['max_drawdown_pct'] / 20.0)  # Штраф за drawdown > 20%
    
    # Взвешенная сумма (приоритет: PnL, Sharpe, Win Rate)
    score = (
        win_rate_score * 0.20 +
        pnl_score * 0.30 +
        sharpe_score * 0.25 +
        profit_factor_score * 0.15 +
        drawdown_penalty * 0.10
    )
    
    return score

def is_mtf_model(model_name: str) -> bool:
    """Проверить, является ли модель MTF (содержит 'mtf' в названии)."""
    return 'mtf' in model_name.lower()

def select_best_models(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    Выбрать лучшие модели для каждого инструмента и таймфрейма.
    Сравнивает MTF и обычные модели.
    """
    results = {}
    
    # Получаем список всех инструментов
    tickers = df['ticker'].unique()
    
    for ticker in tickers:
        ticker_data = df[df['ticker'] == ticker].copy()
        
        # Рассчитываем score для каждой модели
        ticker_data['score'] = ticker_data.apply(calculate_composite_score, axis=1)
        ticker_data['is_mtf'] = ticker_data['model_name'].apply(is_mtf_model)
        
        # Разделяем по таймфреймам
        models_1h = ticker_data[ticker_data['mode_suffix'] == '1h'].copy()
        models_15min = ticker_data[ticker_data['mode_suffix'] == '15min'].copy()
        
        # Выбираем лучшие модели (сравниваем MTF и обычные)
        best_1h = None
        best_1h_mtf = None
        best_15min = None
        best_15min_mtf = None
        
        if not models_1h.empty:
            # Лучшая обычная 1h модель
            models_1h_normal = models_1h[~models_1h['is_mtf']]
            if not models_1h_normal.empty:
                best_1h = models_1h_normal.loc[models_1h_normal['score'].idxmax()]
            
            # Лучшая MTF 1h модель (если есть)
            models_1h_mtf_only = models_1h[models_1h['is_mtf']]
            if not models_1h_mtf_only.empty:
                best_1h_mtf = models_1h_mtf_only.loc[models_1h_mtf_only['score'].idxmax()]
        
        if not models_15min.empty:
            # Лучшая обычная 15min модель
            models_15min_normal = models_15min[~models_15min['is_mtf']]
            if not models_15min_normal.empty:
                best_15min = models_15min_normal.loc[models_15min_normal['score'].idxmax()]
            
            # Лучшая MTF 15min модель
            models_15min_mtf_only = models_15min[models_15min['is_mtf']]
            if not models_15min_mtf_only.empty:
                best_15min_mtf = models_15min_mtf_only.loc[models_15min_mtf_only['score'].idxmax()]
        
        results[ticker] = {
            '1h': {
                'normal': best_1h.to_dict() if best_1h is not None else None,
                'mtf': best_1h_mtf.to_dict() if best_1h_mtf is not None else None
            },
            '15min': {
                'normal': best_15min.to_dict() if best_15min is not None else None,
                'mtf': best_15min_mtf.to_dict() if best_15min_mtf is not None else None
            }
        }
    
    return results

def compare_mtf_vs_normal(models_dict: Dict) -> Tuple[Optional[Dict], Optional[Dict], str]:
    """
    Сравнить MTF и обычную модель, выбрать лучшую.
    Returns: (best_model, comparison_text, recommendation)
    """
    normal = models_dict.get('normal')
    mtf = models_dict.get('mtf')
    
    if normal is None and mtf is None:
        return None, "Модели не найдены", "N/A"
    
    if normal is None:
        return mtf, "Только MTF модель доступна", "MTF"
    
    if mtf is None:
        return normal, "Только обычная модель доступна", "Normal"
    
    # Сравниваем по score
    normal_score = normal.get('score', 0)
    mtf_score = mtf.get('score', 0)
    
    comparison = (
        f"Normal: score={normal_score:.4f}, PnL={normal['total_pnl_pct']:.2f}%, "
        f"Sharpe={normal['sharpe_ratio']:.2f}, WR={normal['win_rate_pct']:.2f}%\n"
        f"MTF:    score={mtf_score:.4f}, PnL={mtf['total_pnl_pct']:.2f}%, "
        f"Sharpe={mtf['sharpe_ratio']:.2f}, WR={mtf['win_rate_pct']:.2f}%"
    )
    
    if mtf_score > normal_score:
        return mtf, comparison, "MTF"
    else:
        return normal, comparison, "Normal"

def print_recommendations(results: Dict[str, Dict]):
    """Вывести рекомендации по лучшим комбинациям."""
    print("=" * 100)
    print("РЕКОМЕНДУЕМЫЕ КОМБИНАЦИИ MTF СТРАТЕГИЙ")
    print("=" * 100)
    print()
    
    for ticker in sorted(results.keys()):
        print(f"📊 {ticker}")
        print("-" * 100)
        
        # Выбираем лучшие модели
        best_1h, comp_1h, rec_1h = compare_mtf_vs_normal(results[ticker]['1h'])
        best_15min, comp_15min, rec_15min = compare_mtf_vs_normal(results[ticker]['15min'])
        
        # 1h модель
        print(f"  ✅ 1h модель (тренд/фильтр):")
        if best_1h is not None:
            print(f"     Название: {best_1h['model_name']}")
            print(f"     Файл: {best_1h['model_filename']}")
            print(f"     Тип: {'MTF' if is_mtf_model(best_1h['model_name']) else 'Normal'}")
            print(f"     Win Rate: {best_1h['win_rate_pct']:.2f}%")
            print(f"     PnL: {best_1h['total_pnl_pct']:.2f}%")
            print(f"     Sharpe: {best_1h['sharpe_ratio']:.2f}")
            print(f"     Profit Factor: {best_1h['profit_factor']:.2f}")
            print(f"     Max Drawdown: {best_1h['max_drawdown_pct']:.2f}%")
            print(f"     Score: {best_1h.get('score', 0):.4f}")
            print(f"     Сравнение:")
            for line in comp_1h.split('\n'):
                print(f"       {line}")
            print(f"     Рекомендация: {rec_1h}")
        else:
            print(f"     ⚠️ Модель не найдена")
        
        print()
        
        # 15min модель
        print(f"  ✅ 15min модель (точка входа):")
        if best_15min is not None:
            print(f"     Название: {best_15min['model_name']}")
            print(f"     Файл: {best_15min['model_filename']}")
            print(f"     Тип: {'MTF' if is_mtf_model(best_15min['model_name']) else 'Normal'}")
            print(f"     Win Rate: {best_15min['win_rate_pct']:.2f}%")
            print(f"     PnL: {best_15min['total_pnl_pct']:.2f}%")
            print(f"     Sharpe: {best_15min['sharpe_ratio']:.2f}")
            print(f"     Profit Factor: {best_15min['profit_factor']:.2f}")
            print(f"     Max Drawdown: {best_15min['max_drawdown_pct']:.2f}%")
            print(f"     Score: {best_15min.get('score', 0):.4f}")
            print(f"     Сравнение:")
            for line in comp_15min.split('\n'):
                print(f"       {line}")
            print(f"     Рекомендация: {rec_15min}")
        else:
            print(f"     ⚠️ Модель не найдена")
        
        print()
        
        # Финальная комбинация
        if best_1h is not None and best_15min is not None:
            print(f"  🎯 ФИНАЛЬНАЯ КОМБИНАЦИЯ MTF СТРАТЕГИИ:")
            print(f"     1h:   {best_1h['model_filename']} ({rec_1h})")
            print(f"     15min: {best_15min['model_filename']} ({rec_15min})")
            print()
        
        print()

def save_recommendations_to_json(results: Dict[str, Dict], output_path: str):
    """Сохранить рекомендации в JSON файл."""
    output = {}
    
    for ticker, models in results.items():
        output[ticker] = {}
        
        # Выбираем лучшие модели
        best_1h, _, rec_1h = compare_mtf_vs_normal(models['1h'])
        best_15min, _, rec_15min = compare_mtf_vs_normal(models['15min'])
        
        if best_1h is not None:
            output[ticker]['model_1h'] = {
                'filename': best_1h['model_filename'],
                'name': best_1h['model_name'],
                'path': best_1h['model_path'],
                'type': 'MTF' if is_mtf_model(best_1h['model_name']) else 'Normal',
                'recommendation': rec_1h,
                'score': best_1h.get('score', 0),
                'pnl_pct': best_1h['total_pnl_pct'],
                'sharpe': best_1h['sharpe_ratio'],
                'win_rate': best_1h['win_rate_pct']
            }
        
        if best_15min is not None:
            output[ticker]['model_15m'] = {
                'filename': best_15min['model_filename'],
                'name': best_15min['model_name'],
                'path': best_15min['model_path'],
                'type': 'MTF' if is_mtf_model(best_15min['model_name']) else 'Normal',
                'recommendation': rec_15min,
                'score': best_15min.get('score', 0),
                'pnl_pct': best_15min['total_pnl_pct'],
                'sharpe': best_15min['sharpe_ratio'],
                'win_rate': best_15min['win_rate_pct']
            }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Рекомендации сохранены в: {output_path}")

def analyze_mtf_vs_normal_overall(df: pd.DataFrame):
    """Общий анализ: MTF vs Normal модели."""
    df['is_mtf'] = df['model_name'].apply(is_mtf_model)
    df['score'] = df.apply(calculate_composite_score, axis=1)
    
    print("=" * 100)
    print("ОБЩИЙ АНАЛИЗ: MTF vs NORMAL МОДЕЛИ")
    print("=" * 100)
    print()
    
    # Статистика по всем моделям
    mtf_models = df[df['is_mtf']]
    normal_models = df[~df['is_mtf']]
    
    print(f"📊 Статистика:")
    print(f"   MTF моделей: {len(mtf_models)}")
    print(f"   Normal моделей: {len(normal_models)}")
    print()
    
    if len(mtf_models) > 0 and len(normal_models) > 0:
        print(f"📈 Средние показатели:")
        print(f"   MTF:")
        print(f"      Средний Score: {mtf_models['score'].mean():.4f}")
        print(f"      Средний PnL: {mtf_models['total_pnl_pct'].mean():.2f}%")
        print(f"      Средний Sharpe: {mtf_models['sharpe_ratio'].mean():.2f}")
        print(f"      Средний Win Rate: {mtf_models['win_rate_pct'].mean():.2f}%")
        print(f"      Средний Profit Factor: {mtf_models['profit_factor'].mean():.2f}")
        print()
        print(f"   Normal:")
        print(f"      Средний Score: {normal_models['score'].mean():.4f}")
        print(f"      Средний PnL: {normal_models['total_pnl_pct'].mean():.2f}%")
        print(f"      Средний Sharpe: {normal_models['sharpe_ratio'].mean():.2f}")
        print(f"      Средний Win Rate: {normal_models['win_rate_pct'].mean():.2f}%")
        print(f"      Средний Profit Factor: {normal_models['profit_factor'].mean():.2f}")
        print()
        
        # Сравнение
        if mtf_models['score'].mean() > normal_models['score'].mean():
            print(f"   ✅ MTF модели показывают лучшие результаты!")
        else:
            print(f"   ✅ Normal модели показывают лучшие результаты!")
        print()
    
    # Анализ по таймфреймам
    print(f"📊 Анализ по таймфреймам:")
    for timeframe in ['1h', '15min']:
        tf_models = df[df['mode_suffix'] == timeframe]
        if len(tf_models) > 0:
            tf_mtf = tf_models[tf_models['is_mtf']]
            tf_normal = tf_models[~tf_models['is_mtf']]
            
            print(f"   {timeframe}:")
            if len(tf_mtf) > 0:
                print(f"      MTF: {len(tf_mtf)} моделей, средний Score: {tf_mtf['score'].mean():.4f}")
            if len(tf_normal) > 0:
                print(f"      Normal: {len(tf_normal)} моделей, средний Score: {tf_normal['score'].mean():.4f}")
            print()
    
    print("=" * 100)
    print()

def main():
    """Основная функция."""
    csv_path = "ml_models_comparison_20260217_021127.csv"
    
    if not Path(csv_path).exists():
        print(f"❌ Файл {csv_path} не найден!")
        return
    
    print(f"📊 Загрузка данных из {csv_path}...")
    df = load_comparison_data(csv_path)
    
    print(f"✅ Загружено {len(df)} записей")
    print()
    
    # Общий анализ MTF vs Normal
    analyze_mtf_vs_normal_overall(df)
    
    print("🔍 Анализ моделей и выбор лучших комбинаций...")
    results = select_best_models(df)
    
    print()
    print_recommendations(results)
    
    # Сохраняем в JSON
    output_path = "best_mtf_combinations_20260217.json"
    save_recommendations_to_json(results, output_path)
    
    print()
    print("=" * 100)
    print("АНАЛИЗ ЗАВЕРШЕН")
    print("=" * 100)

if __name__ == "__main__":
    main()
