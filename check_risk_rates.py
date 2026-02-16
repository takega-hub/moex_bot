"""
Скрипт для проверки метода get_risk_rates для получения ГО и стоимости пункта
"""
import os
import sys
import asyncio
from dotenv import load_dotenv
from t_tech.invest import AsyncClient
from t_tech.invest.schemas import RiskRatesRequest

# Загружаем переменные окружения из .env
load_dotenv()

async def get_instrument_figi(ticker: str, client: AsyncClient) -> tuple:
    """Получить FIGI и instrument_uid по тикеру"""
    try:
        response = await client.instruments.find_instrument(query=ticker)
        if response and response.instruments:
            for inst in response.instruments:
                if inst.ticker.upper() == ticker.upper():
                    return inst.figi, inst.uid
    except Exception as e:
        print(f"Ошибка при поиске FIGI: {e}")
    return None, None

async def main():
    if len(sys.argv) < 2:
        print("Использование: python check_risk_rates.py <TICKER>")
        print("Пример: python check_risk_rates.py NRG6")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    
    # Загружаем токен из переменных окружения
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ Токен не найден в переменных окружения (TINKOFF_TOKEN)")
        sys.exit(1)
    
    try:
        async with AsyncClient(token) as client:
            print(f"\n🔍 Поиск инструмента {ticker}...")
            figi, instrument_uid = await get_instrument_figi(ticker, client)
            if not figi or not instrument_uid:
                print(f"❌ Инструмент {ticker} не найден")
                sys.exit(1)
            
            print(f"✅ FIGI: {figi}")
            print(f"✅ Instrument UID: {instrument_uid}\n")
            
            # ========================================================================
            # МЕТОД: get_risk_rates
            # ========================================================================
            print(f"{'='*80}")
            print(f"📊 МЕТОД: get_risk_rates")
            print(f"{'='*80}\n")
            
            try:
                request = RiskRatesRequest()
                request.instrument_id = [instrument_uid]
                
                print(f"Запрос risk rates для instrument_uid: {instrument_uid}")
                response = await client.instruments.get_risk_rates(request=request)
                
                if response and response.instrument_risk_rates:
                    for risk_rate in response.instrument_risk_rates:
                        print(f"\n✅ Найдены risk rates для инструмента:")
                        print(f"   instrument_uid: {risk_rate.instrument_uid}")
                        
                        # Проверяем все атрибуты объекта
                        print(f"\n   Все атрибуты RiskRate:")
                        for attr_name in dir(risk_rate):
                            if attr_name.startswith('_'):
                                continue
                            try:
                                attr_value = getattr(risk_rate, attr_name)
                                if not callable(attr_value):
                                    if hasattr(attr_value, 'units') and hasattr(attr_value, 'nano'):
                                        units = attr_value.units
                                        nano = attr_value.nano
                                        calculated = float(units) + float(nano) / 1e9
                                        print(f"      {attr_name:30s} = {calculated:.6f} (units={units}, nano={nano})")
                                    elif isinstance(attr_value, (int, float)):
                                        print(f"      {attr_name:30s} = {attr_value}")
                                    else:
                                        print(f"      {attr_name:30s} = {attr_value}")
                            except:
                                pass
                        
                        # Особое внимание к short_risk_rate и long_risk_rate
                        if hasattr(risk_rate, 'short_risk_rate'):
                            short_rate = risk_rate.short_risk_rate
                            if short_rate:
                                if hasattr(short_rate, 'units') and hasattr(short_rate, 'nano'):
                                    short_value = float(short_rate.units) + float(short_rate.nano) / 1e9
                                    print(f"\n   🎯 short_risk_rate (ГО для SHORT): {short_value:.6f}")
                                else:
                                    print(f"\n   🎯 short_risk_rate: {short_rate}")
                            else:
                                print(f"\n   ⚠️ short_risk_rate: None")
                        
                        if hasattr(risk_rate, 'long_risk_rate'):
                            long_rate = risk_rate.long_risk_rate
                            if long_rate:
                                if hasattr(long_rate, 'units') and hasattr(long_rate, 'nano'):
                                    long_value = float(long_rate.units) + float(long_rate.nano) / 1e9
                                    print(f"\n   🎯 long_risk_rate (ГО для LONG): {long_value:.6f}")
                                else:
                                    print(f"\n   🎯 long_risk_rate: {long_rate}")
                            else:
                                print(f"\n   ⚠️ long_risk_rate: None")
                else:
                    print(f"❌ Risk rates не найдены для {ticker}")
                    
            except Exception as e:
                print(f"❌ Ошибка при получении risk rates: {e}")
                import traceback
                traceback.print_exc()
            
            # ========================================================================
            # ДОПОЛНИТЕЛЬНО: Получаем информацию об инструменте для сравнения
            # ========================================================================
            print(f"\n{'='*80}")
            print(f"📊 ДЛЯ СРАВНЕНИЯ: GetInstrumentBy")
            print(f"{'='*80}\n")
            
            try:
                from t_tech.invest import InstrumentIdType
                response = await client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=figi
                )
                instrument = response.instrument
                
                # Проверяем dlong и dshort
                if hasattr(instrument, 'dlong') and instrument.dlong:
                    dlong = float(instrument.dlong.units) + float(instrument.dlong.nano) / 1e9
                    print(f"   dlong (из GetInstrumentBy): {dlong:.6f}")
                
                if hasattr(instrument, 'dshort') and instrument.dshort:
                    dshort = float(instrument.dshort.units) + float(instrument.dshort.nano) / 1e9
                    print(f"   dshort (из GetInstrumentBy): {dshort:.6f}")
                
                # Проверяем min_price_increment_amount
                if hasattr(instrument, 'min_price_increment_amount'):
                    inc_amount = instrument.min_price_increment_amount
                    if inc_amount:
                        if hasattr(inc_amount, 'units') and hasattr(inc_amount, 'nano'):
                            point_value = float(inc_amount.units) + float(inc_amount.nano) / 1e9
                            print(f"   min_price_increment_amount (стоимость пункта): {point_value:.2f} ₽")
                        else:
                            print(f"   min_price_increment_amount: {inc_amount}")
                    else:
                        print(f"   min_price_increment_amount: None")
                else:
                    print(f"   min_price_increment_amount: поле отсутствует")
                    
            except Exception as e:
                print(f"❌ Ошибка при получении информации об инструменте: {e}")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
