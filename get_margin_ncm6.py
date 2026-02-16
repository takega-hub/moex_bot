#!/usr/bin/env python3
"""
Скрипт для получения данных по ГО для любого инструмента.
Использование: python get_margin_ncm6.py <TICKER>
Пример: python get_margin_ncm6.py NCM6
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

try:
    from t_tech.invest import Client, InstrumentIdType
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
    from t_tech.invest.schemas import InstrumentType
    from t_tech.invest import CandleInterval
    from datetime import datetime, timedelta, timezone
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("❌ ERROR: t-tech-investments library not installed")
    sys.exit(1)

from bot.margin_rates import get_margin_for_position, MARGIN_PER_LOT, POINT_VALUE


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


def get_instrument_figi(ticker: str, client: Client) -> str:
    """Получить FIGI для тикера."""
    find_response = client.instruments.find_instrument(
        query=ticker,
        instrument_kind=InstrumentType.INSTRUMENT_TYPE_FUTURES,
        api_trade_available_flag=True
    )
    
    for inst in find_response.instruments:
        if inst.ticker.upper() == ticker.upper():
            return inst.figi
    
    if find_response.instruments:
        return find_response.instruments[0].figi
    
    return None


def get_current_price(figi: str, client: Client) -> float:
    """Получить текущую цену."""
    try:
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=1)
        
        response = client.market_data.get_candles(
            figi=figi,
            from_=from_date,
            to=to_date,
            interval=CandleInterval.CANDLE_INTERVAL_1_MIN
        )
        
        if response.candles:
            last_candle = response.candles[-1]
            if hasattr(last_candle, 'close') and last_candle.close:
                return extract_money_value(last_candle.close)
    except:
        pass
    return 0.0


def main():
    """Главная функция."""
    import sys
    # Принимаем тикер как аргумент командной строки или используем NCM6 по умолчанию
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
    else:
        ticker = "NCM6"
    
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found!")
        sys.exit(1)
    
    print(f"\n{'='*80}")
    print(f"🔍 ПОЛУЧЕНИЕ ДАННЫХ ПО ГО ДЛЯ {ticker}")
    print(f"{'='*80}\n")
    
    target = INVEST_GRPC_API
    
    with Client(token=token, target=target) as client:
        # Получаем FIGI
        print(f"1️⃣ Поиск инструмента {ticker}...")
        figi = get_instrument_figi(ticker, client)
        if not figi:
            print(f"   ❌ Не найден FIGI для {ticker}")
            return
        
        print(f"   ✅ FIGI: {figi}\n")
        
        # Получаем информацию об инструменте
        print("2️⃣ Информация об инструменте:")
        try:
            response = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi
            )
            instrument = response.instrument
            
            name = getattr(instrument, 'name', 'N/A')
            lot = float(getattr(instrument, 'lot', 1.0))
            
            print(f"   Название: {name}")
            print(f"   Тикер: {getattr(instrument, 'ticker', 'N/A')}")
            print(f"   Лот: {lot}")
            
            # Извлекаем коэффициенты маржи
            dlong = extract_money_value(getattr(instrument, 'dlong', None))
            dshort = extract_money_value(getattr(instrument, 'dshort', None))
            klong = extract_money_value(getattr(instrument, 'klong', None))
            kshort = extract_money_value(getattr(instrument, 'kshort', None))
            
            print(f"\n   Коэффициенты маржи из API:")
            if dlong is not None:
                print(f"      dlong: {dlong:.6f}")
            if dshort is not None:
                print(f"      dshort: {dshort:.6f}")
            if klong is not None:
                print(f"      klong: {klong:.6f}")
            if kshort is not None:
                print(f"      kshort: {kshort:.6f}")
            
            # Получаем текущую цену
            print(f"\n3️⃣ Получение текущей цены...")
            current_price = get_current_price(figi, client)
            if current_price > 0:
                print(f"   ✅ Текущая цена: {current_price:.4f} ₽")
            else:
                print(f"   ⚠️ Не удалось получить текущую цену")
            
            # Проверяем наличие в словаре
            print(f"\n4️⃣ Проверка словаря маржи:")
            ticker_upper = ticker.upper()
            dict_margin = MARGIN_PER_LOT.get(ticker_upper, 0.0)
            dict_point_value = POINT_VALUE.get(ticker_upper, 0.0)
            
            if dict_margin > 0:
                print(f"   ✅ Найдено в MARGIN_PER_LOT: {dict_margin:.2f} ₽/лот")
            else:
                print(f"   ⚠️ Нет в MARGIN_PER_LOT (значение: {dict_margin})")
            
            if dict_point_value > 0:
                print(f"   ✅ Найдено в POINT_VALUE: {dict_point_value:.2f} ₽")
            else:
                print(f"   ⚠️ Нет в POINT_VALUE")
            
            # Расчет маржи через функцию
            print(f"\n5️⃣ Расчет маржи через get_margin_for_position:")
            if current_price > 0:
                calculated_margin = get_margin_for_position(
                    ticker=ticker_upper,
                    quantity=1.0,
                    entry_price=current_price,
                    lot_size=lot,
                    dlong=dlong,
                    dshort=dshort,
                    is_long=True,
                    auto_calculate_point_value_flag=True
                )
                print(f"   Рассчитанная маржа (1 лот, LONG): {calculated_margin:.2f} ₽")
                
                calculated_margin_short = get_margin_for_position(
                    ticker=ticker_upper,
                    quantity=1.0,
                    entry_price=current_price,
                    lot_size=lot,
                    dlong=dlong,
                    dshort=dshort,
                    is_long=False,
                    auto_calculate_point_value_flag=True
                )
                print(f"   Рассчитанная маржа (1 лот, SHORT): {calculated_margin_short:.2f} ₽")
            
            # Пробуем разные варианты расчета
            print(f"\n6️⃣ Варианты расчета маржи:")
            if current_price > 0:
                print(f"   Текущая цена: {current_price:.4f} ₽")
                print(f"   Лот: {lot}")
                
                if dlong is not None:
                    print(f"\n   Через dlong:")
                    print(f"      dlong (как есть): {dlong:.6f} ₽")
                    print(f"      dlong * lot: {dlong * lot:.2f} ₽")
                
                if dshort is not None:
                    print(f"\n   Через dshort:")
                    print(f"      dshort (как есть): {dshort:.6f} ₽")
                    print(f"      dshort * lot: {dshort * lot:.2f} ₽")
                
                if klong is not None:
                    print(f"\n   Через klong:")
                    print(f"      price * klong: {current_price * klong:.2f} ₽")
                    print(f"      price * klong * lot: {current_price * klong * lot:.2f} ₽")
                
                if kshort is not None:
                    print(f"\n   Через kshort:")
                    print(f"      price * kshort: {current_price * kshort:.2f} ₽")
                    print(f"      price * kshort * lot: {current_price * kshort * lot:.2f} ₽")
            
            print(f"\n{'='*80}")
            print(f"📝 РЕКОМЕНДАЦИИ:")
            print(f"{'='*80}")
            if dict_margin == 0:
                print(f"   1. Проверьте значение ГО в терминале Tinkoff для {ticker}")
                print(f"   2. Добавьте значение в bot/margin_rates.py:")
                print(f"      MARGIN_PER_LOT[\"{ticker_upper}\"] = <значение_из_терминала>")
            else:
                print(f"   ✅ Значение уже есть в словаре: {dict_margin:.2f} ₽/лот")
                print(f"   💡 Проверьте актуальность значения в терминале")
            
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
