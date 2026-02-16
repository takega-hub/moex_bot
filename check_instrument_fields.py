"""
Скрипт для проверки всех полей инструмента, связанных с шагом цены и стоимостью пункта
"""
import os
import sys
from pprint import pprint
from dotenv import load_dotenv
from t_tech.invest import Client, InstrumentIdType

# Загружаем переменные окружения из .env
load_dotenv()

def get_instrument_figi(ticker: str, client: Client) -> tuple:
    """Получить FIGI, UID и class_code по тикеру"""
    try:
        response = client.instruments.find_instrument(query=ticker)
        if response and response.instruments:
            for inst in response.instruments:
                if inst.ticker.upper() == ticker.upper():
                    return inst.figi, inst.uid, inst.class_code
    except Exception as e:
        print(f"Ошибка при поиске FIGI: {e}")
    return None, None, None

def extract_money_value(obj):
    """Извлечь значение из MoneyValue или Quotation объекта."""
    if obj is None:
        return None
    if hasattr(obj, 'units') and hasattr(obj, 'nano'):
        try:
            return float(obj.units) + float(obj.nano) / 1e9
        except (ValueError, TypeError):
            return None
    return None

def print_field_info(name, value, indent=0):
    """Печатает информацию о поле с форматированием"""
    prefix = "   " * indent
    if value is None:
        print(f"{prefix}{name:40s} = None")
    elif hasattr(value, 'units') and hasattr(value, 'nano'):
        units = value.units
        nano = value.nano
        calculated = float(units) + float(nano) / 1e9
        print(f"{prefix}{name:40s} = {calculated:.6f} (units={units}, nano={nano})")
    elif isinstance(value, (int, float)):
        print(f"{prefix}{name:40s} = {value}")
    elif isinstance(value, str):
        print(f"{prefix}{name:40s} = {value}")
    elif isinstance(value, bool):
        print(f"{prefix}{name:40s} = {value}")
    else:
        value_str = str(value)[:100]
        if len(str(value)) > 100:
            value_str += "..."
        print(f"{prefix}{name:40s} = {value_str}")

