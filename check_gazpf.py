#!/usr/bin/env python3
"""Быстрая проверка ГО для GAZPF"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from t_tech.invest import Client, InstrumentIdType
    from t_tech.invest.constants import INVEST_GRPC_API
    from t_tech.invest.schemas import InstrumentType
    from t_tech.invest import CandleInterval
    from datetime import datetime, timedelta, timezone
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("❌ ERROR: t-tech-investments library not installed")
    sys.exit(1)

from bot.margin_rates import get_margin_per_lot_from_api_data, get_margin_for_position


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
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "GAZPF"
    
    print(f"\n{'='*80}")
    print(f"🔍 ПОИСК ГО ДЛЯ {ticker}")
    print(f"{'='*80}\n")
    
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found!")
        sys.exit(1)
    
    with Client(token=token, target=INVEST_GRPC_API) as client:
        # Получаем FIGI
        figi = get_instrument_figi(ticker, client)
        if not figi:
            print(f"❌ Не найден FIGI для {ticker}")
            return
        
        # Получаем информацию об инструменте
        response = client.instruments.get_instrument_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi
        )
        instrument = response.instrument
        
        # Получаем текущую цену
        current_price = get_current_price(figi, client)
        if current_price == 0:
            print(f"⚠️ Не удалось получить цену для {ticker}")
            current_price = 200.0  # Примерная цена для Газпрома
        
        # Извлекаем коэффициенты
        dlong = extract_money_value(getattr(instrument, 'dlong', None))
        dshort = extract_money_value(getattr(instrument, 'dshort', None))
        min_price_increment = extract_money_value(getattr(instrument, 'min_price_increment', None))
        lot = float(getattr(instrument, 'lot', 1.0))
        
        print(f"📊 Данные инструмента:")
        print(f"   Название: {getattr(instrument, 'name', 'N/A')}")
        print(f"   Текущая цена: {current_price:.2f} ₽")
        print(f"   Лотность: {lot}")
        print(f"   dlong: {dlong}")
        print(f"   dshort: {dshort}")
        print(f"   min_price_increment (стоимость пункта): {min_price_increment}")
        
        # Рассчитываем ГО
        print(f"\n📐 РАСЧЕТ ГО:")
        
        # Через min_price_increment
        if min_price_increment and min_price_increment > 0:
            margin_long = get_margin_per_lot_from_api_data(
                ticker=ticker,
                current_price=current_price,
                point_value=min_price_increment,
                dlong=dlong,
                dshort=dshort,
                is_long=True
            )
            margin_short = get_margin_per_lot_from_api_data(
                ticker=ticker,
                current_price=current_price,
                point_value=min_price_increment,
                dlong=dlong,
                dshort=dshort,
                is_long=False
            )
            
            if margin_long:
                print(f"   LONG: {margin_long:.2f} ₽ (через min_price_increment)")
            if margin_short:
                print(f"   SHORT: {margin_short:.2f} ₽ (через min_price_increment)")
            
            margin_per_lot = max(margin_long or 0, margin_short or 0) if (margin_long and margin_short) else (margin_long or margin_short or 0)
            
            if margin_per_lot > 0:
                print(f"\n✅ ГО за лот: {margin_per_lot:.2f} ₽")
                print(f"   Формула: min_price_increment * price * dlong/dshort")
                print(f"   Расчет: {min_price_increment:.2f} * {current_price:.2f} * {dlong if dlong else dshort:.6f} = {margin_per_lot:.2f} ₽")
        
        # Через стандартную функцию
        margin_standard = get_margin_for_position(
            ticker=ticker,
            quantity=1.0,
            entry_price=current_price,
            lot_size=lot,
            dlong=dlong,
            dshort=dshort,
            is_long=True
        )
        
        if margin_standard > 0:
            print(f"\n   Через get_margin_for_position: {margin_standard:.2f} ₽")
        
        # Стоимость лота
        lot_value = current_price * lot
        print(f"\n💰 Стоимость лота: {lot_value:.2f} ₽")
        print(f"   Для открытия позиции нужно: ГО + стоимость лота = {margin_per_lot:.2f} + {lot_value:.2f} = {margin_per_lot + lot_value:.2f} ₽")


if __name__ == "__main__":
    main()
