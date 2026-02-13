"""
Скрипт для обучения ML моделей на исторических данных из CSV файлов.
Адаптирован для Tinkoff бота.
"""
import warnings
import os
import sys
from bot.ml.model_trainer import ModelTrainer, TripleEnsemble, QuadEnsemble, LIGHTGBM_AVAILABLE, LSTM_AVAILABLE

# Подавляем предупреждения
os.environ['PYTHONWARNINGS'] = 'ignore::UserWarning'
warnings.filterwarnings('ignore')

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

from bot.config import load_settings
from data.storage import DataStorage
from data.collector import DataCollector
from trading.client import TinkoffClient
from bot.ml.feature_engineering import FeatureEngineer
from bot.ml.model_trainer import ModelTrainer
from datetime import datetime, timedelta

# Функция для безопасного вывода
def safe_print(*args, **kwargs):
    """Безопасный print."""
    try:
        print(*args, **kwargs)
        sys.stdout.flush()
    except (UnicodeEncodeError, IOError):
        text = ' '.join(str(arg) for arg in args)
        print(text, **kwargs)


def main():
    """Обучение моделей."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Обучение ML моделей для Tinkoff бота",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Обучение для всех инструментов из конфига
  python train_models.py
  
  # Обучение для конкретного инструмента
  python train_models.py --ticker VBH6
  
  # Обучение БЕЗ MTF (только 15min фичи)
  python train_models.py --no-mtf
        """
    )
    parser.add_argument("--ticker", type=str, help="Тикер инструмента для обучения (если не указано, обучаются все из конфига)")
    parser.add_argument("--mtf", action="store_true", help="Использовать MTF фичи (1h)")
    parser.add_argument("--no-mtf", action="store_true", help="НЕ использовать MTF фичи (только 15min)")
    parser.add_argument("--interval", type=str, default="15min", choices=["15min", "1hour", "day"],
                       help="Базовый таймфрейм для обучения (по умолчанию: 15min)")
    parser.add_argument("--skip-update", action="store_true", help="Пропустить обновление исторических данных перед обучением")
    parser.add_argument("--update-days", type=int, default=180, help="Количество дней исторических данных для обновления (по умолчанию: 180)")
    
    args = parser.parse_args()
    
    safe_print("=" * 80)
    safe_print("ОБУЧЕНИЕ ML МОДЕЛЕЙ ДЛЯ TINKOFF БОТА")
    safe_print("=" * 80)
    
    # Загружаем настройки
    settings = load_settings()
    
    # Определяем инструменты
    if args.ticker:
        tickers = [args.ticker.upper()]
    elif settings.instruments:
        tickers = settings.instruments
    else:
        # По умолчанию
        tickers = ["VBH6", "SRH6", "GLDRUBF"]
        safe_print(f"Используются инструменты по умолчанию: {tickers}")
    
    # Определяем MTF режим
    ml_mtf_enabled = not args.no_mtf if args.no_mtf else (args.mtf if args.mtf else False)
    
    # Определяем интервал
    interval = args.interval
    if interval == "15min":
        base_interval = "15"
        interval_display = "15min"
    elif interval == "1hour":
        base_interval = "60"
        interval_display = "1h"
    else:
        base_interval = "15"
        interval_display = "15min"
    
    safe_print(f"Инструменты: {', '.join(tickers)}")
    safe_print(f"Таймфрейм: {interval_display}")
    safe_print(f"MTF: {'Включено' if ml_mtf_enabled else 'Выключено'}")
    safe_print("=" * 80)
    
    # Инициализируем хранилище данных
    storage = DataStorage()
    
    # Обновляем исторические данные перед обучением
    if not args.skip_update:
        safe_print("\n" + "=" * 80)
        safe_print("ОБНОВЛЕНИЕ ИСТОРИЧЕСКИХ ДАННЫХ")
        safe_print("=" * 80)
        
        try:
            client = TinkoffClient()
            collector = DataCollector(client=client, storage=storage)
            
            # Определяем интервалы для обновления
            intervals_to_update = [interval]
            if ml_mtf_enabled:
                intervals_to_update.extend(["1hour"])
            
            safe_print(f"Обновление данных для интервалов: {', '.join(intervals_to_update)}")
            safe_print(f"Период: {args.update_days} дней\n")
            
            for ticker in tickers:
                safe_print(f"Обновление данных для {ticker}...")
                
                # Получаем информацию об инструменте
                instrument_info = storage.get_instrument_by_ticker(ticker)
                if not instrument_info:
                    # Пытаемся найти инструмент через API
                    safe_print(f"  Инструмент {ticker} не найден в базе. Поиск через API...")
                    instrument_info = collector.collect_instrument_info(
                        ticker=ticker,
                        instrument_type="futures",
                        prefer_perpetual=False
                    )
                    if not instrument_info:
                        safe_print(f"  ❌ Инструмент {ticker} не найден. Пропускаем обновление.")
                        continue
                
                figi = instrument_info["figi"]
                safe_print(f"  FIGI: {figi}")
                
                # Обновляем данные для каждого интервала
                for update_interval in intervals_to_update:
                    safe_print(f"  Обновление {update_interval}...")
                    
                    # Сначала собираем исторические данные (если их нет)
                    to_date = datetime.now()
                    from_date = to_date - timedelta(days=args.update_days)
                    
                    candles_collected = collector.collect_candles(
                        figi=figi,
                        from_date=from_date,
                        to_date=to_date,
                        interval=update_interval,
                        save=True
                    )
                    
                    if candles_collected:
                        safe_print(f"    ✓ Собрано {len(candles_collected)} свечей")
                    else:
                        safe_print(f"    ℹ️  Данные уже актуальны или отсутствуют")
                    
                    # Затем обновляем до текущего момента
                    new_candles = collector.update_candles(
                        figi=figi,
                        interval=update_interval,
                        days_back=1
                    )
                    
                    if new_candles > 0:
                        safe_print(f"    ✓ Обновлено: {new_candles} новых свечей")
                    else:
                        safe_print(f"    ✓ Данные актуальны")
                
                safe_print(f"  ✓ Обновление для {ticker} завершено\n")
            
            safe_print("=" * 80)
            safe_print("ОБНОВЛЕНИЕ ДАННЫХ ЗАВЕРШЕНО")
            safe_print("=" * 80)
        except Exception as e:
            safe_print(f"⚠️  Ошибка при обновлении данных: {e}")
            safe_print("Продолжаем обучение на существующих данных...")
            import traceback
            traceback.print_exc()
    else:
        safe_print("\n⚠️  Обновление данных пропущено (--skip-update)")
    
    # Обучаем модели для каждого инструмента
    for ticker in tickers:
        safe_print("\n" + "=" * 80)
        safe_print(f"ОБУЧЕНИЕ МОДЕЛИ ДЛЯ {ticker}")
        safe_print("=" * 80)
        
        try:
            # Получаем информацию об инструменте
            instrument_info = storage.get_instrument_by_ticker(ticker)
            if not instrument_info:
                safe_print(f"Инструмент {ticker} не найден в базе. Пропускаем.")
                continue
            
            figi = instrument_info["figi"]
            
            # Загружаем данные из CSV
            safe_print(f"\n[1/5] Загрузка данных для {ticker}...")
            df_raw = storage.get_candles(
                figi=figi,
                interval=interval,
                limit=3000  # Берем последние 3000 свечей
            )
            
            if df_raw.empty:
                safe_print(f"Нет данных для {ticker}. Пропускаем.")
                continue
            
            # Переименовываем колонку time в timestamp для совместимости
            if "time" in df_raw.columns:
                df_raw = df_raw.rename(columns={"time": "timestamp"})
            
            # Устанавливаем timestamp как индекс
            if "timestamp" in df_raw.columns:
                df_raw["timestamp"] = pd.to_datetime(df_raw["timestamp"])
                df_raw = df_raw.set_index("timestamp")
            
            safe_print(f"Загружено {len(df_raw)} свечей")
            
            # Feature Engineering
            safe_print(f"\n[2/5] Создание признаков для {ticker}...")
            feature_engineer = FeatureEngineer()
            
            # Создаем технические индикаторы
            df_features = feature_engineer.create_technical_indicators(df_raw)
            
            if df_features.empty:
                safe_print(f"Не удалось создать фичи для {ticker}. Пропускаем.")
                continue
            
            # Добавляем MTF фичи, если нужно
            if ml_mtf_enabled:
                higher_timeframes = {}
                # Загружаем данные для высших таймфреймов (только 1hour для MTF стратегии)
                for htf_interval in ["1hour"]:
                    htf_df = storage.get_candles(
                        figi=figi,
                        interval=htf_interval,
                        limit=1000
                    )
                    if not htf_df.empty:
                        if "time" in htf_df.columns:
                            htf_df = htf_df.rename(columns={"time": "timestamp"})
                        if "timestamp" in htf_df.columns:
                            htf_df["timestamp"] = pd.to_datetime(htf_df["timestamp"])
                            htf_df = htf_df.set_index("timestamp")
                        higher_timeframes[htf_interval] = htf_df
                
                if higher_timeframes:
                    df_features = feature_engineer.add_mtf_features(df_features, higher_timeframes)
                    safe_print(f"Добавлены MTF фичи из {list(higher_timeframes.keys())}")
            
            feature_names = feature_engineer.get_feature_names()
            safe_print(f"Создано {len(feature_names)} признаков")
            
            # Создание таргета
            safe_print(f"\n[3/5] Создание целевой переменной...")
            forward_periods = 5 if base_interval == "15" else 2
            df_with_target = feature_engineer.create_target_variable(
                df_features,
                forward_periods=forward_periods,
                threshold_pct=0.3,
                use_atr_threshold=True,
                use_risk_adjusted=False,
                min_risk_reward_ratio=1.5,
                max_hold_periods=96 if base_interval == "15" else 24,
                min_profit_pct=0.3,
            )
            
            if df_with_target.empty or "target" not in df_with_target.columns:
                safe_print(f"Не удалось создать таргет для {ticker}. Пропускаем.")
                continue
            
            # Анализ распределения классов
            target_dist = df_with_target['target'].value_counts()
            safe_print(f"Распределение классов:")
            for label, count in target_dist.items():
                pct = count / len(df_with_target) * 100
                label_name = "LONG" if label == 1 else ("SHORT" if label == -1 else "HOLD")
                safe_print(f"  {label_name:5s}: {count:5d} ({pct:5.1f}%)")
            
            # Подготовка данных
            safe_print(f"\n[4/5] Подготовка данных для обучения...")
            X, y = feature_engineer.prepare_features_for_ml(df_with_target)
            
            if len(X) == 0 or len(y) == 0:
                safe_print(f"Недостаточно данных для обучения {ticker}. Пропускаем.")
                continue
            
            safe_print(f"Данные подготовлены: {X.shape[0]} samples × {X.shape[1]} features")
            
            # Проверяем количество сигналов
            signal_count = (y != 0).sum()
            if signal_count < 50:
                safe_print(f"Мало сигналов ({signal_count}). Смягчаю параметры таргета...")
                df_with_target = feature_engineer.create_target_variable(
                    df_features,
                    forward_periods=4,
                    threshold_pct=0.3,
                    use_atr_threshold=True,
                    use_risk_adjusted=False,
                    min_risk_reward_ratio=1.2,
                    max_hold_periods=144,
                    min_profit_pct=0.3,
                )
                X, y = feature_engineer.prepare_features_for_ml(df_with_target)
                signal_count = (y != 0).sum()
                safe_print(f"После смягчения: {signal_count} сигналов")
            
            # Обучение моделей
            safe_print(f"\n[5/5] Обучение моделей...")
            trainer = ModelTrainer()
            
            # Вычисляем веса классов
            from sklearn.utils.class_weight import compute_class_weight
            import numpy as np
            
            classes = np.unique(y)
            if len(classes) < 2:
                safe_print("Только один класс в данных. Пропускаем обучение.")
                continue
            
            base_weights = compute_class_weight('balanced', classes=classes, y=y)
            
            # Улучшенная балансировка
            class_counts = {}
            for cls in classes:
                class_counts[cls] = (y == cls).sum()
            
            long_count = class_counts.get(1, 0)
            short_count = class_counts.get(-1, 0)
            
            class_weight_dict = {}
            for i, cls in enumerate(classes):
                if cls == 0:  # HOLD
                    class_weight_dict[cls] = base_weights[i] * 0.3
                else:  # LONG or SHORT
                    base_weight = base_weights[i] * 2.0
                    class_weight_dict[cls] = base_weight
            
            safe_print(f"Веса классов:")
            for cls, weight in class_weight_dict.items():
                label_name = "LONG" if cls == 1 else ("SHORT" if cls == -1 else "HOLD")
                safe_print(f"  {label_name}: {weight:.2f}")
            
            # Формируем суффикс для имени файла
            mode_suffix = f"mtf_{interval_display}" if ml_mtf_enabled else interval_display
            
            # Обучаем Random Forest
            safe_print(f"\nОбучение Random Forest...")
            rf_model, rf_metrics = trainer.train_random_forest_classifier(
                X, y,
                n_estimators=100,
                max_depth=10,
                class_weight=class_weight_dict,
            )
            
            # Сохраняем модель
            rf_filename = f"rf_{ticker}_{base_interval}_{mode_suffix}.pkl"
            trainer.save_model(
                rf_model,
                trainer.scaler,
                feature_names,
                rf_metrics,
                rf_filename,
                symbol=ticker,
                interval=base_interval,
                class_weights=class_weight_dict,
                class_distribution=target_dist.to_dict(),
                training_params={
                    "n_estimators": 100,
                    "max_depth": 10,
                    "forward_periods": forward_periods,
                    "threshold_pct": 0.3,
                    "min_risk_reward_ratio": 1.5,
                },
            )
            safe_print(f"Сохранено: {rf_filename}")
            safe_print(f"Accuracy: {rf_metrics['accuracy']:.4f}")
            safe_print(f"CV Accuracy: {rf_metrics['cv_mean']:.4f} ± {rf_metrics['cv_std']*2:.4f}")
            
            # Обучаем XGBoost (если доступен)
            try:
                safe_print(f"\nОбучение XGBoost...")
                xgb_model, xgb_metrics = trainer.train_xgboost_classifier(
                    X, y,
                    n_estimators=100,
                    max_depth=6,
                    learning_rate=0.1,
                    class_weight=class_weight_dict,
                )
                
                xgb_filename = f"xgb_{ticker}_{base_interval}_{mode_suffix}.pkl"
                trainer.save_model(
                    xgb_model,
                    trainer.scaler,
                    feature_names,
                    xgb_metrics,
                    xgb_filename,
                    symbol=ticker,
                    interval=base_interval,
                    class_weights=class_weight_dict,
                    class_distribution=target_dist.to_dict(),
                    training_params={
                        "n_estimators": 100,
                        "max_depth": 6,
                        "learning_rate": 0.1,
                        "forward_periods": forward_periods,
                        "threshold_pct": 0.3,
                        "min_risk_reward_ratio": 1.5,
                    },
                )
                safe_print(f"Сохранено: {xgb_filename}")
                safe_print(f"Accuracy: {xgb_metrics['accuracy']:.4f}")
                safe_print(f"CV Accuracy: {xgb_metrics['cv_mean']:.4f} ± {xgb_metrics['cv_std']*2:.4f}")
            except Exception as e:
                safe_print(f"XGBoost не доступен: {e}")
            
            # Обучаем Ensemble (Weighted)
            try:
                rf_model
                xgb_model
                safe_print(f"\nОбучение Ensemble (RF + XGBoost)...")
                
                ensemble, ensemble_metrics = trainer.train_ensemble(
                    X, y,
                    rf_n_estimators=100,
                    rf_max_depth=10,
                    xgb_n_estimators=100,
                    xgb_max_depth=6,
                    xgb_learning_rate=0.1,
                    ensemble_method="weighted_average",
                    class_weight=class_weight_dict,
                )
                
                ensemble_filename = f"ensemble_{ticker}_{base_interval}_{mode_suffix}.pkl"
                trainer.save_model(
                    ensemble,
                    trainer.scaler,
                    feature_names,
                    ensemble_metrics,
                    ensemble_filename,
                    symbol=ticker,
                    interval=base_interval,
                    class_weights=class_weight_dict,
                    class_distribution=target_dist.to_dict(),
                    training_params={
                        "forward_periods": forward_periods,
                        "threshold_pct": 0.3,
                        "min_risk_reward_ratio": 1.5,
                    },
                )
                safe_print(f"Сохранено: {ensemble_filename}")
                safe_print(f"CV Accuracy: {ensemble_metrics.get('cv_mean', 0):.4f} ± {ensemble_metrics.get('cv_std', 0)*2:.4f}")
            except Exception as e:
                safe_print(f"Не удалось обучить ансамбль: {e}")
            
            # Обучаем Triple Ensemble (RF + XGBoost + LightGBM)
            try:
                rf_model
                xgb_model
                if LIGHTGBM_AVAILABLE:
                    safe_print(f"\nОбучение Triple Ensemble (RF + XGBoost + LightGBM)...")
                    
                    triple_ensemble, triple_metrics = trainer.train_ensemble(
                        X, y,
                        rf_n_estimators=100,
                        rf_max_depth=10,
                        xgb_n_estimators=100,
                        xgb_max_depth=6,
                        xgb_learning_rate=0.1,
                        ensemble_method="triple",
                        include_lightgbm=True,
                        lgb_n_estimators=100,
                        lgb_max_depth=6,
                        lgb_learning_rate=0.1,
                        class_weight=class_weight_dict,
                    )
                    
                    triple_filename = f"triple_ensemble_{ticker}_{base_interval}_{mode_suffix}.pkl"
                    trainer.save_model(
                        triple_ensemble,
                        trainer.scaler,
                        feature_names,
                        triple_metrics,
                        triple_filename,
                        symbol=ticker,
                        interval=base_interval,
                        class_weights=class_weight_dict,
                        class_distribution=target_dist.to_dict(),
                        training_params={
                            "forward_periods": forward_periods,
                            "threshold_pct": 0.3,
                            "min_risk_reward_ratio": 1.5,
                        },
                    )
                    safe_print(f"Сохранено: {triple_filename}")
                    safe_print(f"CV Accuracy: {triple_metrics.get('cv_mean', 0):.4f} ± {triple_metrics.get('cv_std', 0)*2:.4f}")
                else:
                    safe_print(f"⚠️  LightGBM не доступен, пропускаем Triple Ensemble")
            except Exception as e:
                safe_print(f"Не удалось обучить Triple ансамбль: {e}")
                import traceback
                traceback.print_exc()
            
            # Обучаем Quad Ensemble (RF + XGBoost + LightGBM + RF2)
            try:
                rf_model
                xgb_model
                if LIGHTGBM_AVAILABLE:
                    safe_print(f"\nОбучение Quad Ensemble (RF + XGBoost + LightGBM + RF2)...")
                    
                    quad_ensemble, quad_metrics = trainer.train_ensemble(
                        X, y,
                        rf_n_estimators=100,
                        rf_max_depth=10,
                        xgb_n_estimators=100,
                        xgb_max_depth=6,
                        xgb_learning_rate=0.1,
                        ensemble_method="quad",
                        include_lightgbm=True,
                        lgb_n_estimators=100,
                        lgb_max_depth=6,
                        lgb_learning_rate=0.1,
                        class_weight=class_weight_dict,
                    )
                    
                    quad_filename = f"quad_ensemble_{ticker}_{base_interval}_{mode_suffix}.pkl"
                    trainer.save_model(
                        quad_ensemble,
                        trainer.scaler,
                        feature_names,
                        quad_metrics,
                        quad_filename,
                        symbol=ticker,
                        interval=base_interval,
                        class_weights=class_weight_dict,
                        class_distribution=target_dist.to_dict(),
                        training_params={
                            "forward_periods": forward_periods,
                            "threshold_pct": 0.3,
                            "min_risk_reward_ratio": 1.5,
                        },
                    )
                    safe_print(f"Сохранено: {quad_filename}")
                    safe_print(f"CV Accuracy: {quad_metrics.get('cv_mean', 0):.4f} ± {quad_metrics.get('cv_std', 0)*2:.4f}")
                else:
                    safe_print(f"⚠️  LightGBM не доступен, пропускаем Quad Ensemble")
            except Exception as e:
                safe_print(f"Не удалось обучить Quad ансамбль: {e}")
                import traceback
                traceback.print_exc()
            
            safe_print(f"\nОбучение для {ticker} завершено!")
            
        except Exception as e:
            safe_print(f"Ошибка при обучении {ticker}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    safe_print("\n" + "=" * 80)
    safe_print("ОБУЧЕНИЕ ЗАВЕРШЕНО")
    safe_print("=" * 80)


if __name__ == "__main__":
    main()
