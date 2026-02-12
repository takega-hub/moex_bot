"""ML strategy for trading bot."""
import warnings
import os
import pickle
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np
import pandas as pd

# Suppress warnings
os.environ['PYTHONWARNINGS'] = 'ignore'
warnings.filterwarnings('ignore')

from bot.strategy import Action, Bias, Signal
from bot.ml.feature_engineering import FeatureEngineer
from utils.logger import logger


class MLStrategy:
    """ML strategy using trained model for price prediction."""
    
    def __init__(
        self,
        model_path: str,
        confidence_threshold: float = 0.35,
        min_signal_strength: str = "слабое",
        stability_filter: bool = True
    ):
        """
        Initialize ML strategy.
        
        Args:
            model_path: Path to saved model (.pkl file)
            confidence_threshold: Minimum confidence for opening position (0-1)
            min_signal_strength: Minimum signal strength
            stability_filter: Stability filter for direction changes
        """
        self.model_path = Path(model_path)
        self.confidence_threshold = confidence_threshold
        self.min_signal_strength = min_signal_strength
        self.stability_filter = stability_filter
        
        # Strength thresholds
        strength_thresholds = {
            "слабое": 0.0,
            "умеренное": 0.6,
            "среднее": 0.7,
            "сильное": 0.8,
            "очень_сильное": 0.9
        }
        self.min_strength_threshold = strength_thresholds.get(min_signal_strength, 0.6)
        
        # Load model
        self.model_data = self._load_model()
        if "model" not in self.model_data:
            raise KeyError(f"Model data missing 'model' key. Available: {list(self.model_data.keys())}")
        
        self.model = self.model_data["model"]
        self.scaler = self.model_data.get("scaler")
        self.feature_names = self.model_data.get("feature_names", [])
        
        # Initialize feature engineer
        self.feature_engineer = FeatureEngineer()
        
        # Log model type and key attributes
        model_type = type(self.model).__name__
        has_predict_proba = hasattr(self.model, 'predict_proba')
        has_classes = hasattr(self.model, 'classes_')
        classes_info = f", classes: {self.model.classes_}" if has_classes else ""
        
        logger.info(
            f"ML Strategy initialized: {model_path}, "
            f"model_type: {model_type}, "
            f"has_predict_proba: {has_predict_proba}, "
            f"features: {len(self.feature_names)}{classes_info}"
        )
    
    def _load_model(self) -> Dict[str, Any]:
        """Load model from file."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")
        
        try:
            with open(self.model_path, 'rb') as f:
                model_data = pickle.load(f)
            logger.info(f"Model loaded from {self.model_path}")
            return model_data
        except Exception as e:
            logger.error(f"Error loading model: {e}")
            raise
    
    def predict(
        self,
        df: pd.DataFrame,
        skip_feature_creation: bool = False,
    ) -> tuple[int, float]:
        """
        Получить предсказание модели без генерации полного сигнала.
        
        Args:
            df: DataFrame с историческими данными
            skip_feature_creation: Пропустить создание фичей (если уже созданы)
        
        Returns:
            (prediction, confidence) где:
            - prediction: 1 (LONG), -1 (SHORT), 0 (HOLD)
            - confidence: уверенность (0-1)
        """
        try:
            if df.empty or len(df) < 60:
                return 0, 0.0
            
            # Подготавливаем фичи
            if skip_feature_creation:
                features_df = df
            else:
                features_df = self.feature_engineer.prepare_features_for_prediction(df, lookback=60)
            
            if features_df is None or features_df.empty:
                return 0, 0.0
            
            # Выравниваем фичи с ожидаемыми моделью
            if self.feature_names:
                missing_features = set(self.feature_names) - set(features_df.columns)
                if missing_features:
                    for feat in missing_features:
                        features_df[feat] = 0.0
                features_df = features_df[self.feature_names]
            
            # Масштабируем фичи если есть scaler
            if self.scaler:
                try:
                    feature_array = self.scaler.transform(features_df.values)
                except Exception as e:
                    logger.debug(f"Error scaling features in predict: {e}")
                    feature_array = features_df.values
            else:
                feature_array = features_df.values
            
            # Предсказание
            try:
                prediction = self.model.predict(feature_array)
                probabilities = None
                
                if hasattr(self.model, 'predict_proba'):
                    try:
                        probabilities = self.model.predict_proba(feature_array)
                    except Exception:
                        probabilities = None
                
                # Получаем значение предсказания
                if isinstance(prediction, np.ndarray):
                    pred_value = int(prediction[-1]) if len(prediction) > 0 else 0
                else:
                    pred_value = int(prediction)
                
                # Преобразуем в формат: 1 (LONG), -1 (SHORT), 0 (HOLD)
                if pred_value == 1:
                    pred = 1
                elif pred_value == -1:
                    pred = -1
                else:
                    pred = 0
                
                # Рассчитываем уверенность
                confidence = 0.5
                if probabilities is not None and len(probabilities) > 0:
                    probs = probabilities[-1]  # Берем последнее предсказание
                    
                    if len(probs) >= 3:  # Три класса: -1, 0, 1
                        if pred == 1:
                            confidence = float(probs[2])  # Вероятность LONG
                        elif pred == -1:
                            confidence = float(probs[0])  # Вероятность SHORT
                        else:
                            confidence = float(probs[1])  # Вероятность HOLD
                    elif len(probs) == 2:  # Два класса
                        if pred == 1:
                            confidence = float(probs[1])
                        else:
                            confidence = float(probs[0])
                
                # Возвращаем предсказание и уверенность (порог проверяется в MTF стратегии)
                return pred, confidence
                
            except Exception as e:
                logger.error(f"Error in model prediction: {e}")
                return 0, 0.0
                
        except Exception as e:
            logger.error(f"Error in predict method: {e}")
            return 0, 0.0
    
    def generate_signal(
        self,
        row: pd.Series,
        df: pd.DataFrame,
        has_position: Optional[Bias] = None,
        current_price: float = None,
        leverage: int = 1
    ) -> Optional[Signal]:
        """
        Generate trading signal from model prediction.
        
        Args:
            row: Current row (last closed candle)
            df: Historical DataFrame
            has_position: Current position bias
            current_price: Current price
            leverage: Leverage
        
        Returns:
            Signal or None
        """
        try:
            if df.empty or len(df) < 60:
                logger.debug(f"generate_signal: insufficient data - {len(df)} candles, need 60")
                return None
            
            # Prepare features
            features_df = self.feature_engineer.prepare_features_for_prediction(df, lookback=60)
            if features_df is None or features_df.empty:
                logger.debug(f"generate_signal: failed to prepare features - df shape: {df.shape}")
                return None
            
            # Align features with model's expected features
            if self.feature_names:
                # Ensure we have all required features
                missing_features = set(self.feature_names) - set(features_df.columns)
                if missing_features:
                    logger.warning(f"Missing features: {missing_features}. Adding zeros...")
                    for feat in missing_features:
                        features_df[feat] = 0.0
                
                # Select only features that model expects, in the correct order
                features_df = features_df[self.feature_names]
            
            # Scale features if scaler available
            if self.scaler:
                try:
                    feature_array = self.scaler.transform(features_df.values)
                except Exception as e:
                    logger.warning(f"Error scaling features: {e}")
                    logger.warning(f"Expected {len(self.feature_names) if self.feature_names else 'unknown'} features, got {features_df.shape[1]}")
                    logger.warning(f"Feature names in model: {self.feature_names[:10]}...")
                    logger.warning(f"Feature names in data: {list(features_df.columns[:10])}...")
                    feature_array = features_df.values
            else:
                feature_array = features_df.values
            
            # Predict
            try:
                prediction = self.model.predict(feature_array)
                probabilities = None
                
                # Try to get probabilities
                if hasattr(self.model, 'predict_proba'):
                    try:
                        probabilities = self.model.predict_proba(feature_array)
                    except Exception as e:
                        logger.debug(f"Error getting predict_proba: {e}")
                        probabilities = None
                
                # Get prediction value
                if isinstance(prediction, np.ndarray):
                    pred_value = int(prediction[0]) if len(prediction) > 0 else 0
                else:
                    pred_value = int(prediction)
                
                # Determine action
                if pred_value == 1:
                    action = Action.LONG
                elif pred_value == -1:
                    action = Action.SHORT
                else:
                    action = Action.HOLD
                
                # Calculate confidence
                confidence = 0.5
                if probabilities is not None and len(probabilities) > 0:
                    probs = probabilities[0]
                    
                    # For ensemble models (TripleEnsemble, etc.), probabilities are ordered as [SHORT(-1), HOLD(0), LONG(1)]
                    if len(probs) >= 3:  # Three-class: -1, 0, 1
                        if action == Action.LONG:
                            confidence = float(probs[2])  # Probability of LONG (class 1)
                        elif action == Action.SHORT:
                            confidence = float(probs[0])  # Probability of SHORT (class -1)
                        else:  # HOLD
                            confidence = float(probs[1])  # Probability of HOLD (class 0)
                    elif len(probs) == 2:  # Binary classification
                        confidence = float(max(probs))
                    else:
                        confidence = 0.5
                    
                    logger.debug(
                        f"Prediction: {pred_value}, Action: {action.value}, "
                        f"Probs: {probs if len(probs) <= 3 else 'too many'}, "
                        f"Confidence: {confidence:.2%}"
                    )
                
                # Check confidence threshold
                if confidence < self.confidence_threshold:
                    # Low confidence - log at debug level only
                    logger.debug(
                        f"generate_signal: confidence {confidence:.2%} < threshold {self.confidence_threshold:.2%}, "
                        f"action: {action.value}, prediction: {pred_value}"
                    )
                    return None
                
                # Log successful signal generation (only for LONG/SHORT, not HOLD)
                if action != Action.HOLD:
                    logger.info(
                        f"generate_signal: ✅ Signal generated - action: {action.value}, "
                        f"confidence: {confidence:.2%}, prediction: {pred_value}, "
                        f"model_type: {type(self.model).__name__}"
                    )
                
                # Get current price
                if current_price is None:
                    current_price = float(row.get('close', 0))
                
                # Calculate TP/SL based on ATR or fixed percentage
                atr = None
                if 'atr' in row:
                    atr = float(row['atr'])
                elif 'atr' in df.columns:
                    atr = float(df['atr'].iloc[-1])
                
                # Risk/Reward ratio: 2.5:1 (TP = 2.5 * SL)
                risk_reward_ratio = 2.5
                
                # Default TP/SL percentages (SL = 1%, TP = 2.5%)
                sl_pct = 0.01  # 1%
                tp_pct = sl_pct * risk_reward_ratio  # 2.5%
                
                # Use ATR if available
                if atr and current_price > 0:
                    atr_pct = (atr / current_price)
                    sl_pct = max(0.005, atr_pct)
                    tp_pct = sl_pct * risk_reward_ratio  # TP = 2.5 * SL
                
                # Calculate TP/SL prices
                if action == Action.LONG:
                    take_profit = current_price * (1 + tp_pct)
                    stop_loss = current_price * (1 - sl_pct)
                elif action == Action.SHORT:
                    take_profit = current_price * (1 - tp_pct)
                    stop_loss = current_price * (1 + sl_pct)
                else:
                    # HOLD - no need to log, will be handled in trading_loop
                    return None
                
                # Create signal
                signal = Signal(
                    timestamp=pd.Timestamp.now(),
                    action=action,
                    reason=f"ml_prediction_confidence_{confidence:.2%}_strength_{self.min_signal_strength}",
                    price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    indicators_info={
                        'confidence': confidence,
                        'prediction': int(pred_value),
                        'strength': self.min_signal_strength,
                        'atr': atr,
                        'tp_pct': tp_pct,
                        'sl_pct': sl_pct
                    }
                )
                
                return signal
                
            except Exception as e:
                logger.error(f"Error generating signal: {e}")
                return None
                
        except Exception as e:
            logger.error(f"Error in generate_signal: {e}")
            return None
