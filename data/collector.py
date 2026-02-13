"""Data collector for historical market data."""
from typing import List, Optional
from datetime import datetime, timedelta
import logging
import time

from trading.client import TinkoffClient
from data.storage import DataStorage
from utils.logger import logger

class DataCollector:
    """Collect historical market data from Tinkoff API."""
    
    def __init__(self, client: Optional[TinkoffClient] = None, storage: Optional[DataStorage] = None):
        """Initialize data collector."""
        self.client = client or TinkoffClient()
        self.storage = storage or DataStorage()
    
    def collect_candles(
        self,
        figi: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1min",
        save: bool = True
    ) -> List[dict]:
        """
        Collect candles for instrument.
        Automatically checks existing data and collects only missing periods.
        
        Args:
            figi: Instrument FIGI
            from_date: Start date
            to_date: End date
            interval: Candle interval
            save: Save to CSV files
        """
        try:
            logger.info(f"Collecting candles for {figi} from {from_date.date()} to {to_date.date()} (interval: {interval})")
            
            # Normalize input dates to naive datetime (remove timezone if present)
            if from_date.tzinfo:
                from_date = from_date.replace(tzinfo=None)
            if to_date.tzinfo:
                to_date = to_date.replace(tzinfo=None)
            
            # Check existing data
            existing_range = self.storage.get_data_range(figi, interval)
            all_candles = []
            
            if existing_range:
                existing_from, existing_to = existing_range
                # Normalize existing dates to naive datetime
                if existing_from.tzinfo:
                    existing_from = existing_from.replace(tzinfo=None)
                if existing_to.tzinfo:
                    existing_to = existing_to.replace(tzinfo=None)
                
                logger.info(f"Existing data range: {existing_from.date()} to {existing_to.date()}")
                
                # Determine what needs to be collected
                need_older = from_date < existing_from
                need_newer = to_date > existing_to
                
                # If requested range is completely within existing data, skip collection
                if not need_older and not need_newer:
                    logger.info(f"✓ All requested data already exists. Skipping collection.")
                    # Return existing candles from CSV files
                    import pandas as pd
                    df = self.storage.get_candles(figi, from_date=from_date, to_date=to_date, interval=interval)
                    if not df.empty:
                        return df.to_dict('records')
                    return []
                
                # Collect missing parts
                if need_older:
                    logger.info(f"Collecting older data: {from_date.date()} to {existing_from.date()}")
                    older_candles = self._collect_candles_range(figi, from_date, existing_from, interval)
                    all_candles.extend(older_candles)
                
                if need_newer:
                    logger.info(f"Collecting newer data: {existing_to.date()} to {to_date.date()}")
                    newer_candles = self._collect_candles_range(figi, existing_to, to_date, interval)
                    all_candles.extend(newer_candles)
            else:
                # No existing data, collect full range
                logger.info(f"No existing data found. Collecting full range.")
                all_candles = self._collect_candles_range(figi, from_date, to_date, interval)
            
            # Save collected candles
            if save and all_candles:
                self.storage.save_candles(figi, all_candles, interval)
                logger.info(f"✓ Saved {len(all_candles)} new candles to CSV files")
            elif save and not all_candles:
                logger.info(f"No new candles to save (all data already exists)")
            
            return all_candles
        except Exception as e:
            logger.error(f"Error collecting candles for {figi}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
    
    def _collect_candles_range(
        self,
        figi: str,
        from_date: datetime,
        to_date: datetime,
        interval: str
    ) -> List[dict]:
        """
        Internal method to collect candles for a specific date range.
        Used by collect_candles to avoid code duplication.
        """
        all_candles = []
        current_from = from_date
        day_count = 0
        total_days = (to_date - from_date).days + 1
        
        # Track when data actually starts
        first_data_date = None
        consecutive_empty_days = 0
        max_empty_days_to_log = 30  # Log if more than 30 consecutive empty days
        
        while current_from < to_date:
            # Limit to 1 day per request to avoid API limits
            current_to = min(current_from + timedelta(days=1), to_date)
            day_count += 1
            
            # Log progress every 10 days
            if total_days > 10 and (day_count % 10 == 0 or day_count == 1):
                logger.info(f"Progress: {day_count}/{total_days} days ({day_count*100//total_days if total_days > 0 else 0}%) - Collected {len(all_candles)} candles so far")
            
            try:
                candles = self.client.get_candles(
                    figi=figi,
                    from_date=current_from,
                    to_date=current_to,
                    interval=interval
                )
                
                if candles:
                    if first_data_date is None:
                        first_data_date = current_from
                        logger.info(f"✓ First candles found starting from {current_from.date()}")
                    all_candles.extend(candles)
                    consecutive_empty_days = 0
                    logger.debug(f"Collected {len(candles)} candles for {current_from.date()}")
                else:
                    consecutive_empty_days += 1
                    if consecutive_empty_days == max_empty_days_to_log:
                        logger.info(f"⚠️  No candles for {consecutive_empty_days} consecutive days starting from {(current_from - timedelta(days=consecutive_empty_days)).date()}. Instrument may not have been trading yet.")
                    logger.debug(f"No candles for {current_from.date()}")
            except Exception as e:
                logger.warning(f"Error getting candles for {current_from.date()}: {e}")
            
            current_from = current_to
            
            # Rate limiting
            time.sleep(0.1)
        
        # Log summary about data availability
        if first_data_date and first_data_date > from_date:
            days_without_data = (first_data_date - from_date).days
            logger.info(f"ℹ️  Instrument started trading {days_without_data} days after requested start date. First data: {first_data_date.date()}")
        elif first_data_date is None:
            logger.warning(f"⚠️  No candles found for {figi} in the entire period from {from_date.date()} to {to_date.date()}")
        
        logger.info(f"Collection completed: {len(all_candles)} total candles collected")
        return all_candles
    
    def collect_instrument_info(self, ticker: str, instrument_type: Optional[str] = "futures", prefer_perpetual: bool = True) -> Optional[dict]:
        """
        Collect and save instrument information.
        
        Args:
            ticker: Instrument ticker (from config - will be used as saved ticker)
            instrument_type: Filter by instrument type (default: "futures" for futures trading)
            prefer_perpetual: If True, prefer perpetual futures (default: True)
        """
        try:
            # Для perpetual futures предпочитаем бессрочные контракты
            instrument = self.client.find_instrument(ticker, instrument_type=instrument_type, prefer_perpetual=prefer_perpetual)
            if instrument:
                # Сохраняем с тикером из конфига, а не из API, чтобы можно было искать по конфигу
                self.storage.save_instrument(
                    figi=instrument["figi"],
                    ticker=ticker,  # Используем тикер из конфига, а не из API
                    name=instrument["name"],
                    instrument_type=instrument["instrument_type"]
                )
                logger.info(f"Saved instrument info: {ticker} -> {instrument['ticker']} ({instrument['figi']})")
                # Возвращаем инструмент с тикером из конфига для консистентности
                instrument["ticker"] = ticker.upper()
                return instrument
            return None
        except Exception as e:
            logger.error(f"Error collecting instrument info for {ticker}: {e}")
            return None
    
    def update_candles(
        self,
        figi: str,
        interval: str = "1min",
        days_back: int = 1
    ) -> int:
        """
        Update candles from last saved point to current time.
        
        Args:
            figi: Instrument FIGI
            interval: Candle interval
            days_back: How many days back to collect if no data exists
        
        Returns:
            Number of new candles collected
        """
        try:
            # Get last candle time
            last_candle = self.storage.get_latest_candle(figi, interval)
            
            if last_candle:
                # Handle time from CSV files (may be string or datetime)
                time_value = last_candle["time"]
                if isinstance(time_value, str):
                    from_date = datetime.fromisoformat(time_value.replace('Z', '+00:00'))
                elif isinstance(time_value, datetime):
                    from_date = time_value
                else:
                    from_date = datetime.fromisoformat(str(time_value).replace('Z', '+00:00'))
                
                # Normalize to naive datetime
                if from_date.tzinfo:
                    from_date = from_date.replace(tzinfo=None)
                
                # Start from next candle
                if interval == "1min":
                    from_date += timedelta(minutes=1)
                elif interval == "5min":
                    from_date += timedelta(minutes=5)
                elif interval == "15min":
                    from_date += timedelta(minutes=15)
                elif interval == "1hour":
                    from_date += timedelta(hours=1)
                elif interval == "day":
                    from_date += timedelta(days=1)
            else:
                # No data, collect from days_back
                from_date = datetime.now() - timedelta(days=days_back)
            
            to_date = datetime.now()
            
            if from_date >= to_date:
                logger.debug(f"No new candles to collect for {figi}")
                return 0
            
            candles = self.collect_candles(figi, from_date, to_date, interval, save=True)
            return len(candles)
        except Exception as e:
            logger.error(f"Error updating candles for {figi}: {e}")
            return 0
    
    def collect_futures_data(
        self,
        tickers: List[str],
        from_date: datetime,
        to_date: datetime,
        interval: str = "1min"
    ):
        """Collect data for multiple futures."""
        logger.info(f"Collecting data for {len(tickers)} futures")
        
        for ticker in tickers:
            try:
                # Get instrument info
                instrument = self.collect_instrument_info(ticker)
                if not instrument:
                    logger.warning(f"Instrument {ticker} not found")
                    continue
                
                figi = instrument["figi"]
                
                # Collect candles
                self.collect_candles(figi, from_date, to_date, interval, save=True)
                
                logger.info(f"Completed data collection for {ticker}")
                
                # Rate limiting between instruments
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"Error collecting data for {ticker}: {e}")
                continue
