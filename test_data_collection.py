"""Test script for data collection from Tinkoff API."""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

from trading.client import TinkoffClient
from data.collector import DataCollector
from data.storage import DataStorage
from utils.logger import logger

# Load environment variables
load_dotenv()

def test_client_connection():
    """Test Tinkoff client connection."""
    print("\n" + "="*60)
    print("TEST 1: Tinkoff Client Connection")
    print("="*60)
    
    try:
        token = os.getenv("TINKOFF_TOKEN", "").strip()
        sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() in ("true", "1", "yes")
        
        if not token:
            print("❌ ERROR: TINKOFF_TOKEN not found in .env file!")
            print("   Please set TINKOFF_TOKEN in .env file")
            return False
        
        print(f"✓ Token found (length: {len(token)})")
        print(f"✓ Sandbox mode: {sandbox}")
        
        client = TinkoffClient(token=token, sandbox=sandbox)
        print("✓ TinkoffClient initialized successfully")
        
        return True
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_find_instrument():
    """Test finding instrument by ticker."""
    print("\n" + "="*60)
    print("TEST 2: Find Instrument")
    print("="*60)
    
    try:
        client = TinkoffClient()
        
        # Test with provided tickers
        test_tickers = ["VBH6", "SRH6", "GLDRUBF"]
        
        for test_ticker in test_tickers:
            print(f"Searching for instrument: {test_ticker}")
            
            instrument = client.find_instrument(
                ticker=test_ticker,
                instrument_type="futures",
                prefer_perpetual=False
            )
            
            if instrument:
                print(f"✓ Instrument found:")
                print(f"  FIGI: {instrument['figi']}")
                print(f"  Ticker: {instrument['ticker']}")
                print(f"  Name: {instrument['name']}")
                print(f"  Type: {instrument['instrument_type']}")
                return instrument
            
            print(f"  ⚠️  Not found: {test_ticker}")
        
        # Если ничего не нашли, попробуем получить список доступных
        print(f"\n❌ Could not find any of the test instruments: {test_tickers}")
        print("\nTrying to get list of available futures...")
        try:
            with client._get_client() as tinkoff_client:
                response = tinkoff_client.instruments.futures()
                print(f"Total futures available: {len(response.instruments)}")
                print("\nFirst 30 futures tickers:")
                for i, inst in enumerate(response.instruments[:30], 1):
                    print(f"  {i}. {inst.ticker:<15} - {inst.name}")
                
                # Проверяем, есть ли похожие тикеры
                print("\nSearching for similar tickers...")
                for test_ticker in test_tickers:
                    similar = [inst for inst in response.instruments 
                              if test_ticker.upper() in inst.ticker.upper() 
                              or inst.ticker.upper() in test_ticker.upper()]
                    if similar:
                        print(f"\n  Similar to '{test_ticker}':")
                        for inst in similar[:5]:
                            print(f"    {inst.ticker:<15} - {inst.name}")
                    else:
                        print(f"  No similar tickers found for '{test_ticker}'")
        except Exception as e:
            print(f"Error getting futures list: {e}")
            import traceback
            traceback.print_exc()
        
        return None
                
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

def test_get_candles(client: TinkoffClient, figi: str):
    """Test getting candles from API."""
    print("\n" + "="*60)
    print("TEST 3: Get Candles from API")
    print("="*60)
    
    try:
        # Get candles for last 2 days
        to_date = datetime.now()
        from_date = to_date - timedelta(days=2)
        
        print(f"Requesting candles for FIGI: {figi}")
        print(f"From: {from_date.date()}")
        print(f"To: {to_date.date()}")
        print(f"Interval: 15min")
        
        candles = client.get_candles(
            figi=figi,
            from_date=from_date,
            to_date=to_date,
            interval="15min"
        )
        
        if candles:
            print(f"✓ Successfully retrieved {len(candles)} candles")
            
            # Show first and last candle
            if len(candles) > 0:
                first = candles[0]
                last = candles[-1]
                print(f"\nFirst candle:")
                print(f"  Time: {first['time']}")
                print(f"  O: {first['open']:.2f}, H: {first['high']:.2f}, L: {first['low']:.2f}, C: {first['close']:.2f}")
                print(f"  Volume: {first['volume']}")
                
                print(f"\nLast candle:")
                print(f"  Time: {last['time']}")
                print(f"  O: {last['open']:.2f}, H: {last['high']:.2f}, L: {last['low']:.2f}, C: {last['close']:.2f}")
                print(f"  Volume: {last['volume']}")
            
            return candles
        else:
            print("⚠️  No candles retrieved")
            return []
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return []

