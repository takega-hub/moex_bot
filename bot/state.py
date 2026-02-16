"""Bot state management."""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from pathlib import Path
from datetime import datetime, timedelta
import threading


@dataclass
class TradeRecord:
    """Trade record."""
    instrument: str  # FIGI or ticker
    side: str  # "Buy" or "Sell"
    entry_price: float
    exit_price: Optional[float] = None
    quantity: float = 0.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    entry_time: str = field(default_factory=lambda: datetime.now().isoformat())
    exit_time: Optional[str] = None
    status: str = "open"  # open, closed
    model_name: str = ""
    horizon: str = "short_term"  # short_term, mid_term, long_term
    dca_count: int = 0
    take_profit: Optional[float] = None  # TP цена
    stop_loss: Optional[float] = None  # SL цена
    exit_reason: Optional[str] = None  # Причина закрытия (TP, SL, manual, etc.)


@dataclass
class SignalRecord:
    """Signal record."""
    timestamp: str
    instrument: str
    action: str
    price: float
    confidence: float
    reason: str
    indicators: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InstrumentCooldown:
    """Cooldown for instrument after losses."""
    instrument: str
    cooldown_until: str  # ISO format datetime
    consecutive_losses: int
    reason: str


class BotState:
    """Bot state management."""
    
    def __init__(self, state_file: str = "runtime_state.json"):
        self.state_file = Path(state_file)
        self.lock = threading.RLock()  # Используем RLock для реентерабельности
        
        # Default state
        self.is_running: bool = False
        self.active_instruments: List[str] = []
        self.known_instruments: List[str] = []
        self.instrument_models: Dict[str, str] = {}  # instrument -> model_path
        self.max_active_instruments: int = 5
        
        # History
        self.trades: List[TradeRecord] = []
        self.signals: List[SignalRecord] = []
        
        # Cooldowns
        self.cooldowns: Dict[str, InstrumentCooldown] = {}
        
        # Instrument margins (calculated at startup)
        self.instrument_margins: Dict[str, float] = {}  # ticker -> margin_per_lot
        
        self.load()
    
    def load(self):
        """Load state from file."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not self.state_file.exists():
            logger.debug(f"State file {self.state_file} does not exist, using defaults")
            return
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.is_running = data.get("is_running", False)
                self.active_instruments = data.get("active_instruments", [])
                self.known_instruments = data.get("known_instruments", [])
                self.instrument_models = data.get("instrument_models", {})
                self.instrument_margins = data.get("instrument_margins", {})
                
                # Load trades
                trades_data = data.get("trades", [])
                closed_count = 0
                open_count = 0
                for t in trades_data:
                    trade = TradeRecord(**t)
                    self.trades.append(trade)
                    if trade.status == "closed":
                        closed_count += 1
                    elif trade.status == "open":
                        open_count += 1
                
                logger.info(
                    f"[state] Loaded {len(trades_data)} trades: "
                    f"{closed_count} closed, {open_count} open"
                )
                
                # Log total PnL from closed trades
                if closed_count > 0:
                    closed_trades = [t for t in self.trades if t.status == "closed"]
                    total_pnl = sum(t.pnl_usd for t in closed_trades)
                    logger.info(
                        f"[state] Total PnL from closed trades: {total_pnl:.2f} руб "
                        f"({len([t for t in closed_trades if t.pnl_usd > 0])} wins, "
                        f"{len([t for t in closed_trades if t.pnl_usd < 0])} losses)"
                    )
                
                # Load signals
                for s in data.get("signals", []):
                    self.signals.append(SignalRecord(**s))
                
                # Load cooldowns
                for instrument, cooldown_data in data.get("cooldowns", {}).items():
                    self.cooldowns[instrument] = InstrumentCooldown(**cooldown_data)
            
            logger.debug(f"State loaded: {len(self.active_instruments)} active instruments: {self.active_instruments}")
        except Exception as e:
            logger.error(f"[state] Error loading state from {self.state_file}: {e}", exc_info=True)
    
    def save(self):
        """Save state to file."""
        import logging
        logger = logging.getLogger(__name__)
        
        with self.lock:
            try:
                data = {
                    "is_running": self.is_running,
                    "active_instruments": self.active_instruments,
                    "known_instruments": self.known_instruments,
                    "instrument_models": self.instrument_models,
                    "instrument_margins": self.instrument_margins,
                    "trades": [asdict(t) for t in self.trades[-500:]],
                    "signals": [asdict(s) for s in self.signals[-1000:]],
                    "cooldowns": {instrument: asdict(cooldown) for instrument, cooldown in self.cooldowns.items()}
                }
                
                # Создаем временный файл для атомарной записи
                temp_file = self.state_file.with_suffix('.tmp')
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                
                # Атомарно заменяем старый файл новым
                temp_file.replace(self.state_file)
                
                logger.debug(f"State saved successfully: {len(self.active_instruments)} active instruments: {self.active_instruments}")
            except PermissionError as e:
                logger.error(f"[state] Permission denied saving state to {self.state_file}: {e}")
            except Exception as e:
                logger.error(f"[state] Error saving state to {self.state_file}: {e}", exc_info=True)
    
    def set_running(self, status: bool):
        """Set running status."""
        self.is_running = status
        self.save()
    
    def add_signal(self, instrument: str, action: str, price: float, confidence: float, reason: str, indicators: Dict[str, Any] = None):
        """Add signal to history."""
        signal = SignalRecord(
            timestamp=datetime.now().isoformat(),
            instrument=instrument,
            action=action,
            price=price,
            confidence=confidence,
            reason=reason,
            indicators=indicators or {}
        )
        with self.lock:
            self.signals.append(signal)
            if len(self.signals) > 1000:
                self.signals.pop(0)
        self.save()
    
    def add_trade(self, trade: TradeRecord):
        """Add trade to history."""
        with self.lock:
            self.trades.append(trade)
            if len(self.trades) > 500:
                self.trades.pop(0)
        self.save()
    
    def get_open_position(self, instrument: str) -> Optional[TradeRecord]:
        """Get open position for instrument."""
        with self.lock:
            for trade in reversed(self.trades):
                if trade.instrument == instrument and trade.status == "open":
                    return trade
        return None
    
    def is_instrument_in_cooldown(self, instrument: str) -> bool:
        """Check if instrument is in cooldown."""
        should_save = False
        with self.lock:
            if instrument not in self.cooldowns:
                return False
            
            cooldown = self.cooldowns[instrument]
            cooldown_until = datetime.fromisoformat(cooldown.cooldown_until)
            
            if datetime.now() < cooldown_until:
                return True
            else:
                del self.cooldowns[instrument]
                should_save = True
        
        if should_save:
            self.save()
        return False
    
    def set_cooldown(self, instrument: str, consecutive_losses: int, reason: str):
        """Set cooldown for instrument."""
        if consecutive_losses == 1:
            cooldown_duration = timedelta(minutes=30)
        elif consecutive_losses == 2:
            cooldown_duration = timedelta(hours=2)
        else:
            cooldown_duration = timedelta(hours=24)
        
        cooldown_until = datetime.now() + cooldown_duration
        
        with self.lock:
            self.cooldowns[instrument] = InstrumentCooldown(
                instrument=instrument,
                cooldown_until=cooldown_until.isoformat(),
                consecutive_losses=consecutive_losses,
                reason=reason
            )
        self.save()
    
    def get_consecutive_losses(self, instrument: str) -> int:
        """Get consecutive losses for instrument."""
        with self.lock:
            instrument_trades = [t for t in reversed(self.trades) if t.instrument == instrument and t.status == "closed"]
            
            consecutive_losses = 0
            for trade in instrument_trades:
                if trade.pnl_usd < 0:
                    consecutive_losses += 1
                else:
                    break
            
            return consecutive_losses
    
    def update_trade_tp_sl(self, instrument: str, take_profit: Optional[float], stop_loss: Optional[float]):
        """Update TP/SL for an open trade."""
        with self.lock:
            for trade in reversed(self.trades):
                if trade.instrument == instrument and trade.status == "open":
                    if take_profit is not None:
                        trade.take_profit = take_profit
                    if stop_loss is not None:
                        trade.stop_loss = stop_loss
                    break
        self.save()
    
    def update_trade_on_close(self, instrument: str, exit_price: float, pnl_usd: float, pnl_pct: float, exit_reason: Optional[str] = None):
        """Update trade on close."""
        import logging
        logger = logging.getLogger(__name__)
        
        trade_found = False
        with self.lock:
            # Log all open trades for this instrument for debugging
            open_trades_for_instrument = [t for t in self.trades if t.instrument == instrument and t.status == "open"]
            logger.info(f"[state] update_trade_on_close: instrument={instrument}, open_trades={len(open_trades_for_instrument)}")
            
            for trade in reversed(self.trades):
                if trade.instrument == instrument and trade.status == "open":
                    logger.info(
                        f"[state] ✅ Found open trade to close: {instrument}, "
                        f"entry={trade.entry_price:.2f}, exit={exit_price:.2f}, "
                        f"PnL={pnl_usd:.2f} руб ({pnl_pct:.2f}%)"
                    )
                    trade.exit_price = exit_price
                    trade.exit_time = datetime.now().isoformat()
                    trade.pnl_usd = pnl_usd
                    trade.pnl_pct = pnl_pct
                    trade.status = "closed"
                    if exit_reason:
                        trade.exit_reason = exit_reason
                    trade_found = True
                    break
        
        if not trade_found:
            logger.warning(
                f"[state] ⚠️ No open trade found to close for {instrument}. "
                f"Total trades: {len(self.trades)}, "
                f"Open trades for {instrument}: {len(open_trades_for_instrument)}"
            )
        
        if pnl_usd < 0:
            consecutive_losses = self.get_consecutive_losses(instrument)
            if consecutive_losses > 0:
                reason = f"{consecutive_losses} убыток(ов) подряд"
                self.set_cooldown(instrument, consecutive_losses, reason)
        
        self.save()
        
        # Log updated stats after save
        if trade_found:
            closed_trades = [t for t in self.trades if t.status == "closed"]
            total_pnl = sum(t.pnl_usd for t in closed_trades)
            logger.info(
                f"[state] 📊 Updated stats: Total closed trades: {len(closed_trades)}, "
                f"Total PnL: {total_pnl:.2f} руб"
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """Get trading statistics."""
        import logging
        logger = logging.getLogger(__name__)
        
        with self.lock:
            closed_trades = [t for t in self.trades if t.status == "closed"]
            open_trades = [t for t in self.trades if t.status == "open"]
            
            logger.debug(
                f"[state] get_stats: Total trades: {len(self.trades)}, "
                f"Closed: {len(closed_trades)}, Open: {len(open_trades)}"
            )
            
            if not closed_trades:
                logger.debug("[state] No closed trades found, returning zero stats")
                return {"total_pnl": 0.0, "win_rate": 0.0, "total_trades": 0}
            
            total_pnl = sum(t.pnl_usd for t in closed_trades)
            wins = len([t for t in closed_trades if t.pnl_usd > 0])
            losses = len([t for t in closed_trades if t.pnl_usd < 0])
            win_rate = (wins / len(closed_trades)) * 100 if closed_trades else 0.0
            
            logger.info(
                f"[state] 📊 Stats calculated: "
                f"Total PnL: {total_pnl:.2f} руб, "
                f"Win rate: {win_rate:.1f}%, "
                f"Trades: {len(closed_trades)} (W: {wins}, L: {losses})"
            )
            
            return {
                "total_pnl": total_pnl,
                "win_rate": win_rate,
                "total_trades": len(closed_trades)
            }
    
    def toggle_instrument(self, instrument: str) -> Optional[bool]:
        """Toggle instrument active status. Returns None if limit reached."""
        with self.lock:
            if instrument in self.active_instruments:
                self.active_instruments.remove(instrument)
                self.save()
                return False
            else:
                if len(self.active_instruments) >= self.max_active_instruments:
                    return None
                self.active_instruments.append(instrument)
                if instrument not in self.known_instruments:
                    self.known_instruments.append(instrument)
                self.save()
                return True
    
    def enable_instrument(self, instrument: str) -> Optional[bool]:
        """Enable instrument. Returns None if limit reached."""
        with self.lock:
            if instrument in self.active_instruments:
                return True
            if len(self.active_instruments) >= self.max_active_instruments:
                return None
            self.active_instruments.append(instrument)
            if instrument not in self.known_instruments:
                self.known_instruments.append(instrument)
            self.save()
            return True
    
    def add_known_instrument(self, instrument: str):
        """Add instrument to known list."""
        with self.lock:
            if instrument not in self.known_instruments:
                self.known_instruments.append(instrument)
            self.save()
    
    def get_cooldown_info(self, instrument: str) -> Optional[Dict[str, Any]]:
        """Get cooldown info for instrument."""
        with self.lock:
            if instrument not in self.cooldowns:
                return None
            
            cooldown = self.cooldowns[instrument]
            cooldown_until = datetime.fromisoformat(cooldown.cooldown_until)
            
            if datetime.now() < cooldown_until:
                hours_left = (cooldown_until - datetime.now()).total_seconds() / 3600
                return {
                    "active": True,
                    "hours_left": hours_left,
                    "reason": cooldown.reason,
                    "consecutive_losses": cooldown.consecutive_losses
                }
            else:
                # Cooldown expired, remove it
                del self.cooldowns[instrument]
                self.save()
                return None
    
    def remove_cooldown(self, instrument: str):
        """Remove cooldown for instrument."""
        with self.lock:
            if instrument in self.cooldowns:
                del self.cooldowns[instrument]
                self.save()
