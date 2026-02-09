"""Data preprocessing and feature engineering."""
import pandas as pd
import numpy as np
from typing import Optional, List, Dict
import logging

from utils.logger import logger
from data.advanced_features import AdvancedFeatureEngineer

class DataPreprocessor:
    """Preprocess market data and create features for ML."""
    
    def __init__(self, use_advanced_features: bool = True):
        """
        Initialize preprocessor.
        
        Args:
            use_advanced_features: If True, use advanced feature engineering (100+ features)
        """
        self.use_advanced_features = use_advanced_features
        if use_advanced_features:
            self.advanced_fe = AdvancedFeatureEngineer()
    
    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators.
        
        Args:
            df: DataFrame with columns: time, open, high, low, close, volume
        
        Returns:
            DataFrame with added technical indicators
        """
        if df.empty:
            return df
        
        df = df.copy()
        df = df.sort_values('time')
        
        # RSI (Relative Strength Index)
        df['rsi'] = self._calculate_rsi(df['close'], period=14)
        
        # Moving Averages
        df['sma_5'] = df['close'].rolling(window=5).mean()
        df['sma_10'] = df['close'].rolling(window=10).mean()
        df['sma_20'] = df['close'].rolling(window=20).mean()
        df['sma_50'] = df['close'].rolling(window=50).mean()
        df['ema_12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema_26'] = df['close'].ewm(span=26, adjust=False).mean()
        
        # MACD
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        
        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        df['bb_width'] = df['bb_upper'] - df['bb_lower']
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        # ATR (Average True Range)
        df['atr'] = self._calculate_atr(df, period=14)
        
        # Stochastic Oscillator
        df['stoch_k'], df['stoch_d'] = self._calculate_stochastic(df, period=14)
        
        # Volume indicators
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # Price changes
        df['price_change'] = df['close'].pct_change()
        df['price_change_abs'] = df['close'].diff()
        df['high_low_ratio'] = df['high'] / df['low']
        df['close_open_ratio'] = df['close'] / df['open']
        
        # Volatility
        df['volatility'] = df['close'].rolling(window=20).std()
        df['volatility_pct'] = df['volatility'] / df['close']
        
        # Momentum
        df['momentum'] = df['close'].diff(periods=10)
        df['roc'] = ((df['close'] - df['close'].shift(10)) / df['close'].shift(10)) * 100
        
        # Support/Resistance levels (simplified)
        df['resistance'] = df['high'].rolling(window=20).max()
        df['support'] = df['low'].rolling(window=20).min()
        
        return df
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate ATR (Average True Range)."""
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        
        atr = true_range.rolling(window=period).mean()
        return atr
    
    def _calculate_stochastic(
        self,
        df: pd.DataFrame,
        period: int = 14
    ) -> tuple[pd.Series, pd.Series]:
        """Calculate Stochastic Oscillator."""
        low_min = df['low'].rolling(window=period).min()
        high_max = df['high'].rolling(window=period).max()
        
        stoch_k = 100 * ((df['close'] - low_min) / (high_max - low_min))
        stoch_d = stoch_k.rolling(window=3).mean()
        
        return stoch_k, stoch_d
    
    def create_features(self, df: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
        """
        Create features for ML model.
        
        Args:
            df: DataFrame with candles and technical indicators
            lookback: Number of past candles to use as features (minimum required for indicators)
        
        Returns:
            DataFrame with features
        """
        if df.empty or len(df) < max(lookback, 60):
            return pd.DataFrame()
        
        df = df.copy()
        df = df.sort_values('time')
        
        # Use advanced features if enabled
        if self.use_advanced_features and hasattr(self, 'advanced_fe'):
            try:
                # Create advanced features (100+ features)
                df_with_features = self.advanced_fe.create_advanced_features(df)
                
                if df_with_features.empty:
                    logger.warning("Advanced features returned empty DataFrame, falling back to basic features")
                    df_with_features = self.calculate_technical_indicators(df)
                else:
                    # Use all features except OHLCV and time
                    exclude_cols = ['open', 'high', 'low', 'close', 'volume', 'time', 'figi', 'ticker', 'timeframe', 'interval']
                    # Select only numeric columns
                    numeric_cols = df_with_features.select_dtypes(include=[np.number]).columns
                    feature_cols = [col for col in numeric_cols if col not in exclude_cols]
                    
                    # Select only feature columns
                    features_df = df_with_features[feature_cols + ['time']].copy()
                    
                    # Drop rows with too many NaN (keep rows where at least 50% features are valid)
                    features_df = features_df.dropna(thresh=len(feature_cols) * 0.5)
                    
                    return features_df
            except Exception as e:
                logger.warning(f"Error creating advanced features: {e}, falling back to basic features")
                # Fall through to basic features
        
        # Fallback to basic features
        # Calculate technical indicators if not present
        if 'rsi' not in df.columns:
            df = self.calculate_technical_indicators(df)
        
        # Select feature columns
        feature_columns = [
            'open', 'high', 'low', 'close', 'volume',
            'rsi', 'sma_5', 'sma_10', 'sma_20', 'sma_50',
            'ema_12', 'ema_26', 'macd', 'macd_signal', 'macd_histogram',
            'bb_upper', 'bb_middle', 'bb_lower', 'bb_width', 'bb_position',
            'atr', 'stoch_k', 'stoch_d',
            'volume_ratio', 'price_change', 'volatility', 'momentum', 'roc'
        ]
        
        # Filter available columns
        available_features = [col for col in feature_columns if col in df.columns]
        
        # Create lagged features
        feature_data = []
        for i in range(lookback, len(df)):
            row_features = []
            # Current values
            for col in available_features:
                row_features.append(df[col].iloc[i])
            # Lagged values (past 5, 10, 20 periods)
            for lag in [5, 10, 20]:
                if i >= lag:
                    for col in available_features:
                        row_features.append(df[col].iloc[i - lag])
                else:
                    # Pad with NaN if not enough history
                    row_features.extend([np.nan] * len(available_features))
            
            feature_data.append(row_features)
        
        if not feature_data:
            return pd.DataFrame()
        
        # Create feature names
        feature_names = available_features.copy()
        for lag in [5, 10, 20]:
            feature_names.extend([f"{col}_lag{lag}" for col in available_features])
        
        # Create DataFrame
        features_df = pd.DataFrame(feature_data, columns=feature_names)
        features_df['time'] = df['time'].iloc[lookback:].values
        
        # Drop rows with NaN
        features_df = features_df.dropna()
        
        return features_df
    
    def create_targets(
        self,
        df: pd.DataFrame,
        prediction_horizon: int = 5,
        target_type: str = "classification",
        threshold_pct: float = 0.5,
        use_atr_threshold: bool = True,
        min_profit_pct: float = 0.3
    ) -> pd.Series:
        """
        Create target variables for ML with improved logic.
        
        Args:
            df: DataFrame with price data
            prediction_horizon: Number of periods ahead to predict
            target_type: "classification" (up/down/hold) or "regression" (price change)
            threshold_pct: Minimum price change percentage to consider as signal (default: 0.5%)
            use_atr_threshold: Use dynamic threshold based on ATR (default: True)
            min_profit_pct: Minimum profit percentage to consider as valid signal (default: 0.3%)
        
        Returns:
            Series with targets (-1 = SHORT, 0 = HOLD, 1 = LONG for classification)
        """
        if df.empty or len(df) < prediction_horizon:
            return pd.Series()
        
        df = df.copy()
        df = df.sort_values('time')
        
        # Ensure we have ATR if using dynamic threshold
        if use_atr_threshold and 'atr_pct' not in df.columns:
            if 'atr' in df.columns:
                df['atr_pct'] = (df['atr'] / df['close']) * 100
            else:
                # Calculate ATR if not present
                if self.use_advanced_features and hasattr(self, 'advanced_fe'):
                    df = self.advanced_fe.create_advanced_features(df)
                else:
                    df = self.calculate_technical_indicators(df)
                if 'atr_pct' not in df.columns and 'atr' in df.columns:
                    df['atr_pct'] = (df['atr'] / df['close']) * 100
        
        # Calculate future price
        current_price = df['close'].values
        future_price = np.zeros_like(current_price)
        for i in range(len(current_price)):
            if i + prediction_horizon < len(current_price):
                future_price[i] = current_price[i + prediction_horizon]
            else:
                future_price[i] = current_price[-1]  # Last known price
        
        # Calculate percentage change
        with np.errstate(divide='ignore', invalid='ignore'):
            price_change_pct = np.where(
                current_price > 0,
                (future_price - current_price) / current_price * 100,
                0
            )
        
        if target_type == "classification":
            # Multi-class classification: -1 = SHORT, 0 = HOLD, 1 = LONG
            target = np.zeros(len(df), dtype=int)
            
            # Dynamic threshold based on ATR
            if use_atr_threshold and 'atr_pct' in df.columns:
                atr_pct = df['atr_pct'].values
                dynamic_threshold = np.minimum(threshold_pct, atr_pct * 0.8)
            else:
                dynamic_threshold = np.full(len(df), threshold_pct)
            
            for i in range(len(df) - prediction_horizon):
                change = price_change_pct[i]
                threshold = dynamic_threshold[i]
                
                # LONG: profit > threshold AND >= min_profit_pct
                if change > threshold and change >= min_profit_pct:
                    target[i] = 1
                # SHORT: loss > threshold AND >= min_profit_pct
                elif change < -threshold and abs(change) >= min_profit_pct:
                    target[i] = -1
                # Otherwise: HOLD (0)
            
            targets = pd.Series(target, index=df.index)
        else:
            # Regression: percentage change
            targets = pd.Series(price_change_pct, index=df.index)
        
        # Remove last N rows (no future data)
        if len(targets) > prediction_horizon:
            targets = targets.iloc[:-prediction_horizon]
        
        return targets
    
    def normalize_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, Dict]:
        """
        Normalize features using Min-Max scaling.
        
        Returns:
            Normalized DataFrame and scaling parameters
        """
        if df.empty:
            return df, {}
        
        df = df.copy()
        scaling_params = {}
        
        # Exclude time column
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        if 'time' in df.columns:
            numeric_cols = numeric_cols.drop('time')
        
        for col in numeric_cols:
            col_min = df[col].min()
            col_max = df[col].max()
            
            if col_max > col_min:
                df[col] = (df[col] - col_min) / (col_max - col_min)
                scaling_params[col] = {'min': col_min, 'max': col_max}
        
        return df, scaling_params
    
    def prepare_training_data(
        self,
        df: pd.DataFrame,
        lookback: int = 60,
        prediction_horizon: int = 5,
        target_type: str = "classification",
        threshold_pct: float = 0.5,
        min_profit_pct: float = 0.3,
        use_atr_threshold: bool = True
    ) -> tuple[pd.DataFrame, pd.Series]:
        """
        Prepare complete training dataset with improved target creation.
        
        Args:
            df: DataFrame with market data
            lookback: Number of past candles for features
            prediction_horizon: Number of periods ahead to predict
            target_type: "classification" or "regression"
            threshold_pct: Minimum price change percentage for target labeling
            min_profit_pct: Minimum profit percentage for valid signal
            use_atr_threshold: Use dynamic threshold based on ATR
        
        Returns:
            Features DataFrame and targets Series
        """
        # Calculate indicators (use advanced features if enabled)
        if self.use_advanced_features and hasattr(self, 'advanced_fe'):
            try:
                df_with_indicators = self.advanced_fe.create_advanced_features(df)
                if df_with_indicators.empty:
                    logger.warning("Advanced features returned empty, falling back to basic indicators")
                    df_with_indicators = self.calculate_technical_indicators(df)
            except Exception as e:
                logger.warning(f"Error creating advanced features: {e}, using basic indicators")
                df_with_indicators = self.calculate_technical_indicators(df)
        else:
            df_with_indicators = self.calculate_technical_indicators(df)
        
        # Create features
        features = self.create_features(df_with_indicators, lookback=lookback)
        
        if features.empty:
            return pd.DataFrame(), pd.Series()
        
        # Create targets with improved parameters
        targets = self.create_targets(
            df_with_indicators, 
            prediction_horizon, 
            target_type,
            threshold_pct=threshold_pct,
            min_profit_pct=min_profit_pct,
            use_atr_threshold=use_atr_threshold
        )
        
        # Align features and targets
        if len(features) > len(targets):
            features = features.iloc[:len(targets)]
        elif len(targets) > len(features):
            targets = targets.iloc[:len(features)]
        
        # Remove non-numeric columns from features (time, figi, ticker, timeframe, interval, etc.)
        # Keep only numeric columns
        numeric_cols = features.select_dtypes(include=[np.number]).columns
        features = features[numeric_cols].copy()
        
        # Remove any remaining non-numeric columns explicitly
        exclude_cols = ['time', 'figi', 'ticker', 'timeframe', 'interval']
        for col in exclude_cols:
            if col in features.columns:
                features = features.drop(col, axis=1)
        
        # Final check: ensure all columns are numeric
        non_numeric = features.select_dtypes(exclude=[np.number]).columns
        if len(non_numeric) > 0:
            logger.warning(f"Removing non-numeric columns from features: {list(non_numeric)}")
            features = features.select_dtypes(include=[np.number])
        
        return features, targets
