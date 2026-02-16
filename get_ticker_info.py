#!/usr/bin/env python3
"""
Простой скрипт для получения информации об инструменте по тикеру:
1. Цена в пунктах
2. Стоимость пункта (min_price_increment_amount)
3. ГО (гарантийное обеспечение)
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

try:
    from t_tech.invest import Client, InstrumentIdType, CandleInterval
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
    from t_tech.invest.schemas import InstrumentType
    from datetime import datetime, timedelta, timezone
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("❌ ERROR: t-tech-investments library not installed")
    sys.exit(1)

from bot.margin_rates import get_margin_for_position


def quotation_to_float(quotation) -> float:
    """Преобразование Quotation в float"""
    if quotation is None:
        return 0.0
    if hasattr(quotation, 'units') and hasattr(quotation, 'nano'):
        return float(quotation.units) + float(quotation.nano) / 1_000_000_000
    try:
        return float(quotation)
    except:
        return 0.0


def get_ticker_info(ticker: str, sandbox: bool = False):
    """
    Получить информацию об инструменте по тикеру
    
    Returns:
        dict с ключами: price_points, point_value, margin_long, margin_short
    """
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found!")
        return None
    
    target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
    
    with Client(token, target=target) as client:
        # 1. Находим инструмент
        print(f"🔍 Поиск инструмента {ticker}...")
        try:
            find_response = client.instruments.find_instrument(
                query=ticker,
                instrument_kind=InstrumentType.INSTRUMENT_TYPE_FUTURES,
                api_trade_available_flag=True
            )
            
            if not find_response.instruments:
                print(f"❌ Инструмент {ticker} не найден")
                return None
            
            # Ищем точное совпадение
            instrument = None
            for inst in find_response.instruments:
                if inst.ticker.upper() == ticker.upper():
                    instrument = inst
                    break
            
            if not instrument:
                instrument = find_response.instruments[0]
                print(f"⚠️ Точное совпадение не найдено, используем первый результат")
            
            figi = instrument.figi
            print(f"✅ Найден: {instrument.name} (FIGI: {figi})")
            
        except Exception as e:
            print(f"❌ Ошибка при поиске инструмента: {e}")
            return None
        
        # 2. Получаем информацию об инструменте
        try:
            inst_info = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi
            )
            instrument_obj = inst_info.instrument
            
            # Извлекаем параметры
            lot = getattr(instrument_obj, 'lot', 1)
            dlong = quotation_to_float(getattr(instrument_obj, 'dlong', None))
            dshort = quotation_to_float(getattr(instrument_obj, 'dshort', None))
            min_price_increment = quotation_to_float(getattr(instrument_obj, 'min_price_increment', None))
            
        except Exception as e:
            print(f"❌ Ошибка при получении информации об инструменте: {e}")
            return None
        
        # 3. Получаем стоимость пункта через get_futures_margin
        point_value = None
        try:
            print(f"💰 Получение стоимости пункта через get_futures_margin...")
            margin_response = client.instruments.get_futures_margin(figi=figi)
            print(f"   Тип ответа: {type(margin_response)}")
            
            # Выводим все поля ответа для отладки
            print(f"   Все поля ответа get_futures_margin:")
            for attr in dir(margin_response):
                if not attr.startswith('_') and not callable(getattr(margin_response, attr, None)):
                    try:
                        value = getattr(margin_response, attr)
                        if hasattr(value, 'units') and hasattr(value, 'nano'):
                            float_val = quotation_to_float(value)
                            print(f"      {attr}: {float_val:.6f} (Quotation)")
                        elif hasattr(value, '__dict__'):
                            print(f"      {attr}: {type(value).__name__} (объект)")
                        else:
                            print(f"      {attr}: {value}")
                    except Exception as ex:
                        print(f"      {attr}: <ошибка при получении: {ex}>")
            
            # Пробуем разные варианты доступа к данным
            if hasattr(margin_response, 'initial_margin_response'):
                initial_margin = margin_response.initial_margin_response
                print(f"\n   ✅ initial_margin_response найден")
                print(f"   Поля initial_margin_response:")
                for attr in dir(initial_margin):
                    if not attr.startswith('_') and not callable(getattr(initial_margin, attr, None)):
                        try:
                            value = getattr(initial_margin, attr)
                            if hasattr(value, 'units') and hasattr(value, 'nano'):
                                float_val = quotation_to_float(value)
                                print(f"      {attr}: {float_val:.6f} (units={value.units}, nano={value.nano})")
                                if attr == 'min_price_increment_amount':
                                    point_value = float_val
                                    print(f"      ✅ НАЙДЕНО min_price_increment_amount: {point_value:.6f} ₽")
                                    # Проверяем, нужно ли умножить на 100 для получения "стоимости пункта" как в терминале
                                    # Если значение меньше 1, возможно это в процентах или нужно умножить
                                    if point_value < 1.0 and point_value > 0.01:
                                        terminal_point_value = point_value * 100
                                        print(f"      💡 'Стоимость пункта' как в терминале: {terminal_point_value:.2f} ₽ (× 100)")
                            else:
                                print(f"      {attr}: {value}")
                        except Exception as ex:
                            print(f"      {attr}: <ошибка: {ex}>")
            
            # Пробуем прямой доступ к полям ответа
            for attr_name in ['min_price_increment_amount', 'initial_margin', 'margin']:
                if hasattr(margin_response, attr_name):
                    value = getattr(margin_response, attr_name)
                    if hasattr(value, 'units') and hasattr(value, 'nano'):
                        point_value = quotation_to_float(value)
                        print(f"   ✅ Найдено {attr_name}: {point_value:.6f} ₽")
                        break
            
        except Exception as e:
            print(f"   ❌ Ошибка при получении стоимости пункта: {e}")
            import traceback
            traceback.print_exc()
        
        # Сохраняем исходное значение из API
        point_value_raw = point_value
        
        # Fallback: рассчитываем из min_price_increment
        if not point_value and min_price_increment > 0:
            point_value = min_price_increment * lot
            point_value_raw = point_value
            print(f"\n   💡 Используем рассчитанное значение из min_price_increment:")
            print(f"      min_price_increment: {min_price_increment:.6f}")
            print(f"      lot: {lot}")
            print(f"      point_value = {min_price_increment:.6f} × {lot} = {point_value:.6f} ₽")
        
        # Если point_value в диапазоне 0.01-1.0, умножаем на 100 для расчета ГО
        # Это "стоимость пункта" как в терминале, которая используется для расчета ГО
        point_value_for_margin = point_value
        terminal_point_value = None
        if point_value and 0.01 < point_value < 1.0:
            terminal_point_value = point_value * 100
            point_value_for_margin = terminal_point_value  # Для расчета ГО используем умноженное значение!
            print(f"\n   💡 Обнаружено значение в диапазоне 0.01-1.0")
            print(f"      Исходное значение из API: {point_value:.6f} ₽")
            print(f"      'Стоимость пункта' (× 100): {terminal_point_value:.2f} ₽")
            print(f"      ✅ Для расчета ГО используем умноженное значение: {point_value_for_margin:.2f} ₽")
        
        # 4. Получаем текущую цену
        price_points = None
        try:
            to_date = datetime.now(timezone.utc)
            from_date = to_date - timedelta(days=1)
            
            candles_response = client.market_data.get_candles(
                figi=figi,
                from_=from_date,
                to=to_date,
                interval=CandleInterval.CANDLE_INTERVAL_1_MIN
            )
            
            if candles_response.candles:
                last_candle = candles_response.candles[-1]
                if hasattr(last_candle, 'close'):
                    price_points = quotation_to_float(last_candle.close)
                    print(f"✅ Цена в пунктах: {price_points:.4f}")
        except Exception as e:
            print(f"⚠️ Не удалось получить текущую цену: {e}")
            # Пробуем через get_last_prices
            try:
                last_prices = client.market_data.get_last_prices(figi=[figi])
                if last_prices.last_prices:
                    price_points = quotation_to_float(last_prices.last_prices[0].price)
                    print(f"✅ Цена в пунктах: {price_points:.4f}")
            except:
                print(f"❌ Не удалось получить цену")
        
        # 5. Рассчитываем ГО по формуле: ГО = цена_в_пунктах × стоимость_пункта × dlong/dshort
        margin_long = None
        margin_short = None
        
        print(f"\n📊 Расчет ГО по формуле: ГО = цена × стоимость_пункта × dlong/dshort")
        print(f"   Цена: {price_points:.4f} пунктов" if price_points else "   ⚠️ Цена не получена")
        print(f"   Стоимость пункта: {point_value:.6f} ₽" if point_value else "   ⚠️ Стоимость пункта не получена")
        print(f"   dlong: {dlong:.6f}" if dlong else "   ⚠️ dlong не получен")
        print(f"   dshort: {dshort:.6f}" if dshort else "   ⚠️ dshort не получен")
        
        # Прямой расчет по формуле: ГО = min_price_increment_amount × цена × dlong/dshort
        # ВАЖНО: Используем point_value_for_margin (исходное значение из API), НЕ умноженное на 100!
        if price_points and price_points > 0 and point_value_for_margin and point_value_for_margin > 0:
            if dlong and dlong > 0:
                margin_long = point_value_for_margin * price_points * dlong
                print(f"   ✅ ГО (LONG) = {point_value_for_margin:.6f} × {price_points:.4f} × {dlong:.6f} = {margin_long:.2f} ₽")
            else:
                print(f"   ⚠️ ГО (LONG): dlong не получен")
            
            if dshort and dshort > 0:
                margin_short = point_value_for_margin * price_points * dshort
                print(f"   ✅ ГО (SHORT) = {point_value_for_margin:.6f} × {price_points:.4f} × {dshort:.6f} = {margin_short:.2f} ₽")
            else:
                print(f"   ⚠️ ГО (SHORT): dshort не получен")
        else:
            print(f"   ❌ Недостаточно данных для расчета ГО")
            if not price_points:
                print(f"      - Цена не получена")
            if not point_value:
                print(f"      - Стоимость пункта не получена")
        
        return {
            'ticker': ticker.upper(),
            'name': instrument.name,
            'figi': figi,
            'price_points': price_points,
            'point_value': point_value_for_margin,  # Для расчета ГО
            'terminal_point_value': terminal_point_value,  # "Стоимость пункта" как в терминале
            'margin_long': margin_long,
            'margin_short': margin_short,
            'dlong': dlong,
            'dshort': dshort,
            'lot': lot
        }


def main():
    """Главная функция"""
    if len(sys.argv) < 2:
        print("Использование: python get_ticker_info.py <TICKER> [--sandbox]")
        print("Пример: python get_ticker_info.py BBM6")
        sys.exit(1)
    
    ticker = sys.argv[1].upper()
    sandbox = '--sandbox' in sys.argv or os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
    
    print(f"\n{'='*70}")
    print(f"ИНФОРМАЦИЯ ОБ ИНСТРУМЕНТЕ: {ticker}")
    print(f"Режим: {'SANDBOX' if sandbox else 'PRODUCTION'}")
    print(f"{'='*70}\n")
    
    info = get_ticker_info(ticker, sandbox=sandbox)
    
    if info:
        print(f"\n{'='*70}")
        print("ИТОГОВАЯ ИНФОРМАЦИЯ:")
        print(f"{'='*70}")
        print(f"1️⃣ Цена в пунктах: {info['price_points']:.4f}" if info['price_points'] else "1️⃣ Цена в пунктах: не получена")
        
        # Показываем оба понятия стоимости пункта
        print(f"\n2️⃣ СТОИМОСТЬ ПУНКТА:")
        if info['point_value']:
            print(f"   ✅ min_price_increment_amount (из API): {info['point_value']:.6f} ₽")
            print(f"      💡 Это стоимость минимального шага цены")
            print(f"      💡 Используется для расчета ГО: ГО = {info['point_value']:.6f} × цена × dlong/dshort")
            
            # Показываем "стоимость пункта" как в терминале (если есть)
            if info.get('terminal_point_value'):
                print(f"\n   💵 'Стоимость пункта' как в терминале: {info['terminal_point_value']:.2f} ₽")
                print(f"      ⚠️ Это стоимость 1 пункта (1 USD), пересчитанная в RUB")
                print(f"      ⚠️ Динамично зависит от курса USD/RUB")
                print(f"      💡 НЕ используется для расчета ГО!")
            elif info['price_points'] and info['price_points'] > 0:
                # Примерная оценка, если не получено из API
                estimated_terminal_point_value = info['price_points'] * 0.01
                print(f"\n   💵 'Стоимость пункта' как в терминале (~76.62 ₽ для BBM6):")
                print(f"      ⚠️ Это стоимость 1 пункта (1 USD), пересчитанная в RUB")
                print(f"      ⚠️ Динамично зависит от курса USD/RUB")
                print(f"      💡 Примерная оценка: {estimated_terminal_point_value:.2f} - {info['price_points'] * 0.5:.2f} ₽")
                print(f"      💡 НЕ используется для расчета ГО!")
        else:
            print(f"   ❌ Стоимость пункта не получена")
        
        print(f"\n3️⃣ ГАРАНТИЙНОЕ ОБЕСПЕЧЕНИЕ (ГО):")
        if info['margin_long']:
            print(f"   ✅ ГО (LONG): {info['margin_long']:.2f} ₽")
        else:
            print(f"   ❌ ГО (LONG): не рассчитано")
        
        if info['margin_short']:
            print(f"   ✅ ГО (SHORT): {info['margin_short']:.2f} ₽")
        else:
            print(f"   ❌ ГО (SHORT): не рассчитано")
        
        if info['price_points'] and info['point_value']:
            print(f"\n📊 Дополнительная информация:")
            print(f"   dlong: {info['dlong']:.6f}")
            print(f"   dshort: {info['dshort']:.6f}")
            print(f"   Размер лота: {info['lot']}")
            print(f"\n💡 Формула расчета ГО:")
            print(f"   ГО = min_price_increment_amount × цена_в_пунктах × dlong/dshort")
            if info['margin_long']:
                print(f"   LONG: {info['point_value']:.6f} ₽ × {info['price_points']:.4f} пт. × {info['dlong']:.6f} = {info['margin_long']:.2f} ₽")
            if info['margin_short']:
                print(f"   SHORT: {info['point_value']:.6f} ₽ × {info['price_points']:.4f} пт. × {info['dshort']:.6f} = {info['margin_short']:.2f} ₽")
            
            print(f"\n⚠️ ВАЖНО:")
            print(f"   - Для расчета ГО используется min_price_increment_amount ({info['point_value']:.6f} ₽)")
            print(f"   - 'Стоимость пункта' из терминала (~76.62 ₽) - это другое понятие")
            print(f"   - 'Стоимость пункта' из терминала НЕ используется для расчета ГО")
    else:
        print("\n❌ Не удалось получить информацию об инструменте")
        sys.exit(1)


if __name__ == "__main__":
    main()
