"""Data storage using CSV files (similar to crypto bot)."""
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path
import logging

from config.settings import BASE_DIR
from utils.logger import logger


class DataStorage:
    """CSV-based storage for trading data (similar to crypto bot structure)."""
    
    def __init__(self, data_dir: Optional[Path] = None):
        """Initialize storage."""
        self.data_dir = data_dir or (BASE_DIR / "ml_data")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Data storage initialized at {self.data_dir}")
    
    def _get_ticker_from_figi(self, figi: str) -> Optional[str]:
        """Get ticker from FIGI using instruments cache."""
        # Try to find ticker in instruments cache file
        instruments_file = self.data_dir / "instruments.csv"
        if instruments_file.exists():
            try:
                df = pd.read_csv(instruments_file)
                match = df[df['figi'] == figi]
                if not match.empty:
                    return match.iloc[0]['ticker']
            except Exception as e:
                logger.debug(f"Error reading instruments file: {e}")
        return None
    
    def _get_figi_from_ticker(self, ticker: str) -> Optional[str]:
        """Get FIGI from ticker using instruments cache."""
        instruments_file = self.data_dir / "instruments.csv"
        if instruments_file.exists():
            try:
                df = pd.read_csv(instruments_file)
                match = df[df['ticker'] == ticker.upper()]
                if not match.empty:
                    return match.iloc[0]['figi']
            except Exception as e:
                logger.debug(f"Error reading instruments file: {e}")
        return None
    
    def _normalize_interval(self, interval: str) -> str:
        """Normalize interval to match crypto bot format (15, 60, 240, etc.)."""
        interval_map = {
            "1min": "1",
            "5min": "5",
            "15min": "15",
            "1hour": "60",
            "day": "1440",
        }
        return interval_map.get(interval.lower(), interval.replace("min", "").replace("hour", ""))
    
    def _cache_path(self, ticker: str, interval: str) -> Path:
        """Path to cache file for ticker and interval."""
        interval_norm = self._normalize_interval(interval)
        return self.data_dir / f"{ticker}_{interval_norm}_cache.csv"
    
    def _historical_file_path(self, ticker: str, interval: str, start_date: datetime, end_date: datetime) -> Path:
        """Path to historical file for date range."""
        interval_norm = self._normalize_interval(interval)
        filename = f"{ticker}_{interval_norm}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.csv"
        return self.data_dir / filename
    
    def _load_cache(self, ticker: str, interval: str) -> pd.DataFrame:
        """Load cached data if available."""
        cache_path = self._cache_path(ticker, interval)
        if not cache_path.exists():
            # Try to build cache from historical files
            interval_norm = self._normalize_interval(interval)
            pattern = f"{ticker}_{interval_norm}_*.csv"
            candidate_files = [p for p in self.data_dir.glob(pattern) if p.name != cache_path.name]
            if not candidate_files:
                return pd.DataFrame()
            try:
                frames = []
                for file_path in candidate_files:
                    df = pd.read_csv(file_path)
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        frames.append(df)
                if not frames:
                    return pd.DataFrame()
                merged = pd.concat(frames, ignore_index=True)
                merged = merged.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
                logger.info(f"Built cache from {len(candidate_files)} files for {ticker}")
                return merged
            except Exception as e:
                logger.warning(f"Failed to build cache from existing files: {e}")
                return pd.DataFrame()
        
        try:
            df = pd.read_csv(cache_path)
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
            return df
        except Exception as e:
            logger.warning(f"Failed to load cache {cache_path}: {e}")
            return pd.DataFrame()
    
    def _save_cache(self, ticker: str, interval: str, df: pd.DataFrame) -> None:
        """Save data to cache file."""
        if df.empty:
            return
        cache_path = self._cache_path(ticker, interval)
        try:
            df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
            df.to_csv(cache_path, index=False)
            logger.debug(f"Cache saved to {cache_path} ({len(df)} candles)")
        except Exception as e:
            logger.error(f"Failed to save cache {cache_path}: {e}")
    
    def save_candles(self, figi: str, candles: List[Dict], interval: str = "1min"):
        """Save candles to CSV files."""
        if not candles:
            return
        
        # Get ticker from FIGI
        ticker = self._get_ticker_from_figi(figi)
        if not ticker:
            # Try to get from instruments
            instruments_file = self.data_dir / "instruments.csv"
            if instruments_file.exists():
                try:
                    df_instruments = pd.read_csv(instruments_file)
                    match = df_instruments[df_instruments['figi'] == figi]
                    if not match.empty:
                        ticker = match.iloc[0]['ticker']
                except:
                    pass
        
        if not ticker:
            logger.warning(f"Could not find ticker for FIGI {figi}, using FIGI as ticker")
            ticker = figi
        
        # Convert candles to DataFrame
        rows = []
        for candle in candles:
            time_value = candle["time"]
            if hasattr(time_value, 'to_pydatetime'):
                time_value = time_value.to_pydatetime()
            elif isinstance(time_value, str):
                try:
                    time_value = datetime.fromisoformat(time_value.replace('Z', '+00:00'))
                except:
                    continue
            
            if isinstance(time_value, datetime) and time_value.tzinfo:
                time_value = time_value.replace(tzinfo=None)
            
            rows.append({
                "timestamp": time_value,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": int(candle["volume"]),
            })
        
        if not rows:
            return
        
        df_new = pd.DataFrame(rows)
        df_new["timestamp"] = pd.to_datetime(df_new["timestamp"])
        
        # Load existing cache
        df_cache = self._load_cache(ticker, interval)
        
        if df_cache.empty:
            df_merged = df_new
        else:
            # Merge with existing data
            df_merged = pd.concat([df_cache, df_new], ignore_index=True)
            df_merged = df_merged.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)
        
        # Save cache
        self._save_cache(ticker, interval, df_merged)
        
        # Save historical file if we have a date range
        if len(df_new) > 0:
            start_date = df_new["timestamp"].min()
            end_date = df_new["timestamp"].max()
            hist_path = self._historical_file_path(ticker, interval, start_date, end_date)
            try:
                df_new.to_csv(hist_path, index=False)
                logger.debug(f"Historical file saved: {hist_path}")
            except Exception as e:
                logger.warning(f"Failed to save historical file: {e}")
        
        logger.info(f"Saved {len(df_new)} candles for {ticker} ({interval})")
    
    def get_candles(
        self,
        figi: str,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        interval: str = "1min",
        limit: Optional[int] = None
    ) -> pd.DataFrame:
        """Get candles from CSV files."""
        # Get ticker from FIGI
        ticker = self._get_ticker_from_figi(figi)
        if not ticker:
            # Try to get from instruments
            instruments_file = self.data_dir / "instruments.csv"
            if instruments_file.exists():
                try:
                    df_instruments = pd.read_csv(instruments_file)
                    match = df_instruments[df_instruments['figi'] == figi]
                    if not match.empty:
                        ticker = match.iloc[0]['ticker']
                except:
                    pass
        
        if not ticker:
            logger.warning(f"Could not find ticker for FIGI {figi}")
            return pd.DataFrame()
        
        # Load cache
        df = self._load_cache(ticker, interval)
        
        if df.empty:
            return pd.DataFrame()
        
        # Filter by date range
        if from_date:
            if isinstance(from_date, datetime) and from_date.tzinfo:
                from_date = from_date.replace(tzinfo=None)
            df = df[df["timestamp"] >= from_date]
        
        if to_date:
            if isinstance(to_date, datetime) and to_date.tzinfo:
                to_date = to_date.replace(tzinfo=None)
            df = df[df["timestamp"] <= to_date]
        
        # Apply limit
        if limit:
            df = df.tail(limit).reset_index(drop=True)
        
        # Rename timestamp to time for compatibility
        if "timestamp" in df.columns:
            df = df.rename(columns={"timestamp": "time"})
        
        return df
    
    def get_latest_candle(self, figi: str, interval: str = "1min") -> Optional[Dict]:
        """Get latest candle for instrument."""
        ticker = self._get_ticker_from_figi(figi)
        if not ticker:
            return None
        
        df = self._load_cache(ticker, interval)
        if df.empty:
            return None
        
        latest = df.iloc[-1]
        time_value = latest["timestamp"]
        if isinstance(time_value, pd.Timestamp):
            time_value = time_value.to_pydatetime()
        if isinstance(time_value, datetime) and time_value.tzinfo:
            time_value = time_value.replace(tzinfo=None)
        
        return {
            "time": time_value,
            "open": float(latest["open"]),
            "high": float(latest["high"]),
            "low": float(latest["low"]),
            "close": float(latest["close"]),
            "volume": int(latest["volume"]),
        }
    
    def save_instrument(self, figi: str, ticker: str, name: str, instrument_type: str):
        """Save instrument information to CSV."""
        instruments_file = self.data_dir / "instruments.csv"
        
        # Load existing instruments
        if instruments_file.exists():
            try:
                df = pd.read_csv(instruments_file)
            except:
                df = pd.DataFrame(columns=["figi", "ticker", "name", "instrument_type", "updated_at"])
        else:
            df = pd.DataFrame(columns=["figi", "ticker", "name", "instrument_type", "updated_at"])
        
        # Update or add instrument
        ticker_upper = ticker.upper()
        updated_at_str = datetime.now().isoformat()
        mask = df["figi"] == figi
        if mask.any():
            df.loc[mask, ["ticker", "name", "instrument_type", "updated_at"]] = [
                ticker_upper, name, instrument_type, updated_at_str
            ]
        else:
            new_row = pd.DataFrame([{
                "figi": figi,
                "ticker": ticker_upper,
                "name": name,
                "instrument_type": instrument_type,
                "updated_at": updated_at_str
            }])
            df = pd.concat([df, new_row], ignore_index=True)
        
        df.to_csv(instruments_file, index=False)
        logger.debug(f"Saved instrument: {ticker_upper} ({figi})")
    
    def get_instrument(self, figi: str) -> Optional[Dict]:
        """Get instrument information by FIGI."""
        instruments_file = self.data_dir / "instruments.csv"
        if not instruments_file.exists():
            return None
        
        try:
            df = pd.read_csv(instruments_file)
            match = df[df["figi"] == figi]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "figi": row["figi"],
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "instrument_type": row["instrument_type"],
                    "updated_at": row.get("updated_at", None)
                }
        except Exception as e:
            logger.error(f"Error getting instrument: {e}")
        
        return None
    
    def get_instrument_by_ticker(self, ticker: str) -> Optional[Dict]:
        """Get instrument information by ticker."""
        instruments_file = self.data_dir / "instruments.csv"
        if not instruments_file.exists():
            return None
        
        try:
            df = pd.read_csv(instruments_file)
            match = df[df["ticker"] == ticker.upper()]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "figi": row["figi"],
                    "ticker": row["ticker"],
                    "name": row["name"],
                    "instrument_type": row["instrument_type"],
                    "updated_at": row.get("updated_at", None)
                }
        except Exception as e:
            logger.error(f"Error getting instrument by ticker: {e}")
        
        return None
    
    def save_trade(
        self,
        order_id: str,
        figi: str,
        direction: str,
        quantity: int,
        price: Optional[float] = None,
        status: str = "executed"
    ):
        """Save trade information to CSV."""
        trades_file = self.data_dir / "trades.csv"
        
        # Load existing trades
        if trades_file.exists():
            try:
                df = pd.read_csv(trades_file)
            except:
                df = pd.DataFrame(columns=["order_id", "figi", "direction", "quantity", "price", "executed_at", "status"])
        else:
            df = pd.DataFrame(columns=["order_id", "figi", "direction", "quantity", "price", "executed_at", "status"])
        
        # Add new trade
        executed_at_str = datetime.now().isoformat()
        new_row = pd.DataFrame([{
            "order_id": order_id,
            "figi": figi,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "executed_at": executed_at_str,
            "status": status
        }])
        df = pd.concat([df, new_row], ignore_index=True)
        df.to_csv(trades_file, index=False)
        logger.info(f"Saved trade: {order_id} - {direction} {quantity} {figi} @ {price}")
    
    def get_trades(
        self,
        figi: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100
    ) -> pd.DataFrame:
        """Get trades from CSV."""
        trades_file = self.data_dir / "trades.csv"
        if not trades_file.exists():
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(trades_file)
            if "executed_at" in df.columns:
                df["executed_at"] = pd.to_datetime(df["executed_at"])
            
            if figi:
                df = df[df["figi"] == figi]
            
            if from_date:
                df = df[df["executed_at"] >= from_date]
            
            if to_date:
                df = df[df["executed_at"] <= to_date]
            
            df = df.sort_values("executed_at", ascending=False).head(limit)
            return df
        except Exception as e:
            logger.error(f"Error getting trades: {e}")
            return pd.DataFrame()
    
    def get_data_range(self, figi: str, interval: str = "1min") -> Optional[tuple]:
        """Get date range of available data."""
        ticker = self._get_ticker_from_figi(figi)
        if not ticker:
            return None
        
        df = self._load_cache(ticker, interval)
        if df.empty or "timestamp" not in df.columns:
            return None
        
        from_time = df["timestamp"].min()
        to_time = df["timestamp"].max()
        
        if isinstance(from_time, pd.Timestamp):
            from_time = from_time.to_pydatetime()
        if isinstance(to_time, pd.Timestamp):
            to_time = to_time.to_pydatetime()
        
        if from_time.tzinfo:
            from_time = from_time.replace(tzinfo=None)
        if to_time.tzinfo:
            to_time = to_time.replace(tzinfo=None)
        
        return (from_time, to_time)
