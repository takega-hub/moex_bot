"""Trading loop for Tinkoff bot."""
import time
import asyncio
import logging
import math
import json
import pandas as pd
from typing import List, Dict, Optional, Union
from datetime import datetime, timedelta

from bot.config import AppSettings
from bot.state import BotState, TradeRecord
from trading.client import TinkoffClient
from bot.ml.strategy_ml import MLStrategy
from bot.ml.mtf_strategy import MultiTimeframeMLStrategy
from bot.strategy import Action, Signal, Bias
from data.collector import DataCollector
from data.storage import DataStorage
from utils.logger import logger


class TradingLoop:
    """Main trading loop for Tinkoff bot."""
    
    def __init__(self, settings: AppSettings, state: BotState, tinkoff: TinkoffClient, tg_bot=None):
        self.settings = settings
        self.state = state
        self.tinkoff = tinkoff
        self.tg_bot = tg_bot
        self.strategies: Dict[str, Union[MLStrategy, MultiTimeframeMLStrategy]] = {}
        self.last_processed_candle: Dict[str, Optional[pd.Timestamp]] = {}
        
        # Data collector for historical data
        self.data_collector = DataCollector(client=tinkoff)
        self.storage = DataStorage()
        
        # Data collection settings
        self.last_data_collection: Dict[str, datetime] = {}
        self.data_collection_interval = timedelta(hours=1)  # Collect data every hour
        self.initial_data_days = 30  # Days of historical data to collect on startup
    
    async def run(self):
        """Run trading loop."""
        logger.info("Starting Trading Loop...")
        
        if not self.state.is_running:
            logger.info("Setting bot state to running...")
            self.state.set_running(True)
        
        # Sync positions with exchange
        await self.sync_positions_with_exchange()
        
        # Initial data collection for all active instruments
        await self._initial_data_collection()
        
        # Run all loops in parallel
        try:
            await asyncio.gather(
                self._signal_processing_loop(),
                self._position_monitoring_loop(),
                self._data_collection_loop(),  # Background data collection
                return_exceptions=True
            )
        except Exception as e:
            logger.error(f"Fatal error in trading loop: {e}", exc_info=True)
            raise
    
    def _get_seconds_until_next_candle_close(self, timeframe: str) -> float:
        """Calculate seconds until next candle close."""
        now = datetime.now()
        
        # Parse timeframe
        if timeframe.endswith('min'):
            minutes = int(timeframe[:-3])
        elif timeframe.endswith('hour'):
            minutes = int(timeframe[:-4]) * 60
        elif timeframe == 'day':
            minutes = 24 * 60
        else:
            minutes = 15
        
        if minutes < 60:
            current_minute = now.minute
            next_close_minute = ((current_minute // minutes) + 1) * minutes
            if next_close_minute >= 60:
                next_close = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            else:
                next_close = now.replace(minute=next_close_minute, second=0, microsecond=0)
        elif minutes == 60:
            next_close = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        else:
            hours = minutes // 60
            current_hour = now.hour
            next_close_hour = ((current_hour // hours) + 1) * hours
            if next_close_hour >= 24:
                next_close = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            else:
                next_close = now.replace(hour=next_close_hour, minute=0, second=0, microsecond=0)
        
        return max(0, (next_close - now).total_seconds())
    
    async def _signal_processing_loop(self):
        """Main signal processing loop."""
        logger.info("Starting Signal Processing Loop...")
        iteration = 0
        
        while True:
            try:
                iteration += 1
                
                if not self.state.is_running:
                    await asyncio.sleep(10)
                    continue
                
                active_count = len(self.state.active_instruments)
                logger.info(
                    f"🔄 Processing {active_count} instruments: {self.state.active_instruments}"
                )
                
                if active_count == 0:
                    logger.warning("⚠️ No active instruments! Bot is waiting. Add instruments via Telegram or .env file.")
                    await asyncio.sleep(60)  # Wait longer if no instruments
                    continue
                
                for instrument in self.state.active_instruments:
                    logger.debug(f"🔄 About to process instrument: {instrument}")
                    try:
                        await self.process_instrument(instrument)
                    except Exception as e:
                        logger.error(f"❌ Error processing {instrument}: {e}", exc_info=True)
                    if len(self.state.active_instruments) > 1:
                        await asyncio.sleep(2)
                
                # Smart pause based on candle close time
                seconds_until_close = self._get_seconds_until_next_candle_close(self.settings.timeframe)
                sleep_time = min(self.settings.live_poll_seconds, max(10, seconds_until_close - 5))
                
                logger.info(f"✅ Completed iteration {iteration}, sleeping for {sleep_time}s...")
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Error in signal processing loop: {e}")
                await asyncio.sleep(30)
    
    async def _position_monitoring_loop(self):
        """Position monitoring loop."""
        logger.info("Starting Position Monitoring Loop...")
        await asyncio.sleep(10)
        
        cycle_count = 0
        while True:
            try:
                if not self.state.is_running:
                    await asyncio.sleep(10)
                    continue
                
                cycle_count += 1
                
                # Sync positions with exchange every 10 cycles (every ~4 minutes)
                if cycle_count % 10 == 0:
                    logger.info(f"📊 Position Monitoring: Cycle {cycle_count}")
                    await self.sync_positions_with_exchange()
                
                # Get all positions (с таймаутом 30 секунд)
                try:
                    pos_info = await asyncio.wait_for(
                        asyncio.to_thread(self.tinkoff.get_position_info),
                        timeout=30.0
                    )
                except asyncio.TimeoutError:
                    logger.error("Timeout getting position info in _position_monitoring_loop (30s exceeded)")
                    pos_info = None
                except Exception as e:
                    logger.error(f"Error getting position info in _position_monitoring_loop: {e}")
                    pos_info = None
                
                if pos_info and pos_info.get("retCode") == 0:
                    positions = pos_info.get("result", {}).get("list", [])
                    
                    # Log all found positions for debugging
                    found_tickers = []
                    skipped_tickers = []
                    currency_positions = []
                    unknown_positions = []
                    
                    logger.debug(f"📊 Found {len(positions)} total positions from exchange")
                    
                    for position in positions:
                        figi = position.get("figi")
                        quantity = abs(float(position.get("quantity", 0)))
                        if quantity == 0:
                            continue
                        
                        # Skip currency positions (RUB, USD, etc.) - they're not futures
                        if figi and ("RUB" in figi or figi.startswith("RUB") or "CURRENCY" in str(figi).upper()):
                            currency_positions.append(figi)
                            logger.debug(f"💰 Skipping currency position: FIGI={figi}, Qty={quantity}")
                            continue
                        
                        # Get ticker from FIGI
                        instrument_info = self.storage.get_instrument(figi)
                        if not instrument_info:
                            unknown_positions.append(f"{figi} (qty={quantity})")
                            logger.warning(
                                f"⚠️ Position found with FIGI {figi} but instrument not found in storage. "
                                f"Quantity: {quantity}. This might be a currency or unknown instrument type."
                            )
                            continue
                        
                        ticker = instrument_info.get("ticker")
                        if not ticker:
                            logger.warning(
                                f"⚠️ Position found with FIGI {figi} but ticker is missing. "
                                f"Instrument info: {instrument_info}"
                            )
                            continue
                        
                        if ticker in self.state.active_instruments:
                            found_tickers.append(ticker)
                            await self.check_position(figi, position)
                        else:
                            skipped_tickers.append(ticker)
                            logger.warning(
                                f"⚠️ Position found for {ticker} (FIGI: {figi}, Qty: {quantity}) "
                                f"but it's not in active_instruments. "
                                f"Current active ({len(self.state.active_instruments)}/{self.state.max_active_instruments}): {self.state.active_instruments}. "
                                f"Adding {ticker} to active instruments automatically."
                            )
                            # Automatically add instrument with open position to active list
                            result = await asyncio.to_thread(self.state.enable_instrument, ticker)
                            if result:
                                logger.info(f"✅ Added {ticker} to active instruments. Now checking position.")
                                # Check position now that it's active
                                await self.check_position(figi, position)
                            elif result is None:
                                logger.error(
                                    f"❌ Cannot add {ticker} - max active instruments limit reached "
                                    f"({len(self.state.active_instruments)}/{self.state.max_active_instruments}). "
                                    f"Please remove an instrument manually or increase the limit."
                                )
                    
                    # Log summary
                    if found_tickers or skipped_tickers or currency_positions or unknown_positions:
                        logger.info(
                            f"📊 Position monitoring summary: "
                            f"Active positions: {found_tickers}, "
                            f"Auto-added: {skipped_tickers}, "
                            f"Currency (ignored): {len(currency_positions)}, "
                            f"Unknown (ignored): {len(unknown_positions)}"
                        )
                        if currency_positions:
                            logger.debug(f"   Currency positions: {currency_positions}")
                        if unknown_positions:
                            logger.debug(f"   Unknown positions: {unknown_positions}")
                
                await asyncio.sleep(25)
                
            except Exception as e:
                logger.error(f"Error in position monitoring loop: {e}")
                await asyncio.sleep(30)
    
    async def process_instrument(self, instrument: str):
        """Process single instrument."""
        try:
            logger.info(f"[{instrument}] 🚀 START process_instrument()")
            
            # Log active instruments for debugging
            logger.debug(
                f"[{instrument}] Active instruments: {self.state.active_instruments}, "
                f"Current instrument in list: {instrument in self.state.active_instruments}"
            )
            
            # Check cooldown
            if await asyncio.to_thread(self.state.is_instrument_in_cooldown, instrument):
                logger.info(f"[{instrument}] In cooldown, returning")
                return
            
            # Get instrument info (FIGI)
            # First try to get from storage
            instrument_info = await asyncio.to_thread(self.storage.get_instrument_by_ticker, instrument)
            
            if not instrument_info:
                # Try to find instrument via API (с таймаутом 30 секунд)
                logger.warning(f"[{instrument}] ⚠️ Instrument not in storage, searching via API...")
                try:
                    instrument_data = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.tinkoff.find_instrument,
                            instrument,
                            instrument_type="futures"
                        ),
                        timeout=30.0
                    )
                    if instrument_data:
                        logger.info(f"[{instrument}] Found via API, saving to storage...")
                        await asyncio.wait_for(
                            asyncio.to_thread(
                                self.storage.save_instrument,
                                figi=instrument_data["figi"],
                                ticker=instrument,
                                name=instrument_data["name"],
                                instrument_type=instrument_data["instrument_type"]
                            ),
                            timeout=10.0
                        )
                        instrument_info = instrument_data
                    else:
                        logger.warning(f"[{instrument}] Instrument not found via API")
                        return
                except asyncio.TimeoutError:
                    logger.error(f"[{instrument}] Timeout finding instrument via API (30s exceeded)")
                    return
                except Exception as e:
                    logger.error(f"[{instrument}] Error finding instrument via API: {e}", exc_info=True)
                    return
            
            # Extract FIGI
            if isinstance(instrument_info, dict):
                figi = instrument_info.get("figi")
            else:
                figi = getattr(instrument_info, "figi", None)
            
            if not figi:
                logger.warning(f"[{instrument}] Could not extract FIGI")
                return
            
            # Get historical data from storage
            logger.info(f"[{instrument}] 📊 Fetching historical data...")
            
            # Update candles if needed (с таймаутом 60 секунд)
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(
                        self.data_collector.update_candles,
                        figi,
                        interval=self.settings.timeframe,
                        days_back=1
                    ),
                    timeout=60.0
                )
                logger.debug(f"[{instrument}] Candles updated successfully")
            except asyncio.TimeoutError:
                logger.error(f"[{instrument}] Timeout updating candles in process_instrument (60s exceeded)")
            except Exception as e:
                logger.error(f"[{instrument}] Error updating candles in process_instrument: {e}", exc_info=True)
            
            # Get candles from storage
            df = self.storage.get_candles(
                figi=figi,
                interval=self.settings.timeframe,
                limit=self.settings.kline_limit
            )
            
            if df.empty:
                logger.warning(f"[{instrument}] ⚠️ No data available")
                return
            
            logger.info(f"[{instrument}] ✅ Data received: {len(df)} candles")
            
            # Warn if insufficient data for signal generation
            if len(df) < 60:
                logger.warning(
                    f"[{instrument}] ⚠️ Insufficient historical data: {len(df)} candles. "
                    f"Need at least 60 candles for signal generation. "
                    f"Consider running initial data collection or wait for more data."
                )
            
            # Initialize strategy if needed
            if instrument not in self.strategies:
                logger.info(f"[{instrument}] 🔄 Strategy not loaded, initializing...")
                from pathlib import Path
                models_dir = Path("ml_models")
                
                # Проверяем, включена ли MTF стратегия
                use_mtf = self.settings.ml_strategy.use_mtf_strategy
                
                if use_mtf:
                    # Пытаемся загрузить сохраненные MTF модели из mtf_models.json
                    mtf_models_file = Path("mtf_models.json")
                    model_1h_path = None
                    model_15m_path = None
                    
                    if mtf_models_file.exists():
                        try:
                            with open(mtf_models_file, 'r', encoding='utf-8') as f:
                                mtf_data = json.load(f)
                                mtf_models = mtf_data.get(instrument.upper(), {})
                                if mtf_models.get("model_1h") and mtf_models.get("model_15m"):
                                    model_1h_path = models_dir / f"{mtf_models['model_1h']}.pkl"
                                    model_15m_path = models_dir / f"{mtf_models['model_15m']}.pkl"
                        except Exception as e:
                            logger.debug(f"[{instrument}] Could not load MTF models from file: {e}")
                    
                    # Если не нашли в файле, ищем автоматически
                    if not model_1h_path or not model_15m_path or not model_1h_path.exists() or not model_15m_path.exists():
                        models_1h = list(models_dir.glob(f"*_{instrument}_60_*.pkl")) + list(models_dir.glob(f"*_{instrument}_*1h*.pkl"))
                        models_15m = list(models_dir.glob(f"*_{instrument}_15_*.pkl")) + list(models_dir.glob(f"*_{instrument}_*15m*.pkl"))
                        
                        if models_1h and models_15m:
                            model_1h_path = models_1h[0]
                            model_15m_path = models_15m[0]
                    
                    if model_1h_path and model_15m_path and model_1h_path.exists() and model_15m_path.exists():
                        logger.info(f"[{instrument}] 🔄 Loading MTF strategy:")
                        logger.info(f"  1h model: {model_1h_path.name}")
                        logger.info(f"  15m model: {model_15m_path.name}")
                        
                        try:
                            self.strategies[instrument] = MultiTimeframeMLStrategy(
                                model_1h_path=str(model_1h_path),
                                model_15m_path=str(model_15m_path),
                                confidence_threshold_1h=self.settings.ml_strategy.mtf_confidence_threshold_1h,
                                confidence_threshold_15m=self.settings.ml_strategy.mtf_confidence_threshold_15m,
                                alignment_mode=self.settings.ml_strategy.mtf_alignment_mode,
                                require_alignment=self.settings.ml_strategy.mtf_require_alignment,
                            )
                            logger.info(f"[{instrument}] ✅ MTF strategy loaded successfully")
                        except Exception as e:
                            logger.error(f"[{instrument}] ❌ Failed to load MTF strategy: {e}", exc_info=True)
                            logger.warning(f"[{instrument}] Falling back to single timeframe strategy")
                            use_mtf = False
                    else:
                        logger.warning(
                            f"[{instrument}] ⚠️ MTF strategy enabled but models not found. "
                            f"Falling back to single timeframe strategy."
                        )
                        use_mtf = False
                
                if not use_mtf:
                    # Используем обычную стратегию (15m)
                    model_path = self.state.instrument_models.get(instrument)
                    if not model_path:
                        models = list(models_dir.glob(f"*_{instrument}_*.pkl"))
                        if models:
                            model_path = str(models[0])
                            self.state.instrument_models[instrument] = model_path
                    
                    if model_path:
                        logger.info(f"[{instrument}] 🔄 Loading model: {model_path}")
                        ml_settings = self.settings.get_ml_settings_for_instrument(instrument)
                        try:
                            self.strategies[instrument] = MLStrategy(
                                model_path=model_path,
                                confidence_threshold=ml_settings.confidence_threshold or self.settings.ml_strategy.confidence_threshold,
                                min_signal_strength=ml_settings.min_signal_strength or self.settings.ml_strategy.min_signal_strength
                            )
                            logger.info(
                                f"[{instrument}] ✅ Model loaded successfully. "
                                f"Confidence threshold: {ml_settings.confidence_threshold or self.settings.ml_strategy.confidence_threshold:.2%}, "
                                f"Data available: {len(df)} candles"
                            )
                        except Exception as e:
                            logger.error(f"[{instrument}] ❌ Failed to load model: {e}", exc_info=True)
                            return
                    else:
                        logger.warning(
                            f"[{instrument}] ⚠️ No model found. "
                            f"Search pattern: *_{instrument}_*.pkl in ml_models/"
                        )
                        return
            
            # Generate signal
            strategy = self.strategies.get(instrument)
            if not strategy:
                logger.warning(f"[{instrument}] ⚠️ No strategy loaded for instrument")
                return
            
            # Логируем тип стратегии (MultiTimeframeMLStrategy уже импортирован в начале файла)
            strategy_type = "MTF" if isinstance(strategy, MultiTimeframeMLStrategy) else "Single"
            logger.info(f"[{instrument}] 📊 Strategy type: {strategy_type}")
            
            if len(df) >= 2:
                row = df.iloc[-2]  # Last closed candle
                current_price = df.iloc[-1]['close']
            else:
                row = df.iloc[-1]
                current_price = row['close']
            
            # Get position info (с таймаутом 30 секунд)
            try:
                pos_info = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_position_info, figi=figi),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error(f"[{instrument}] Timeout getting position info (30s exceeded)")
                pos_info = None
            except Exception as e:
                logger.error(f"[{instrument}] Error getting position info: {e}")
                pos_info = None
            
            has_pos = None
            
            if pos_info and pos_info.get("retCode") == 0:
                positions = pos_info.get("result", {}).get("list", [])
                if positions:
                    pos = positions[0]
                    quantity = float(pos.get("quantity", 0))
                    if quantity > 0:
                        has_pos = Bias.LONG  # Tinkoff doesn't have short positions for futures in same way
            
            # Generate signal
            df_for_signal = df.iloc[:-1] if len(df) >= 2 else df
            
            # Проверяем, это MTF стратегия или обычная
            if isinstance(strategy, MultiTimeframeMLStrategy):
                # MTF стратегия - загружаем 1h данные если есть
                df_1h = None
                try:
                    df_1h = self.storage.get_candles(
                        figi=figi,
                        interval="1hour",
                        limit=1000
                    )
                    if not df_1h.empty and "time" in df_1h.columns:
                        df_1h["timestamp"] = pd.to_datetime(df_1h["time"])
                        df_1h = df_1h.set_index("timestamp")
                except Exception as e:
                    logger.debug(f"[{instrument}] Could not load 1h data, will aggregate from 15m: {e}")
                    df_1h = None
                
                signal = await asyncio.to_thread(
                    strategy.generate_signal,
                    row=row,
                    df_15m=df_for_signal,
                    df_1h=df_1h,
                    has_position=has_pos,
                    current_price=current_price,
                    leverage=self.settings.leverage
                )
            else:
                # Обычная стратегия
                signal = await asyncio.to_thread(
                    strategy.generate_signal,
                    row=row,
                    df=df_for_signal,
                    has_position=has_pos,
                    current_price=current_price,
                    leverage=self.settings.leverage
                )
            
            if not signal:
                # Log detailed reason why signal wasn't generated
                if df_for_signal.empty or len(df_for_signal) < 60:
                    logger.warning(
                        f"[{instrument}] ⚠️ No signal: insufficient data. "
                        f"Have {len(df_for_signal)} candles, need at least 60"
                    )
                else:
                    # Check if it's HOLD prediction by trying to get prediction value
                    # For HOLD, just log simple message
                    logger.info(f"[{instrument}] Model predicted HOLD. No trading signal.")
                return
            
            # Log signal
            indicators_info = signal.indicators_info or {}
            # Для MTF стратегии confidence может быть в mtf_confidence или confidence
            confidence = indicators_info.get('mtf_confidence') or indicators_info.get('confidence', 0)
            
            # Если confidence = 0 и это HOLD, пытаемся вычислить из 1h и 15m confidence
            if confidence == 0 and signal.action == Action.HOLD and indicators_info.get('strategy') == 'MTF_ML':
                # Для HOLD сигнала используем среднее confidence обеих моделей
                conf_1h = indicators_info.get('1h_conf', 0)
                conf_15m = indicators_info.get('15m_conf', 0)
                if conf_1h > 0 or conf_15m > 0:
                    confidence = (conf_1h + conf_15m) / 2
            
            logger.info(f"[{instrument}] Signal: {signal.action.value} | Confidence: {confidence:.2%} | Price: {current_price:.2f}")
            
            # Дополнительная информация для MTF стратегии
            if indicators_info.get('strategy') == 'MTF_ML':
                reason = indicators_info.get('mtf_reason') or indicators_info.get('reason') or 'N/A'
                logger.info(
                    f"[{instrument}] MTF details: "
                    f"1h={indicators_info.get('1h_pred', '?')}({indicators_info.get('1h_conf', 0):.2%}), "
                    f"15m={indicators_info.get('15m_pred', '?')}({indicators_info.get('15m_conf', 0):.2%}), "
                    f"reason={reason}"
                )
            
            # Add to history
            if signal.action != Action.HOLD:
                self.state.add_signal(
                    instrument=instrument,
                    action=signal.action.value,
                    price=signal.price,
                    confidence=confidence,
                    reason=signal.reason,
                    indicators=indicators_info
                )
            
            # Execute trade if signal is strong enough
            if signal.action in (Action.LONG, Action.SHORT):
                min_confidence = self.settings.ml_strategy.confidence_threshold
                if confidence < min_confidence:
                    logger.info(f"[{instrument}] Signal rejected: confidence {confidence:.2%} < {min_confidence:.2%}")
                    return
                
                await self.execute_trade(instrument, figi, signal, current_price)
                
        except Exception as e:
            logger.error(f"[{instrument}] Error processing instrument: {e}", exc_info=True)
    
    async def execute_trade(
        self,
        instrument: str,
        figi: str,
        signal: Signal,
        current_price: float
    ):
        """Execute trade."""
        try:
            logger.info(f"[{instrument}] 🚀 execute_trade() called")
            
            # Check exchange position FIRST (source of truth) (с таймаутом 30 секунд)
            try:
                pos_info = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_position_info, figi=figi),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error(f"[{instrument}] Timeout getting position info in execute_trade (30s exceeded)")
                return
            except Exception as e:
                logger.error(f"[{instrument}] Error getting position info in execute_trade: {e}")
                return
            
            exchange_has_position = False
            exchange_quantity = 0.0
            
            if pos_info and pos_info.get("retCode") == 0:
                positions = pos_info.get("result", {}).get("list", [])
                for pos in positions:
                    quantity = float(pos.get("quantity", 0))
                    if abs(quantity) > 0:  # Check absolute value for both long and short
                        exchange_has_position = True
                        exchange_quantity = quantity
                        logger.info(
                            f"[{instrument}] ⚠️ Exchange shows open position: "
                            f"{quantity} units. Skipping new trade."
                        )
                        return
            
            # Check local state - if it says we have position but exchange doesn't, sync it
            local_pos = await asyncio.to_thread(self.state.get_open_position, instrument)
            if local_pos and local_pos.status == "open":
                if not exchange_has_position:
                    # Position was closed externally (manually), sync local state
                    logger.info(
                        f"[{instrument}] 🔄 Syncing: Local state shows open position, "
                        f"but exchange shows none. Closing local position record."
                    )
                    await self.handle_position_closed(figi, local_pos, "external_manual")
                else:
                    # Both show position, but local state exists - log and skip
                    logger.info(
                        f"[{instrument}] ⚠️ Already have open position: "
                        f"{local_pos.side} {local_pos.quantity} lots @ {local_pos.entry_price:.2f}. "
                        f"Skipping new trade."
                    )
                    return
            
            # Get lot size (quantity step) (с таймаутом 30 секунд)
            try:
                lot_size = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_qty_step, figi),
                    timeout=30.0
                )
                if lot_size <= 0:
                    lot_size = 1.0
            except asyncio.TimeoutError:
                logger.error(f"[{instrument}] Timeout getting lot size (30s exceeded), using default 1.0")
                lot_size = 1.0
            except Exception as e:
                logger.error(f"[{instrument}] Error getting lot size: {e}, using default 1.0")
                lot_size = 1.0
            
            # Get balance and available funds (с таймаутом 30 секунд)
            try:
                balance_info = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_wallet_balance),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error(f"[{instrument}] Timeout getting balance (30s exceeded)")
                return
            except Exception as e:
                logger.error(f"[{instrument}] Error getting balance: {e}")
                return
            
            total_balance = 0.0
            available_balance = 0.0
            
            if balance_info and balance_info.get("retCode") == 0:
                result = balance_info.get("result", {})
                list_data = result.get("list", [])
                if list_data:
                    wallet_item = list_data[0]
                    coin_list = wallet_item.get("coin", [])
                    if coin_list:
                        rub_coin = next((c for c in coin_list if c.get("coin") == "RUB"), None)
                        if rub_coin:
                            total_balance = float(rub_coin.get("walletBalance", 0))
                            # Use available balance if available, otherwise use total balance
                            available_balance = float(rub_coin.get("availableBalance", total_balance))
            
            # Calculate total margin used by all open positions
            # Use same margin rate as for new positions (15% for safety)
            margin_rate_used = 0.15
            total_margin_used = 0.0
            try:
                for ticker in self.state.active_instruments:
                    # Skip current instrument to avoid double counting
                    if ticker == instrument:
                        continue
                    
                    instrument_info = self.storage.get_instrument_by_ticker(ticker)
                    if not instrument_info:
                        continue
                    pos_figi = instrument_info["figi"]
                    
                    try:
                        pos_info = await asyncio.wait_for(
                            asyncio.to_thread(self.tinkoff.get_position_info, figi=pos_figi),
                            timeout=10.0
                        )
                        if pos_info and pos_info.get("retCode") == 0:
                            positions = pos_info.get("result", {}).get("list", [])
                            for pos in positions:
                                quantity = abs(float(pos.get("quantity", 0)))
                                if quantity > 0:
                                    avg_price = float(pos.get("average_price", 0))
                                    if avg_price > 0:
                                        # Get lot size for this instrument
                                        pos_lot_size = await asyncio.to_thread(
                                            self.tinkoff.get_qty_step, pos_figi
                                        )
                                        if pos_lot_size <= 0:
                                            pos_lot_size = 1.0
                                        
                                        # Calculate margin for this position (15% of position value for safety)
                                        # For futures, quantity is usually in lots already
                                        # Position value = average_price * quantity * lot_size
                                        position_value = avg_price * quantity * pos_lot_size
                                        pos_margin = position_value * margin_rate_used
                                        total_margin_used += pos_margin
                                        logger.info(
                                            f"[{instrument}] 📊 Position {ticker}: "
                                            f"qty={quantity} lots, price={avg_price:.2f}, "
                                            f"lot_size={pos_lot_size}, "
                                            f"position_value={position_value:.2f} руб, "
                                            f"margin={pos_margin:.2f} руб"
                                        )
                    except asyncio.TimeoutError:
                        logger.debug(f"[{instrument}] Timeout getting position info for {ticker}")
                        continue
                    except Exception as e:
                        logger.debug(f"[{instrument}] Error getting position info for {ticker}: {e}")
                        continue
            except Exception as e:
                logger.warning(f"[{instrument}] Error calculating total margin used: {e}")
            
            # Use availableBalance from API directly - exchange knows best what's available
            # Don't try to calculate used margin ourselves - exchange already accounts for it
            # Apply conservative safety factor (40%) to account for exchange's internal calculations
            # Exchange may have additional requirements (variation margin, fees, etc.)
            api_available_safe = available_balance * 0.4  # Use only 40% of API available balance
            
            # Log both values for comparison
            logger.info(
                f"[{instrument}] 💰 Margin info: "
                f"Total balance: {total_balance:.2f} руб, "
                f"API available balance: {available_balance:.2f} руб, "
                f"API available (40%): {api_available_safe:.2f} руб, "
                f"Margin used by other positions (estimated): {total_margin_used:.2f} руб"
            )
            
            # Use API available balance with safety factor - trust the exchange
            balance = api_available_safe
            
            if balance <= 0:
                logger.error(
                    f"[{instrument}] ❌ No available margin. "
                    f"Total balance: {total_balance:.2f} руб, "
                    f"Margin used: {total_margin_used:.2f} руб"
                )
                return
            
            # Calculate position size
            # For Tinkoff futures, margin is typically ~12% of position value
            # Use 20% for safety margin (very conservative) - exchange may require more
            margin_rate = 0.20  # 20% margin requirement (very conservative, actual is ~12%)
            
            if lot_size <= 0:
                lot_size = 1.0
            
            position_value_per_lot = current_price * lot_size
            margin_per_lot = position_value_per_lot * margin_rate
            
            if margin_per_lot <= 0:
                logger.error(f"[{instrument}] ❌ Invalid margin calculation: price={current_price}, lot_size={lot_size}")
                return
            
            # Calculate available margin
            # Strategy: use fixed amount if balance is large enough, otherwise use percentage
            # But ensure we use enough to open at least 1 lot if balance allows
            fixed_margin = self.settings.risk.base_order_usd
            pct_margin = balance * self.settings.risk.margin_pct_balance
            
            # If balance is large enough for fixed margin, use fixed (capped at balance)
            if balance >= fixed_margin:
                available_margin = min(fixed_margin, balance)
            else:
                # For smaller balances, use percentage, but ensure it's enough for at least 1 lot
                # If percentage is too small but balance is enough, use more
                if pct_margin >= margin_per_lot:
                    # Percentage is sufficient
                    available_margin = min(pct_margin, balance)
                elif balance >= margin_per_lot:
                    # Balance is enough for 1 lot, but percentage isn't - use more (up to balance)
                    # Use a higher percentage or minimum needed for 1 lot
                    min_needed = margin_per_lot * 1.2  # 20% buffer for safety
                    available_margin = min(min_needed, balance)
                else:
                    # Balance is too small even for 1 lot
                    available_margin = balance
            
            # Apply safety margin: use only 85% of available margin to account for exchange requirements
            # Exchange may require more margin than calculated due to volatility, fees, etc.
            safety_factor = 0.85
            available_margin = available_margin * safety_factor
            
            # Check if we have enough margin for at least 1 lot
            if available_margin < margin_per_lot:
                logger.warning(
                    f"[{instrument}] ⚠️ Insufficient margin for position. "
                    f"Available (after safety): {available_margin:.2f} руб, "
                    f"Required for 1 lot: {margin_per_lot:.2f} руб, "
                    f"Total balance: {total_balance:.2f} руб, "
                    f"Margin used: {total_margin_used:.2f} руб. "
                    f"Increase base_order_usd (current: {fixed_margin:.2f} руб) or add funds."
                )
                return
            
            lots = int(available_margin / margin_per_lot)
            
            # Ensure minimum 1 lot if we have enough margin
            if lots <= 0 and available_margin >= margin_per_lot:
                lots = 1
            
            if lots <= 0:
                logger.error(
                    f"[{instrument}] ❌ Calculated lots is zero. "
                    f"Available margin: {available_margin:.2f} руб, "
                    f"Margin per lot: {margin_per_lot:.2f} руб, "
                    f"Price: {current_price:.2f}, Lot size: {lot_size}, "
                    f"Balance: {balance:.2f} руб"
                )
                return
            
            # Calculate required margin for the order
            required_margin = margin_per_lot * lots
            
            logger.info(
                f"[{instrument}] 💰 Position sizing: "
                f"Available margin: {available_margin:.2f} руб, "
                f"Lots: {lots}, "
                f"Margin per lot: {margin_per_lot:.2f} руб, "
                f"Required margin: {required_margin:.2f} руб, "
                f"Safety buffer: {(available_margin - required_margin):.2f} руб"
            )
            
            # Place order
            direction = "Buy" if signal.action == Action.LONG else "Sell"
            
            logger.info(
                f"[{instrument}] 📤 Placing order: {direction} {lots} lots @ {current_price:.2f}, "
                f"Required margin: {required_margin:.2f} руб"
            )
            
            resp = await asyncio.to_thread(
                self.tinkoff.place_order,
                figi=figi,
                quantity=lots,
                direction=direction,
                order_type="Market"
            )
            
            if resp and resp.get("retCode") == 0:
                logger.info(f"[{instrument}] ✅ Order placed successfully")
                
                # Add to trade history with TP/SL
                trade = TradeRecord(
                    instrument=instrument,
                    side=direction,
                    entry_price=current_price,
                    quantity=lots,
                    status="open",
                    model_name=self.state.instrument_models.get(instrument, ""),
                    take_profit=signal.take_profit,
                    stop_loss=signal.stop_loss
                )
                self.state.add_trade(trade)
                logger.info(
                    f"[{instrument}] 📝 Trade recorded: Entry={current_price:.2f}, "
                    f"TP={signal.take_profit:.2f}, SL={signal.stop_loss:.2f}"
                )
                
                if self.tg_bot:
                    await self.tg_bot.send_message(
                        f"🚀 ОТКРЫТА ПОЗИЦИЯ {direction} {instrument}\n"
                        f"Цена: {current_price}\n"
                        f"Лотов: {lots}\n"
                        f"TP: {signal.take_profit}\n"
                        f"SL: {signal.stop_loss}"
                    )
            else:
                error_msg = resp.get("retMsg", "Unknown error") if resp else "No response"
                logger.error(f"[{instrument}] ❌ Failed to place order: {error_msg}")
                
                # Check for insufficient margin error
                if "Not enough assets" in str(error_msg) or "30042" in str(error_msg):
                    logger.warning(
                        f"[{instrument}] ⚠️ Insufficient margin on exchange. "
                        f"Available margin: {balance:.2f} руб, "
                        f"Required: {margin_per_lot * lots:.2f} руб, "
                        f"Lots requested: {lots}, "
                        f"Total balance: {total_balance:.2f} руб, "
                        f"API available: {available_balance:.2f} руб, "
                        f"Margin used: {total_margin_used:.2f} руб"
                    )
                    # Try with fewer lots - reduce very aggressively
                    # Try multiple attempts with decreasing lot sizes
                    max_attempts = 5
                    attempt = 0
                    success = False
                    
                    while attempt < max_attempts and lots > 0 and not success:
                        attempt += 1
                        
                        if attempt == 1:
                            # First attempt: reduce by 75%
                            reduced_lots = max(1, int(lots * 0.25))
                        elif attempt == 2:
                            # Second attempt: reduce to 10% of original
                            reduced_lots = max(1, int(lots * 0.1))
                        elif attempt == 3:
                            # Third attempt: calculate based on available margin with 50% buffer
                            max_lots_by_margin = int((balance * 0.5) / margin_per_lot)
                            reduced_lots = max(1, min(max_lots_by_margin, lots // 4))
                        elif attempt == 4:
                            # Fourth attempt: try just 1 lot
                            reduced_lots = 1
                        else:
                            # Last attempt: calculate absolute minimum based on available margin
                            # Use only 30% of available margin for maximum safety
                            max_lots_by_margin = int((balance * 0.3) / margin_per_lot)
                            reduced_lots = max(1, min(max_lots_by_margin, 1))  # Cap at 1 lot max
                        
                        if reduced_lots <= 0:
                            break
                        
                        logger.info(
                            f"[{instrument}] 🔄 Attempt {attempt}/{max_attempts}: "
                            f"Trying with {reduced_lots} lots "
                            f"(reduced from {lots})"
                        )
                        
                        resp2 = await asyncio.to_thread(
                            self.tinkoff.place_order,
                            figi=figi,
                            quantity=reduced_lots,
                            direction=direction,
                            order_type="Market"
                        )
                        
                        if resp2 and resp2.get("retCode") == 0:
                            logger.info(f"[{instrument}] ✅ Order placed with reduced lots: {reduced_lots}")
                            success = True
                            # Record trade with reduced lots
                            trade = TradeRecord(
                                instrument=instrument,
                                side=direction,
                                entry_price=current_price,
                                quantity=reduced_lots,
                                status="open",
                                model_name=self.state.instrument_models.get(instrument, ""),
                                take_profit=signal.take_profit,
                                stop_loss=signal.stop_loss
                            )
                            self.state.add_trade(trade)
                            if self.tg_bot:
                                await self.tg_bot.send_message(
                                    f"🚀 ОТКРЫТА ПОЗИЦИЯ {direction} {instrument} (уменьшенный размер)\n"
                                    f"Цена: {current_price}\n"
                                    f"Лотов: {reduced_lots}\n"
                                    f"TP: {signal.take_profit}\n"
                                    f"SL: {signal.stop_loss}"
                                )
                        else:
                            error_msg2 = resp2.get("retMsg", "Unknown error") if resp2 else "No response"
                            if "Not enough assets" in str(error_msg2) or "30042" in str(error_msg2):
                                logger.warning(
                                    f"[{instrument}] ⚠️ Attempt {attempt} failed: "
                                    f"Still insufficient margin for {reduced_lots} lots"
                                )
                            else:
                                logger.error(f"[{instrument}] ❌ Attempt {attempt} failed: {error_msg2}")
                    
                    if not success:
                        logger.error(
                            f"[{instrument}] ❌ All {max_attempts} retry attempts failed. "
                            f"Cannot open position with available margin. "
                            f"Even 1 lot failed with available balance: {available_balance:.2f} руб, "
                            f"margin per lot: {margin_per_lot:.2f} руб. "
                            f"This suggests insufficient funds or exchange requirements not met."
                        )
                
                if self.tg_bot:
                    await self.tg_bot.send_message(
                        f"❌ ОШИБКА ОТКРЫТИЯ ПОЗИЦИИ {instrument}\n"
                        f"Ошибка: {error_msg}"
                    )
                
        except Exception as e:
            logger.error(f"[{instrument}] ❌ Exception in execute_trade: {e}", exc_info=True)
    
    async def check_position(self, figi: str, position: Dict):
        """Check and update position - monitor TP/SL and close if needed."""
        try:
            # Get instrument info first to get ticker
            instrument_info = self.storage.get_instrument(figi)
            if not instrument_info:
                return
            
            ticker = instrument_info.get("ticker", figi)
            
            quantity = float(position.get("quantity", 0))
            if quantity == 0:
                # Position closed externally
                local_pos = await asyncio.to_thread(self.state.get_open_position, ticker)
                if local_pos:
                    await self.handle_position_closed(figi, local_pos, "external")
                return
            
            # Get local trade record (use ticker, not figi)
            local_pos = await asyncio.to_thread(self.state.get_open_position, ticker)
            if not local_pos or local_pos.status != "open":
                return
            
            # Get latest price - try from position API first, then from storage
            current_price = float(position.get("current_price", 0))
            if current_price <= 0:
                # Fallback to storage
                df = self.storage.get_candles(figi=figi, interval=self.settings.timeframe, limit=1)
                if not df.empty:
                    current_price = float(df['close'].iloc[-1])
                else:
                    logger.warning(f"[{ticker}] ⚠️ Cannot get current price for position check")
                    return
            
            # Log position status for debugging
            logger.debug(
                f"[{ticker}] 📊 Position check: "
                f"Price={current_price:.2f}, "
                f"Entry={local_pos.entry_price:.2f}, "
                f"TP={local_pos.take_profit}, "
                f"SL={local_pos.stop_loss}, "
                f"Side={local_pos.side}, "
                f"Qty={quantity}"
            )
            
            # Check TP/SL - check each independently (don't require both)
            should_close = False
            exit_reason = None
            
            if local_pos.side == "Buy":
                # LONG position
                if local_pos.take_profit and current_price >= local_pos.take_profit:
                    should_close = True
                    exit_reason = "TP"
                    logger.info(f"[{ticker}] ✅ TP hit: {current_price:.2f} >= {local_pos.take_profit:.2f}")
                elif local_pos.stop_loss and current_price <= local_pos.stop_loss:
                    should_close = True
                    exit_reason = "SL"
                    logger.info(f"[{ticker}] ❌ SL hit: {current_price:.2f} <= {local_pos.stop_loss:.2f}")
            else:
                # SHORT position
                if local_pos.take_profit and current_price <= local_pos.take_profit:
                    should_close = True
                    exit_reason = "TP"
                    logger.info(f"[{ticker}] ✅ TP hit: {current_price:.2f} <= {local_pos.take_profit:.2f}")
                elif local_pos.stop_loss and current_price >= local_pos.stop_loss:
                    should_close = True
                    exit_reason = "SL"
                    logger.info(f"[{ticker}] ❌ SL hit: {current_price:.2f} >= {local_pos.stop_loss:.2f}")
            
            # Auto-set TP/SL if missing
            if not local_pos.take_profit or not local_pos.stop_loss:
                # Try to get ATR from storage for better TP/SL calculation
                df_for_atr = self.storage.get_candles(figi=figi, interval=self.settings.timeframe, limit=20)
                atr = None
                if not df_for_atr.empty and 'atr' in df_for_atr.columns:
                    atr = float(df_for_atr['atr'].iloc[-1])
                
                # Risk/Reward ratio: 2.5:1 (TP = 2.5 * SL)
                risk_reward_ratio = 2.5
                
                # Default TP/SL percentages from config
                sl_pct = self.settings.risk.stop_loss_pct  # Default 1%
                tp_pct = self.settings.risk.take_profit_pct  # Default 2%
                
                # Use ATR if available for more accurate SL
                if atr and local_pos.entry_price > 0:
                    atr_pct = (atr / local_pos.entry_price)
                    sl_pct = max(0.005, min(atr_pct, 0.02))  # Between 0.5% and 2%
                    tp_pct = sl_pct * risk_reward_ratio  # TP = 2.5 * SL
                
                # Calculate TP/SL prices based on entry price
                new_take_profit = None
                new_stop_loss = None
                
                if local_pos.side == "Buy":
                    # LONG position
                    if not local_pos.take_profit:
                        new_take_profit = local_pos.entry_price * (1 + tp_pct)
                    if not local_pos.stop_loss:
                        new_stop_loss = local_pos.entry_price * (1 - sl_pct)
                else:
                    # SHORT position
                    if not local_pos.take_profit:
                        new_take_profit = local_pos.entry_price * (1 - tp_pct)
                    if not local_pos.stop_loss:
                        new_stop_loss = local_pos.entry_price * (1 + sl_pct)
                
                # Update TP/SL if calculated
                if new_take_profit or new_stop_loss:
                    await asyncio.to_thread(
                        self.state.update_trade_tp_sl,
                        ticker,
                        new_take_profit if new_take_profit else local_pos.take_profit,
                        new_stop_loss if new_stop_loss else local_pos.stop_loss
                    )
                    logger.info(
                        f"[{ticker}] ✅ Auto-set TP/SL: "
                        f"TP={new_take_profit if new_take_profit else local_pos.take_profit:.2f}, "
                        f"SL={new_stop_loss if new_stop_loss else local_pos.stop_loss:.2f}, "
                        f"Entry={local_pos.entry_price:.2f}, "
                        f"ATR={'used' if atr else 'not available'}"
                    )
                    # Update local_pos for current check
                    if new_take_profit:
                        local_pos.take_profit = new_take_profit
                    if new_stop_loss:
                        local_pos.stop_loss = new_stop_loss
                else:
                    logger.warning(
                        f"[{ticker}] ⚠️ Position has no TP/SL and cannot calculate! "
                        f"Entry: {local_pos.entry_price:.2f}, Current: {current_price:.2f}, "
                        f"PnL: {((current_price - local_pos.entry_price) / local_pos.entry_price * 100):+.2f}%"
                    )
            
            # Close position if TP/SL hit
            if should_close and exit_reason:
                await self.close_position(figi, ticker, local_pos, current_price, exit_reason)
                
        except Exception as e:
            logger.error(f"Error checking position {figi}: {e}", exc_info=True)
    
    async def close_position(
        self,
        figi: str,
        ticker: str,
        trade: TradeRecord,
        current_price: float,
        reason: str
    ):
        """Close position by placing opposite order."""
        try:
            logger.info(f"[{ticker}] 🔄 Closing position: {reason}")
            
            # Determine opposite direction
            close_direction = "Sell" if trade.side == "Buy" else "Buy"
            
            # Place closing order
            resp = await asyncio.to_thread(
                self.tinkoff.place_order,
                figi=figi,
                quantity=int(trade.quantity),
                direction=close_direction,
                order_type="Market"
            )
            
            if resp and resp.get("retCode") == 0:
                logger.info(f"[{ticker}] ✅ Position closed: {reason}")
                
                # Calculate PnL
                if trade.side == "Buy":
                    pnl_pct = ((current_price - trade.entry_price) / trade.entry_price) * 100
                else:
                    pnl_pct = ((trade.entry_price - current_price) / trade.entry_price) * 100
                
                margin = trade.entry_price * trade.quantity
                pnl_usd = (pnl_pct / 100) * margin
                
                # Update trade
                self.state.update_trade_on_close(figi, current_price, pnl_usd, pnl_pct, exit_reason=reason)
                
                # Update exit reason
                for t in reversed(self.state.trades):
                    if t.instrument == ticker and t.status == "closed" and not t.exit_reason:
                        t.exit_reason = reason
                        break
                self.state.save()
                
                # Send notification
                if self.tg_bot:
                    pnl_emoji = "✅" if pnl_usd > 0 else "❌" if pnl_usd < 0 else "➖"
                    await self.tg_bot.send_message(
                        f"{pnl_emoji} ПОЗИЦИЯ ЗАКРЫТА {ticker}\n"
                        f"Причина: {reason}\n"
                        f"Вход: {trade.entry_price:.2f} руб\n"
                        f"Выход: {current_price:.2f} руб\n"
                        f"PnL: {pnl_usd:+.2f} руб ({pnl_pct:+.2f}%)"
                    )
            else:
                logger.error(f"[{ticker}] ❌ Failed to close position: {resp}")
                
        except Exception as e:
            logger.error(f"[{ticker}] ❌ Error closing position: {e}", exc_info=True)
    
    async def handle_position_closed(self, figi: str, local_pos: TradeRecord, reason: str = "external"):
        """Handle position closed externally (not by our TP/SL)."""
        try:
            # Get current price
            instrument_info = self.storage.get_instrument(figi)
            if not instrument_info:
                return
            
            ticker = instrument_info.get("ticker", figi)
            
            # Get latest price from storage
            df = self.storage.get_candles(figi=figi, interval=self.settings.timeframe, limit=1)
            if df.empty:
                return
            
            exit_price = float(df['close'].iloc[-1])
            
            # Calculate PnL
            if local_pos.side == "Buy":
                pnl_pct = ((exit_price - local_pos.entry_price) / local_pos.entry_price) * 100
            else:
                pnl_pct = ((local_pos.entry_price - exit_price) / local_pos.entry_price) * 100
            
            margin = local_pos.entry_price * local_pos.quantity
            pnl_usd = (pnl_pct / 100) * margin
            
            # Update trade
            self.state.update_trade_on_close(figi, exit_price, pnl_usd, pnl_pct)
            
            # Update exit reason
            for t in reversed(self.state.trades):
                if t.instrument == ticker and t.status == "closed" and not t.exit_reason:
                    t.exit_reason = reason
                    break
            self.state.save()
            
            logger.info(f"Position {ticker} closed ({reason}): PnL={pnl_usd:.2f} руб ({pnl_pct:.2f}%)")
            
        except Exception as e:
            logger.error(f"Error handling closed position {figi}: {e}")
    
    async def handle_externally_opened_position(self, figi: str, instrument: str):
        """Handle position that was opened externally (not by bot)."""
        try:
            # Get full position details from exchange (с таймаутом 30 секунд)
            try:
                pos_info = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_position_info, figi=figi),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error(f"Timeout getting position info in handle_position_closed (30s exceeded)")
                pos_info = None
            except Exception as e:
                logger.error(f"Error getting position info in handle_position_closed: {e}")
                pos_info = None
            
            if not pos_info or pos_info.get("retCode") != 0:
                logger.warning(f"[{instrument}] Could not get position details from exchange")
                return
            
            positions_list = pos_info.get("result", {}).get("list", [])
            if not positions_list:
                logger.warning(f"[{instrument}] No position found in exchange response")
                return
            
            # Find the position for this FIGI
            exchange_pos = None
            for pos in positions_list:
                if pos.get("figi") == figi:
                    quantity = float(pos.get("quantity", 0))
                    if abs(quantity) > 0:
                        exchange_pos = pos
                        break
            
            if not exchange_pos:
                logger.warning(f"[{instrument}] Position not found in exchange response")
                return
            
            # Extract position details
            quantity = float(exchange_pos.get("quantity", 0))
            average_price = float(exchange_pos.get("average_price", 0))
            current_price = float(exchange_pos.get("current_price", 0))
            
            if average_price <= 0:
                logger.warning(f"[{instrument}] Invalid average price from exchange: {average_price}")
                return
            
            # Determine side
            side = "Buy" if quantity > 0 else "Sell"
            abs_quantity = abs(quantity)
            
            # Create trade record for externally opened position
            trade = TradeRecord(
                instrument=instrument,
                side=side,
                entry_price=average_price,
                quantity=abs_quantity,
                status="open",
                model_name=self.state.instrument_models.get(instrument, ""),
                take_profit=None,  # Unknown for externally opened positions
                stop_loss=None     # Unknown for externally opened positions
            )
            
            # Add to state
            self.state.add_trade(trade)
            
            # Calculate current PnL for logging
            if side == "Buy":
                pnl_pct = ((current_price - average_price) / average_price) * 100 if average_price > 0 else 0
            else:
                pnl_pct = ((average_price - current_price) / average_price) * 100 if average_price > 0 else 0
            
            margin = average_price * abs_quantity * 0.12  # Approximate margin
            pnl_usd = (pnl_pct / 100) * margin
            
            logger.info(
                f"[{instrument}] ✅ Synced externally opened position: "
                f"{side} {abs_quantity} lots @ {average_price:.2f} руб. "
                f"Current PnL: {pnl_usd:.2f} руб ({pnl_pct:.2f}%)"
            )
            
            # Notify via Telegram if available
            if self.tg_bot:
                await self.tg_bot.send_message(
                    f"⚠️ Обнаружена внешняя позиция {side} {instrument}\n"
                    f"Цена входа: {average_price:.2f} руб\n"
                    f"Лотов: {abs_quantity}\n"
                    f"Текущая цена: {current_price:.2f} руб\n"
                    f"PnL: {pnl_usd:.2f} руб ({pnl_pct:.2f}%)\n"
                    f"Позиция добавлена в локальное состояние для отслеживания."
                )
            
        except Exception as e:
            logger.error(f"[{instrument}] Error handling externally opened position: {e}", exc_info=True)
    
    async def sync_positions_with_exchange(self):
        """Sync positions with exchange - check if local state matches exchange reality."""
        logger.info("🔄 Syncing positions with exchange...")
        
        try:
            # Get all positions from exchange (с таймаутом 30 секунд)
            try:
                pos_info = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_position_info),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.error("Timeout getting position info in sync_positions (30s exceeded)")
                pos_info = None
            except Exception as e:
                logger.error(f"Error getting position info in sync_positions: {e}")
                pos_info = None
            
            if not pos_info or pos_info.get("retCode") != 0:
                logger.warning("Could not get positions from exchange for sync")
                return
            
            exchange_positions = {}
            positions_list = pos_info.get("result", {}).get("list", [])
            
            # Build map of exchange positions by FIGI
            for pos in positions_list:
                figi = pos.get("figi")
                quantity = float(pos.get("quantity", 0))
                if abs(quantity) > 0 and figi:
                    exchange_positions[figi] = quantity
            
            # Check all active instruments
            for instrument in self.state.active_instruments:
                try:
                    # Get FIGI for instrument
                    instrument_info = await asyncio.to_thread(
                        self.storage.get_instrument_by_ticker, instrument
                    )
                    if not instrument_info:
                        continue
                    
                    figi = instrument_info.get("figi")
                    if not figi:
                        continue
                    
                    # Check local state
                    local_pos = await asyncio.to_thread(
                        self.state.get_open_position, instrument
                    )
                    
                    # If local says open but exchange says closed - sync
                    if local_pos and local_pos.status == "open":
                        if figi not in exchange_positions or abs(exchange_positions[figi]) == 0:
                            logger.info(
                                f"[{instrument}] 🔄 Syncing: Position closed externally, "
                                f"updating local state"
                            )
                            await self.handle_position_closed(figi, local_pos, "external_manual")
                    
                    # If exchange says open but local says closed - could be new position opened externally
                    elif figi in exchange_positions and abs(exchange_positions[figi]) > 0:
                        logger.info(
                            f"[{instrument}] ⚠️ Exchange shows position but local state doesn't. "
                            f"Syncing externally opened position..."
                        )
                        await self.handle_externally_opened_position(figi, instrument)
                        
                except Exception as e:
                    logger.error(f"Error syncing position for {instrument}: {e}")
                    continue
            
            logger.info("✅ Position sync completed")
            
        except Exception as e:
            logger.error(f"Error in sync_positions_with_exchange: {e}", exc_info=True)
    
    async def _initial_data_collection(self):
        """Collect initial historical data for all active instruments."""
        logger.info("🔄 Starting initial data collection...")
        
        active_instruments = list(self.state.active_instruments)
        if not active_instruments:
            logger.warning("⚠️ No active instruments for data collection")
            logger.info("💡 To add instruments:")
            logger.info("   1. Set TRADING_INSTRUMENTS in .env file (e.g., TRADING_INSTRUMENTS=VBH6,SRH6)")
            logger.info("   2. Use Telegram bot: /start -> ⚙️ ИНСТРУМЕНТЫ")
            logger.info("   3. Restart bot after adding instruments")
            return
        
        logger.info(f"Collecting initial data for {len(active_instruments)} instruments...")
        
        for instrument in active_instruments:
            try:
                # Get instrument info
                instrument_info = await asyncio.to_thread(
                    self.storage.get_instrument_by_ticker, instrument
                )
                
                if not instrument_info:
                    # Try to find via API
                    instrument_data = await asyncio.to_thread(
                        self.tinkoff.find_instrument,
                        instrument,
                        instrument_type="futures"
                    )
                    if instrument_data:
                        await asyncio.to_thread(
                            self.storage.save_instrument,
                            figi=instrument_data["figi"],
                            ticker=instrument,
                            name=instrument_data["name"],
                            instrument_type=instrument_data["instrument_type"]
                        )
                        instrument_info = instrument_data
                    else:
                        logger.warning(f"[{instrument}] Instrument not found, skipping data collection")
                        continue
                
                figi = instrument_info.get("figi") if isinstance(instrument_info, dict) else getattr(instrument_info, "figi", None)
                if not figi:
                    logger.warning(f"[{instrument}] Could not extract FIGI")
                    continue
                
                # Check if we already have sufficient historical data
                # Get current data count
                existing_df = await asyncio.to_thread(
                    self.storage.get_candles,
                    figi=figi,
                    interval=self.settings.timeframe,
                    limit=1000
                )
                
                if not existing_df.empty and len(existing_df) >= 60:
                    # Check if data is recent (within 24 hours)
                    latest_candle = await asyncio.to_thread(
                        self.storage.get_latest_candle,
                        figi=figi,
                        interval=self.settings.timeframe
                    )
                    
                    if latest_candle:
                        candle_time = latest_candle.get("time")
                        if isinstance(candle_time, str):
                            candle_time = datetime.fromisoformat(candle_time.replace('Z', '+00:00'))
                        if candle_time.tzinfo:
                            candle_time = candle_time.replace(tzinfo=None)
                        
                        # If we have sufficient data (>=60 candles) and it's recent, skip collection
                        if (datetime.now() - candle_time) < timedelta(hours=24):
                            logger.info(
                                f"[{instrument}] Sufficient data exists ({len(existing_df)} candles, "
                                f"latest: {candle_time}), skipping initial collection"
                            )
                            continue
                else:
                    logger.info(
                        f"[{instrument}] Insufficient data ({len(existing_df) if not existing_df.empty else 0} candles), "
                        f"will collect {self.initial_data_days} days of history"
                    )
                
                # Collect historical data
                logger.info(f"[{instrument}] Collecting {self.initial_data_days} days of historical data...")
                to_date = datetime.now()
                from_date = to_date - timedelta(days=self.initial_data_days)
                
                await asyncio.to_thread(
                    self.data_collector.collect_candles,
                    figi=figi,
                    from_date=from_date,
                    to_date=to_date,
                    interval=self.settings.timeframe,
                    save=True
                )
                
                logger.info(f"[{instrument}] ✅ Initial data collection completed")
                
                # Small delay between instruments
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"[{instrument}] Error in initial data collection: {e}", exc_info=True)
                continue
        
        logger.info("✅ Initial data collection completed for all instruments")
    
    async def _data_collection_loop(self):
        """Background loop for automatic data collection."""
        logger.info("Starting Data Collection Loop...")
        await asyncio.sleep(60)  # Wait 1 minute before starting
        
        while True:
            try:
                if not self.state.is_running:
                    await asyncio.sleep(60)
                    continue
                
                active_instruments = list(self.state.active_instruments)
                if not active_instruments:
                    await asyncio.sleep(300)  # Wait 5 minutes if no instruments
                    continue
                
                logger.info(f"📊 Data Collection Cycle: Processing {len(active_instruments)} instruments...")
                
                for instrument in active_instruments:
                    try:
                        # Check if we need to collect data for this instrument
                        last_collection = self.last_data_collection.get(instrument)
                        if last_collection and (datetime.now() - last_collection) < self.data_collection_interval:
                            continue  # Skip if collected recently
                        
                        # Get instrument info
                        instrument_info = await asyncio.to_thread(
                            self.storage.get_instrument_by_ticker, instrument
                        )
                        
                        if not instrument_info:
                            continue
                        
                        figi = instrument_info.get("figi") if isinstance(instrument_info, dict) else getattr(instrument_info, "figi", None)
                        if not figi:
                            continue
                        
                        # Update candles (с таймаутом 60 секунд)
                        logger.debug(f"[{instrument}] Updating candles...")
                        try:
                            new_candles = await asyncio.wait_for(
                                asyncio.to_thread(
                                    self.data_collector.update_candles,
                                    figi=figi,
                                    interval=self.settings.timeframe,
                                    days_back=1
                                ),
                                timeout=60.0  # 60 секунд для сбора данных
                            )
                            
                            if new_candles > 0:
                                logger.info(f"[{instrument}] ✅ Collected {new_candles} new candles")
                        except asyncio.TimeoutError:
                            logger.error(f"[{instrument}] Timeout updating candles (60s exceeded)")
                        except Exception as e:
                            logger.error(f"[{instrument}] Error updating candles: {e}", exc_info=True)
                        
                        self.last_data_collection[instrument] = datetime.now()
                        
                        # Small delay between instruments
                        await asyncio.sleep(1)
                        
                    except Exception as e:
                        logger.error(f"[{instrument}] Error in data collection: {e}", exc_info=True)
                        continue
                
                # Wait before next cycle
                await asyncio.sleep(300)  # 5 minutes between cycles
                
            except Exception as e:
                logger.error(f"Error in data collection loop: {e}", exc_info=True)
                await asyncio.sleep(300)
