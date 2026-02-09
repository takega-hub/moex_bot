"""
Модуль для обучения ML-моделей на исторических данных.
"""
import warnings
import os
import sys

# Подавляем предупреждения scikit-learn ДО импорта библиотек
# Устанавливаем переменную окружения ПЕРВОЙ
os.environ['PYTHONWARNINGS'] = 'ignore::UserWarning'
os.environ['SKLEARN_WARNINGS'] = 'ignore'
os.environ['JOBLIB_TEMP_FOLDER'] = '/tmp'  # Для joblib

# Агрессивная фильтрация всех UserWarning
warnings.simplefilter('ignore', UserWarning)
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', module='sklearn')
warnings.filterwarnings('ignore', message='.*sklearn.*')
warnings.filterwarnings('ignore', message='.*parallel.*')
warnings.filterwarnings('ignore', message='.*delayed.*')
warnings.filterwarnings('ignore', message='.*sklearn.utils.parallel.*')
warnings.filterwarnings('ignore', message='.*should be used with.*')
warnings.filterwarnings('ignore', message='.*propagate the scikit-learn configuration.*')
warnings.filterwarnings('ignore', message='.*sklearn.utils.parallel.delayed.*')
warnings.filterwarnings('ignore', message='.*joblib.*')

# Перехватываем предупреждения на уровне stderr для подавления sklearn warnings
class WarningFilter:
    def __init__(self, original_stderr):
        self.original_stderr = original_stderr
        self.skip_patterns = [
            'sklearn.utils.parallel',
            'delayed',
            'joblib',
            'should be used with',
            'propagate the scikit-learn configuration'
        ]
    
    def write(self, message):
        # Пропускаем сообщения, содержащие паттерны предупреждений sklearn
        if any(pattern in message for pattern in self.skip_patterns):
            return
        self.original_stderr.write(message)
    
    def flush(self):
        self.original_stderr.flush()
    
    def __getattr__(self, name):
        # Проксируем все остальные атрибуты к оригинальному stderr
        return getattr(self.original_stderr, name)

# Сохраняем оригинальный stderr и устанавливаем фильтр
_original_stderr = sys.stderr
sys.stderr = WarningFilter(_original_stderr)

import pickle
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, VotingClassifier
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, precision_recall_fscore_support
from sklearn.preprocessing import StandardScaler
try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False
    xgb = None
    print("[model_trainer] Warning: XGBoost not available. Install with: pip install xgboost")
try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    lgb = None
    print("[model_trainer] Warning: LightGBM not available. Install with: pip install lightgbm")
from collections import Counter

from bot.ml.feature_engineering import FeatureEngineer

# Импорт для LSTM (опционально)
try:
    from bot.ml.lstm_model import LSTMTrainer
    LSTM_AVAILABLE = True
except ImportError:
    LSTM_AVAILABLE = False
    # LSTM is optional - no warning needed if not available


class PreTrainedVotingEnsemble:
    """Ансамбль с предобученными моделями для voting метода."""
    def __init__(self, rf_model, xgb_model, rf_weight, xgb_weight):
        self.rf_model = rf_model
        self.xgb_model = xgb_model
        self.rf_weight = rf_weight
        self.xgb_weight = xgb_weight
        self.classes_ = np.array([-1, 0, 1])  # SHORT, HOLD, LONG
    
    def predict_proba(self, X):
        # Получаем вероятности от обеих моделей
        rf_proba = self.rf_model.predict_proba(X)
        # Для XGBoost нужно преобразовать классы обратно
        xgb_proba = self.xgb_model.predict_proba(X)
        # XGBoost возвращает классы 0,1,2, нужно преобразовать в -1,0,1
        xgb_proba_reordered = np.zeros_like(rf_proba)
        xgb_proba_reordered[:, 0] = xgb_proba[:, 0]  # SHORT (0 -> -1)
        xgb_proba_reordered[:, 1] = xgb_proba[:, 1]  # HOLD (1 -> 0)
        xgb_proba_reordered[:, 2] = xgb_proba[:, 2]  # LONG (2 -> 1)
        
        # Взвешенное усреднение
        ensemble_proba = (self.rf_weight * rf_proba + 
                         self.xgb_weight * xgb_proba_reordered)
        return ensemble_proba
    
    def predict(self, X):
        proba = self.predict_proba(X)
        return self.classes_[np.argmax(proba, axis=1)]


