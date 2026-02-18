"""Script to collect historical data for configured instruments."""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from trading.client import TinkoffClient
from data.collector import DataCollector
from data.storage import DataStorage
from bot.config import load_settings
from utils.logger import logger

# Load environment variables
load_dotenv()


def collect_data_for_instruments(instruments: list, days_back: int = 180, interval: str = "15min"):
    """
    Collect historical data for specified instruments.
    
    Args:
        instruments: List of instrument tickers (e.g., ["VBH6", "SRH6", "GLDRUBF"])
        days_back: Number of days of historical data to collect
        interval: Candle interval (15min, 1hour, day)
    """
    print("\n" + "="*70)
    print("HISTORICAL DATA COLLECTION")
    print("="*70)
    print(f"Instruments: {', '.join(instruments)}")
    print(f"Period: {days_back} days")
    print(f"Interval: {interval}")
    print("="*70 + "\n")
    
    # Initialize clients
    try:
        client = TinkoffClient()
        collector = DataCollector(client=client)
        storage = DataStorage()
    except Exception as e:
        print(f"❌ ERROR: Failed to initialize clients: {e}")
        return
    
    # Calculate date range
    to_date = datetime.now()
    from_date = to_date - timedelta(days=days_back)
    
    print(f"Date range: {from_date.date()} to {to_date.date()}\n")
    
    # Collect data for each instrument
    for i, ticker in enumerate(instruments, 1):
        print(f"\n[{i}/{len(instruments)}] Processing {ticker}...")
        print("-" * 70)
        
        try:
            # Step 1: Find and save instrument info
            print(f"1. Finding instrument {ticker}...")
            instrument_info = collector.collect_instrument_info(
                ticker=ticker,
                instrument_type="futures",
                prefer_perpetual=False
            )
            
            if not instrument_info:
                print(f"   ❌ Instrument {ticker} not found. Skipping...")
                continue
            
            figi = instrument_info["figi"]
            print(f"   ✓ Found: {instrument_info['name']} (FIGI: {figi})")
            
            # Step 2: Check existing data
            print(f"\n2. Checking existing data...")
            existing_range = storage.get_data_range(figi, interval)
            if existing_range:
                existing_from, existing_to = existing_range
                print(f"   Existing data: {existing_from.date()} to {existing_to.date()}")
            else:
                print(f"   No existing data found.")
            
            # Step 3: Collect missing candles
            # collect_candles автоматически проверяет существующие данные и собирает только недостающие периоды
            print(f"\n3. Collecting missing candles...")
            candles = collector.collect_candles(
                figi=figi,
                from_date=from_date,
                to_date=to_date,
                interval=interval,
                save=True
            )
            
            if candles:
                print(f"   ✓ Collected {len(candles)} new candles")
            else:
                print(f"   ✓ No new candles needed (all data already exists)")
            
            # Step 4: Update to latest (collect any candles after to_date up to now)
            print(f"\n4. Updating to latest data...")
            new_candles = collector.update_candles(
                figi=figi,
                interval=interval,
                days_back=1
            )
            
            if new_candles > 0:
                print(f"   ✓ Updated with {new_candles} new candles")
            else:
                print(f"   ✓ Already up to date")
            
            # Step 5: Summary
            print(f"\n5. Summary for {ticker}:")
            final_range = storage.get_data_range(figi, interval)
            if final_range:
                final_from, final_to = final_range
                df = storage.get_candles(figi=figi, interval=interval)
                print(f"   Total candles: {len(df)}")
                print(f"   Date range: {final_from.date()} to {final_to.date()}")
                print(f"   ✓ {ticker} data collection completed")
            else:
                print(f"   ⚠️  No data available for {ticker}")
            
        except Exception as e:
            print(f"   ❌ ERROR processing {ticker}: {e}")
            import traceback
            traceback.print_exc()
            continue
        
        # Small delay between instruments
        if i < len(instruments):
            print(f"\n   Waiting 2 seconds before next instrument...")
            import time
            time.sleep(2)
    
    print("\n" + "="*70)
    print("DATA COLLECTION COMPLETED")
    print("="*70)
    print(f"\nData saved to: {storage.data_dir}")
    print(f"Cache files: {list(storage.data_dir.glob('*_cache.csv'))}")
    print(f"Instruments file: {storage.data_dir / 'instruments.csv'}")


def main():
    """Main function."""
    # Load settings
    settings = load_settings()
    
    # Get instruments from settings or command line
    if len(sys.argv) > 1:
        instruments = [ticker.strip().upper() for ticker in sys.argv[1:]]
    elif settings.instruments:
        instruments = settings.instruments
    else:
        # Default instruments
        instruments = ["VBH6", "SRH6", "GLDRUBF"]
        print(f"⚠️  No instruments specified. Using defaults: {instruments}")
        print(f"   To specify instruments, use: python {sys.argv[0]} VBH6 SRH6 GLDRUBF")
        print(f"   Or set TRADING_INSTRUMENTS in .env file\n")
    
    # Get days from environment or use default
    days_back = int(os.getenv("DATA_COLLECTION_DAYS", "180"))
    
    # Get interval from environment or use default
    interval = os.getenv("DATA_COLLECTION_INTERVAL", "15min")
    
    # Collect data
    collect_data_for_instruments(
        instruments=instruments,
        days_back=days_back,
        interval=interval
    )


if __name__ == "__main__":
    main()
