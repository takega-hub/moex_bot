"""Model manager for ML models."""
import os
import subprocess
import sys
import pandas as pd
import json
import logging
import traceback
from pathlib import Path
from typing import Dict, Any, Optional
from bot.config import AppSettings
from bot.state import BotState

logger = logging.getLogger(__name__)

class ModelManager:
    """Manages ML models for trading."""
    
    def __init__(self, settings: AppSettings, state: BotState):
        self.settings = settings
        self.state = state
        self.models_dir = Path("ml_models")
        self.models_dir.mkdir(exist_ok=True)
    
    def find_models_for_instrument(self, instrument: str) -> list:
        """Find all available models for instrument."""
        instrument = instrument.upper()
        models = []
        
        patterns = [
            f"*_{instrument}_*.pkl",
            f"*{instrument}*.pkl"
        ]
        
        for pattern in patterns:
            for model_file in self.models_dir.glob(pattern):
                if model_file.is_file() and model_file not in models:
                    models.append(model_file)
        
        models.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return models
    
    def test_model(self, model_path: str, instrument: str, days: int = 14, initial_balance: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Тестирует модель на исторических данных и возвращает метрики
        
        Args:
            model_path: Путь к модели
            instrument: Тикер инструмента
            days: Количество дней для тестирования
            initial_balance: Начальный баланс (по умолчанию 100000.0 руб)
        """
        if initial_balance is None:
            initial_balance = 100000.0
        
        try:
            from backtest_ml_strategy import run_exact_backtest
            
            logger.info(f"[test_model] Starting backtest for {model_path} on {instrument} ({days} days, balance={initial_balance:.2f} руб)")
            
            # Определяем интервал из настроек или используем 15min
            interval = getattr(self.settings, 'timeframe', '15min')
            if interval not in ['15min', '1hour', '1h', '60min']:
                interval = '15min'
            
            metrics = run_exact_backtest(
                model_path=str(model_path),
                ticker=instrument,
                days_back=days,
                interval=interval,
                initial_balance=initial_balance,
                risk_per_trade=0.02,
                leverage=1,  # Для Tinkoff используем leverage=1
            )
            
            if metrics:
                logger.info(f"[test_model] Backtest completed successfully for {model_path}")
                logger.info(
                    f"[test_model] Results: PnL={metrics.total_pnl_pct:.2f}%, "
                    f"WR={metrics.win_rate:.1f}%, Trades={metrics.total_trades}"
                )
                return {
                    "total_pnl_pct": metrics.total_pnl_pct,
                    "win_rate": metrics.win_rate,
                    "total_trades": metrics.total_trades,
                    "trades_per_day": getattr(metrics, 'trade_frequency_per_day', metrics.total_trades / days if days > 0 else 0),
                    "profit_factor": metrics.profit_factor,
                    "max_drawdown_pct": metrics.max_drawdown_pct,
                    "sharpe_ratio": getattr(metrics, 'sharpe_ratio', 0.0),
                }
            else:
                logger.warning(
                    f"[test_model] Backtest returned None for {model_path}. "
                    f"Possible reasons: "
                    f"1) Model file not found or corrupted, "
                    f"2) No historical data available, "
                    f"3) Error during strategy initialization, "
                    f"4) Model failed to generate any valid signals."
                )
                return None
        except Exception as e:
            error_msg = str(e)
            error_traceback = traceback.format_exc()
            logger.error(f"[model_manager] Error testing model {model_path}: {error_msg}")
            logger.error(f"[model_manager] Traceback: {error_traceback}")
            return None
    
    def get_model_test_results(self, instrument: str) -> Dict[str, Dict[str, Any]]:
        """Получает сохраненные результаты тестов для всех моделей инструмента"""
        results_file = Path(f"model_test_results_{instrument}.json")
        if results_file.exists():
            try:
                with open(results_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[model_manager] Error loading test results: {e}")
        return {}
    
    def save_model_test_result(self, instrument: str, model_path: str, results: Dict[str, Any]):
        """Сохраняет результаты теста модели"""
        results_file = Path(f"model_test_results_{instrument}.json")
        all_results = self.get_model_test_results(instrument)
        all_results[str(model_path)] = results
        try:
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[model_manager] Error saving test results: {e}")
    
    def train_and_compare(self, instrument: str, use_mtf: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        """
        Запускает обучение моделей для инструмента и возвращает отчет.
        
        Args:
            instrument: Тикер инструмента
            use_mtf: Использовать MTF фичи (None = из настроек, True/False = явно)
        """
        instrument = instrument.upper()
        logger.info(f"[model_manager] Starting training for {instrument}...")
        
        # Определяем, использовать ли MTF
        if use_mtf is None:
            use_mtf = getattr(self.settings.ml_strategy, 'mtf_enabled', False)
        
        try:
            # Вызываем скрипт обучения
            python_exe = sys.executable
            script_path = "tools/train_models.py" if os.path.exists("tools/train_models.py") else "train_models.py"
            cmd = [python_exe, script_path, "--ticker", instrument]
            
            # Добавляем параметр MTF
            if use_mtf:
                cmd.append("--mtf")
            else:
                cmd.append("--no-mtf")
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info(f"[model_manager] Training output: {result.stdout[-500:]}")
            
            # После обучения ищем новые модели
            new_models = list(self.models_dir.glob(f"*_{instrument}_*.pkl"))
            if not new_models:
                logger.warning(f"[model_manager] No models found after training for {instrument}")
                return None
            
            # Сортируем по времени изменения
            new_models.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            # Запускаем сравнение моделей
            compare_script = "tools/compare_ml_models.py" if os.path.exists("tools/compare_ml_models.py") else "compare_ml_models.py"
            compare_cmd = [python_exe, compare_script, "--tickers", instrument, "--days", "14", "--output", "csv"]
            subprocess.run(compare_cmd, capture_output=True, text=True)
            
            # Ищем последний CSV отчет сравнения
            reports = list(Path(".").glob(f"ml_models_comparison_*.csv"))
            if not reports:
                logger.warning(f"[model_manager] No comparison reports found for {instrument}")
                return None
            
            reports.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            df = pd.read_csv(reports[0])
            # В moex_bot используется 'ticker' вместо 'symbol'
            ticker_col = 'ticker' if 'ticker' in df.columns else 'symbol'
            if ticker_col not in df.columns:
                logger.warning(f"[model_manager] No ticker/symbol column in comparison report")
                return None
            
            instrument_results = df[df[ticker_col] == instrument]
            
            if instrument_results.empty:
                logger.warning(f"[model_manager] No results found for {instrument} in comparison report")
                return None
            
            # Берем лучшую модель (по total_pnl_pct)
            best_new = instrument_results.iloc[0].to_dict()
            
            # Получаем метрики текущей модели для сравнения, если она есть
            current_model_path = self.state.instrument_models.get(instrument)
            comparison = {
                "instrument": instrument,
                "new_model": best_new,
                "current_model_path": current_model_path
            }
            
            return comparison
            
        except subprocess.CalledProcessError as e:
            logger.error(f"[model_manager] Error during training for {instrument}: {e}")
            logger.error(f"[model_manager] stderr: {e.stderr}")
            return None
        except Exception as e:
            logger.error(f"[model_manager] Error during training/comparison for {instrument}: {e}")
            return None
    
    def apply_model(self, instrument: str, model_path: str):
        """Apply model to instrument."""
        with self.state.lock:
            self.state.instrument_models[instrument] = model_path
        self.state.save()
        logger.info(f"[model_manager] Applied model {model_path} for {instrument}")
