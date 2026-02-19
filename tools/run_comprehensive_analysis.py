import os
import sys
import pandas as pd
import numpy as np
import glob
import json
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import joblib

import logging

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Disable file logging for backtests to prevent locking issues
logging.getLogger("trading_bot").handlers = []
logging.basicConfig(level=logging.WARNING) # Only show warnings/errors to console

from bot.config import load_settings
from bot.ml.strategy_ml import MLStrategy
from bot.strategy import Action, Signal, Bias
from tools.backtest_ml_strategy import MLBacktestSimulator, BacktestMetrics

# Configuration
RESULTS_DIR = "research_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

def load_data_for_ticker(ticker: str, interval: str) -> Optional[pd.DataFrame]:
    """Loads and merges all available data for a ticker/interval."""
    data_dir = Path("ml_data")
    pattern = f"{ticker}_{interval.replace('min', '')}_*.csv"
    files = list(data_dir.glob(pattern))
    
    if not files:
        print(f"⚠️ No data found for {ticker} {interval}")
        return None
        
    dfs = []
    for f in files:
        if "cache" in f.name: continue
        try:
            df = pd.read_csv(f)
            dfs.append(df)
        except Exception:
            continue
            
    if not dfs:
        return None
        
    full_df = pd.concat(dfs)
    
    # Clean and Sort
    if "time" in full_df.columns:
        full_df["timestamp"] = pd.to_datetime(full_df["time"])
    elif "timestamp" in full_df.columns:
        full_df["timestamp"] = pd.to_datetime(full_df["timestamp"])
        
    full_df = full_df.set_index("timestamp").sort_index()
    full_df = full_df[~full_df.index.duplicated(keep='first')]
    
    return full_df

def run_backtest_session(
    strategy: MLStrategy, 
    df: pd.DataFrame, 
    ticker: str, 
    model_name: str,
    initial_balance: float = 100000.0
) -> Optional[BacktestMetrics]:
    """Runs a single backtest session."""
    
    # Feature Engineering (if needed, usually MLStrategy handles it but needs the df)
    try:
        # We need to simulate the feed
        # MLStrategy expects a window of data to generate features
        # But for speed, we should pre-calculate features if possible
        # However, MLStrategy.generate_signal does feature engineering on the fly for the window
        
        # Pre-calculate indicators to speed up
        df_with_features = strategy.feature_engineer.create_technical_indicators(df.copy())
        
        simulator = MLBacktestSimulator(initial_balance=initial_balance)
        simulator._base_order_rub = 10000.0 # Standard size
        
        min_window = 200
        total_bars = len(df_with_features)
        
        # Optimization: Don't print every trade
        # original_stdout = sys.stdout
        # sys.stdout = open(os.devnull, 'w')
        
        try:
            for idx in range(min_window, total_bars):
                row = df_with_features.iloc[idx]
                current_time = df_with_features.index[idx]
                current_price = float(row['close'])
                high = float(row['high'])
                low = float(row['low'])
                
                # Check Exits
                if simulator.current_position:
                    exited = simulator.check_exit(current_time, current_price, high, low)
                    if exited: continue
                
                # Generate Signal
                df_window = df_with_features.iloc[:idx+1]
                
                has_position = None
                if simulator.current_position:
                    has_position = Bias.LONG if simulator.current_position.action == Action.LONG else Bias.SHORT
                
                try:
                    signal = strategy.generate_signal(
                        row=row,
                        df=df_window,
                        has_position=has_position,
                        current_price=current_price
                    )
                except Exception:
                    continue
                    
                simulator.analyze_signal(signal, current_price)
                
                if simulator.current_position is None and signal and signal.action in (Action.LONG, Action.SHORT):
                    simulator.open_position(signal, current_time, ticker)
            
            # Close all at end
            if simulator.current_position:
                simulator.close_all_positions(df_with_features.index[-1], float(df_with_features['close'].iloc[-1]))
                
        finally:
            # sys.stdout = original_stdout
            pass
            
        return simulator.calculate_metrics(ticker, model_name, days_back=(df.index[-1] - df.index[0]).days)
        
    except Exception as e:
        print(f"❌ Error backtesting {model_name}: {e}")
        traceback.print_exc()
        return None

