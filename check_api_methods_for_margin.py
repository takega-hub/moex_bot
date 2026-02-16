"""
Скрипт для проверки всех методов API для получения стоимости пункта и ГО
"""
import os
import sys
from dotenv import load_dotenv
from t_tech.invest import Client, InstrumentIdType, OrderDirection, OrderType

# Загружаем переменные окружения из .env
load_dotenv()

def get_instrument_figi(ticker: str, client: Client) -> str:
    """Получить FIGI по тикеру"""
    try:
        response = client.instruments.find_instrument(query=ticker)
        if response and response.instruments:
            for inst in response.instruments:
                if inst.ticker.upper() == ticker.upper():
                    return inst.figi
    except Exception as e:
        print(f"Ошибка при поиске FIGI: {e}")
    return None

def main():
    if len(sys.argv) < 2:
        print("Использование: python check_api_methods_for_margin.py <TICKER>")
        print("Пример: python check_api_methods_for_margin.py NRG6")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    
    # Загружаем токен из переменных окружения
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ Токен не найден в переменных окружения (TINKOFF_TOKEN)")
        sys.exit(1)
    
    try:
        with Client(token) as client:
            print(f"\n🔍 Поиск инструмента {ticker}...")
            figi = get_instrument_figi(ticker, client)
            if not figi:
                print(f"❌ Инструмент {ticker} не найден")
                sys.exit(1)
            
            print(f"✅ FIGI: {figi}\n")
            
            # ========================================================================
            # МЕТОД 1: GetInstrumentBy - получение информации об инструменте
            # ========================================================================
            print(f"{'='*80}")
            print(f"📊 МЕТОД 1: GetInstrumentBy")
            print(f"{'='*80}\n")
            
            response = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi
            )
            instrument = response.instrument
            
            # Проверяем min_price_increment_amount
            if hasattr(instrument, 'min_price_increment_amount'):
                inc_amount = instrument.min_price_increment_amount
                if inc_amount:
                    if hasattr(inc_amount, 'units') and hasattr(inc_amount, 'nano'):
                        point_value = float(inc_amount.units) + float(inc_amount.nano) / 1e9
                        print(f"✅ min_price_increment_amount (стоимость пункта): {point_value:.2f} ₽")
                    else:
                        print(f"⚠️ min_price_increment_amount: {inc_amount}")
                else:
                    print(f"❌ min_price_increment_amount: None")
            else:
                print(f"❌ min_price_increment_amount: поле отсутствует")
            
            # Проверяем dlong и dshort
            if hasattr(instrument, 'dlong') and instrument.dlong:
                dlong = float(instrument.dlong.units) + float(instrument.dlong.nano) / 1e9
                print(f"✅ dlong (ГО для LONG): {dlong:.6f}")
            else:
                print(f"❌ dlong: отсутствует")
            
            if hasattr(instrument, 'dshort') and instrument.dshort:
                dshort = float(instrument.dshort.units) + float(instrument.dshort.nano) / 1e9
                print(f"✅ dshort (ГО для SHORT): {dshort:.6f}")
            else:
                print(f"❌ dshort: отсутствует")
            
            # ========================================================================
            # МЕТОД 2: GetOrderPrice - получение предварительной стоимости заявки
            # ========================================================================
            print(f"\n{'='*80}")
            print(f"📊 МЕТОД 2: GetOrderPrice (предварительная стоимость заявки)")
            print(f"{'='*80}\n")
            
            try:
                # Получаем текущую цену
                from t_tech.invest import CandleInterval
                from datetime import datetime, timedelta, timezone
                
                to_time = datetime.now(timezone.utc)
                from_time = to_time - timedelta(hours=1)
                
                candles = client.market_data.get_candles(
                    figi=figi,
                    from_=from_time,
                    to=to_time,
                    interval=CandleInterval.CANDLE_INTERVAL_1_MIN
                )
                
                current_price = None
                if candles.candles:
                    last_candle = candles.candles[-1]
                    current_price = float(last_candle.close.units) + float(last_candle.close.nano) / 1e9
                    print(f"Текущая цена: {current_price:.2f} ₽")
                
                # Получаем аккаунт
                accounts = client.users.get_accounts()
                if accounts.accounts:
                    account_id = accounts.accounts[0].id
                    
                    # Пробуем GetOrderPrice для LONG
                    try:
                        order_price_response = client.orders.get_order_price(
                            account_id=account_id,
                            figi=figi,
                            price=current_price if current_price else 0,
                            direction=OrderDirection.ORDER_DIRECTION_BUY,
                            quantity=1
                        )
                        
                        print(f"\n✅ GetOrderPrice (LONG, 1 лот):")
                        if hasattr(order_price_response, 'total_order_amount'):
                            total = order_price_response.total_order_amount
                            if hasattr(total, 'units') and hasattr(total, 'nano'):
                                total_value = float(total.units) + float(total.nano) / 1e9
                                print(f"   total_order_amount: {total_value:.2f} ₽")
                        
                        if hasattr(order_price_response, 'initial_order_amount'):
                            initial = order_price_response.initial_order_amount
                            if hasattr(initial, 'units') and hasattr(initial, 'nano'):
                                initial_value = float(initial.units) + float(initial.nano) / 1e9
                                print(f"   initial_order_amount: {initial_value:.2f} ₽")
                        
                        if hasattr(order_price_response, 'executed_commission'):
                            commission = order_price_response.executed_commission
                            if hasattr(commission, 'units') and hasattr(commission, 'nano'):
                                comm_value = float(commission.units) + float(commission.nano) / 1e9
                                print(f"   executed_commission: {comm_value:.2f} ₽")
                        
                        # Проверяем все атрибуты ответа
                        print(f"\n   Все атрибуты GetOrderPrice:")
                        for attr in dir(order_price_response):
                            if not attr.startswith('_'):
                                try:
                                    value = getattr(order_price_response, attr)
                                    if not callable(value):
                                        if hasattr(value, 'units') and hasattr(value, 'nano'):
                                            val = float(value.units) + float(value.nano) / 1e9
                                            print(f"      {attr:30s} = {val:.2f} ₽")
                                        else:
                                            print(f"      {attr:30s} = {value}")
                                except:
                                    pass
                    except Exception as e:
                        print(f"❌ Ошибка GetOrderPrice: {e}")
                else:
                    print(f"❌ Аккаунт не найден")
            except Exception as e:
                print(f"❌ Ошибка при получении данных для GetOrderPrice: {e}")
                import traceback
                traceback.print_exc()
            
            # ========================================================================
            # МЕТОД 3: Проверка сервиса Operations
            # ========================================================================
            print(f"\n{'='*80}")
            print(f"📊 МЕТОД 3: Проверка сервиса Operations")
            print(f"{'='*80}\n")
            
            try:
                # Проверяем доступные методы в operations
                operations_methods = [m for m in dir(client.operations) if not m.startswith('_')]
                print(f"Доступные методы в operations: {operations_methods}")
                
                # Ищем методы, связанные с маржой
                margin_methods = [m for m in operations_methods if any(kw in m.lower() for kw in ['margin', 'guarantee', 'collateral'])]
                if margin_methods:
                    print(f"\n✅ Найдены методы, связанные с маржой: {margin_methods}")
                else:
                    print(f"\n⚠️ Методы, связанные с маржой, не найдены")
            except Exception as e:
                print(f"❌ Ошибка при проверке Operations: {e}")
            
            # ========================================================================
            # МЕТОД 4: Проверка всех полей инструмента, связанных с маржой
            # ========================================================================
            print(f"\n{'='*80}")
            print(f"📊 МЕТОД 4: Все поля инструмента, связанные с маржой/стоимостью пункта")
            print(f"{'='*80}\n")
            
            margin_related_fields = []
            for attr_name in dir(instrument):
                if attr_name.startswith('_'):
                    continue
                attr_lower = attr_name.lower()
                if any(kw in attr_lower for kw in ['margin', 'guarantee', 'collateral', 'deposit', 'point', 'tick', 'increment', 'amount', 'value', 'dlong', 'dshort', 'klong', 'kshort']):
                    try:
                        attr_value = getattr(instrument, attr_name)
                        if not callable(attr_value):
                            margin_related_fields.append((attr_name, attr_value))
                    except:
                        pass
            
            if margin_related_fields:
                for field_name, field_value in margin_related_fields:
                    print(f"   {field_name:30s} = ", end="")
                    if field_value is None:
                        print("None")
                    elif hasattr(field_value, 'units') and hasattr(field_value, 'nano'):
                        units = field_value.units
                        nano = field_value.nano
                        calculated = float(units) + float(nano) / 1e9
                        print(f"{calculated:.6f} (units={units}, nano={nano})")
                    else:
                        print(f"{field_value}")
            else:
                print(f"   (поля не найдены)")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
