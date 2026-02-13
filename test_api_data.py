#!/usr/bin/env python3
"""
Тестовый скрипт для проверки данных, которые возвращает Tinkoff API
по балансу и позициям.
"""
import os
import sys
import json
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.insert(0, str(Path(__file__).parent))

# Загружаем переменные окружения из .env файла
try:
    from dotenv import load_dotenv
    load_dotenv()  # Загружает .env из текущей директории
    print("✅ Loaded .env file")
except ImportError:
    print("⚠️  python-dotenv not installed, trying to use environment variables directly")

from trading.client import TinkoffClient
from utils.logger import logger

def print_section(title):
    """Печатает заголовок секции."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")

def print_dict(data, indent=0):
    """Печатает словарь в читаемом формате."""
    for key, value in data.items():
        if isinstance(value, dict):
            print("  " * indent + f"{key}:")
            print_dict(value, indent + 1)
        elif isinstance(value, list):
            print("  " * indent + f"{key}: [{len(value)} items]")
            for i, item in enumerate(value):
                print("  " * (indent + 1) + f"[{i}]:")
                if isinstance(item, dict):
                    print_dict(item, indent + 2)
                else:
                    print("  " * (indent + 2) + str(item))
        else:
            print("  " * indent + f"{key}: {value}")

def test_balance():
    """Тестирует получение баланса."""
    print_section("БАЛАНС (get_wallet_balance)")
    
    try:
        client = TinkoffClient()
        balance_info = client.get_wallet_balance()
        
        print("Raw response:")
        print(json.dumps(balance_info, indent=2, ensure_ascii=False))
        
        print("\n" + "-" * 80)
        print("Parsed data:")
        print("-" * 80)
        
        if balance_info.get("retCode") == 0:
            result = balance_info.get("result", {})
            list_data = result.get("list", [])
            
            if list_data:
                wallet = list_data[0].get("coin", [])
                rub_coin = next((c for c in wallet if c.get("coin") == "RUB"), None)
                
                if rub_coin:
                    wallet_balance = float(rub_coin.get("walletBalance", 0))
                    available_balance = float(rub_coin.get("availableBalance", 0))
                    
                    print(f"Wallet Balance: {wallet_balance:.2f} руб")
                    print(f"Available Balance: {available_balance:.2f} руб")
                    print(f"Difference (frozen margin): {wallet_balance - available_balance:.2f} руб")
                else:
                    print("RUB coin not found in response")
            else:
                print("No data in response")
        else:
            print(f"Error: {balance_info.get('retMsg', 'Unknown error')}")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_positions():
    """Тестирует получение позиций."""
    print_section("ПОЗИЦИИ (get_position_info)")
    
    try:
        client = TinkoffClient()
        
        # Получаем все позиции
        print("Getting all positions...")
        pos_info = client.get_position_info()
        
        print("\nRaw response:")
        print(json.dumps(pos_info, indent=2, ensure_ascii=False))
        
        print("\n" + "-" * 80)
        print("Parsed data:")
        print("-" * 80)
        
        if pos_info.get("retCode") == 0:
            list_data = pos_info.get("result", {}).get("list", [])
            
            if list_data:
                print(f"Found {len(list_data)} position(s):\n")
                
                for i, pos in enumerate(list_data):
                    print(f"Position #{i + 1}:")
                    print(f"  FIGI: {pos.get('figi', 'N/A')}")
                    print(f"  Quantity: {pos.get('quantity', 0)}")
                    print(f"  Average Price: {pos.get('average_price', 0):.2f}")
                    print(f"  Current Price: {pos.get('current_price', 0):.2f}")
                    
                    # Проверяем наличие полей маржи
                    if "current_margin" in pos:
                        print(f"  Current Margin: {pos.get('current_margin', 0):.2f} руб")
                    else:
                        print(f"  Current Margin: NOT IN RESPONSE")
                    
                    if "initial_margin" in pos:
                        print(f"  Initial Margin: {pos.get('initial_margin', 0):.2f} руб")
                    else:
                        print(f"  Initial Margin: NOT IN RESPONSE")
                    
                    if "blocked" in pos:
                        print(f"  Blocked: {pos.get('blocked', 0):.2f} руб")
                    else:
                        print(f"  Blocked: NOT IN RESPONSE")
                    
                    if "expected_yield" in pos:
                        print(f"  Expected Yield (Variation Margin): {pos.get('expected_yield', 0):.2f} руб")
                    else:
                        print(f"  Expected Yield: NOT IN RESPONSE")
                    
                    # Рассчитываем маржу
                    quantity = abs(float(pos.get('quantity', 0)))
                    avg_price = float(pos.get('average_price', 0))
                    calculated_margin = avg_price * quantity * 1.0 * 0.12  # Предполагаем lot_size=1, margin_rate=0.12
                    print(f"  Calculated Margin (12%): {calculated_margin:.2f} руб")
                    
                    print()
            else:
                print("No positions found")
        else:
            print(f"Error: {pos_info.get('retMsg', 'Unknown error')}")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_instrument_info():
    """Тестирует получение информации об инструменте, включая маржу."""
    print_section("ИНФОРМАЦИЯ ОБ ИНСТРУМЕНТЕ (get_instrument_by)")
    
    try:
        from t_tech.invest import Client, InstrumentIdType
        from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
        
        token = os.getenv("TINKOFF_TOKEN", "").strip()
        if not token:
            print("ERROR: TINKOFF_TOKEN not found in environment")
            return
        
        sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
        target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
        
        # Тестируем для S1H6 (FUTSILVM0326)
        test_figi = "FUTSILVM0326"
        
        with Client(token=token, target=target) as client:
            print(f"Getting instrument info for {test_figi}...\n")
            
            try:
                response = client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=test_figi
                )
                instrument = response.instrument
                
                print("Instrument object:")
                print(f"  All attributes: {dir(instrument)}")
                
                # Проверяем все атрибуты, связанные с маржой
                margin_related = [attr for attr in dir(instrument) if 'margin' in attr.lower() or 'guarantee' in attr.lower() or 'collateral' in attr.lower()]
                print(f"\n  Margin/guarantee related attributes: {margin_related}")
                
                for attr in margin_related:
                    if not attr.startswith('_'):
                        try:
                            value = getattr(instrument, attr)
                            print(f"  {attr}: {value} (type: {type(value)})")
                            if value is not None and not isinstance(value, bool):
                                if hasattr(value, 'units'):
                                    units = value.units
                                    nano = value.nano if hasattr(value, 'nano') else 0
                                    total = float(units) + float(nano) / 1e9
                                    print(f"    total: {total:.2f}")
                        except Exception as e:
                            print(f"  {attr}: Error accessing - {e}")
                
                # Проверяем основные атрибуты
                important_attrs = ['lot', 'min_price_increment', 'ticker', 'name']
                print(f"\n  Important attributes:")
                for attr in important_attrs:
                    if hasattr(instrument, attr):
                        value = getattr(instrument, attr)
                        print(f"    {attr}: {value}")
                        
            except Exception as e:
                print(f"ERROR calling get_instrument_by: {e}")
                import traceback
                traceback.print_exc()
                
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_margin_attributes():
    """Тестирует получение маржинальных атрибутов через GetMarginAttributes."""
    print_section("МАРЖИНАЛЬНЫЕ АТРИБУТЫ (GetMarginAttributes)")
    
    try:
        from t_tech.invest import Client, InstrumentIdType
        from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
        
        token = os.getenv("TINKOFF_TOKEN", "").strip()
        if not token:
            print("ERROR: TINKOFF_TOKEN not found in environment")
            return
        
        sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
        target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
        
        with Client(token=token, target=target) as client:
            accounts = client.users.get_accounts()
            if not accounts.accounts:
                print("ERROR: No accounts found")
                return
            
            account_id = accounts.accounts[0].id
            print(f"Using account ID: {account_id}\n")
            
            # Пробуем получить маржинальные атрибуты
            try:
                margin_attrs = client.operations.get_margin_attributes(account_id=account_id)
                print("Margin attributes object:")
                print(f"  All attributes: {dir(margin_attrs)}")
                
                # Проверяем все атрибуты
                for attr in dir(margin_attrs):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(margin_attrs, attr)
                            print(f"  {attr}: {value} (type: {type(value)})")
                            if value is not None and not isinstance(value, bool):
                                if hasattr(value, 'units'):
                                    units = value.units
                                    nano = value.nano if hasattr(value, 'nano') else 0
                                    total = float(units) + float(nano) / 1e9
                                    print(f"    total: {total:.2f}")
                        except Exception as e:
                            print(f"  {attr}: Error accessing - {e}")
            except Exception as e:
                print(f"ERROR calling get_margin_attributes: {e}")
                import traceback
                traceback.print_exc()
                
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_portfolio_raw():
    """Тестирует получение портфеля напрямую через API."""
    print_section("ПОРТФЕЛЬ (get_portfolio - RAW API)")
    
    try:
        from t_tech.invest import Client, InstrumentIdType
        from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
        
        token = os.getenv("TINKOFF_TOKEN", "").strip()
        if not token:
            print("ERROR: TINKOFF_TOKEN not found in environment")
            return
        
        sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
        
        # Используем правильный target из констант
        target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
        print(f"Using target: {target} (sandbox={sandbox})")
        
        with Client(token=token, target=target) as client:
            accounts = client.users.get_accounts()
            if not accounts.accounts:
                print("ERROR: No accounts found")
                return
            
            account_id = accounts.accounts[0].id
            print(f"Using account ID: {account_id}\n")
            
            portfolio = client.operations.get_portfolio(account_id=account_id)
            
            print("Portfolio object attributes:")
            print(f"  total_amount_portfolio: {portfolio.total_amount_portfolio}")
            print(f"  total_amount_portfolio.units: {portfolio.total_amount_portfolio.units}")
            print(f"  total_amount_portfolio.nano: {portfolio.total_amount_portfolio.nano}")
            
            # Проверяем все атрибуты портфеля, связанные с доступными средствами
            portfolio_attrs = dir(portfolio)
            margin_related = [attr for attr in portfolio_attrs if 'margin' in attr.lower() or 'available' in attr.lower() or 'blocked' in attr.lower()]
            print(f"\n  Margin/available related attributes: {margin_related}")
            
            for attr in margin_related:
                if not attr.startswith('_'):
                    try:
                        value = getattr(portfolio, attr)
                        print(f"  {attr}: {value} (type: {type(value)})")
                        if value is not None and not isinstance(value, bool):
                            if hasattr(value, 'units'):
                                units = value.units
                                nano = value.nano if hasattr(value, 'nano') else 0
                                total = float(units) + float(nano) / 1e9
                                print(f"    total: {total:.2f} руб")
                    except Exception as e:
                        print(f"  {attr}: Error accessing - {e}")
            
            print(f"\n  Positions count: {len(portfolio.positions) if portfolio.positions else 0}")
            
            if portfolio.positions:
                print("\nPosition details:")
                for i, pos in enumerate(portfolio.positions):
                    print(f"\n  Position #{i + 1}:")
                    print(f"    figi: {pos.figi}")
                    print(f"    quantity: {pos.quantity}")
                    print(f"    average_position_price: {pos.average_position_price}")
                    print(f"    current_price: {pos.current_price}")
                    
                    # Проверяем все атрибуты позиции
                    print(f"    All attributes: {dir(pos)}")
                    
                    # Проверяем наличие полей маржи
                    margin_fields = ['initial_margin', 'current_margin', 'blocked', 'expected_yield', 'var_margin', 'blocked_lots']
                    for field in margin_fields:
                        if hasattr(pos, field):
                            value = getattr(pos, field)
                            print(f"    {field}: {value} (type: {type(value)})")
                            if value is not None and not isinstance(value, bool):
                                if hasattr(value, 'units'):
                                    print(f"      units: {value.units}, nano: {value.nano}")
                                    # Конвертируем в рубли
                                    if hasattr(value, 'units') and hasattr(value, 'nano'):
                                        total = float(value.units) + float(value.nano) / 1e9
                                        print(f"      total: {total:.2f}")
                        else:
                            print(f"    {field}: NOT FOUND")
                    
                    # Проверяем available_withdrawal_draw_limit из портфеля
                    print(f"    Checking portfolio-level margin info...")
                            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Основная функция."""
    print("\n" + "=" * 80)
    print("  ТЕСТИРОВАНИЕ ДАННЫХ TINKOFF API")
    print("=" * 80)
    
    # Проверяем наличие токена
    if not os.getenv("TINKOFF_TOKEN"):
        print("\nERROR: TINKOFF_TOKEN not found in environment variables!")
        print("Please set TINKOFF_TOKEN in .env file or environment")
        return
    
    # Тестируем баланс
    test_balance()
    
    # Тестируем позиции
    test_positions()
    
    # Тестируем портфель напрямую
    test_portfolio_raw()
    
    # Тестируем маржинальные атрибуты
    test_margin_attributes()
    
    # Тестируем информацию об инструменте
    test_instrument_info()
    
    print("\n" + "=" * 80)
    print("  ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