def run_hybrid_backtest(
    strategies: List[MLStrategy],
    df: pd.DataFrame,
    ticker: str,
    model_name: str,
    initial_balance: float = 100000.0
) -> Optional[BacktestMetrics]:
    """Runs a backtest for a hybrid ensemble of strategies."""
    try:
        # Pre-calculate features for ALL strategies
        # This is expensive but necessary as they might use different features
        dfs_with_features = []
        for s in strategies:
            dfs_with_features.append(s.feature_engineer.create_technical_indicators(df.copy()))
            
        simulator = MLBacktestSimulator(initial_balance=initial_balance)
        simulator._base_order_rub = 10000.0
        
        min_window = 200
        total_bars = len(df)
        
        # original_stdout = sys.stdout
        # sys.stdout = open(os.devnull, 'w')
        
        try:
            for idx in range(min_window, total_bars):
                current_time = df.index[idx]
                row_raw = df.iloc[idx]
                current_price = float(row_raw['close'])
                high = float(row_raw['high'])
                low = float(row_raw['low'])
                
                # Check Exits
                if simulator.current_position:
                    exited = simulator.check_exit(current_time, current_price, high, low)
                    if exited: continue
                
                # Generate Signals from all strategies
                votes = []
                confidences = []
                
                has_position = None
                if simulator.current_position:
                    has_position = Bias.LONG if simulator.current_position.action == Action.LONG else Bias.SHORT
                
                for i, s in enumerate(strategies):
                    try:
                        df_feat = dfs_with_features[i]
                        row = df_feat.iloc[idx]
                        df_window = df_feat.iloc[:idx+1]
                        
                        signal = s.generate_signal(
                            row=row,
                            df=df_window,
                            has_position=has_position,
                            current_price=current_price
                        )
                        
                        if signal:
                            if signal.action == Action.LONG:
                                votes.append(1)
                                confidences.append(signal.indicators_info.get('confidence', 0.5))
                            elif signal.action == Action.SHORT:
                                votes.append(-1)
                                confidences.append(signal.indicators_info.get('confidence', 0.5))
                            else:
                                votes.append(0)
                        else:
                            votes.append(0)
                    except Exception:
                        votes.append(0)
                
                # Majority Vote
                vote_sum = sum(votes)
                final_action = Action.HOLD
                avg_confidence = np.mean(confidences) if confidences else 0.0
                
                if vote_sum >= 2: # At least 2 LONGs
                    final_action = Action.LONG
                elif vote_sum <= -2: # At least 2 SHORTs
                    final_action = Action.SHORT
                
                if final_action != Action.HOLD:
                    # Construct signal
                    # Use standard ATR for SL/TP from the first strategy's data
                    row = dfs_with_features[0].iloc[idx]
                    atr = float(row.get('atr', current_price * 0.01))
                    atr_pct = (atr / current_price) if current_price > 0 else 0.01
                    sl_pct = max(0.005, atr_pct)
                    tp_pct = sl_pct * 2.5
                    
                    if final_action == Action.LONG:
                        stop_loss = current_price * (1 - sl_pct)
                        take_profit = current_price * (1 + tp_pct)
                    else:
                        stop_loss = current_price * (1 + sl_pct)
                        take_profit = current_price * (1 - tp_pct)
                        
                    signal = Signal(
                        timestamp=current_time,
                        action=final_action,
                        reason=f"hybrid_vote_{vote_sum}",
                        price=current_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        indicators_info={'confidence': avg_confidence}
                    )
                    
                    simulator.analyze_signal(signal, current_price)
                    
                    if simulator.current_position is None:
                        simulator.open_position(signal, current_time, ticker)
            
            if simulator.current_position:
                simulator.close_all_positions(df.index[-1], float(df['close'].iloc[-1]))
                
        finally:
            # sys.stdout = original_stdout
            pass
            
        return simulator.calculate_metrics(ticker, model_name, days_back=(df.index[-1] - df.index[0]).days)
        
    except Exception as e:
        print(f"❌ Error in hybrid backtest: {e}")
        traceback.print_exc()
        return None

