"""Trading loop for Tinkoff bot."""
import time
import asyncio
import logging
import math
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from bot.config import AppSettings
from bot.state import BotState, TradeRecord
from trading.client import TinkoffClient
from bot.ml.strategy_ml import MLStrategy
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
        self.strategies: Dict[str, MLStrategy] = {}
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
                logger.info(f"🔄 Processing {active_count} instruments...")
                
                if active_count == 0:
                    logger.warning("⚠️ No active instruments! Bot is waiting. Add instruments via Telegram or .env file.")
                    await asyncio.sleep(60)  # Wait longer if no instruments
                    continue
                
                for instrument in self.state.active_instruments:
                    await self.process_instrument(instrument)
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
                
                # Get all positions
                pos_info = await asyncio.to_thread(self.tinkoff.get_position_info)
                
                if pos_info and pos_info.get("retCode") == 0:
                    positions = pos_info.get("result", {}).get("list", [])
                    
                    for position in positions:
                        figi = position.get("figi")
                        # Get ticker from FIGI to check if it's in active instruments
                        instrument_info = self.storage.get_instrument(figi)
                        if instrument_info:
                            ticker = instrument_info.get("ticker")
                            if ticker and ticker in self.state.active_instruments:
                                await self.check_position(figi, position)
                
                await asyncio.sleep(25)
                
            except Exception as e:
                logger.error(f"Error in position monitoring loop: {e}")
                await asyncio.sleep(30)
    
    async def process_instrument(self, instrument: str):
        """Process single instrument."""
        try:
            logger.info(f"[{instrument}] 🚀 START process_instrument()")
            
            # Check cooldown
            if await asyncio.to_thread(self.state.is_instrument_in_cooldown, instrument):
                logger.info(f"[{instrument}] In cooldown, returning")
                return
            
            # Get instrument info (FIGI)
            # First try to get from storage
            instrument_info = await asyncio.to_thread(self.storage.get_instrument_by_ticker, instrument)
            
            if not instrument_info:
                # Try to find instrument via API
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
                    logger.warning(f"[{instrument}] Instrument not found")
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
            
            # Update candles if needed
            await asyncio.to_thread(
                self.data_collector.update_candles,
                figi,
                interval=self.settings.timeframe,
                days_back=1
            )
            
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
                model_path = self.state.instrument_models.get(instrument)
                if not model_path:
                    from pathlib import Path
                    models_dir = Path("ml_models")
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
            strategy = self.strategies[instrument]
            
            if len(df) >= 2:
                row = df.iloc[-2]  # Last closed candle
                current_price = df.iloc[-1]['close']
            else:
                row = df.iloc[-1]
                current_price = row['close']
            
            # Get position info
            pos_info = await asyncio.to_thread(self.tinkoff.get_position_info, figi=figi)
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
            confidence = indicators_info.get('confidence', 0)
            logger.info(f"[{instrument}] Signal: {signal.action.value} | Confidence: {confidence:.2%} | Price: {current_price:.2f}")
            
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
            
            # Check exchange position FIRST (source of truth)
            pos_info = await asyncio.to_thread(self.tinkoff.get_position_info, figi=figi)
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
            
            # Get lot size (quantity step)
            lot_size = await asyncio.to_thread(self.tinkoff.get_qty_step, figi)
            if lot_size <= 0:
                lot_size = 1.0
            
            # Get balance and available funds
            balance_info = await asyncio.to_thread(self.tinkoff.get_wallet_balance)
            balance = 0.0
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
                            balance = float(rub_coin.get("walletBalance", 0))
                            # Use available balance if available, otherwise use total balance
                            available_balance = float(rub_coin.get("availableBalance", balance))
            
            # Use available balance for margin calculations (excludes locked margin)
            balance = available_balance if available_balance > 0 else balance
            
            if balance <= 0:
                logger.error(f"[{instrument}] ❌ Cannot get balance")
                return
            
            # Calculate position size
            # For Tinkoff futures, margin is typically ~12% of position value
            margin_rate = 0.12  # 12% margin requirement for Tinkoff futures
            
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
                    min_needed = margin_per_lot * 1.1  # 10% buffer
                    available_margin = min(min_needed, balance)
                else:
                    # Balance is too small even for 1 lot
                    available_margin = balance
            
            # Check if we have enough margin for at least 1 lot
            if available_margin < margin_per_lot:
                logger.warning(
                    f"[{instrument}] ⚠️ Insufficient margin for position. "
                    f"Available: {available_margin:.2f} руб, "
                    f"Required for 1 lot: {margin_per_lot:.2f} руб, "
                    f"Balance: {balance:.2f} руб. "
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
            
            logger.info(
                f"[{instrument}] 💰 Position sizing: "
                f"Available: {available_margin:.2f} руб, "
                f"Lots: {lots}, "
                f"Margin per lot: {margin_per_lot:.2f} руб"
            )
            
            # Place order
            direction = "Buy" if signal.action == Action.LONG else "Sell"
            
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
                        f"Available: {balance:.2f} руб, "
                        f"Required: {margin_per_lot * lots:.2f} руб, "
                        f"Lots requested: {lots}"
                    )
                    # Try with fewer lots
                    if lots > 1:
                        reduced_lots = max(1, lots - 1)
                        logger.info(f"[{instrument}] 🔄 Retrying with reduced lots: {reduced_lots}")
                        resp2 = await asyncio.to_thread(
                            self.tinkoff.place_order,
                            figi=figi,
                            quantity=reduced_lots,
                            direction=direction,
                            order_type="Market"
                        )
                        if resp2 and resp2.get("retCode") == 0:
                            logger.info(f"[{instrument}] ✅ Order placed with reduced lots: {reduced_lots}")
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
                            logger.error(f"[{instrument}] ❌ Retry also failed: {resp2}")
                    else:
                        logger.error(f"[{instrument}] ❌ Cannot reduce lots further (already at 1)")
                
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
            
            # Get latest price
            df = self.storage.get_candles(figi=figi, interval=self.settings.timeframe, limit=1)
            if df.empty:
                return
            
            current_price = float(df['close'].iloc[-1])
            
            # Check TP/SL
            should_close = False
            exit_reason = None
            
            if local_pos.take_profit and local_pos.stop_loss:
                if local_pos.side == "Buy":
                    # LONG position
                    if current_price >= local_pos.take_profit:
                        should_close = True
                        exit_reason = "TP"
                        logger.info(f"[{ticker}] ✅ TP hit: {current_price:.2f} >= {local_pos.take_profit:.2f}")
                    elif current_price <= local_pos.stop_loss:
                        should_close = True
                        exit_reason = "SL"
                        logger.info(f"[{ticker}] ❌ SL hit: {current_price:.2f} <= {local_pos.stop_loss:.2f}")
                else:
                    # SHORT position
                    if current_price <= local_pos.take_profit:
                        should_close = True
                        exit_reason = "TP"
                        logger.info(f"[{ticker}] ✅ TP hit: {current_price:.2f} <= {local_pos.take_profit:.2f}")
                    elif current_price >= local_pos.stop_loss:
                        should_close = True
                        exit_reason = "SL"
                        logger.info(f"[{ticker}] ❌ SL hit: {current_price:.2f} >= {local_pos.stop_loss:.2f}")
            
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
            # Get full position details from exchange
            pos_info = await asyncio.to_thread(self.tinkoff.get_position_info, figi=figi)
            
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
            # Get all positions from exchange
            pos_info = await asyncio.to_thread(self.tinkoff.get_position_info)
            
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
                        
                        # Update candles
                        logger.debug(f"[{instrument}] Updating candles...")
                        new_candles = await asyncio.to_thread(
                            self.data_collector.update_candles,
                            figi=figi,
                            interval=self.settings.timeframe,
                            days_back=1
                        )
                        
                        if new_candles > 0:
                            logger.info(f"[{instrument}] ✅ Collected {new_candles} new candles")
                        
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
