"""
Бэктест ML стратегии для Tinkoff бота с точной имитацией работы сервера.

ВАЖНО: Этот бэктест НЕ исправляет ошибки стратегии!
Он показывает КАК стратегия работает на самом деле.
"""
import pandas as pd
import numpy as np
import os
import sys
import argparse
import warnings
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum

warnings.filterwarnings('ignore')

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.config import load_settings
from bot.ml.strategy_ml import MLStrategy
from bot.strategy import Action, Signal, Bias
from data.storage import DataStorage


class ExitReason(Enum):
    """Причины закрытия позиции."""
    TAKE_PROFIT = "TP"
    STOP_LOSS = "SL"
    TIME_LIMIT = "TIME_LIMIT"
    END_OF_BACKTEST = "END_OF_BACKTEST"


@dataclass
class Trade:
    """Сделка в бэктесте."""
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    action: Action
    size_lots: int
    size_usd: float
    pnl: float
    pnl_pct: float
    entry_reason: str
    exit_reason: Optional[ExitReason]
    ticker: str
    confidence: float
    stop_loss: float
    take_profit: float
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0
    signal_tp_pct: Optional[float] = None
    signal_sl_pct: Optional[float] = None


@dataclass
class BacktestMetrics:
    """Метрики бэктеста."""
    ticker: str
    model_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    total_pnl_pct: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    total_signals: int
    long_signals: int
    short_signals: int
    avg_trade_duration_hours: float
    best_trade_pnl: float
    worst_trade_pnl: float
    consecutive_wins: int
    consecutive_losses: int
    largest_win: float
    largest_loss: float
    avg_confidence: float
    avg_mfe: float
    avg_mae: float
    mfe_mae_ratio: float
    recovery_factor: float
    expectancy_usd: float
    risk_reward_ratio: float
    trade_frequency_per_day: float
    avg_tp_distance_pct: float = 0.0
    avg_sl_distance_pct: float = 0.0
    avg_rr_ratio: float = 0.0
    signal_quality_score: float = 0.0
    signals_with_tp_sl_pct: float = 100.0
    signals_with_correct_sl_pct: float = 100.0
    avg_position_size_usd: float = 0.0


@dataclass
class SignalStats:
    """Статистика сигналов стратегии."""
    total_signals: int = 0
    long_signals: int = 0
    short_signals: int = 0
    hold_signals: int = 0
    signals_with_tp_sl: int = 0
    signals_without_tp_sl: int = 0
    signals_with_correct_sl: int = 0
    signals_with_wrong_sl: int = 0
    avg_confidence: float = 0.0
    sl_distances: List[float] = field(default_factory=list)
    tp_distances: List[float] = field(default_factory=list)
    reasons: Dict[str, int] = field(default_factory=dict)