def analyze_models():
    print("🚀 STARTING COMPREHENSIVE MODEL RESEARCH")
    print("=" * 60)
    
    models_dir = Path("ml_models")
    model_files = list(models_dir.glob("*.pkl"))
    
    # Group by Ticker
    models_by_ticker = {}
    for m in model_files:
        parts = m.stem.split('_')
        # Heuristic to find ticker: usually 2nd element (e.g. rf_GAZPF_15...)
        # or 3rd if ensemble (ensemble_GAZPF_...)
        # or 4th if triple (triple_ensemble_GAZPF...)
        
        ticker = None
        for p in parts:
            if p in ["GAZPF", "IMOEXF", "NRG6", "RLH6", "S1H6", "VBH6", "SRH6", "GLDRUBF"]:
                ticker = p
                break
        
        if ticker:
            if ticker not in models_by_ticker:
                models_by_ticker[ticker] = []
            models_by_ticker[ticker].append(m)
            
    results_csv = os.path.join(RESULTS_DIR, "model_comparison.csv")
    
    # Load existing results if any
    if os.path.exists(results_csv):
        try:
            existing_df = pd.read_csv(results_csv)
            results = [BacktestMetrics(**row) for row in existing_df.to_dict('records')]
            processed_models = set(existing_df['model_name'].tolist())
            print(f"🔄 Loaded {len(results)} existing results.")
        except Exception:
            results = []
            processed_models = set()
    else:
        results = []
        processed_models = set()
    
    for ticker, models in models_by_ticker.items():
        print(f"\n📊 Analyzing Ticker: {ticker} ({len(models)} models)")
        
        # Load Data (try 15min first, fallback to 1h if needed, but models are specific)
        # We need to match model timeframe to data
        
        # Separate models by timeframe
        models_15m = [m for m in models if "15" in m.stem or "15min" in m.stem]
        models_1h = [m for m in models if "60" in m.stem or "1h" in m.stem]
        
        # --- Process 15m Models ---
        if models_15m:
            print(f"  🔹 Loading 15min data for {ticker}...")
            df_15 = load_data_for_ticker(ticker, "15min")
            
            if df_15 is not None:
                # Limit data for faster analysis
                df_15 = df_15.iloc[-3000:]
                print(f"     Data loaded: {len(df_15)} bars ({df_15.index[0].date()} - {df_15.index[-1].date()})")
                
                settings = load_settings()
                
                # for model_path in models_15m:
                #     print(f"     Testing {model_path.name}...", end="", flush=True)
                #     try:
                #         strategy = MLStrategy(
                #             model_path=str(model_path),
                #             confidence_threshold=settings.ml_strategy.confidence_threshold,
                #             min_signal_strength=settings.ml_strategy.min_signal_strength
                #         )
                #         
                #         metrics = run_backtest_session(strategy, df_15, ticker, model_path.stem)
                #         if metrics:
                #             results.append(metrics)
                #             # Incremental Save
                #             pd.DataFrame([vars(m) for m in results]).to_csv(results_csv, index=False)
                #             print(f" ✅ PnL: {metrics.total_pnl_pct:.2f}% | Sharpe: {metrics.sharpe_ratio:.2f}")
                #         else:
                #             print(f" ❌ Failed")
                #     except Exception as e:
                #         print(f" ❌ Error: {e}")

        # --- Process 1h Models ---
        if models_1h:
            print(f"  🔹 Loading 1h data for {ticker}...")
            df_1h = load_data_for_ticker(ticker, "60min")
            
            if df_1h is not None:
                # Limit data for faster analysis
                df_1h = df_1h.iloc[-1000:]
                print(f"     Data loaded: {len(df_1h)} bars")
                
                # for model_path in models_1h:
                #     if model_path.stem in processed_models:
                #         print(f"     Skipping {model_path.name} (already processed)")
                #         continue
                #         
                #     print(f"     Testing {model_path.name}...", end="", flush=True)
                #     try:
                #         strategy = MLStrategy(
                #             model_path=str(model_path),
                #             confidence_threshold=settings.ml_strategy.confidence_threshold,
                #             min_signal_strength=settings.ml_strategy.min_signal_strength
                #         )
                #         
                #         metrics = run_backtest_session(strategy, df_1h, ticker, model_path.stem)
                #         if metrics:
                #             results.append(metrics)
                #             # Incremental Save
                #             pd.DataFrame([vars(m) for m in results]).to_csv(results_csv, index=False)
                #             print(f" ✅ PnL: {metrics.total_pnl_pct:.2f}% | Sharpe: {metrics.sharpe_ratio:.2f}")
                #         else:
                #             print(f" ❌ Failed")
                #     except Exception as e:
                #         print(f" ❌ Error: {e}")

        # --- HYBRID ENSEMBLE ANALYSIS ---
        # Select top 3 models for this ticker based on Sharpe Ratio
        ticker_results = [r for r in results if r.ticker == ticker]
        if len(ticker_results) >= 3:
            # Check if hybrid already exists
            hybrid_name = f"Hybrid_{ticker}"
            if any(r.model_name == hybrid_name for r in results):
                print(f"  🧬 Hybrid ensemble for {ticker} already processed.")
            else:
                print(f"\n  🧬 Testing Hybrid Ensemble for {ticker}...")
                top_3 = sorted(ticker_results, key=lambda x: x.sharpe_ratio, reverse=True)[:3]
                top_3_names = [m.model_name for m in top_3]
                print(f"     Top 3 models: {', '.join(top_3_names)}")
                
                # Identify common timeframe (prefer 15m)
                ensemble_tf = "15min"
                # If all top models are 1h, use 1h
                if all("60" in m or "1h" in m for m in top_3_names):
                    ensemble_tf = "60min"
                
                # Load data
                df_ensemble = df_15 if ensemble_tf == "15min" and df_15 is not None else df_1h
                
                if df_ensemble is not None:
                    try:
                        # Create strategies
                        strategies = []
                        settings = load_settings()
                        valid_ensemble = True
                        
                        for m_name in top_3_names:
                            # Find path
                            m_path = next((p for p in models if p.stem == m_name), None)
                            if m_path:
                                try:
                                    s = MLStrategy(
                                        model_path=str(m_path),
                                        confidence_threshold=settings.ml_strategy.confidence_threshold,
                                        min_signal_strength=settings.ml_strategy.min_signal_strength
                                    )
                                    strategies.append(s)
                                except Exception:
                                    valid_ensemble = False
                                    break
                        
                        if valid_ensemble and len(strategies) == 3:
                            metrics = run_hybrid_backtest(strategies, df_ensemble, ticker, hybrid_name)
                            if metrics:
                                results.append(metrics)
                                # Incremental Save
                                pd.DataFrame([vars(m) for m in results]).to_csv(results_csv, index=False)
                                print(f"     ✅ Hybrid PnL: {metrics.total_pnl_pct:.2f}% | Sharpe: {metrics.sharpe_ratio:.2f}")
                    except Exception as e:
                        print(f"     ❌ Hybrid Error: {e}")

        # --- MTF COMBINATION ANALYSIS (15m + 1h) ---
        print(f"  ℹ️ Models count: 15m={len(models_15m)}, 1h={len(models_1h)}")
        if models_15m and models_1h:
            print(f"\n  ⏱️ Testing MTF Combinations for {ticker}...")
            
            # Load 15m data (base timeframe for simulation)
            if df_15 is None:
                df_15 = load_data_for_ticker(ticker, "15min")
                if df_15 is not None:
                    df_15 = df_15.iloc[-3000:]
            
            if df_15 is not None:
                # Iterate through all pairs of (best 15m, best 1h) to save time
                # Pick top 2 of each timeframe based on individual performance
                best_15m = sorted([m for m in models_15m if m.stem in processed_models], 
                                key=lambda m: next((r.sharpe_ratio for r in results if r.model_name == m.stem), -999), 
                                reverse=True)[:2]
                
                best_1h = sorted([m for m in models_1h if m.stem in processed_models], 
                               key=lambda m: next((r.sharpe_ratio for r in results if r.model_name == m.stem), -999), 
                               reverse=True)[:2]
                
                # If no processed models found (e.g. first run), use all or top by name
                if not best_15m: best_15m = models_15m[:2]
                if not best_1h: best_1h = models_1h[:2]
                
                import itertools
                for m15, m1h in itertools.product(best_15m, best_1h):
                    combo_name = f"MTF_{m15.stem}_&_{m1h.stem}"
                    
                    if any(r.model_name == combo_name for r in results):
                        continue
                        
                    print(f"     Testing Combo: {m15.stem} (15m) + {m1h.stem} (1h)...", end="", flush=True)
                    
                    try:
                        settings = load_settings()
                        s15 = MLStrategy(str(m15), settings.ml_strategy.confidence_threshold, settings.ml_strategy.min_signal_strength)
                        s1h = MLStrategy(str(m1h), settings.ml_strategy.confidence_threshold, settings.ml_strategy.min_signal_strength)
                        
                        # Use run_hybrid_backtest with these 2 strategies
                        # It requires 2 votes for LONG/SHORT, which effectively means AND condition
                        metrics = run_hybrid_backtest([s15, s1h], df_15, ticker, combo_name)
                        
                        if metrics:
                            results.append(metrics)
                            pd.DataFrame([vars(m) for m in results]).to_csv(results_csv, index=False)
                            print(f" ✅ PnL: {metrics.total_pnl_pct:.2f}% | Sharpe: {metrics.sharpe_ratio:.2f}")
                    except Exception as e:
                        print(f" ❌ Error: {e}")

    # Save Results
    if results:
        # Final Save
        df_results = pd.DataFrame([vars(m) for m in results])
        df_results.to_csv(results_csv, index=False)
        print(f"\n✅ Analysis Complete. Results saved to {results_csv}")
        
        # Generate Report
        generate_report(df_results)
    else:
        print("\n❌ No results generated.")

