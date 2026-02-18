"""Script to list available instruments from Tinkoff API."""
import os
from dotenv import load_dotenv

from trading.client import TinkoffClient
from utils.logger import logger

# Load environment variables
load_dotenv()

def list_futures():
    """List all available futures."""
    print("\n" + "="*60)
    print("LISTING AVAILABLE FUTURES")
    print("="*60)
    
    try:
        client = TinkoffClient()
        
        with client._get_client() as tinkoff_client:
            print("Fetching futures list...")
            response = tinkoff_client.instruments.futures()
            
            print(f"\nTotal futures found: {len(response.instruments)}")
            print("\nFirst 50 futures:")
            print("-" * 80)
            print(f"{'Ticker':<15} {'FIGI':<20} {'Name':<40}")
            print("-" * 80)
            
            for i, instrument in enumerate(response.instruments[:50]):
                print(f"{instrument.ticker:<15} {instrument.figi:<20} {instrument.name[:40]:<40}")
            
            if len(response.instruments) > 50:
                print(f"\n... and {len(response.instruments) - 50} more futures")
            
            # Поиск похожих тикеров
            print("\n" + "="*60)
            print("SEARCHING FOR SIMILAR TICKERS")
            print("="*60)
            
            search_terms = ["Si", "RI", "RTS", "SBRF", "GAZP", "LKOH"]
            for term in search_terms:
                matches = [inst for inst in response.instruments if term.upper() in inst.ticker.upper()]
                if matches:
                    print(f"\nTickers containing '{term}':")
                    for inst in matches[:10]:
                        print(f"  {inst.ticker:<15} - {inst.name}")
                    if len(matches) > 10:
                        print(f"  ... and {len(matches) - 10} more")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_find_instrument():
    """Test find_instrument method."""
    print("\n" + "="*60)
    print("TESTING find_instrument METHOD")
    print("="*60)
    
    try:
        client = TinkoffClient()
        
        test_queries = ["Si", "RI", "RTS", "фьючерс"]
        
        with client._get_client() as tinkoff_client:
            from t_tech.invest.schemas import InstrumentType
            
            for query in test_queries:
                print(f"\nSearching for: '{query}'")
                try:
                    response = tinkoff_client.instruments.find_instrument(
                        query=query,
                        instrument_kind=InstrumentType.INSTRUMENT_TYPE_FUTURES,
                        api_trade_available_flag=True
                    )
                    
                    if response.instruments:
                        print(f"  Found {len(response.instruments)} instruments:")
                        for inst in response.instruments[:5]:
                            print(f"    {inst.ticker:<15} - {inst.name}")
                        if len(response.instruments) > 5:
                            print(f"    ... and {len(response.instruments) - 5} more")
                    else:
                        print(f"  No instruments found")
                except Exception as e:
                    print(f"  Error: {e}")
                    
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main function."""
    print("\n" + "="*60)
    print("TINKOFF INSTRUMENTS EXPLORER")
    print("="*60)
    
    # Test connection
    try:
        token = os.getenv("TINKOFF_TOKEN", "").strip()
        if not token:
            print("❌ ERROR: TINKOFF_TOKEN not found in .env file!")
            return
        
        print(f"✓ Token found (length: {len(token)})")
        client = TinkoffClient()
        print("✓ Client initialized")
    except Exception as e:
        print(f"❌ ERROR initializing client: {e}")
        return
    
    # List futures
    list_futures()
    
    # Test find_instrument
    test_find_instrument()
    
    print("\n" + "="*60)
    print("EXPLORATION COMPLETE")
    print("="*60)

if __name__ == "__main__":
    main()