class MLBacktestSimulator:
    """Симулятор для бэктеста, который ТОЧНО имитирует работу реального бота."""
    
    def __init__(
        self,
        initial_balance: float = 100000.0,
        risk_per_trade: float = 0.02,
        commission: float = 0.0005,
        leverage: int = 1,
        max_position_hours: float = 48.0,
        lot_size: int = 1,
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.risk_per_trade = risk_per_trade
        self.commission = commission
        self.leverage = leverage
        self.max_position_hours = max_position_hours
        self.lot_size = lot_size
        
        self.trades: List[Trade] = []
        self.current_position: Optional[Trade] = None
        self.equity_curve: List[float] = [initial_balance]
        self.max_equity = initial_balance
        
        self.signal_stats = SignalStats()
        self.signal_history: List[Dict] = []
        
        print(f"[Backtest] Режим: ТОЧНАЯ ИМИТАЦИЯ реального сервера")
    
    def analyze_signal(self, signal: Optional[Signal], current_price: float):
        """Анализирует сигнал от стратегии."""
        if signal is None:
            # Если сигнал None, создаем HOLD сигнал для статистики
            signal = Signal(
                timestamp=datetime.now(),
                action=Action.HOLD,
                reason="no_signal",
                price=current_price
            )
        
        self.signal_stats.total_signals += 1
        
        reason_key = signal.reason[:50] if signal.reason else "no_reason"
        self.signal_stats.reasons[reason_key] = self.signal_stats.reasons.get(reason_key, 0) + 1
        
        if signal.action == Action.LONG:
            self.signal_stats.long_signals += 1
        elif signal.action == Action.SHORT:
            self.signal_stats.short_signals += 1
        else:
            self.signal_stats.hold_signals += 1
        
        has_tp_sl = signal.stop_loss is not None and signal.take_profit is not None
        
        if not has_tp_sl and signal.indicators_info:
            has_tp_sl = (signal.indicators_info.get('stop_loss') is not None and 
                        signal.indicators_info.get('take_profit') is not None)
        
        if has_tp_sl:
            self.signal_stats.signals_with_tp_sl += 1
            
            sl_price = signal.stop_loss or signal.indicators_info.get('stop_loss')
            tp_price = signal.take_profit or signal.indicators_info.get('take_profit')
            
            if sl_price and tp_price and current_price > 0:
                if signal.action == Action.LONG:
                    sl_distance_pct = (current_price - sl_price) / current_price * 100
                    tp_distance_pct = (tp_price - current_price) / current_price * 100
                else:
                    sl_distance_pct = (sl_price - current_price) / current_price * 100
                    tp_distance_pct = (current_price - tp_price) / current_price * 100
                
                self.signal_stats.sl_distances.append(sl_distance_pct)
                self.signal_stats.tp_distances.append(tp_distance_pct)
                
                if 0.8 <= sl_distance_pct <= 1.2:
                    self.signal_stats.signals_with_correct_sl += 1
                else:
                    self.signal_stats.signals_with_wrong_sl += 1
        else:
            if signal.action != Action.HOLD:
                self.signal_stats.signals_without_tp_sl += 1
        
        self.signal_history.append({
            'timestamp': datetime.now(),
            'action': signal.action.value,
            'price': current_price,
            'reason': signal.reason,
            'has_tp_sl': has_tp_sl,
            'confidence': signal.indicators_info.get('confidence', 0) if signal.indicators_info else 0
        })
    
    def calculate_position_size(self, entry_price: float, stop_loss: float, action: Action,
                               base_order_rub: float = 10000.0) -> Tuple[int, float]:
        """Рассчитывает размер позиции в лотах для Tinkoff."""
        position_size_rub = base_order_rub
        lot_value = entry_price * self.lot_size
        lots = int(position_size_rub / lot_value) if lot_value > 0 else 0
        
        if lots < 1:
            lots = 1
        
        margin_ratio = 0.12
        margin_required = (entry_price * self.lot_size * lots) * margin_ratio
        
        if margin_required > self.balance:
            max_lots = int(self.balance / (entry_price * self.lot_size * margin_ratio))
            lots = max(1, max_lots)
            margin_required = (entry_price * self.lot_size * lots) * margin_ratio
        
        return lots, margin_required
    
    def open_position(self, signal: Signal, current_time: datetime, ticker: str) -> bool:
        """Открывает позицию ТОЧНО как реальный бот."""
        if self.current_position is not None:
            return False
        
        if signal.action == Action.HOLD:
            return False
        
        stop_loss = signal.stop_loss
        take_profit = signal.take_profit
        
        if (stop_loss is None or take_profit is None) and signal.indicators_info:
            stop_loss = signal.indicators_info.get('stop_loss')
            take_profit = signal.indicators_info.get('take_profit')
        
        if stop_loss is None or take_profit is None:
            return False
        
        base_order_rub = getattr(self, '_base_order_rub', 10000.0)
        
        lots, margin_required = self.calculate_position_size(
            signal.price, stop_loss, signal.action,
            base_order_rub=base_order_rub
        )
        
        if lots <= 0 or margin_required > self.balance:
            return False
        
        self.balance -= margin_required
        
        if signal.action == Action.LONG:
            sl_distance_pct = (signal.price - stop_loss) / signal.price * 100
            tp_distance_pct = (take_profit - signal.price) / signal.price * 100
        else:
            sl_distance_pct = (stop_loss - signal.price) / signal.price * 100
            tp_distance_pct = (signal.price - take_profit) / signal.price * 100
        
        confidence = signal.indicators_info.get('confidence', 0.5) if signal.indicators_info else 0.5
        position_size_rub = signal.price * self.lot_size * lots
        
        self.current_position = Trade(
            entry_time=current_time,
            exit_time=None,
            entry_price=signal.price,
            exit_price=None,
            action=signal.action,
            size_lots=lots,
            size_usd=position_size_rub,
            pnl=0.0,
            pnl_pct=0.0,
            entry_reason=signal.reason,
            exit_reason=None,
            ticker=ticker,
            confidence=confidence,
            stop_loss=stop_loss,
            take_profit=take_profit,
            signal_sl_pct=sl_distance_pct,
            signal_tp_pct=tp_distance_pct,
        )
        
        if len(self.trades) < 5:
            print(f"\n📊 Открыта позиция #{len(self.trades) + 1}:")
            print(f"   {signal.action.value} @ {signal.price:.2f} руб")
            print(f"   Лотов: {lots}, TP: {take_profit:.2f}, SL: {stop_loss:.2f}")
        
        return True
    
    def check_exit(self, current_time: datetime, current_price: float, high: float, low: float) -> bool:
        """Проверяет условия выхода из позиции."""
        if self.current_position is None:
            return False
        
        pos = self.current_position
        
        position_duration = (current_time - pos.entry_time).total_seconds() / 3600
        if position_duration >= self.max_position_hours:
            self.close_position(current_time, current_price, ExitReason.TIME_LIMIT)
            return True
        
        if pos.action == Action.LONG:
            if low <= pos.stop_loss:
                exit_price = min(pos.stop_loss, current_price)
                self.close_position(current_time, exit_price, ExitReason.STOP_LOSS)
                return True
            elif high >= pos.take_profit:
                exit_price = max(pos.take_profit, current_price)
                self.close_position(current_time, exit_price, ExitReason.TAKE_PROFIT)
                return True
        else:
            if high >= pos.stop_loss:
                exit_price = max(pos.stop_loss, current_price)
                self.close_position(current_time, exit_price, ExitReason.STOP_LOSS)
                return True
            elif low <= pos.take_profit:
                exit_price = min(pos.take_profit, current_price)
                self.close_position(current_time, exit_price, ExitReason.TAKE_PROFIT)
                return True
        
        if pos.action == Action.LONG:
            mfe = (high - pos.entry_price) / pos.entry_price
            mae = (low - pos.entry_price) / pos.entry_price
        else:
            mfe = (pos.entry_price - low) / pos.entry_price
            mae = (pos.entry_price - high) / pos.entry_price
        
        pos.max_favorable_excursion = max(pos.max_favorable_excursion, mfe)
        pos.max_adverse_excursion = min(pos.max_adverse_excursion, mae)
        
        return False
    
    def close_position(self, exit_time: datetime, exit_price: float, exit_reason: ExitReason):
        """Закрывает позицию."""
        if self.current_position is None:
            return
        
        pos = self.current_position
        pos.exit_time = exit_time
        pos.exit_price = exit_price
        pos.exit_reason = exit_reason
        
        if pos.action == Action.LONG:
            price_change_pct = (exit_price - pos.entry_price) / pos.entry_price
        else:
            price_change_pct = (pos.entry_price - exit_price) / pos.entry_price
        
        pnl_rub_before_commission = pos.size_lots * self.lot_size * (exit_price - pos.entry_price) if pos.action == Action.LONG else pos.size_lots * self.lot_size * (pos.entry_price - exit_price)
        
        notional_entry = pos.entry_price * pos.size_lots * self.lot_size
        notional_exit = exit_price * pos.size_lots * self.lot_size
        commission_cost = (notional_entry + notional_exit) * self.commission
        
        pnl_rub = pnl_rub_before_commission - commission_cost
        
        margin_used = (pos.entry_price * self.lot_size * pos.size_lots) * 0.12
        if margin_used > 0:
            pnl_pct = (pnl_rub / margin_used) * 100
        else:
            pnl_pct = 0.0
        
        self.balance += margin_used + pnl_rub
        
        pos.pnl = pnl_rub
        pos.pnl_pct = pnl_pct
        
        self.equity_curve.append(self.balance)
        
        if self.balance > self.max_equity:
            self.max_equity = self.balance
        
        self.trades.append(pos)
        self.current_position = None
        
        if len(self.trades) <= 10:
            print(f"\n📊 Закрыта позиция #{len(self.trades)}:")
            print(f"   {pos.action.value} @ {pos.entry_price:.2f} -> {exit_price:.2f} руб")
            print(f"   PnL: {pnl_rub:.2f} руб ({pos.pnl_pct:.2f}%)")
    
    def close_all_positions(self, final_time: datetime, final_price: float):
        """Закрывает все позиции в конце бэктеста."""
        if self.current_position is not None:
            self.close_position(final_time, final_price, ExitReason.END_OF_BACKTEST)
    
    def calculate_metrics(self, ticker: str, model_name: str, days_back: int = 0) -> BacktestMetrics:
        """Рассчитывает метрики бэктеста."""
        trades_per_day = len(self.trades) / days_back if days_back > 0 and self.trades else 0.0
        
        if not self.trades:
            return BacktestMetrics(
                ticker=ticker, model_name=model_name, total_trades=0, winning_trades=0,
                losing_trades=0, win_rate=0.0, total_pnl=0.0, total_pnl_pct=0.0,
                avg_win=0.0, avg_loss=0.0, profit_factor=0.0, max_drawdown=0.0,
                max_drawdown_pct=0.0, sharpe_ratio=0.0, sortino_ratio=0.0, calmar_ratio=0.0,
                total_signals=self.signal_stats.total_signals, long_signals=self.signal_stats.long_signals,
                short_signals=self.signal_stats.short_signals, avg_trade_duration_hours=0.0,
                best_trade_pnl=0.0, worst_trade_pnl=0.0, consecutive_wins=0, consecutive_losses=0,
                largest_win=0.0, largest_loss=0.0, avg_confidence=0.0, avg_mfe=0.0, avg_mae=0.0,
                mfe_mae_ratio=0.0, recovery_factor=0.0, expectancy_usd=0.0, risk_reward_ratio=0.0,
                trade_frequency_per_day=trades_per_day, avg_tp_distance_pct=0.0, avg_sl_distance_pct=0.0,
                avg_rr_ratio=0.0, signal_quality_score=0.0, signals_with_tp_sl_pct=0.0,
                signals_with_correct_sl_pct=0.0, avg_position_size_usd=0.0,
            )
        
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = (len(winning_trades) / len(self.trades)) * 100 if self.trades else 0.0
        total_pnl = self.balance - self.initial_balance
        total_pnl_pct = (total_pnl / self.initial_balance) * 100
        
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0.0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0.0
        
        total_profit = sum(t.pnl for t in winning_trades)
        total_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else 0.0
        
        max_drawdown = 0.0
        max_drawdown_pct = 0.0
        peak = self.initial_balance
        
        for equity in self.equity_curve:
            if equity > peak:
                peak = equity
            drawdown = peak - equity
            drawdown_pct = (drawdown / peak) * 100 if peak > 0 else 0.0
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                max_drawdown_pct = drawdown_pct
        
        sharpe_ratio = 0.0
        if len(self.trades) > 1:
            returns = np.array([t.pnl_pct / 100 for t in self.trades], dtype=float)
            std = float(np.std(returns))
            if std >= 1e-9:
                sharpe_ratio = float(np.mean(returns) / std * np.sqrt(252))
        
        tp_distances = [t.signal_tp_pct for t in self.trades if t.signal_tp_pct is not None]
        sl_distances = [t.signal_sl_pct for t in self.trades if t.signal_sl_pct is not None]
        
        avg_tp_distance = np.mean(tp_distances) if tp_distances else 0.0
        avg_sl_distance = np.mean(sl_distances) if sl_distances else 0.0
        
        avg_rr_ratio = 0.0
        if sl_distances and np.mean(sl_distances) > 0:
            avg_rr_ratio = avg_tp_distance / np.mean(sl_distances)
        
        tradable_signals = self.signal_stats.long_signals + self.signal_stats.short_signals
        signals_with_tp_sl_pct = (self.signal_stats.signals_with_tp_sl / 
                                 max(1, tradable_signals)) * 100 if tradable_signals > 0 else 0.0
        
        signals_with_correct_sl_pct = (self.signal_stats.signals_with_correct_sl / 
                                      max(1, self.signal_stats.signals_with_tp_sl)) * 100
        
        avg_position_size = np.mean([t.size_usd for t in self.trades]) if self.trades else 0.0
        
        return BacktestMetrics(
            ticker=ticker, model_name=model_name, total_trades=len(self.trades),
            winning_trades=len(winning_trades), losing_trades=len(losing_trades),
            win_rate=win_rate, total_pnl=total_pnl, total_pnl_pct=total_pnl_pct,
            avg_win=avg_win, avg_loss=avg_loss, profit_factor=profit_factor,
            max_drawdown=max_drawdown, max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio, sortino_ratio=0.0,
            calmar_ratio=total_pnl_pct / abs(max_drawdown_pct) if abs(max_drawdown_pct) > 0 else 0.0,
            total_signals=self.signal_stats.total_signals,
            long_signals=self.signal_stats.long_signals, short_signals=self.signal_stats.short_signals,
            avg_trade_duration_hours=0.0, best_trade_pnl=max([t.pnl for t in self.trades]) if self.trades else 0.0,
            worst_trade_pnl=min([t.pnl for t in self.trades]) if self.trades else 0.0,
            consecutive_wins=0, consecutive_losses=0,
            largest_win=max([t.pnl for t in winning_trades]) if winning_trades else 0.0,
            largest_loss=min([t.pnl for t in losing_trades]) if losing_trades else 0.0,
            avg_confidence=np.mean([t.confidence for t in self.trades]) if self.trades else 0.0,
            avg_mfe=np.mean([t.max_favorable_excursion for t in self.trades]) * 100 if self.trades else 0.0,
            avg_mae=np.mean([abs(t.max_adverse_excursion) for t in self.trades]) * 100 if self.trades else 0.0,
            mfe_mae_ratio=np.mean([t.max_favorable_excursion / abs(t.max_adverse_excursion) if t.max_adverse_excursion != 0 else 0.0 for t in self.trades]) if self.trades else 0.0,
            recovery_factor=total_pnl / max_drawdown if max_drawdown > 0 else 0.0,
            expectancy_usd=(win_rate/100 * avg_win) - ((100 - win_rate)/100 * abs(avg_loss)),
            risk_reward_ratio=avg_win / abs(avg_loss) if abs(avg_loss) > 0 else 0.0,
            trade_frequency_per_day=trades_per_day, avg_tp_distance_pct=avg_tp_distance,
            avg_sl_distance_pct=avg_sl_distance, avg_rr_ratio=avg_rr_ratio,
            signal_quality_score=0.0, signals_with_tp_sl_pct=signals_with_tp_sl_pct,
            signals_with_correct_sl_pct=signals_with_correct_sl_pct, avg_position_size_usd=avg_position_size,
        )


def run_exact_backtest(
    model_path: str,
    ticker: str = "VBH6",
    days_back: int = 30,
    interval: str = "15min",
    initial_balance: float = 100000.0,
    risk_per_trade: float = 0.02,
    leverage: int = 1,
) -> Optional[BacktestMetrics]:
    """Запускает ТОЧНЫЙ бэктест для Tinkoff бота."""
    import traceback
    
    try:
        print("=" * 80)
        print("🚀 ТОЧНЫЙ БЭКТЕСТ ДЛЯ TINKOFF БОТА")
        print("=" * 80)
        print(f"Модель: {Path(model_path).name}")
        print(f"Инструмент: {ticker}")
        print(f"Дней: {days_back}")
        print(f"Интервал: {interval}")
        print(f"Начальный баланс: {initial_balance:.2f} руб")
        print("=" * 80)
        
        model_file = Path(model_path)
        if not model_file.exists():
            model_file = Path("ml_models") / model_path
            if not model_file.exists():
                print(f"❌ Файл модели не найден: {model_path}")
                return None
        
        try:
            settings = load_settings()
        except Exception as e:
            print(f"❌ Ошибка загрузки настроек: {e}")
            return None
        
        storage = DataStorage()
        
        instrument_info = storage.get_instrument_by_ticker(ticker)
        if not instrument_info:
            print(f"❌ Инструмент {ticker} не найден в базе")
            return None
        
        figi = instrument_info["figi"]
        
        print(f"\n📊 Загрузка исторических данных из CSV...")
        try:
            interval_for_storage = interval
            
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days_back)
            
            df = storage.get_candles(
                figi=figi,
                from_date=from_date,
                to_date=to_date,
                interval=interval_for_storage,
                limit=10000
            )
            
            if df.empty:
                print(f"❌ Нет данных для {ticker}")
                return None
            
            if "time" in df.columns:
                df["timestamp"] = pd.to_datetime(df["time"])
                df = df.set_index("timestamp")
            
            print(f"✅ Загружено {len(df)} свечей")
        except Exception as e:
            print(f"❌ Ошибка загрузки данных: {e}")
            traceback.print_exc()
            return None
        
        print(f"\n🤖 Подготовка ML стратегии...")
        try:
            strategy = MLStrategy(
                model_path=str(model_file),
                confidence_threshold=settings.ml_strategy.confidence_threshold,
                min_signal_strength=settings.ml_strategy.min_signal_strength,
            )
            
            df_with_features = strategy.feature_engineer.create_technical_indicators(df.copy())
            
            print(f"   ✅ Стратегия готова")
        except Exception as e:
            print(f"❌ Ошибка подготовки стратегии: {e}")
            traceback.print_exc()
            return None
        
        lot_size = 1
        
        simulator = MLBacktestSimulator(
            initial_balance=initial_balance,
            risk_per_trade=risk_per_trade,
            leverage=leverage,
            max_position_hours=48.0,
            lot_size=lot_size,
        )
        
        simulator._base_order_rub = getattr(settings.risk, 'base_order_usd', 10000.0)
        
        print(f"\n📈 Запуск точного бэктеста...")
        
        min_window_size = 200
        total_bars = len(df_with_features)
        
        for idx in range(min_window_size, total_bars):
            try:
                current_time = df_with_features.index[idx]
                row = df_with_features.iloc[idx]
                current_price = float(row['close'])
                high = float(row['high'])
                low = float(row['low'])
            except Exception as e:
                continue
            
            df_window = df_with_features.iloc[:idx+1]
            
            has_position = None
            if simulator.current_position is not None:
                has_position = Bias.LONG if simulator.current_position.action == Action.LONG else Bias.SHORT
            
            try:
                signal = strategy.generate_signal(
                    row=row,
                    df=df_window,
                    has_position=has_position,
                    current_price=current_price,
                    leverage=leverage,
                )
            except Exception as e:
                signal = Signal(
                    timestamp=current_time,
                    action=Action.HOLD,
                    reason=f"ml_ошибка_{str(e)[:30]}",
                    price=current_price
                )
            
            # Анализируем сигнал (даже если None, метод обработает это)
            simulator.analyze_signal(signal, current_price)
            
            if simulator.current_position is not None:
                exited = simulator.check_exit(current_time, current_price, high, low)
                if exited:
                    continue
            
            # Открываем позицию только если сигнал не None и это LONG/SHORT
            if simulator.current_position is None and signal is not None and signal.action in (Action.LONG, Action.SHORT):
                simulator.open_position(signal, current_time, ticker)
        
        if simulator.current_position is not None:
            final_price = float(df_with_features['close'].iloc[-1])
            final_time = df_with_features.index[-1]
            simulator.close_all_positions(final_time, final_price)
        
        print(f"\n📊 Расчет метрик...")
        metrics = simulator.calculate_metrics(ticker, model_file.stem, days_back=days_back)
        
        print("\n" + "=" * 80)
        print("📈 РЕЗУЛЬТАТЫ ТОЧНОГО БЭКТЕСТА")
        print("=" * 80)
        print(f"Инструмент: {metrics.ticker}")
        print(f"Модель: {metrics.model_name}")
        print(f"\n💰 Финансовые метрики:")
        print(f"   Начальный баланс: {initial_balance:.2f} руб")
        print(f"   Конечный баланс: {initial_balance + metrics.total_pnl:.2f} руб")
        print(f"   Общий PnL: {metrics.total_pnl:.2f} руб ({metrics.total_pnl_pct:+.2f}%)")
        print(f"   Макс. просадка: {metrics.max_drawdown:.2f} руб ({metrics.max_drawdown_pct:.2f}%)")
        print(f"\n📊 Статистика сделок:")
        print(f"   Всего сделок: {metrics.total_trades}")
        print(f"   Прибыльных: {metrics.winning_trades}")
        print(f"   Убыточных: {metrics.losing_trades}")
        print(f"   Win Rate: {metrics.win_rate:.2f}%")
        print(f"   Profit Factor: {metrics.profit_factor:.2f}")
        print(f"\n📈 Коэффициенты:")
        print(f"   Sharpe Ratio: {metrics.sharpe_ratio:.2f}")
        print(f"   Calmar Ratio: {metrics.calmar_ratio:.2f}")
        print("\n" + "=" * 80)
        
        return metrics
    
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА В БЭКТЕСТЕ:")
        print(f"   {e}")
        traceback.print_exc()
        return None


def main():
    parser = argparse.ArgumentParser(description='Точный бэктест ML стратегии для Tinkoff бота')
    parser.add_argument('--model', type=str, required=True, help='Путь к файлу модели')
    parser.add_argument('--ticker', type=str, default='VBH6', help='Тикер инструмента')
    parser.add_argument('--days', type=int, default=30, help='Количество дней для бэктеста')
    parser.add_argument('--interval', type=str, default='15min', help='Таймфрейм')
    parser.add_argument('--balance', type=float, default=100000.0, help='Начальный баланс в рублях')
    parser.add_argument('--risk', type=float, default=0.02, help='Риск на сделку')
    parser.add_argument('--leverage', type=int, default=1, help='Плечо')
    
    args = parser.parse_args()
    
    metrics = run_exact_backtest(
        model_path=args.model,
        ticker=args.ticker,
        days_back=args.days,
        interval=args.interval,
        initial_balance=args.balance,
        risk_per_trade=args.risk,
        leverage=args.leverage,
    )
    
    if metrics:
        print(f"\n✅ Точный бэктест завершен!")
    else:
        print(f"\n❌ Бэктест не удался!")
        sys.exit(1)


if __name__ == "__main__":
    main()
