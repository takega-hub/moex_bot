#!/usr/bin/env python3
"""
Скрипт для получения полной информации об инструменте из Tinkoff API.
Помогает диагностировать требования к марже и другие параметры инструмента.
"""
import os
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

try:
    from t_tech.invest import Client, InstrumentIdType
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("❌ ERROR: t-tech-investments library not installed")
    print("Install with: pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple")
    sys.exit(1)

def setup_logging():
    """Настройка логирования."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def get_instrument_by_figi(figi: str, sandbox: bool = False):
    """Получить информацию об инструменте по FIGI."""
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found in environment variables!")
        print("   Please set TINKOFF_TOKEN in .env file or environment")
        sys.exit(1)
    
    target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
    
    with Client(token=token, target=target) as client:
        print(f"🔍 Getting instrument info for FIGI: {figi}")
        print(f"   Using {'SANDBOX' if sandbox else 'REAL'} API\n")
        
        try:
            response = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi
            )
            return response.instrument
        except Exception as e:
            print(f"❌ Error getting instrument: {e}")
            return None

def get_instrument_by_ticker(ticker: str, instrument_type: str = "futures", sandbox: bool = False):
    """Получить информацию об инструменте по тикеру."""
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found in environment variables!")
        print("   Please set TINKOFF_TOKEN in .env file or environment")
        sys.exit(1)
    
    target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
    
    with Client(token=token, target=target) as client:
        print(f"🔍 Searching for instrument: {ticker} (type: {instrument_type})")
        print(f"   Using {'SANDBOX' if sandbox else 'REAL'} API\n")
        
        try:
            from t_tech.invest.schemas import InstrumentType
            instrument_kind = None
            if instrument_type == "futures":
                instrument_kind = InstrumentType.INSTRUMENT_TYPE_FUTURES
            elif instrument_type == "shares":
                instrument_kind = InstrumentType.INSTRUMENT_TYPE_SHARE
            elif instrument_type == "bonds":
                instrument_kind = InstrumentType.INSTRUMENT_TYPE_BOND
            
            # Поиск по тикеру
            find_response = client.instruments.find_instrument(
                query=ticker,
                instrument_kind=instrument_kind,
                api_trade_available_flag=True
            )
            
            if not find_response.instruments:
                print(f"❌ Instrument {ticker} not found")
                return None
            
            # Ищем точное совпадение
            for inst in find_response.instruments:
                if inst.ticker.upper() == ticker.upper():
                    print(f"✅ Found instrument: {inst.ticker} ({inst.figi})")
                    # Получаем полную информацию
                    response = client.instruments.get_instrument_by(
                        id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                        id=inst.figi
                    )
                    return response.instrument
            
            # Если точного совпадения нет, берем первый
            inst = find_response.instruments[0]
            print(f"⚠️ Using first match: {inst.ticker} ({inst.figi})")
            response = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=inst.figi
            )
            return response.instrument
            
        except Exception as e:
            print(f"❌ Error finding instrument: {e}")
            import traceback
            traceback.print_exc()
            return None

def extract_money_value(obj, name: str):
    """Извлечь значение из MoneyValue или Quotation объекта."""
    if obj is None:
        return None
    if hasattr(obj, 'units') and hasattr(obj, 'nano'):
        try:
            value = float(obj.units) + float(obj.nano) / 1e9
            return value
        except (ValueError, TypeError):
            return None
    return None

def get_current_price(figi: str, sandbox: bool = False):
    """Получить текущую цену инструмента."""
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        return None
    
    target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
    
    try:
        from t_tech.invest import CandleInterval
        from datetime import datetime, timedelta, timezone
        
        with Client(token=token, target=target) as client:
            # Получаем последние свечи
            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=1)
            
            # Пробуем получить последнюю свечу
            response = client.market_data.get_candles(
                figi=figi,
                from_=from_date,
                to=to_date,
                interval=CandleInterval.CANDLE_INTERVAL_1_MIN
            )
            
            if response.candles:
                last_candle = response.candles[-1]
                if hasattr(last_candle, 'close') and last_candle.close:
                    price = extract_money_value(last_candle.close, 'close')
                    return price
            
            return None
    except Exception as e:
        print(f"   ⚠️ Не удалось получить текущую цену: {e}")
        return None

def print_instrument_info(instrument, logger=None, current_price: Optional[float] = None, sandbox: bool = False):
    """Вывести всю информацию об инструменте."""
    if instrument is None:
        print("❌ Instrument is None")
        return
    
    print("=" * 80)
    print("📊 ПОЛНАЯ ИНФОРМАЦИЯ ОБ ИНСТРУМЕНТЕ")
    print("=" * 80)
    
    # Базовые поля
    basic_fields = ['figi', 'ticker', 'name', 'instrument_type', 'api_trade_available_flag']
    print("\n🔹 БАЗОВЫЕ ПОЛЯ:")
    for field in basic_fields:
        if hasattr(instrument, field):
            value = getattr(instrument, field)
            print(f"   {field:30s} = {value}")
    
    # Поля, связанные с лотом и ценой
    print("\n🔹 ЛОТ И ЦЕНА:")
    if hasattr(instrument, 'lot'):
        print(f"   {'lot':30s} = {instrument.lot}")
    
    # Ищем все поля, связанные с размером контракта/лота
    print("\n🔹 ПОЛЯ, СВЯЗАННЫЕ С РАЗМЕРОМ КОНТРАКТА:")
    contract_size_keywords = ['lot', 'size', 'contract', 'quantity', 'unit', 'step', 'min_quantity']
    for attr_name in dir(instrument):
        if attr_name.startswith('_'):
            continue
        attr_lower = attr_name.lower()
        if any(keyword in attr_lower for keyword in contract_size_keywords):
            try:
                attr_value = getattr(instrument, attr_name)
                if not callable(attr_value):
                    extracted = extract_money_value(attr_value, attr_name)
                    if extracted is not None:
                        print(f"   {attr_name:30s} = {extracted}")
                    else:
                        value_str = str(attr_value)[:100]
                        print(f"   {attr_name:30s} = {value_str} (type: {type(attr_value).__name__})")
            except Exception as e:
                pass
    
    if hasattr(instrument, 'min_price_increment'):
        inc = instrument.min_price_increment
        value = extract_money_value(inc, 'min_price_increment')
        if value is not None:
            print(f"   {'min_price_increment':30s} = {value}")
        else:
            print(f"   {'min_price_increment':30s} = {inc}")
    
    # Поля, связанные с маржой (коэффициенты гарантийного обеспечения)
    print("\n🔹 КОЭФФИЦИЕНТЫ ГАРАНТИЙНОГО ОБЕСПЕЧЕНИЯ (МАРЖИ):")
    margin_fields = {}
    
    # dlong, dshort - дисконты (гарантийное обеспечение за лот)
    # klong, kshort - коэффициенты
    margin_field_names = ['dlong', 'dlong_client', 'dlong_min', 'dshort', 'dshort_client', 'dshort_min', 
                          'klong', 'kshort']
    
    for field_name in margin_field_names:
        if hasattr(instrument, field_name):
            value = getattr(instrument, field_name)
            extracted = extract_money_value(value, field_name)
            if extracted is not None:
                margin_fields[field_name] = extracted
                print(f"   {field_name:30s} = {extracted:.2f} руб")
            else:
                margin_fields[field_name] = value
                print(f"   {field_name:30s} = {value} (type: {type(value).__name__})")
    
    # Дополнительные поля, связанные с маржой
    print("\n🔹 ДОПОЛНИТЕЛЬНЫЕ ПОЛЯ, СВЯЗАННЫЕ С МАРЖЕЙ:")
    margin_keywords = ['margin', 'initial', 'blocked', 'guarantee', 'collateral', 'deposit']
    margin_fields_found = False
    
    for attr_name in dir(instrument):
        if attr_name.startswith('_'):
            continue
        if attr_name in margin_field_names:
            continue  # Уже вывели
        
        # Проверяем, содержит ли поле ключевые слова о марже
        attr_lower = attr_name.lower()
        if any(keyword in attr_lower for keyword in margin_keywords):
            margin_fields_found = True
            try:
                attr_value = getattr(instrument, attr_name)
                if attr_value is not None:
                    # Пытаемся извлечь значение
                    extracted = extract_money_value(attr_value, attr_name)
                    if extracted is not None:
                        print(f"   {attr_name:30s} = {extracted:.2f} руб (extracted)")
                    else:
                        print(f"   {attr_name:30s} = {attr_value} (type: {type(attr_value).__name__})")
            except Exception as e:
                print(f"   {attr_name:30s} = <error: {e}>")
    
    if not margin_fields_found:
        print("   ⚠️ Дополнительные поля, связанные с маржой, не найдены")
    
    # Расчет маржи на основе коэффициентов
    if margin_fields:
        print("\n🔹 РАСЧЕТ МАРЖИ НА ОСНОВЕ КОЭФФИЦИЕНТОВ:")
        
        # Получаем текущую цену, если не передана
        if current_price is None and hasattr(instrument, 'figi'):
            print("   Получение текущей цены...")
            current_price = get_current_price(instrument.figi, sandbox=sandbox)
        
        if current_price and current_price > 0:
            print(f"   Текущая цена инструмента: {current_price:.4f} руб")
        else:
            print("   ⚠️ Текущая цена недоступна, используем примерную цену 3.00 руб")
            current_price = 3.00
        
        print()
        
        # dlong/dshort - это фиксированное гарантийное обеспечение за лот (в рублях)
        if 'dlong' in margin_fields and margin_fields['dlong']:
            dlong = margin_fields['dlong']
            print(f"   ✅ Маржа для LONG позиции (dlong): {dlong:.2f} руб за лот")
            print(f"      Это фиксированное значение гарантийного обеспечения!")
        
        if 'dshort' in margin_fields and margin_fields['dshort']:
            dshort = margin_fields['dshort']
            print(f"   ✅ Маржа для SHORT позиции (dshort): {dshort:.2f} руб за лот")
            print(f"      Это фиксированное значение гарантийного обеспечения!")
        
        # klong/kshort - коэффициенты для расчета маржи (цена * коэффициент)
        if 'klong' in margin_fields and margin_fields['klong']:
            klong = margin_fields['klong']
            print(f"   Коэффициент для LONG (klong): {klong:.2f}")
            if current_price > 0:
                margin_long_calc = current_price * klong
                print(f"   Расчетная маржа LONG (цена {current_price:.4f} * klong {klong:.2f}): {margin_long_calc:.4f} руб за лот")
        
        if 'kshort' in margin_fields and margin_fields['kshort']:
            kshort = margin_fields['kshort']
            print(f"   Коэффициент для SHORT (kshort): {kshort:.2f}")
            if current_price > 0:
                margin_short_calc = current_price * kshort
                print(f"   Расчетная маржа SHORT (цена {current_price:.4f} * kshort {kshort:.2f}): {margin_short_calc:.4f} руб за лот")
        
        print("\n   💡 ВЫВОД:")
        lot_value = float(instrument.lot) if hasattr(instrument, 'lot') else 1.0
        
        if 'dlong' in margin_fields and margin_fields['dlong']:
            dlong = margin_fields['dlong']
            print(f"      Для LONG позиции:")
            print(f"         dlong (как есть): {dlong:.2f} руб")
            if lot_value > 1.0:
                dlong_per_lot = dlong * lot_value
                print(f"         dlong * lot ({lot_value}): {dlong_per_lot:.2f} руб за лот")
            else:
                print(f"         ⚠️ ВНИМАНИЕ: lot = {lot_value}, возможно нужно умножить на реальную лотность!")
        
        if 'dshort' in margin_fields and margin_fields['dshort']:
            dshort = margin_fields['dshort']
            print(f"      Для SHORT позиции:")
            print(f"         dshort (как есть): {dshort:.2f} руб")
            if lot_value > 1.0:
                dshort_per_lot = dshort * lot_value
                print(f"         dshort * lot ({lot_value}): {dshort_per_lot:.2f} руб за лот")
            else:
                print(f"         ⚠️ ВНИМАНИЕ: lot = {lot_value}, возможно нужно умножить на реальную лотность!")
        
        # Для NGG6 из терминала: 7 667,72 ₽, lot = 100
        if hasattr(instrument, 'ticker') and instrument.ticker.upper() == "NGG6":
            terminal_margin = 7667.72
            terminal_lot = 100
            print(f"\n      📱 ДАННЫЕ ИЗ ТЕРМИНАЛА:")
            print(f"         Гарантийное обеспечение: {terminal_margin:.2f} ₽ за лот")
            print(f"         Лотность: {terminal_lot}")
            print(f"         Маржа за единицу: {terminal_margin / terminal_lot:.2f} ₽")
            print(f"\n      🔍 СРАВНЕНИЕ:")
            if 'dlong' in margin_fields:
                dlong_unit = margin_fields['dlong']
                dlong_calculated = dlong_unit * terminal_lot
                print(f"         dlong ({dlong_unit:.2f}) * {terminal_lot} = {dlong_calculated:.2f} ₽")
                diff = abs(dlong_calculated - terminal_margin)
                if diff < 100:
                    print(f"         ✅ Близко к терминалу (разница: {diff:.2f} ₽)")
                else:
                    print(f"         ❌ Далеко от терминала (разница: {diff:.2f} ₽)")
                    print(f"         💡 Возможно, нужно использовать другое поле или расчет!")
    
    # Все остальные поля
    print("\n🔹 ВСЕ ОСТАЛЬНЫЕ ПОЛЯ:")
    printed_fields = set(basic_fields + ['lot', 'min_price_increment'])
    other_fields = []
    
    for attr_name in dir(instrument):
        if attr_name.startswith('_'):
            continue
        if attr_name in printed_fields:
            continue
        if any(keyword in attr_name.lower() for keyword in margin_keywords):
            continue  # Уже вывели
        
        try:
            attr_value = getattr(instrument, attr_name)
            if not callable(attr_value):
                other_fields.append((attr_name, attr_value))
        except:
            pass
    
    # Сортируем по имени
    other_fields.sort(key=lambda x: x[0])
    
    for attr_name, attr_value in other_fields[:30]:  # Показываем первые 30
        try:
            # Пытаемся извлечь значение из MoneyValue/Quotation
            extracted = extract_money_value(attr_value, attr_name)
            if extracted is not None:
                print(f"   {attr_name:30s} = {extracted:.2f} руб")
            else:
                value_str = str(attr_value)[:100]
                print(f"   {attr_name:30s} = {value_str} (type: {type(attr_value).__name__})")
        except Exception as e:
            print(f"   {attr_name:30s} = <error: {e}>")
    
    if len(other_fields) > 30:
        print(f"   ... и еще {len(other_fields) - 30} полей")
    
    print("\n" + "=" * 80)

def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Get full instrument information from Tinkoff API')
    parser.add_argument('identifier', help='FIGI or ticker of the instrument')
    parser.add_argument('--figi', action='store_true', help='Treat identifier as FIGI (default: ticker)')
    parser.add_argument('--type', default='futures', choices=['futures', 'shares', 'bonds'],
                       help='Instrument type when searching by ticker (default: futures)')
    parser.add_argument('--sandbox', action='store_true', help='Use sandbox API')
    
    args = parser.parse_args()
    
    logger = setup_logging()
    
    if args.figi:
        instrument = get_instrument_by_figi(args.identifier, sandbox=args.sandbox)
    else:
        instrument = get_instrument_by_ticker(args.identifier, instrument_type=args.type, sandbox=args.sandbox)
    
    if instrument:
        print_instrument_info(instrument, logger, sandbox=args.sandbox)
    else:
        print("❌ Failed to get instrument information")
        sys.exit(1)

if __name__ == "__main__":
    main()