def test_data_collector(instrument_info: dict):
    """Test DataCollector."""
    print("\n" + "="*60)
    print("TEST 4: Data Collector")
    print("="*60)
    
    try:
        collector = DataCollector()
        
        ticker = instrument_info['ticker']
        figi = instrument_info['figi']
        
        print(f"Testing with instrument: {ticker} ({figi})")
        
        # Test collect_instrument_info
        print("\n1. Testing collect_instrument_info...")
        saved_instrument = collector.collect_instrument_info(ticker, instrument_type="futures")
        
        if saved_instrument:
            print(f"✓ Instrument info saved to CSV files")
            print(f"  FIGI: {saved_instrument['figi']}")
            print(f"  Ticker: {saved_instrument['ticker']}")
        else:
            print("⚠️  Could not save instrument info")
        
        # Test collect_candles
        print("\n2. Testing collect_candles...")
        to_date = datetime.now()
        from_date = to_date - timedelta(days=1)  # Last 1 day
        
        print(f"Collecting candles from {from_date.date()} to {to_date.date()}")
        
        candles = collector.collect_candles(
            figi=figi,
            from_date=from_date,
            to_date=to_date,
            interval="15min",
            save=True
        )
        
        if candles:
            print(f"✓ Collected and saved {len(candles)} candles to CSV files")
        else:
            print("⚠️  No candles collected")
        
        # Test reading from CSV files
        print("\n3. Testing read from CSV files...")
        storage = DataStorage()
        df = storage.get_candles(figi=figi, interval="15min", limit=10)
        
        if not df.empty:
            print(f"✓ Successfully read {len(df)} candles from CSV files")
            print(f"\nLast 5 candles:")
            print(df[['time', 'open', 'high', 'low', 'close', 'volume']].tail().to_string())
        else:
            print("⚠️  No data in CSV files")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_update_candles(figi: str):
    """Test updating candles."""
    print("\n" + "="*60)
    print("TEST 5: Update Candles")
    print("="*60)
    
    try:
        collector = DataCollector()
        
        print(f"Updating candles for FIGI: {figi}")
        print("This will collect new candles since last saved point...")
        
        new_candles = collector.update_candles(
            figi=figi,
            interval="15min",
            days_back=1
        )
        
        print(f"✓ Updated: {new_candles} new candles collected")
        
        return True
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("TINKOFF DATA COLLECTION TEST")
    print("="*60)
    
    # Test 1: Client connection
    if not test_client_connection():
        print("\n❌ Client connection test failed. Stopping tests.")
        return
    
    # Test 2: Find instrument
    instrument = test_find_instrument()
    if not instrument:
        print("\n❌ Could not find test instrument. Stopping tests.")
        return
    
    figi = instrument['figi']
    
    # Test 3: Get candles directly from API
    client = TinkoffClient()
    candles = test_get_candles(client, figi)
    
    if not candles:
        print("\n⚠️  Could not get candles from API. Continuing with other tests...")
    
    # Test 4: Data collector
    test_data_collector(instrument)
    
    # Test 5: Update candles
    test_update_candles(figi)
    
    print("\n" + "="*60)
    print("ALL TESTS COMPLETED")
    print("="*60)
    print("\nIf all tests passed, data collection is working correctly!")
    print("You can now use DataCollector in your trading bot.")

if __name__ == "__main__":
    main()
