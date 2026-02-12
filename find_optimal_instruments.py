"""Script to find optimal trading instruments based on lot cost, volatility, and volume."""
import argparse
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import pandas as pd
import numpy as np
from dotenv import load_dotenv

from trading.client import TinkoffClient
from data.collector import DataCollector
from utils.logger import logger

# Load environment variables
load_dotenv()


def get_all_futures(client: TinkoffClient) -> List[Dict[str, Any]]:
    """
    Get list of all available futures from Tinkoff API.
    
    Returns:
        List of dictionaries with figi, ticker, name
    """
    futures = []
    try:
        with client._get_client() as tinkoff_client:
            logger.info("Fetching all futures from Tinkoff API...")
            response = tinkoff_client.instruments.futures()
            
            for instrument in response.instruments:
                futures.append({
                    "figi": instrument.figi,
                    "ticker": instrument.ticker,
                    "name": instrument.name
                })
            
            logger.info(f"Found {len(futures)} futures")
    except Exception as e:
        logger.error(f"Error fetching futures: {e}", exc_info=True)
    
    return futures


def get_current_price(client: TinkoffClient, figi: str) -> Optional[float]:
    """
    Get current price for instrument by fetching last candle.
    
    Args:
        client: TinkoffClient instance
        figi: Instrument FIGI
    
    Returns:
        Current price or None if error
    """
    try:
        # Get last few candles to get current price
        to_date = datetime.now()
        from_date = to_date - timedelta(days=1)
        
        candles = client.get_candles(figi, from_date, to_date, interval="1hour")
        if candles:
            # Use last candle's close price
            return candles[-1]["close"]
        
        # Try with 15min interval if hourly failed
        candles = client.get_candles(figi, from_date, to_date, interval="15min")
        if candles:
            return candles[-1]["close"]
        
        logger.warning(f"No candles found for {figi} to get current price")
        return None
    except Exception as e:
        logger.warning(f"Error getting current price for {figi}: {e}")
        return None


def get_instrument_info(client: TinkoffClient, figi: str) -> Dict[str, Any]:
    """
    Get instrument information (lot size, price step).
    
    Args:
        client: TinkoffClient instance
        figi: Instrument FIGI
    
    Returns:
        Dict with lot_size, price_step
    """
    try:
        lot_size = client.get_qty_step(figi)
        price_step = client.get_price_step(figi)
        
        return {
            "lot_size": lot_size,
            "price_step": price_step
        }
    except Exception as e:
        logger.warning(f"Error getting instrument info for {figi}: {e}")
        return {
            "lot_size": 1.0,
            "price_step": 0.01
        }


