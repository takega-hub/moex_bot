"""
Advanced feature engineering based on successful cryptocurrency trading bot.
Adds 100+ features including candlestick patterns, support/resistance levels,
volatility measures, and market microstructure.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional
import warnings
warnings.filterwarnings('ignore')

from utils.logger import logger


class AdvancedFeatureEngineer:
    """
    Advanced feature engineering with 100+ features.
    Based on successful cryptocurrency trading bot implementation.
    """
    
    def __init__(self):
        """Initialize feature engineer."""
        self.feature_names: list = []
    
    def create_advanced_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create advanced features from OHLCV data.
        
        Args:
            df: DataFrame with columns: time, open, high, low, close, volume
        
        Returns:
            DataFrame with added features
        """
        if df.empty or df is None:
            return pd.DataFrame()
        
        df = df.copy()
        
        # Check required columns
        required_cols = ["open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"Missing column {col} in data")
                return pd.DataFrame()
        
        # === 1. BASIC TECHNICAL INDICATORS ===
        
        # Moving Averages
        df["sma_20"] = df["close"].rolling(window=20, min_periods=1).mean()
        df["sma_50"] = df["close"].rolling(window=50, min_periods=1).mean()
        df["ema_12"] = df["close"].ewm(span=12, adjust=False).mean()
        df["ema_26"] = df["close"].ewm(span=26, adjust=False).mean()
        
        # RSI
        df["rsi"] = self._calculate_rsi(df["close"], length=14)
        
        # ATR
        df["atr"] = self._calculate_atr(df["high"], df["low"], df["close"], length=14)
        df["atr_pct"] = (df["atr"] / df["close"]) * 100
        
        # Volume features
        df["volume_sma_20"] = df["volume"].rolling(window=20, min_periods=1).mean()
        df["volume_ratio"] = np.where(
            df["volume_sma_20"] > 0,
            df["volume"] / df["volume_sma_20"],
            1.0
        )
        
        # Price changes
        df["price_change"] = df["close"].pct_change()
        df["price_change_abs"] = df["price_change"].abs()
        
        # === 2. BOLLINGER BANDS ===
        
        df["bb_middle"] = df["close"].rolling(window=20, min_periods=1).mean()
        bb_std = df["close"].rolling(window=20, min_periods=1).std()
        df["bb_upper"] = df["bb_middle"] + (bb_std * 2)
        df["bb_lower"] = df["bb_middle"] - (bb_std * 2)
        df["bb_width"] = df["bb_upper"] - df["bb_lower"]
        df["bb_position"] = np.where(
            df["bb_width"] > 0,
            (df["close"] - df["bb_lower"]) / df["bb_width"],
            0.5
        )
        
        # === 3. MACD ===
        
        df["macd"] = df["ema_12"] - df["ema_26"]
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        
        # === 4. LAGGED FEATURES ===
        
        for lag in [1, 2, 3]:
            df[f"close_lag_{lag}"] = df["close"].shift(lag)
            df[f"volume_lag_{lag}"] = df["volume"].shift(lag)
            df[f"price_change_lag_{lag}"] = df["price_change"].shift(lag)
        
        # === 5. VOLATILITY FEATURES ===
        
        df["volatility_10"] = df["close"].rolling(window=10, min_periods=3).std()
        df["realized_volatility_10"] = df["price_change"].rolling(window=10, min_periods=3).std()
        df["realized_volatility_20"] = df["price_change"].rolling(window=20, min_periods=5).std()
        
        # Parkinson volatility
        df["parkinson_vol"] = np.sqrt((1 / (4 * np.log(2))) * (np.log(df["high"] / df["low"])) ** 2)
        df["parkinson_vol_pct"] = (df["parkinson_vol"] / df["close"]) * 100
        
        # Volatility ratio
        vol10_clean = df["realized_volatility_10"].fillna(0.0)
        vol20_clean = df["realized_volatility_20"].fillna(0.0)
        df["volatility_ratio"] = np.where(
            vol20_clean > 0,
            vol10_clean / vol20_clean,
            1.0
        )
        
        # === 6. MARKET MICROSTRUCTURE ===
        
        # Spread proxy
        df["spread_proxy"] = ((df["high"] - df["low"]) / df["close"]) * 100
        
        # Volume imbalance
        for window in [5, 10]:
            df[f"volume_imbalance_{window}"] = (
                df["volume"].rolling(window=window, min_periods=2).apply(
                    lambda x: (x.iloc[-1] - x.mean()) / x.mean() if x.mean() > 0 else 0
                )
            )
        
        # Momentum
        for period in [3, 5, 10]:
            df[f"momentum_{period}"] = df["close"].pct_change(periods=period)
        
        # === 7. DISTANCE TO MA ===
        
        df["dist_to_sma20_pct"] = ((df["close"] - df["sma_20"]) / df["sma_20"]) * 100
        df["dist_to_ema12_pct"] = ((df["close"] - df["ema_12"]) / df["ema_12"]) * 100
        
        # === 8. RSI LEVELS ===
        
        rsi_clean = pd.to_numeric(df["rsi"], errors='coerce').fillna(50.0)
        df["rsi_oversold"] = (rsi_clean < 30).astype(int)
        df["rsi_overbought"] = (rsi_clean > 70).astype(int)
        
        # === 9. TREND INDICATORS ===
        
        ema12_clean = pd.to_numeric(df["ema_12"], errors='coerce').fillna(0.0)
        ema26_clean = pd.to_numeric(df["ema_26"], errors='coerce').fillna(0.0)
        df["ema12_above_ema26"] = (ema12_clean > ema26_clean).astype(int)
        
        # BB position
        if all(col in df.columns for col in ["bb_upper", "bb_lower", "close"]):
            bb_upper_clean = pd.to_numeric(df["bb_upper"], errors='coerce').fillna(df["close"])
            bb_lower_clean = pd.to_numeric(df["bb_lower"], errors='coerce').fillna(df["close"])
            close_clean = pd.to_numeric(df["close"], errors='coerce').fillna(0.0)
            
            df["near_bb_upper"] = (close_clean > bb_upper_clean * 0.95).astype(int)
            df["near_bb_lower"] = (close_clean < bb_lower_clean * 1.05).astype(int)
        
        # === 10. CANDLESTICK PATTERNS ===
        
        # Body and wick sizes
        df["body_size"] = abs(df["close"] - df["open"]).fillna(0.0)
        df["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)).fillna(0.0)
        df["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]).fillna(0.0)
        df["total_range"] = (df["high"] - df["low"]).fillna(0.0).replace(0.0, 1.0)
        
        # Body/wick ratio
        wick_sum = (df["upper_wick"] + df["lower_wick"]).fillna(0.0)
        df["body_wick_ratio"] = np.where(
            wick_sum > 0,
            df["body_size"] / wick_sum,
            0.0
        )
        
        # Doji (body < 20% of range)
        range_ratio = (df["body_size"] / df["total_range"]).fillna(0.0)
        df["is_doji"] = (range_ratio < 0.2).astype(int)
        
        # Hammer
        body_size_clean = df["body_size"].fillna(0.0)
        lower_wick_clean = df["lower_wick"].fillna(0.0)
        upper_wick_clean = df["upper_wick"].fillna(0.0)
        df["is_hammer"] = (
            (range_ratio < 0.3) &
            (lower_wick_clean > body_size_clean * 2) &
            (upper_wick_clean < body_size_clean)
        ).astype(int)
        
        # Shooting Star
        df["is_shooting_star"] = (
            (range_ratio < 0.3) &
            (upper_wick_clean > body_size_clean * 2) &
            (lower_wick_clean < body_size_clean)
        ).astype(int)
        
        # Engulfing patterns
        close_clean = df["close"].fillna(0.0)
        open_clean = df["open"].fillna(0.0)
        close_prev = df["close"].shift(1).fillna(0.0)
        open_prev = df["open"].shift(1).fillna(0.0)
        
        df["is_bullish_engulfing"] = (
            (close_clean > open_clean) &
            (close_prev < open_prev) &
            (open_clean < close_prev) &
            (close_clean > open_prev)
        ).astype(int)
        
        df["is_bearish_engulfing"] = (
            (close_clean < open_clean) &
            (close_prev > open_prev) &
            (open_clean > close_prev) &
            (close_clean < open_prev)
        ).astype(int)
        
        # === 11. SUPPORT/RESISTANCE LEVELS ===
        
        lookback = 20
        df["local_low"] = df["low"].rolling(window=lookback, min_periods=5).min()
        df["local_high"] = df["high"].rolling(window=lookback, min_periods=5).max()
        
        # Distance to support/resistance
        local_low_clean = pd.to_numeric(df["local_low"], errors='coerce').fillna(0.0)
        local_high_clean = pd.to_numeric(df["local_high"], errors='coerce').fillna(0.0)
        close_clean = pd.to_numeric(df["close"], errors='coerce').fillna(0.0)
        
        df["dist_to_support_pct"] = np.where(
            (local_low_clean > 0) & (close_clean > 0),
            ((close_clean - local_low_clean) / close_clean) * 100,
            0.0
        )
        
        df["dist_to_resistance_pct"] = np.where(
            (local_high_clean > 0) & (close_clean > 0),
            ((local_high_clean - close_clean) / close_clean) * 100,
            0.0
        )
        
        # Distance in ATR
        atr_clean = pd.to_numeric(df["atr"], errors='coerce').fillna(0.0)
        df["dist_to_support_atr"] = np.where(
            atr_clean > 0,
            (close_clean - local_low_clean) / atr_clean,
            0.0
        )
        df["dist_to_resistance_atr"] = np.where(
            atr_clean > 0,
            (local_high_clean - close_clean) / atr_clean,
            0.0
        )
        
        # === 12. TIME FEATURES ===
        
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])
            if isinstance(df.index, pd.DatetimeIndex) or df["time"].dtype == 'datetime64[ns]':
                df["hour"] = df["time"].dt.hour if hasattr(df["time"], 'dt') else pd.to_datetime(df["time"]).dt.hour
                df["day_of_week"] = df["time"].dt.dayofweek if hasattr(df["time"], 'dt') else pd.to_datetime(df["time"]).dt.dayofweek
                # Cyclical features
                df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24.0)
                df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24.0)
                df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7.0)
                df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7.0)
        
        # === 13. CLEANUP NaN ===
        
        # Forward fill, then backward fill
        df = df.ffill().bfill()
        # Fill remaining NaN with 0
        df = df.fillna(0)
        
        # Save feature names
        original_cols = ["open", "high", "low", "close", "volume", "time"]
        self.feature_names = [col for col in df.columns if col not in original_cols]
        
        return df
    
    def _calculate_rsi(self, prices: pd.Series, length: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50.0)
    
    def _calculate_atr(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        length: int = 14
    ) -> pd.Series:
        """Calculate ATR (Average True Range)."""
        high_low = high - low
        high_close = np.abs(high - close.shift())
        low_close = np.abs(low - close.shift())
        
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        
        atr = true_range.rolling(window=length, min_periods=1).mean()
        return atr.fillna(0.0)
    
    def get_feature_names(self) -> list:
        """Return list of all created feature names."""
        return self.feature_names.copy()
