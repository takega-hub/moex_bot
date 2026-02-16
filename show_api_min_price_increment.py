"""
Скрипт для показа полного ответа API по min_price_increment
"""
import os
import sys
from dotenv import load_dotenv
from t_tech.invest import Client, InstrumentIdType

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
        print("Использование: python show_api_min_price_increment.py <TICKER>")
        print("Пример: python show_api_min_price_increment.py NRG6")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    
    # Загружаем токен из переменных окружения
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ Токен не найден в переменных окружения (TINKOFF_TOKEN)")
        print("   Убедитесь, что файл .env существует и содержит TINKOFF_TOKEN")
        sys.exit(1)
    
    # Используем клиент в контекстном менеджере
    # Просто передаем token, клиент сам определит режим
    try:
        with Client(token) as client:
            print(f"\n🔍 Поиск инструмента {ticker}...")
            figi = get_instrument_figi(ticker, client)
            if not figi:
                print(f"❌ Инструмент {ticker} не найден")
                sys.exit(1)
            
            print(f"✅ FIGI: {figi}\n")
            
            # Получаем информацию об инструменте
            print("📡 Получение данных из API...")
            response = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi
            )
            instrument = response.instrument
            
            print(f"\n{'='*80}")
        print(f"📊 ПОЛНЫЙ ОТВЕТ API ДЛЯ min_price_increment")
        print(f"{'='*80}\n")
        
        # Проверяем наличие атрибута
        if hasattr(instrument, 'min_price_increment'):
            min_price_inc = instrument.min_price_increment
            print(f"✅ Атрибут min_price_increment найден")
            print(f"\n📦 Тип объекта: {type(min_price_inc)}")
            print(f"📦 Значение объекта: {min_price_inc}")
            
            # Показываем все атрибуты объекта
            print(f"\n🔍 Все атрибуты объекта min_price_increment:")
            if min_price_inc is not None:
                for attr in dir(min_price_inc):
                    if not attr.startswith('_'):
                        try:
                            value = getattr(min_price_inc, attr)
                            if not callable(value):
                                print(f"   {attr:30s} = {value} (тип: {type(value).__name__})")
                        except:
                            pass
                
                # Показываем структуру Quotation/MoneyValue
                units = None
                nano = None
                
                if hasattr(min_price_inc, 'units'):
                    units = min_price_inc.units
                    print(f"\n📊 Структура Quotation/MoneyValue:")
                    print(f"   units = {units} (тип: {type(units).__name__})")
                    
                if hasattr(min_price_inc, 'nano'):
                    nano = min_price_inc.nano
                    print(f"   nano  = {nano} (тип: {type(nano).__name__})")
                    
                    # Рассчитываем значение
                    if units is not None and nano is not None:
                        calculated = float(units) + float(nano) / 1e9
                        print(f"\n💡 Рассчитанное значение:")
                        print(f"   float(units) + float(nano) / 1e9")
                        print(f"   = {float(units)} + {float(nano)} / 1e9")
                        print(f"   = {float(units)} + {float(nano) / 1e9}")
                        print(f"   = {calculated}")
                        
                        if calculated == 0:
                            print(f"\n⚠️ ВНИМАНИЕ: Рассчитанное значение = 0!")
                            print(f"   units = {units}")
                            print(f"   nano  = {nano}")
                            print(f"   Это означает, что API возвращает 0 для min_price_increment")
            else:
                print(f"⚠️ min_price_increment = None")
        else:
            print(f"❌ Атрибут min_price_increment не найден в объекте instrument")
        
        # Показываем другие связанные поля
        print(f"\n{'='*80}")
        print(f"📊 ДРУГИЕ ПОЛЯ, СВЯЗАННЫЕ СО СТОИМОСТЬЮ ПУНКТА")
        print(f"{'='*80}\n")
        
        # ВАЖНО: Проверяем min_price_increment_amount - это может быть реальная стоимость пункта!
        found_point_value = False
        if hasattr(instrument, 'min_price_increment_amount'):
            inc_amount = instrument.min_price_increment_amount
            print(f"🎯 НАЙДЕНО: min_price_increment_amount (стоимость шага цены)")
            if hasattr(inc_amount, 'units') and hasattr(inc_amount, 'nano'):
                units = inc_amount.units
                nano = inc_amount.nano
                calculated = float(units) + float(nano) / 1e9
                print(f"   units = {units}, nano = {nano}")
                print(f"   Рассчитанное значение: {calculated:.2f} ₽")
                print(f"   ✅ ЭТО И ЕСТЬ РЕАЛЬНАЯ СТОИМОСТЬ ПУНКТА!")
                found_point_value = True
            else:
                print(f"   Значение: {inc_amount}")
        else:
            print(f"   ⚠️ min_price_increment_amount НЕ НАЙДЕНО в API")
        
        # Ищем все поля, содержащие 'amount', 'value', 'cost', 'price' и т.д.
        related_fields = []
        for attr_name in dir(instrument):
            if attr_name.startswith('_'):
                continue
            attr_lower = attr_name.lower()
            # Ищем поля, связанные со стоимостью пункта, шагом цены и т.д.
            if any(kw in attr_lower for kw in ['point', 'tick', 'step', 'increment', 'value', 'amount', 'cost', 'price']) and ('price' in attr_lower or 'increment' in attr_lower or 'amount' in attr_lower or 'value' in attr_lower):
                try:
                    attr_value = getattr(instrument, attr_name)
                    if not callable(attr_value):
                        related_fields.append((attr_name, attr_value))
                except:
                    pass
        
        if related_fields:
            for field_name, field_value in related_fields:
                print(f"   {field_name:30s} = {field_value}")
                if field_value is not None:
                    if hasattr(field_value, 'units') and hasattr(field_value, 'nano'):
                        units = field_value.units
                        nano = field_value.nano
                        calculated = float(units) + float(nano) / 1e9
                        print(f"      └─ units: {units}, nano: {nano} → {calculated}")
        else:
            print(f"   (других полей не найдено)")
        
        # Показываем полную структуру ответа (первые несколько уровней)
        print(f"\n{'='*80}")
        print(f"📊 СТРУКТУРА ОБЪЕКТА instrument (первые 50 атрибутов)")
        print(f"{'='*80}\n")
        
        attrs_shown = 0
        for attr_name in dir(instrument):
            if attr_name.startswith('_'):
                continue
            if attrs_shown >= 50:
                print(f"   ... (показано 50 из {len([a for a in dir(instrument) if not a.startswith('_')])} атрибутов)")
                break
            try:
                attr_value = getattr(instrument, attr_name)
                if not callable(attr_value):
                    value_str = str(attr_value)[:100]
                    if len(str(attr_value)) > 100:
                        value_str += "..."
                    print(f"   {attr_name:30s} = {value_str}")
                    attrs_shown += 1
            except:
                pass
    except Exception as e:
        print(f"❌ Ошибка при получении данных: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