def calculate_volatility(df: pd.DataFrame, current_price: float) -> float:
    """
    Calculate daily volatility percentage from historical data.
    
    Uses ATR (Average True Range) method normalized by current price.
    
    Args:
        df: DataFrame with columns: open, high, low, close
        current_price: Current price of instrument
    
    Returns:
        Daily volatility as percentage
    """
    if df.empty or len(df) < 2:
        return 0.0
    
    try:
        # Calculate True Range
        df = df.copy()
        df['prev_close'] = df['close'].shift(1)
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['prev_close'])
        df['tr3'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # Calculate ATR (14 period, or use all available data if less)
        period = min(14, len(df) - 1)
        if period > 0:
            atr = df['tr'].tail(period).mean()
        else:
            atr = df['tr'].mean()
        
        # Convert to daily volatility percentage
        if current_price > 0:
            volatility_pct = (atr / current_price) * 100
        else:
            volatility_pct = 0.0
        
        return volatility_pct
    except Exception as e:
        logger.warning(f"Error calculating volatility: {e}")
        # Fallback: use standard deviation of daily returns
        try:
            df['returns'] = df['close'].pct_change()
            daily_std = df['returns'].std() * 100
            return abs(daily_std) if not np.isnan(daily_std) else 0.0
        except:
            return 0.0


def calculate_avg_volume(df: pd.DataFrame, lot_size: float, current_price: float) -> Dict[str, float]:
    """
    Calculate average trading volume.
    
    Args:
        df: DataFrame with volume column
        lot_size: Lot size for instrument
        current_price: Current price
    
    Returns:
        Dict with avg_volume_lots and avg_volume_rub
    """
    if df.empty:
        return {"avg_volume_lots": 0.0, "avg_volume_rub": 0.0}
    
    try:
        # Calculate daily volumes
        # Group by date if we have timestamp column
        if 'timestamp' in df.columns:
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.date
        elif 'time' in df.columns:
            df['date'] = pd.to_datetime(df['time']).dt.date
        else:
            # Use index as date if no timestamp
            df['date'] = df.index
        
        daily_volumes = df.groupby('date')['volume'].sum()
        avg_volume = daily_volumes.mean()
        
        # For Tinkoff API, volume is typically in units (contracts), not lots
        # Convert to lots (divide by lot_size)
        # Note: Some instruments might have volume already in lots, but we'll convert anyway
        avg_volume_lots = avg_volume / lot_size if lot_size > 0 else avg_volume
        
        # Calculate volume in rubles: volume_lots * lot_size * price
        # This gives us the total value traded
        avg_volume_rub = avg_volume_lots * lot_size * current_price if current_price > 0 else 0.0
        
        return {
            "avg_volume_lots": float(avg_volume_lots),
            "avg_volume_rub": float(avg_volume_rub)
        }
    except Exception as e:
        logger.warning(f"Error calculating average volume: {e}")
        return {"avg_volume_lots": 0.0, "avg_volume_rub": 0.0}


def analyze_instrument(
    client: TinkoffClient,
    collector: DataCollector,
    figi: str,
    ticker: str,
    name: str,
    balance: float,
    margin_pct: float,
    volatility_min: float,
    volatility_max: float,
    period_days: int,
    margin_rate: float = 0.15
) -> Optional[Dict[str, Any]]:
    """
    Analyze single instrument.
    
    Args:
        client: TinkoffClient instance
        collector: DataCollector instance
        figi: Instrument FIGI
        ticker: Instrument ticker
        name: Instrument name
        balance: Account balance in RUB
        margin_pct: Maximum margin percentage of balance
        volatility_min: Minimum volatility threshold
        volatility_max: Maximum volatility threshold
        period_days: Analysis period in days
        margin_rate: Margin rate for futures (default 0.15 = 15%)
    
    Returns:
        Dict with analysis results or None if doesn't meet criteria
    """
    try:
        logger.info(f"Analyzing {ticker} ({figi})...")
        
        # Get instrument info
        info = get_instrument_info(client, figi)
        lot_size = info["lot_size"]
        price_step = info["price_step"]
        
        # Get current price
        current_price = get_current_price(client, figi)
        if current_price is None or current_price <= 0:
            logger.warning(f"Skipping {ticker}: cannot get current price")
            return None
        
        # Calculate lot value and margin
        lot_value = current_price * lot_size
        margin_per_lot = lot_value * margin_rate
        
        # Check margin criterion
        max_margin = balance * (margin_pct / 100.0)
        if margin_per_lot > max_margin:
            logger.debug(f"Skipping {ticker}: margin {margin_per_lot:.2f} > max {max_margin:.2f}")
            return None
        
        # Collect historical data
        to_date = datetime.now()
        from_date = to_date - timedelta(days=period_days)
        
        logger.debug(f"Collecting historical data for {ticker} from {from_date.date()} to {to_date.date()}")
        candles = collector.collect_candles(
            figi=figi,
            from_date=from_date,
            to_date=to_date,
            interval="1hour",  # Use hourly for volatility calculation
            save=False  # Don't save to avoid cluttering storage
        )
        
        if not candles or len(candles) < 10:
            logger.warning(f"Skipping {ticker}: insufficient historical data ({len(candles) if candles else 0} candles)")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        if 'time' in df.columns:
            # Convert time to datetime if needed
            df['time'] = pd.to_datetime(df['time'])
            df['timestamp'] = df['time'].astype('int64') // 10**6  # Convert to milliseconds
        # Sort by time
        if 'time' in df.columns:
            df = df.sort_values('time').reset_index(drop=True)
        
        # Calculate volatility
        volatility = calculate_volatility(df, current_price)
        
        # Check volatility criterion
        if volatility < volatility_min or volatility > volatility_max:
            logger.debug(f"Skipping {ticker}: volatility {volatility:.2f}% not in range [{volatility_min}, {volatility_max}]")
            return None
        
        # Calculate average volume
        volume_info = calculate_avg_volume(df, lot_size, current_price)
        
        # Calculate score (higher is better)
        # Score based on volume (higher volume = higher score)
        # and volatility closeness to middle of range
        volatility_mid = (volatility_min + volatility_max) / 2
        volatility_score = 1.0 - abs(volatility - volatility_mid) / volatility_mid
        volume_score = min(volume_info["avg_volume_rub"] / 1000000.0, 1.0)  # Normalize to 1M RUB
        score = (volume_score * 0.7 + volatility_score * 0.3) * 100
        
        result = {
            "figi": figi,
            "ticker": ticker,
            "name": name,
            "current_price": current_price,
            "lot_size": lot_size,
            "price_step": price_step,
            "lot_value": lot_value,
            "margin_per_lot": margin_per_lot,
            "margin_pct_of_balance": (margin_per_lot / balance) * 100 if balance > 0 else 0,
            "volatility_pct": volatility,
            "avg_volume_lots": volume_info["avg_volume_lots"],
            "avg_volume_rub": volume_info["avg_volume_rub"],
            "score": score,
            "date_analyzed": datetime.now().isoformat(),
            "analysis_period_days": period_days
        }
        
        logger.info(f"✓ {ticker}: margin={margin_per_lot:.2f} руб ({result['margin_pct_of_balance']:.1f}%), "
                   f"volatility={volatility:.2f}%, volume={volume_info['avg_volume_rub']:.0f} руб/день")
        
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing {ticker}: {e}", exc_info=True)
        return None


def filter_and_rank_instruments(results: List[Dict[str, Any]], limit: int = 50) -> List[Dict[str, Any]]:
    """
    Filter and rank instruments by priority.
    
    Priority:
    1. Volume (descending) - more liquid instruments preferred
    2. Volatility (closer to middle of range)
    3. Margin cost (lower is better for diversification)
    
    Args:
        results: List of analysis results
        limit: Maximum number of results to return
    
    Returns:
        Sorted and limited list of results
    """
    if not results:
        return []
    
    # Sort by score (descending), then by volume, then by margin
    sorted_results = sorted(
        results,
        key=lambda x: (
            -x.get("score", 0),  # Higher score first
            -x.get("avg_volume_rub", 0),  # Higher volume first
            x.get("margin_per_lot", float('inf'))  # Lower margin first
        )
    )
    
    return sorted_results[:limit]


def print_results(results: List[Dict[str, Any]]):
    """Print results to console as formatted table."""
    if not results:
        print("\n❌ No instruments found matching the criteria.")
        return
    
    print(f"\n{'='*120}")
    print(f"FOUND {len(results)} OPTIMAL INSTRUMENTS")
    print(f"{'='*120}\n")
    
    # Print header
    header = (
        f"{'Ticker':<12} {'Price':<10} {'Lot Size':<10} {'Lot Value':<12} "
        f"{'Margin':<10} {'Margin %':<10} {'Volatility %':<12} "
        f"{'Avg Vol (lots)':<15} {'Avg Vol (RUB)':<15} {'Score':<8}"
    )
    print(header)
    print("-" * 120)
    
    # Print rows
    for r in results:
        row = (
            f"{r['ticker']:<12} {r['current_price']:>9.2f} {r['lot_size']:>9.1f} "
            f"{r['lot_value']:>11.2f} {r['margin_per_lot']:>9.2f} "
            f"{r['margin_pct_of_balance']:>9.1f}% {r['volatility_pct']:>11.2f}% "
            f"{r['avg_volume_lots']:>14.1f} {r['avg_volume_rub']:>14.0f} "
            f"{r['score']:>7.1f}"
        )
        print(row)
    
    print(f"\n{'='*120}\n")


def save_to_csv(results: List[Dict[str, Any]], filename: str):
    """Save results to CSV file."""
    if not results:
        logger.warning("No results to save")
        return
    
    try:
        df = pd.DataFrame(results)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"✓ Results saved to {filename}")
        print(f"✓ Results saved to {filename}")
    except Exception as e:
        logger.error(f"Error saving CSV: {e}", exc_info=True)
        print(f"❌ Error saving CSV: {e}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Find optimal trading instruments based on lot cost, volatility, and volume"
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=5000.0,
        help="Account balance in RUB (default: 5000)"
    )
    parser.add_argument(
        "--margin-pct",
        type=float,
        default=25.0,
        help="Maximum margin percentage of balance per lot (default: 25)"
    )
    parser.add_argument(
        "--volatility-min",
        type=float,
        default=1.0,
        help="Minimum daily volatility percentage (default: 1.0)"
    )
    parser.add_argument(
        "--volatility-max",
        type=float,
        default=5.0,
        help="Maximum daily volatility percentage (default: 5.0)"
    )
    parser.add_argument(
        "--period-days",
        type=int,
        default=30,
        help="Analysis period in days (default: 30)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV filename (default: optimal_instruments_YYYYMMDD_HHMMSS.csv)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of results (default: 50)"
    )
    parser.add_argument(
        "--margin-rate",
        type=float,
        default=0.15,
        help="Margin rate for futures (default: 0.15 = 15%%)"
    )
    
    args = parser.parse_args()
    
    # Generate output filename if not provided
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"optimal_instruments_{timestamp}.csv"
    
    print("\n" + "="*120)
    print("OPTIMAL INSTRUMENTS FINDER")
    print("="*120)
    print(f"Balance: {args.balance:.2f} RUB")
    print(f"Max margin per lot: {args.margin_pct}% of balance = {args.balance * args.margin_pct / 100:.2f} RUB")
    print(f"Volatility range: {args.volatility_min}% - {args.volatility_max}%")
    print(f"Analysis period: {args.period_days} days")
    print(f"Margin rate: {args.margin_rate * 100:.1f}%")
    print(f"Max results: {args.limit}")
    print("="*120 + "\n")
    
    # Initialize clients
    try:
        client = TinkoffClient()
        collector = DataCollector(client=client)
    except Exception as e:
        logger.error(f"Failed to initialize clients: {e}", exc_info=True)
        print(f"❌ Error: {e}")
        return
    
    # Get all futures
    futures = get_all_futures(client)
    if not futures:
        print("❌ No futures found or error fetching futures")
        return
    
    print(f"Analyzing {len(futures)} futures...\n")
    
    # Analyze each instrument
    results = []
    processed = 0
    for future in futures:
        processed += 1
        print(f"[{processed}/{len(futures)}] ", end="", flush=True)
        
        result = analyze_instrument(
            client=client,
            collector=collector,
            figi=future["figi"],
            ticker=future["ticker"],
            name=future["name"],
            balance=args.balance,
            margin_pct=args.margin_pct,
            volatility_min=args.volatility_min,
            volatility_max=args.volatility_max,
            period_days=args.period_days,
            margin_rate=args.margin_rate
        )
        
        if result:
            results.append(result)
    
    # Filter and rank
    ranked_results = filter_and_rank_instruments(results, limit=args.limit)
    
    # Print results
    print_results(ranked_results)
    
    # Save to CSV
    if ranked_results:
        save_to_csv(ranked_results, args.output)
    
    print(f"\n✓ Analysis complete. Found {len(ranked_results)} optimal instruments out of {len(futures)} analyzed.")


if __name__ == "__main__":
    main()