def generate_report(df: pd.DataFrame):
    report_path = os.path.join(RESULTS_DIR, "comprehensive_report.md")
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 📊 Comprehensive ML Model Analysis Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        
        f.write("## 🏆 Top Performers by ROI (Net Profit %)\n\n")
        top_roi = df.sort_values("total_pnl_pct", ascending=False).head(10)
        f.write(top_roi[["ticker", "model_name", "total_pnl_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate"]].to_markdown(index=False))
        f.write("\n\n")
        
        f.write("## ⚖️ Top Performers by Sharpe Ratio (Stability)\n\n")
        top_sharpe = df.sort_values("sharpe_ratio", ascending=False).head(10)
        f.write(top_sharpe[["ticker", "model_name", "sharpe_ratio", "total_pnl_pct", "profit_factor", "max_drawdown_pct"]].to_markdown(index=False))
        f.write("\n\n")
        
        f.write("## 🛡️ Safest Models (Lowest Drawdown)\n\n")
        top_safe = df[df["total_pnl_pct"] > 0].sort_values("max_drawdown_pct", ascending=True).head(10)
        f.write(top_safe[["ticker", "model_name", "max_drawdown_pct", "total_pnl_pct", "profit_factor", "win_rate"]].to_markdown(index=False))
        f.write("\n\n")
        
        f.write("## 🤖 Model Type Analysis\n\n")
        # Extract model type (rf, xgb, ensemble)
        df["type"] = df["model_name"].apply(lambda x: x.split("_")[0])
        type_stats = df.groupby("type")[["total_pnl_pct", "sharpe_ratio", "win_rate"]].mean()
        f.write(type_stats.to_markdown())
        f.write("\n\n")

    print(f"📄 Report generated: {report_path}")

if __name__ == "__main__":
    analyze_models()