class WeightedEnsemble:
    """Взвешенный ансамбль из RandomForest и XGBoost."""
    def __init__(self, rf_model, xgb_model, rf_weight=0.5, xgb_weight=0.5):
        self.rf_model = rf_model
        self.xgb_model = xgb_model
        self.rf_weight = rf_weight
        self.xgb_weight = xgb_weight
        self.classes_ = np.array([-1, 0, 1])  # SHORT, HOLD, LONG
    
    def predict_proba(self, X):
        """Предсказывает вероятности для всех классов."""
        # Получаем вероятности от обеих моделей
        rf_proba = self.rf_model.predict_proba(X)
        
        # Для XGBoost нужно преобразовать классы обратно
        xgb_proba = self.xgb_model.predict_proba(X)
        # XGBoost возвращает классы 0,1,2, нужно преобразовать в -1,0,1
        # Переупорядочиваем: [0,1,2] -> [-1,0,1]
        xgb_proba_reordered = np.zeros_like(rf_proba)
        xgb_proba_reordered[:, 0] = xgb_proba[:, 0]  # SHORT (0 -> -1)
        xgb_proba_reordered[:, 1] = xgb_proba[:, 1]  # HOLD (1 -> 0)
        xgb_proba_reordered[:, 2] = xgb_proba[:, 2]  # LONG (2 -> 1)
        
        # Взвешенное усреднение
        ensemble_proba = (self.rf_weight * rf_proba + 
                         self.xgb_weight * xgb_proba_reordered)
        return ensemble_proba
    
    def predict(self, X):
        """Предсказывает классы."""
        proba = self.predict_proba(X)
        return self.classes_[np.argmax(proba, axis=1)]


class TripleEnsemble:
    """Взвешенный ансамбль из RandomForest, XGBoost и LightGBM."""
    def __init__(self, rf_model, xgb_model, lgb_model, rf_weight=0.33, xgb_weight=0.33, lgb_weight=0.34):
        self.rf_model = rf_model
        self.xgb_model = xgb_model
        self.lgb_model = lgb_model
        self.rf_weight = rf_weight
        self.xgb_weight = xgb_weight
        self.lgb_weight = lgb_weight
        self.classes_ = np.array([-1, 0, 1])  # SHORT, HOLD, LONG
    
    def predict_proba(self, X):
        # Получаем вероятности от всех трех моделей
        rf_proba = self.rf_model.predict_proba(X)
        
        # Для XGBoost нужно преобразовать классы обратно
        xgb_proba = self.xgb_model.predict_proba(X)
        xgb_proba_reordered = np.zeros_like(rf_proba)
        xgb_proba_reordered[:, 0] = xgb_proba[:, 0]  # SHORT (0 -> -1)
        xgb_proba_reordered[:, 1] = xgb_proba[:, 1]  # HOLD (1 -> 0)
        xgb_proba_reordered[:, 2] = xgb_proba[:, 2]  # LONG (2 -> 1)
        
        # Для LightGBM тоже нужно преобразовать
        # Подавляем предупреждение о feature names (не критично для работы модели)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            lgb_proba = self.lgb_model.predict_proba(X)
        lgb_proba_reordered = np.zeros_like(rf_proba)
        lgb_proba_reordered[:, 0] = lgb_proba[:, 0]  # SHORT (0 -> -1)
        lgb_proba_reordered[:, 1] = lgb_proba[:, 1]  # HOLD (1 -> 0)
        lgb_proba_reordered[:, 2] = lgb_proba[:, 2]  # LONG (2 -> 1)
        
        # Взвешенное усреднение всех трех моделей
        ensemble_proba = (self.rf_weight * rf_proba + 
                         self.xgb_weight * xgb_proba_reordered +
                         self.lgb_weight * lgb_proba_reordered)
        return ensemble_proba
    
    def predict(self, X):
        proba = self.predict_proba(X)
        return self.classes_[np.argmax(proba, axis=1)]


class QuadEnsemble:
    """Взвешенный ансамбль из RandomForest, XGBoost, LightGBM и дополнительной модели."""
    def __init__(self, rf_model, xgb_model, lgb_model, rf_model2, rf_weight=0.25, xgb_weight=0.25, lgb_weight=0.25, rf2_weight=0.25):
        self.rf_model = rf_model
        self.xgb_model = xgb_model
        self.lgb_model = lgb_model
        self.rf_model2 = rf_model2
        self.rf_weight = rf_weight
        self.xgb_weight = xgb_weight
        self.lgb_weight = lgb_weight
        self.rf2_weight = rf2_weight
        self.classes_ = np.array([-1, 0, 1])  # SHORT, HOLD, LONG
    
    def predict_proba(self, X):
        # Получаем вероятности от всех четырех моделей
        rf_proba = self.rf_model.predict_proba(X)
        
        # Для XGBoost нужно преобразовать классы обратно
        xgb_proba = self.xgb_model.predict_proba(X)
        xgb_proba_reordered = np.zeros_like(rf_proba)
        xgb_proba_reordered[:, 0] = xgb_proba[:, 0]  # SHORT (0 -> -1)
        xgb_proba_reordered[:, 1] = xgb_proba[:, 1]  # HOLD (1 -> 0)
        xgb_proba_reordered[:, 2] = xgb_proba[:, 2]  # LONG (2 -> 1)
        
        # Для LightGBM тоже нужно преобразовать
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            lgb_proba = self.lgb_model.predict_proba(X)
        lgb_proba_reordered = np.zeros_like(rf_proba)
        lgb_proba_reordered[:, 0] = lgb_proba[:, 0]  # SHORT (0 -> -1)
        lgb_proba_reordered[:, 1] = lgb_proba[:, 1]  # HOLD (1 -> 0)
        lgb_proba_reordered[:, 2] = lgb_proba[:, 2]  # LONG (2 -> 1)
        
        # Вторая RF модель
        rf2_proba = self.rf_model2.predict_proba(X)
        
        # Взвешенное усреднение всех четырех моделей
        ensemble_proba = (self.rf_weight * rf_proba + 
                         self.xgb_weight * xgb_proba_reordered +
                         self.lgb_weight * lgb_proba_reordered +
                         self.rf2_weight * rf2_proba)
        return ensemble_proba
    
    def predict(self, X):
        proba = self.predict_proba(X)
        return self.classes_[np.argmax(proba, axis=1)]