def main():
    if len(sys.argv) < 2:
        print("Использование: python check_instrument_fields.py <TICKER>")
        print("Пример: python check_instrument_fields.py NRG6")
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
            figi, uid, class_code = get_instrument_figi(ticker, client)
            if not figi or not uid:
                print(f"❌ Инструмент {ticker} не найден")
                sys.exit(1)
            
            print(f"✅ FIGI: {figi}")
            print(f"✅ UID: {uid}")
            print(f"✅ Class Code: {class_code}\n")
            
            # ========================================================================
            # МЕТОД 1: get_instrument_by через FIGI
            # ========================================================================
            print(f"{'='*80}")
            print(f"📊 МЕТОД 1: get_instrument_by (FIGI)")
            print(f"{'='*80}\n")
            
            try:
                response = client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=figi
                )
                instrument = response.instrument
                
                print(f"Тип инструмента: {instrument.instrument_type if hasattr(instrument, 'instrument_type') else 'N/A'}")
                print(f"Тикер: {instrument.ticker if hasattr(instrument, 'ticker') else 'N/A'}")
                print(f"Название: {instrument.name if hasattr(instrument, 'name') else 'N/A'}\n")
                
                # Ищем все поля, связанные с ценой, шагом, стоимостью пункта
                print(f"🔍 ПОЛЯ, СВЯЗАННЫЕ С ЦЕНОЙ, ШАГОМ И СТОИМОСТЬЮ ПУНКТА:\n")
                
                price_related_keywords = ['price', 'increment', 'step', 'tick', 'point', 'amount', 'value', 'cost', 'lot', 'size']
                margin_related_keywords = ['margin', 'guarantee', 'collateral', 'deposit', 'dlong', 'dshort', 'klong', 'kshort', 'risk']
                
                found_fields = {}
                
                for attr_name in dir(instrument):
                    if attr_name.startswith('_'):
                        continue
                    attr_lower = attr_name.lower()
                    
                    # Проверяем, связано ли поле с ценой/шагом/стоимостью
                    if any(kw in attr_lower for kw in price_related_keywords) or any(kw in attr_lower for kw in margin_related_keywords):
                        try:
                            attr_value = getattr(instrument, attr_name)
                            if not callable(attr_value):
                                found_fields[attr_name] = attr_value
                        except:
                            pass
                
                # Сортируем и выводим
                for field_name in sorted(found_fields.keys()):
                    print_field_info(field_name, found_fields[field_name])
                
                # Особое внимание к ключевым полям
                print(f"\n🎯 КЛЮЧЕВЫЕ ПОЛЯ ДЛЯ РАСЧЕТА ГО:\n")
                
                key_fields = {
                    'min_price_increment': 'Шаг цены (минимальное изменение)',
                    'min_price_increment_amount': 'Стоимость шага цены (СТОИМОСТЬ ПУНКТА!)',
                    'dlong': 'Коэффициент ГО для LONG',
                    'dshort': 'Коэффициент ГО для SHORT',
                    'klong': 'Коэффициент klong',
                    'kshort': 'Коэффициент kshort',
                    'lot': 'Размер лота',
                }
                
                for field_name, description in key_fields.items():
                    if hasattr(instrument, field_name):
                        value = getattr(instrument, field_name)
                        print(f"   {field_name:30s} ({description}):")
                        print_field_info("", value, indent=2)
                    else:
                        print(f"   {field_name:30s} ({description}): ❌ отсутствует")
                
            except Exception as e:
                print(f"❌ Ошибка при получении инструмента через FIGI: {e}")
                import traceback
                traceback.print_exc()
            
            # ========================================================================
            # МЕТОД 2: get_instrument_by через UID (как в примере)
            # ========================================================================
            print(f"\n{'='*80}")
            print(f"📊 МЕТОД 2: get_instrument_by (UID + class_code)")
            print(f"{'='*80}\n")
            
            try:
                # Определяем тип инструмента для выбора правильного метода
                # Для фьючерсов используем futures_by
                if class_code:
                    try:
                        response = client.instruments.futures_by(
                            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_UID,
                            class_code=class_code,
                            id=uid
                        )
                        instrument = response
                        
                        print(f"✅ Получено через futures_by")
                        print(f"Тикер: {instrument.ticker if hasattr(instrument, 'ticker') else 'N/A'}")
                        print(f"Название: {instrument.name if hasattr(instrument, 'name') else 'N/A'}\n")
                        
                        # Проверяем те же поля
                        print(f"🔍 КЛЮЧЕВЫЕ ПОЛЯ:\n")
                        for field_name, description in key_fields.items():
                            if hasattr(instrument, field_name):
                                value = getattr(instrument, field_name)
                                print(f"   {field_name:30s} ({description}):")
                                print_field_info("", value, indent=2)
                            else:
                                print(f"   {field_name:30s} ({description}): ❌ отсутствует")
                                
                    except Exception as e1:
                        print(f"⚠️ Ошибка futures_by: {e1}")
                        # Пробуем через get_instrument_by с UID
                        try:
                            response = client.instruments.get_instrument_by(
                                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_UID,
                                id=uid
                            )
                            instrument = response.instrument
                            print(f"✅ Получено через get_instrument_by (UID)")
                            
                            for field_name, description in key_fields.items():
                                if hasattr(instrument, field_name):
                                    value = getattr(instrument, field_name)
                                    print(f"   {field_name:30s} ({description}):")
                                    print_field_info("", value, indent=2)
                        except Exception as e2:
                            print(f"❌ Ошибка get_instrument_by (UID): {e2}")
            except Exception as e:
                print(f"❌ Ошибка при получении инструмента через UID: {e}")
            
            # ========================================================================
            # МЕТОД 3: Полный вывод объекта (pprint)
            # ========================================================================
            print(f"\n{'='*80}")
            print(f"📊 МЕТОД 3: Полный вывод объекта инструмента (pprint)")
            print(f"{'='*80}\n")
            
            try:
                response = client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=figi
                )
                instrument = response.instrument
                
                print("Полный объект инструмента:")
                pprint(instrument)
                
            except Exception as e:
                print(f"❌ Ошибка при pprint: {e}")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