class ModelTrainer:
    """
    Обучает ML-модели для предсказания движения цены.
    """
    
    def __init__(self, model_dir: Optional[Path] = None):
        if model_dir is None:
            model_dir = Path(__file__).parent.parent.parent / "ml_models"
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)
        
        self.scaler = StandardScaler()
        self.feature_engineer = FeatureEngineer()
    
    def train_random_forest_classifier(
        self,
        X: np.ndarray,
        y: np.ndarray,
        n_estimators: int = 100,
        max_depth: Optional[int] = None,
        min_samples_split: int = 2,
        random_state: int = 42,
        class_weight: Optional[Dict[int, float]] = None,
    ) -> Tuple[RandomForestClassifier, Dict[str, Any]]:
        """
        Обучает Random Forest классификатор.
        
        Args:
            X: Матрица фичей
            y: Целевая переменная (1 = LONG, -1 = SHORT, 0 = HOLD)
            n_estimators: Количество деревьев
            max_depth: Максимальная глубина дерева
            min_samples_split: Минимальное количество образцов для разделения
            random_state: Seed для воспроизводимости
            class_weight: Кастомные веса классов (если None, используется автоматическая балансировка)
        
        Returns:
            (model, metrics) - обученная модель и метрики
        """
        print(f"[model_trainer] Training Random Forest Classifier...")
        print(f"  Samples: {len(X)}, Features: {X.shape[1]}")
        print(f"  Class distribution: {np.bincount(y + 1)}")  # +1 чтобы индексы были 0,1,2
        
        # Нормализуем фичи
        X_scaled = self.scaler.fit_transform(X)
        
        # Определяем веса классов
        if class_weight is not None:
            # Используем переданные кастомные веса
            class_weights = class_weight
            print(f"  Using custom class weights: {class_weights}")
        else:
            # Вычисляем веса классов для более агрессивного обучения на LONG/SHORT
            # Увеличиваем вес для LONG и SHORT классов относительно HOLD
            unique_classes, class_counts = np.unique(y, return_counts=True)
            total_samples = len(y)
            class_weights = {}
            
            for cls, count in zip(unique_classes, class_counts):
                if count > 0:
                    # Используем обратную частоту, но с дополнительным весом для LONG/SHORT
                    base_weight = total_samples / (len(unique_classes) * count)
                    if cls != 0:  # LONG (1) или SHORT (-1) получают дополнительный вес
                        class_weights[int(cls)] = base_weight * 1.5  # +50% вес для торговых сигналов
                    else:  # HOLD (0) - базовый вес
                        class_weights[int(cls)] = base_weight * 0.8  # -20% вес для HOLD
            print(f"  Using auto-balanced class weights: {class_weights}")
        
        # Создаем и обучаем модель
        model = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            random_state=random_state,
            n_jobs=-1,  # Используем все ядра
            class_weight=class_weights if class_weights else "balanced",  # Используем кастомные веса
        )
        
        # Time-series cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        # Подавляем предупреждения при cross-validation
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            cv_scores = cross_val_score(model, X_scaled, y, cv=tscv, scoring="accuracy", n_jobs=1)  # n_jobs=1 чтобы избежать предупреждений joblib
        
        # Обучаем на всех данных
        model.fit(X_scaled, y)
        
        # Предсказания для оценки
        y_pred = model.predict(X_scaled)
        accuracy = accuracy_score(y, y_pred)
        
        # Метрики
        metrics = {
            "accuracy": accuracy,
            "cv_mean": cv_scores.mean(),
            "cv_std": cv_scores.std(),
            "classification_report": classification_report(y, y_pred, output_dict=True),
            "confusion_matrix": confusion_matrix(y, y_pred).tolist(),
            "feature_importance": dict(zip(
                self.feature_engineer.get_feature_names(),
                model.feature_importances_
            )),
        }
        
        print(f"[model_trainer] Training completed:")
        print(f"  Accuracy: {accuracy:.4f}")
        print(f"  CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std() * 2:.4f})")
        
        return model, metrics
    
    def train_xgboost_classifier(
        self,
        X: np.ndarray,
        y: np.ndarray,
        n_estimators: int = 100,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        random_state: int = 42,
        class_weight: Optional[Dict[int, float]] = None,
    ) -> Tuple[Any, Dict[str, Any]]:  # Any вместо xgb.XGBClassifier для совместимости
        """
        Обучает XGBoost классификатор.
        
        Args:
            X: Матрица фичей
            y: Целевая переменная
            n_estimators: Количество деревьев
            max_depth: Максимальная глубина дерева
            learning_rate: Скорость обучения
            random_state: Seed для воспроизводимости
            class_weight: Кастомные веса классов (если None, используется автоматическая балансировка)
        
        Returns:
            (model, metrics) - обученная модель и метрики
        """
        # Перепроверяем доступность XGBoost (на случай, если он был установлен после импорта модуля)
        try:
            import xgboost as xgb_check
            xgb_available = True
            # Используем локальный импорт для гарантии доступности
            xgb = xgb_check
        except ImportError:
            xgb_available = False
            # Если локальный импорт не удался, пробуем использовать глобальный
            if xgb is None:
                raise ImportError("XGBoost is not installed. Install with: pip install xgboost")
        
        if not xgb_available and not XGBOOST_AVAILABLE:
            raise ImportError("XGBoost is not installed. Install with: pip install xgboost")
        
        print(f"[model_trainer] Training XGBoost Classifier...")
        print(f"  Samples: {len(X)}, Features: {X.shape[1]}")
        
        # XGBoost может работать с ненормализованными данными, но нормализуем для консистентности
        X_scaled = self.scaler.fit_transform(X)
        
        # Преобразуем y для XGBoost (нужны индексы 0,1,2 вместо -1,0,1)
        y_xgb = y + 1  # -1,0,1 -> 0,1,2
        
        # Вычисляем веса образцов для XGBoost
        sample_weights = np.zeros(len(y_xgb))
        
        if class_weight is not None:
            # Используем переданные кастомные веса
            # Конвертируем класс-веса в веса образцов
            for orig_cls, weight in class_weight.items():
                xgb_cls = orig_cls + 1  # Преобразуем -1,0,1 -> 0,1,2
                sample_weights[y_xgb == xgb_cls] = weight
            print(f"  Using custom class weights (converted to sample_weights)")
        else:
            # Вычисляем веса классов для XGBoost (для классов 0,1,2)
            unique_classes, class_counts = np.unique(y_xgb, return_counts=True)
            total_samples = len(y_xgb)
            
            for cls, count in zip(unique_classes, class_counts):
                if count > 0:
                    base_weight = total_samples / (len(unique_classes) * count)
                    # Класс 1 (HOLD) - индекс 1 в XGBoost формате
                    if cls == 1:  # HOLD - уменьшаем вес
                        weight = base_weight * 0.8
                    else:  # LONG (2) или SHORT (0) - увеличиваем вес
                        weight = base_weight * 1.5
                    sample_weights[y_xgb == cls] = weight
            print(f"  Using auto-balanced sample weights")
        
        # Создаем и обучаем модель
        # Примечание: scale_pos_weight работает только для бинарной классификации,
        # поэтому не используем его для мультиклассовой задачи (3 класса)
        model = xgb.XGBClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=random_state,
            n_jobs=-1,
            eval_metric="mlogloss",
            # Балансировка классов выполняется через sample_weight в fit()
        )
        
        # Обучаем с весами образцов
        model.fit(X_scaled, y_xgb, sample_weight=sample_weights)
        
        # Time-series cross-validation (без весов, так как cross_val_score не поддерживает sample_weight напрямую)
        tscv = TimeSeriesSplit(n_splits=5)
        # Подавляем предупреждения при cross-validation
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            cv_scores = cross_val_score(model, X_scaled, y_xgb, cv=tscv, scoring="accuracy", n_jobs=1)  # n_jobs=1 чтобы избежать предупреждений joblib
        
        # Модель уже обучена выше с весами образцов
        
        # Предсказания
        y_pred_xgb = model.predict(X_scaled)
        y_pred = y_pred_xgb - 1  # Обратно в -1,0,1
        accuracy = accuracy_score(y, y_pred)
        
        # Метрики
        metrics = {
            "accuracy": accuracy,
            "cv_mean": cv_scores.mean(),
            "cv_std": cv_scores.std(),
            "classification_report": classification_report(y, y_pred, output_dict=True),
            "confusion_matrix": confusion_matrix(y, y_pred).tolist(),
            "feature_importance": dict(zip(
                self.feature_engineer.get_feature_names(),
                model.feature_importances_
            )),
        }
        
        print(f"[model_trainer] Training completed:")
        print(f"  Accuracy: {accuracy:.4f}")
        print(f"  CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std() * 2:.4f})")
        
        return model, metrics
    
    def train_lightgbm_classifier(
        self,
        X: np.ndarray,
        y: np.ndarray,
        n_estimators: int = 100,
        max_depth: int = 6,
        learning_rate: float = 0.1,
        random_state: int = 42,
        class_weight: Optional[Dict[int, float]] = None,
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Обучает LightGBM классификатор.
        
        Args:
            X: Матрица фичей
            y: Целевая переменная (-1 = SHORT, 0 = HOLD, 1 = LONG)
            n_estimators: Количество деревьев
            max_depth: Максимальная глубина дерева
            learning_rate: Скорость обучения
            random_state: Seed для воспроизводимости
            class_weight: Кастомные веса классов (если None, используется автоматическая балансировка)
        
        Returns:
            (model, metrics) - обученная модель и метрики
        """
        if not LIGHTGBM_AVAILABLE:
            raise ImportError("LightGBM is not installed. Install with: pip install lightgbm")
        
        print(f"[model_trainer] Training LightGBM Classifier...")
        print(f"  Samples: {len(X)}, Features: {X.shape[1]}")
        
        # LightGBM может работать с ненормализованными данными, но нормализуем для консистентности
        X_scaled = self.scaler.fit_transform(X)
        
        # Преобразуем y для LightGBM (нужны индексы 0,1,2 вместо -1,0,1)
        y_lgb = y + 1  # -1,0,1 -> 0,1,2
        
        # Вычисляем веса классов для LightGBM
        if class_weight is not None:
            # Используем переданные кастомные веса
            class_weights_dict = {}
            for orig_cls, weight in class_weight.items():
                lgb_cls = orig_cls + 1  # Преобразуем -1,0,1 -> 0,1,2
                class_weights_dict[int(lgb_cls)] = weight
            print(f"  Using custom class weights: {class_weights_dict}")
        else:
            # Вычисляем веса классов автоматически
            unique_classes, class_counts = np.unique(y_lgb, return_counts=True)
            total_samples = len(y_lgb)
            class_weights_dict = {}
            
            for cls, count in zip(unique_classes, class_counts):
                if count > 0:
                    base_weight = total_samples / (len(unique_classes) * count)
                    if cls == 1:  # HOLD - уменьшаем вес
                        class_weights_dict[int(cls)] = base_weight * 0.8
                    else:  # LONG (2) или SHORT (0) - увеличиваем вес
                        class_weights_dict[int(cls)] = base_weight * 1.5
            print(f"  Using auto-balanced class weights: {class_weights_dict}")
        
        # Создаем и обучаем модель
        model = lgb.LGBMClassifier(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            random_state=random_state,
            n_jobs=-1,
            verbose=-1,  # Отключаем вывод
            class_weight=class_weights_dict if class_weights_dict else None,
            objective='multiclass',
            num_class=3,
        )
        
        # Обучаем модель
        model.fit(X_scaled, y_lgb)
        
        # Time-series cross-validation
        tscv = TimeSeriesSplit(n_splits=5)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            cv_scores = cross_val_score(model, X_scaled, y_lgb, cv=tscv, scoring="accuracy", n_jobs=1)
        
        # Предсказания
        y_pred_lgb = model.predict(X_scaled)
        y_pred = y_pred_lgb - 1  # Обратно в -1,0,1
        accuracy = accuracy_score(y, y_pred)
        
        # Метрики
        metrics = {
            "accuracy": accuracy,
            "cv_mean": cv_scores.mean(),
            "cv_std": cv_scores.std(),
            "classification_report": classification_report(y, y_pred, output_dict=True),
            "confusion_matrix": confusion_matrix(y, y_pred).tolist(),
            "feature_importance": dict(zip(
                self.feature_engineer.get_feature_names(),
                model.feature_importances_
            )),
        }
        
        print(f"[model_trainer] Training completed:")
        print(f"  Accuracy: {accuracy:.4f}")
        print(f"  CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std() * 2:.4f})")
        
        return model, metrics
    
    def save_model(
        self, 
        model: Any, 
        scaler: StandardScaler, 
        feature_names: list, 
        metrics: Dict[str, Any], 
        filename: str,
        symbol: str = "ETHUSDT",
        interval: str = "15",
        model_type: Optional[str] = None,
        class_weights: Optional[Dict[int, float]] = None,
        class_distribution: Optional[Dict[int, int]] = None,
        training_params: Optional[Dict[str, Any]] = None,
    ):
        """Сохраняет модель, scaler, метрики и метаданные в файл."""
        filepath = self.model_dir / filename
        
        # Определяем model_type из имени файла, если не передан
        if model_type is None:
            filename_base = filename.replace('.pkl', '')
            parts = filename_base.split('_')
            if len(parts) >= 1:
                model_type = parts[0].lower()  # rf, xgb и т.д.
            else:
                model_type = "unknown"
        
        # Подготовка данных о распределении классов
        data_info = {}
        if class_distribution:
            data_info['class_distribution'] = class_distribution
            total = sum(class_distribution.values())
            data_info['total_rows'] = total
            data_info['class_percentages'] = {
                cls: (count / total * 100) for cls, count in class_distribution.items()
            } if total > 0 else {}
        
        # Для обычных моделей используем метрики напрямую
        accuracy = metrics.get("accuracy", 0.0)
        cv_mean = metrics.get("cv_mean", 0.0)
        cv_std = metrics.get("cv_std", 0.0)
        precision = metrics.get("precision", None)
        recall = metrics.get("recall", None)
        f1_score = metrics.get("f1_score", None)
        cv_f1_mean = metrics.get("cv_f1_mean", None)
        
        model_data = {
            "model": model,
            "scaler": scaler,
            "feature_names": feature_names,
            "metrics": metrics,
            "model_type": model_type,  # Для обратной совместимости (старый формат)
            "timestamp": datetime.now().isoformat(),  # Для обратной совместимости
            "data_info": data_info,  # Информация о данных обучения
            "class_weights": class_weights,  # Веса классов, использованные при обучении
            "training_params": training_params,  # Параметры обучения
            "metadata": {
                "symbol": symbol,
                "interval": interval,
                "model_type": model_type,
                "trained_at": datetime.now().isoformat(),
                "accuracy": accuracy,
                "cv_mean": cv_mean,
                "cv_std": cv_std,
                "precision": precision if precision is not None else 0.0,
                "recall": recall if recall is not None else 0.0,
                "f1_score": f1_score if f1_score is not None else 0.0,
                "cv_f1_mean": cv_f1_mean if cv_f1_mean is not None else 0.0,
                "rf_weight": metrics.get("rf_weight", None),  # Веса ансамбля (только для ансамблей)
                "xgb_weight": metrics.get("xgb_weight", None),
                "lgb_weight": metrics.get("lgb_weight", None),
                "rf2_weight": metrics.get("rf2_weight", None),  # Вес второй RF модели (для Quad ансамбля)
                "ensemble_method": metrics.get("ensemble_method", None),
            }
        }
        
        with open(filepath, "wb") as f:
            pickle.dump(model_data, f)
        
        print(f"[model_trainer] Model saved to {filepath}")
        return filepath
    
    def load_model_metadata(self, model_path: str) -> Optional[Dict[str, Any]]:
        """
        Загружает только метаданные модели без самой модели.
        """
        try:
            with open(model_path, "rb") as f:
                model_data = pickle.load(f)
                return model_data.get("metadata", {})
        except Exception as e:
            print(f"[model_trainer] Error loading model metadata: {e}")
            return None
    
    def load_model(self, filename: str) -> Dict[str, Any]:
        """Загружает модель из файла."""
        filepath = self.model_dir / filename
        
        with open(filepath, "rb") as f:
            model_data = pickle.load(f)
        
        print(f"[model_trainer] Model loaded from {filepath}")
        return model_data
    
    def train_ensemble(
        self,
        X: np.ndarray,
        y: np.ndarray,
        rf_n_estimators: int = 100,
        rf_max_depth: Optional[int] = 10,
        xgb_n_estimators: int = 100,
        xgb_max_depth: int = 6,
        xgb_learning_rate: float = 0.1,
        ensemble_method: str = "voting",  # "voting", "weighted_average" или "triple"
        random_state: int = 42,
        class_weight: Optional[Dict[int, float]] = None,
        include_lightgbm: bool = False,  # Включить LightGBM в ансамбль
        lgb_n_estimators: int = 100,
        lgb_max_depth: int = 6,
        lgb_learning_rate: float = 0.1,
    ) -> Tuple[Any, Dict[str, Any]]:
        """
        Обучает ансамбль из RandomForest и XGBoost.
        
        Args:
            X: Матрица фичей
            y: Целевая переменная (1 = LONG, -1 = SHORT, 0 = HOLD)
            rf_n_estimators: Количество деревьев для RandomForest
            rf_max_depth: Максимальная глубина для RandomForest
            xgb_n_estimators: Количество деревьев для XGBoost
            xgb_max_depth: Максимальная глубина для XGBoost
            xgb_learning_rate: Скорость обучения для XGBoost
            ensemble_method: Метод ансамбля ("voting" или "weighted_average")
            random_state: Seed для воспроизводимости
            class_weight: Кастомные веса классов (передаются в обе модели)
        
        Returns:
            (ensemble_model, metrics) - обученный ансамбль и метрики
        """
        ensemble_name = f"{ensemble_method}"
        if include_lightgbm and ensemble_method == "triple":
            ensemble_name = "triple (RF+XGB+LGB)"
        elif include_lightgbm and ensemble_method == "quad":
            ensemble_name = "quad (RF+XGB+LGB+RF2)"
        print(f"[model_trainer] Training Ensemble Model ({ensemble_name})...")
        print(f"  Samples: {len(X)}, Features: {X.shape[1]}")
        print(f"  Class distribution: {Counter(y)}")
        
        # Нормализуем фичи
        X_scaled = self.scaler.fit_transform(X)
        
        # Обучаем отдельные модели
        if include_lightgbm and ensemble_method == "quad":
            model_count = 4
        elif include_lightgbm and ensemble_method == "triple":
            model_count = 3
        else:
            model_count = 2
        
        print(f"\n  [1/{model_count}] Training RandomForest...")
        rf_model, rf_metrics = self.train_random_forest_classifier(
            X, y,
            n_estimators=rf_n_estimators,
            max_depth=rf_max_depth,
            random_state=random_state,
            class_weight=class_weight,  # Передаем веса классов
        )
        
        print(f"\n  [2/{model_count}] Training XGBoost...")
        xgb_model, xgb_metrics = self.train_xgboost_classifier(
            X, y,
            n_estimators=xgb_n_estimators,
            max_depth=xgb_max_depth,
            learning_rate=xgb_learning_rate,
            random_state=random_state,
            class_weight=class_weight,  # Передаем веса классов
        )
        
        lgb_model = None
        lgb_metrics = None
        
        # Если включен LightGBM и метод "triple" или "quad", обучаем LightGBM
        if include_lightgbm and ensemble_method in ("triple", "quad"):
            if not LIGHTGBM_AVAILABLE:
                print(f"\n  ⚠️  LightGBM not available, skipping...")
                include_lightgbm = False
            else:
                print(f"\n  [3/{model_count}] Training LightGBM...")
                lgb_model, lgb_metrics = self.train_lightgbm_classifier(
                    X, y,
                    n_estimators=lgb_n_estimators,
                    max_depth=lgb_max_depth,
                    learning_rate=lgb_learning_rate,
                    random_state=random_state,
                    class_weight=class_weight,  # Передаем веса классов
                )
        
        # Вычисляем веса на основе CV метрик
        rf_cv_score = rf_metrics.get("cv_mean", 0.5)
        xgb_cv_score = xgb_metrics.get("cv_mean", 0.5)
        
        rf2_weight = 0.0
        rf_model2 = None
        rf_metrics2 = None
        
        if include_lightgbm and lgb_model is not None:
            lgb_cv_score = lgb_metrics.get("cv_mean", 0.5)
            if ensemble_method == "quad":
                # Для quad ансамбля обучаем вторую RF модель
                print(f"\n  [4/{model_count}] Training RandomForest #2 (для Quad ансамбля)...")
                rf_model2, rf_metrics2 = self.train_random_forest_classifier(
                    X, y,
                    n_estimators=rf_n_estimators,
                    max_depth=rf_max_depth + 2 if rf_max_depth else None,  # Немного глубже
                    random_state=random_state + 1,  # Другой seed
                    class_weight=class_weight,
                )
                rf2_cv_score = rf_metrics2.get("cv_mean", 0.5)
                total_score = rf_cv_score + xgb_cv_score + lgb_cv_score + rf2_cv_score
                if total_score > 0:
                    rf_weight = rf_cv_score / total_score
                    xgb_weight = xgb_cv_score / total_score
                    lgb_weight = lgb_cv_score / total_score
                    rf2_weight = rf2_cv_score / total_score
                else:
                    rf_weight = xgb_weight = lgb_weight = rf2_weight = 0.25
            else:
                total_score = rf_cv_score + xgb_cv_score + lgb_cv_score
                if total_score > 0:
                    rf_weight = rf_cv_score / total_score
                    xgb_weight = xgb_cv_score / total_score
                    lgb_weight = lgb_cv_score / total_score
                else:
                    rf_weight = xgb_weight = lgb_weight = 1.0 / 3.0
        else:
            total_score = rf_cv_score + xgb_cv_score
            if total_score > 0:
                rf_weight = rf_cv_score / total_score
                xgb_weight = xgb_cv_score / total_score
            else:
                rf_weight = xgb_weight = 0.5
            lgb_weight = 0.0
        
        # Создаем ансамбль
        if ensemble_method == "quad" and include_lightgbm and lgb_model is not None and rf_model2 is not None:
            # Четверной ансамбль: RF + XGB + LGB + RF2
            ensemble = QuadEnsemble(rf_model, xgb_model, lgb_model, rf_model2, rf_weight, xgb_weight, lgb_weight, rf2_weight)
            print(f"  Ensemble weights: RF={rf_weight:.3f}, XGB={xgb_weight:.3f}, LGB={lgb_weight:.3f}, RF2={rf2_weight:.3f}")
        elif ensemble_method == "triple" and include_lightgbm and lgb_model is not None:
            # Тройной ансамбль: RF + XGB + LGB
            ensemble = TripleEnsemble(rf_model, xgb_model, lgb_model, rf_weight, xgb_weight, lgb_weight)
            print(f"  Ensemble weights: RF={rf_weight:.3f}, XGB={xgb_weight:.3f}, LGB={lgb_weight:.3f}")
        elif ensemble_method == "voting":
            # Используем класс, определенный на уровне модуля
            ensemble = PreTrainedVotingEnsemble(rf_model, xgb_model, rf_weight, xgb_weight)
            print(f"  Ensemble weights: RF={rf_weight:.3f}, XGB={xgb_weight:.3f}")
        elif ensemble_method == "weighted_average":
            # Используем класс, определенный на уровне модуля
            ensemble = WeightedEnsemble(rf_model, xgb_model, rf_weight, xgb_weight)
            print(f"  Ensemble weights: RF={rf_weight:.3f}, XGB={xgb_weight:.3f}")
        else:
            raise ValueError(f"Unknown ensemble_method: {ensemble_method}")
        
        # Улучшенная валидация: Walk-Forward Validation
        print(f"\n  Performing Walk-Forward Validation...")
        tscv = TimeSeriesSplit(n_splits=5)
        cv_scores = []
        cv_precision = []
        cv_recall = []
        cv_f1 = []
        
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            for fold, (train_idx, val_idx) in enumerate(tscv.split(X_scaled)):
                X_train_fold, X_val_fold = X_scaled[train_idx], X_scaled[val_idx]
                y_train_fold, y_val_fold = y[train_idx], y[val_idx]
                
                # Обучаем модели на fold
                # Обучаем RF на fold
                rf_fold = RandomForestClassifier(
                    n_estimators=rf_n_estimators,
                    max_depth=rf_max_depth,
                    random_state=random_state,
                    n_jobs=-1,
                    class_weight="balanced",
                )
                rf_fold.fit(X_train_fold, y_train_fold)
                
                # Обучаем XGBoost на fold
                y_train_xgb = y_train_fold + 1
                xgb_fold = xgb.XGBClassifier(
                    n_estimators=xgb_n_estimators,
                    max_depth=xgb_max_depth,
                    learning_rate=xgb_learning_rate,
                    random_state=random_state,
                    n_jobs=-1,
                    eval_metric="mlogloss",
                )
                xgb_fold.fit(X_train_fold, y_train_xgb)
                
                # Обучаем LightGBM на fold (если включен)
                lgb_fold = None
                if include_lightgbm and ensemble_method in ("triple", "quad") and LIGHTGBM_AVAILABLE:
                    y_train_lgb = y_train_fold + 1
                    lgb_fold = lgb.LGBMClassifier(
                        n_estimators=lgb_n_estimators,
                        max_depth=lgb_max_depth,
                        learning_rate=lgb_learning_rate,
                        random_state=random_state,
                        n_jobs=-1,
                        verbose=-1,
                        objective='multiclass',
                        num_class=3,
                    )
                    lgb_fold.fit(X_train_fold, y_train_lgb)
                
                # Обучаем вторую RF модель для quad ансамбля
                rf_fold2 = None
                if ensemble_method == "quad" and include_lightgbm and lgb_fold is not None:
                    rf_fold2 = RandomForestClassifier(
                        n_estimators=rf_n_estimators,
                        max_depth=rf_max_depth + 2 if rf_max_depth else None,
                        random_state=random_state + 1,
                        n_jobs=-1,
                        class_weight="balanced",
                    )
                    rf_fold2.fit(X_train_fold, y_train_fold)
                
                # Создаем ансамбль для fold
                if ensemble_method == "quad" and include_lightgbm and lgb_fold is not None and rf_fold2 is not None:
                    ensemble_fold = QuadEnsemble(rf_fold, xgb_fold, lgb_fold, rf_fold2, rf_weight, xgb_weight, lgb_weight, rf2_weight)
                elif ensemble_method == "triple" and include_lightgbm and lgb_fold is not None:
                    ensemble_fold = TripleEnsemble(rf_fold, xgb_fold, lgb_fold, rf_weight, xgb_weight, lgb_weight)
                elif ensemble_method == "voting":
                    ensemble_fold = PreTrainedVotingEnsemble(rf_fold, xgb_fold, rf_weight, xgb_weight)
                else:
                    ensemble_fold = WeightedEnsemble(rf_fold, xgb_fold, rf_weight, xgb_weight)
                
                y_pred_fold = ensemble_fold.predict(X_val_fold)
                
                # Метрики для fold
                fold_accuracy = accuracy_score(y_val_fold, y_pred_fold)
                precision, recall, f1, _ = precision_recall_fscore_support(
                    y_val_fold, y_pred_fold, average='weighted', zero_division=0
                )
                
                cv_scores.append(fold_accuracy)
                cv_precision.append(precision)
                cv_recall.append(recall)
                cv_f1.append(f1)
                
                print(f"    Fold {fold + 1}: Accuracy={fold_accuracy:.4f}, F1={f1:.4f}")
        
        # Предсказания на всех данных
        y_pred = ensemble.predict(X_scaled)
        accuracy = accuracy_score(y, y_pred)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y, y_pred, average='weighted', zero_division=0
        )
        
        # Метрики
        metrics = {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1,
            "cv_mean": np.mean(cv_scores),
            "cv_std": np.std(cv_scores),
            "cv_precision_mean": np.mean(cv_precision),
            "cv_recall_mean": np.mean(cv_recall),
            "cv_f1_mean": np.mean(cv_f1),
            "classification_report": classification_report(y, y_pred, output_dict=True),
            "confusion_matrix": confusion_matrix(y, y_pred).tolist(),
            "rf_metrics": rf_metrics,
            "xgb_metrics": xgb_metrics,
            "lgb_metrics": lgb_metrics if lgb_metrics else None,
            "ensemble_method": ensemble_method,
            "rf_weight": rf_weight,  # Веса ансамбля
            "xgb_weight": xgb_weight,
            "lgb_weight": lgb_weight if include_lightgbm else None,
            "rf2_weight": rf2_weight if ensemble_method == "quad" else None,
        }
        
        print(f"\n[model_trainer] Ensemble training completed:")
        print(f"  Accuracy: {accuracy:.4f}")
        print(f"  Precision: {precision:.4f}")
        print(f"  Recall: {recall:.4f}")
        print(f"  F1-Score: {f1:.4f}")
        print(f"  CV Accuracy: {metrics['cv_mean']:.4f} (+/- {metrics['cv_std'] * 2:.4f})")
        print(f"  CV F1-Score: {metrics['cv_f1_mean']:.4f}")
        if include_lightgbm and lgb_metrics:
            print(f"  LightGBM CV Accuracy: {lgb_metrics.get('cv_mean', 0):.4f}")
        
        return ensemble, metrics
