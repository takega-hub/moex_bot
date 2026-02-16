"""
Пример расчета ГО (гарантийного обеспечения) для TBH6.

Демонстрирует все приоритеты расчета ГО согласно алгоритму.
"""
from typing import Optional

# Импортируем функции расчета
from bot.margin_rates import (
    MARGIN_PER_LOT,
    MARGIN_RATE_PCT,
    POINT_VALUE,
    get_margin_for_position,
    get_margin_per_lot_from_api_data,
    auto_calculate_point_value
)

def calculate_margin_for_tbh6_example():
    """
    Пошаговый расчет ГО для TBH6 с демонстрацией всех приоритетов.
    """
    ticker = "TBH6"
    ticker_upper = ticker.upper()
    
    print("=" * 80)
    print(f"РАСЧЕТ ГО ДЛЯ {ticker_upper}")
    print("=" * 80)
    print()
    
    # Предположим, что мы получили данные из API
    # (в реальности эти данные получаются через TinkoffClient)
    current_price = 2500.0  # Пример: текущая цена
    lot_size = 1.0
    api_dlong = 0.15  # Пример: из API (может быть неверным!)
    api_dshort = 0.15  # Пример: из API (может быть неверным!)
    min_price_increment = 0.1  # Пример: стоимость пункта из API
    
    print(f"📊 Исходные данные:")
    print(f"   Текущая цена: {current_price:.2f} ₽")
    print(f"   Лотность: {lot_size}")
    print(f"   Стоимость лота: {current_price * lot_size:.2f} ₽")
    print(f"   dlong (из API): {api_dlong}")
    print(f"   dshort (из API): {api_dshort}")
    print(f"   min_price_increment (стоимость пункта): {min_price_increment}")
    print()
    
    # ============================================================
    # ПРИОРИТЕТ 1: Проверка словаря MARGIN_PER_LOT
    # ============================================================
    print("🔍 ПРИОРИТЕТ 1: Проверка словаря MARGIN_PER_LOT")
    print("-" * 80)
    
    if ticker_upper in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker_upper] > 0:
        margin_per_lot = MARGIN_PER_LOT[ticker_upper]
        print(f"✅ Найдено в словаре: {margin_per_lot:.2f} ₽ за лот")
        print(f"   Источник: Терминал Tinkoff (проверено)")
        print(f"   ✅ ИСПОЛЬЗУЕМ ЭТО ЗНАЧЕНИЕ")
        return margin_per_lot
    else:
        print(f"❌ Не найдено в словаре MARGIN_PER_LOT")
        print(f"   MARGIN_PER_LOT['{ticker_upper}'] = {MARGIN_PER_LOT.get(ticker_upper, 'не существует')}")
    print()
    
    # ============================================================
    # ПРИОРИТЕТ 2: Автоматический расчет из похожих инструментов
    # ============================================================
    print("🔍 ПРИОРИТЕТ 2: Автоматический расчет из похожих инструментов")
    print("-" * 80)
    
    # Группы похожих инструментов
    instrument_groups = {
        "S": ["S1H6", "SVH6"],  # Серебро
        "P": ["PTH6"],  # Платина
        "NG": ["NGG6", "NRG6"],  # Газ
        "TB": ["VBH6"],  # Возможно, TBH6 похож на VBH6?
        "VB": ["VBH6"],
        "SR": ["SRH6"],
        "GLD": ["GLDRUBF"],
    }
    
    # Определяем группу текущего инструмента
    current_group = None
    for prefix, group_tickers in instrument_groups.items():
        if ticker_upper.startswith(prefix):
            current_group = group_tickers
            print(f"   Найдена группа '{prefix}': {group_tickers}")
            break
    
    if current_group:
        for similar_ticker in current_group:
            if similar_ticker in MARGIN_PER_LOT and MARGIN_PER_LOT[similar_ticker] > 0:
                known_margin = MARGIN_PER_LOT[similar_ticker]
                print(f"   Найден похожий инструмент: {similar_ticker} с ГО = {known_margin:.2f} ₽")
                
                # Пробуем вычислить стоимость пункта
                calculated_point_value = auto_calculate_point_value(
                    ticker=ticker_upper,
                    known_margin=known_margin,
                    current_price=current_price,
                    dlong=api_dlong,
                    dshort=api_dshort
                )
                
                if calculated_point_value and calculated_point_value > 0:
                    print(f"   ✅ Вычислена стоимость пункта: {calculated_point_value:.2f}")
                    
                    # Используем для расчета маржи
                    if api_dshort and api_dshort > 0:
                        margin_per_lot = calculated_point_value * current_price * api_dshort
                        print(f"   ✅ Рассчитана маржа: {margin_per_lot:.2f} ₽")
                        print(f"      Формула: {calculated_point_value:.2f} × {current_price:.2f} × {api_dshort} = {margin_per_lot:.2f} ₽")
                        print(f"   ⚠️  РЕКОМЕНДУЕТСЯ проверить в терминале!")
                        return margin_per_lot
    else:
        print(f"   ❌ Не найдена группа похожих инструментов для {ticker_upper}")
    print()
    
    # ============================================================
    # ПРИОРИТЕТ 3: Расчет через стоимость пункта (min_price_increment)
    # ============================================================
    print("🔍 ПРИОРИТЕТ 3: Расчет через min_price_increment")
    print("-" * 80)
    
    if min_price_increment and min_price_increment > 0:
        print(f"   min_price_increment = {min_price_increment}")
        
        # Пробуем для LONG
        margin_long = get_margin_per_lot_from_api_data(
            ticker=ticker_upper,
            current_price=current_price,
            point_value=min_price_increment,
            dlong=api_dlong,
            dshort=api_dshort,
            is_long=True
        )
        
        # Пробуем для SHORT
        margin_short = get_margin_per_lot_from_api_data(
            ticker=ticker_upper,
            current_price=current_price,
            point_value=min_price_increment,
            dlong=api_dlong,
            dshort=api_dshort,
            is_long=False
        )
        
        if margin_long or margin_short:
            margin_per_lot = max(margin_long or 0, margin_short or 0) if (margin_long and margin_short) else (margin_long or margin_short or 0)
            if margin_per_lot > 0:
                print(f"   ✅ Рассчитана маржа через min_price_increment:")
                print(f"      LONG: {margin_long:.2f} ₽ (если доступно)")
                print(f"      SHORT: {margin_short:.2f} ₽ (если доступно)")
                print(f"      Используем максимальную: {margin_per_lot:.2f} ₽")
                print(f"   ⚠️  РЕКОМЕНДУЕТСЯ проверить в терминале!")
                return margin_per_lot
        else:
            print(f"   ❌ Не удалось рассчитать через min_price_increment")
    else:
        print(f"   ❌ min_price_increment не доступен или = 0")
    print()
    
    # ============================================================
    # ПРИОРИТЕТ 4: Расчет через стандартную функцию get_margin_for_position
    # ============================================================
    print("🔍 ПРИОРИТЕТ 4: Расчет через get_margin_for_position")
    print("-" * 80)
    
    margin_long = get_margin_for_position(
        ticker=ticker_upper,
        quantity=1.0,
        entry_price=current_price,
        lot_size=lot_size,
        dlong=api_dlong,
        dshort=api_dshort,
        is_long=True
    )
    
    margin_short = get_margin_for_position(
        ticker=ticker_upper,
        quantity=1.0,
        entry_price=current_price,
        lot_size=lot_size,
        dlong=api_dlong,
        dshort=api_dshort,
        is_long=False
    )
    
    margin_per_lot = max(margin_long, margin_short) if margin_long > 0 and margin_short > 0 else (margin_long if margin_long > 0 else margin_short)
    
    if margin_per_lot > 0:
        print(f"   ✅ Рассчитана маржа через get_margin_for_position:")
        print(f"      LONG: {margin_long:.2f} ₽")
        print(f"      SHORT: {margin_short:.2f} ₽")
        print(f"      Используем максимальную: {margin_per_lot:.2f} ₽")
        
        # Проверяем, откуда взялось значение
        if ticker_upper in MARGIN_RATE_PCT:
            margin_rate = MARGIN_RATE_PCT[ticker_upper] / 100.0
            print(f"   Источник: MARGIN_RATE_PCT = {MARGIN_RATE_PCT[ticker_upper]}%")
            print(f"   Формула: {current_price:.2f} × {lot_size} × {margin_rate} = {margin_per_lot:.2f} ₽")
        else:
            print(f"   Источник: fallback (12% по умолчанию)")
            print(f"   Формула: {current_price:.2f} × {lot_size} × 0.12 = {margin_per_lot:.2f} ₽")
        
        print(f"   ⚠️  РЕКОМЕНДУЕТСЯ проверить в терминале и добавить в MARGIN_PER_LOT!")
        return margin_per_lot
    else:
        print(f"   ❌ Не удалось рассчитать через get_margin_for_position")
    print()
    
    # ============================================================
    # FALLBACK: Процент от стоимости позиции
    # ============================================================
    print("🔍 FALLBACK: Процент от стоимости позиции")
    print("-" * 80)
    
    lot_value = current_price * lot_size
    margin_rate = MARGIN_RATE_PCT.get(ticker_upper, 0.12)  # 12% по умолчанию
    
    margin_per_lot = lot_value * margin_rate
    
    print(f"   ⚠️  Используется fallback расчет:")
    print(f"      Стоимость лота: {lot_value:.2f} ₽")
    print(f"      Коэффициент маржи: {margin_rate * 100:.1f}%")
    print(f"      ГО: {lot_value:.2f} × {margin_rate} = {margin_per_lot:.2f} ₽")
    print(f"   ❌ ОБЯЗАТЕЛЬНО обновить из терминала и добавить в MARGIN_PER_LOT!")
    
    return margin_per_lot


def demonstrate_with_real_api_data():
    """
    Демонстрация с реальными данными из API (если доступны).
    """
    print("\n" + "=" * 80)
    print("ДЕМОНСТРАЦИЯ С РЕАЛЬНЫМИ ДАННЫМИ ИЗ API")
    print("=" * 80)
    print()
    
    try:
        from trading.client import TinkoffClient
        from find_optimal_instruments import get_instrument_info, get_current_price
        
        client = TinkoffClient()
        
        # Пробуем найти TBH6
        print("🔍 Поиск инструмента TBH6 в API...")
        instrument = client.find_instrument("TBH6", instrument_type="futures")
        
        if not instrument:
            print("❌ Инструмент TBH6 не найден в API")
            print("   Возможно, это неправильный тикер или инструмент недоступен")
            return
        
        print(f"✅ Найден инструмент:")
        print(f"   FIGI: {instrument['figi']}")
        print(f"   Ticker: {instrument['ticker']}")
        print(f"   Name: {instrument['name']}")
        print()
        
        # Получаем информацию об инструменте
        print("📊 Получение информации об инструменте...")
        info = get_instrument_info(client, instrument['figi'])
        print(f"   Lot size: {info['lot_size']}")
        print(f"   Price step: {info['price_step']}")
        print(f"   dlong: {info.get('dlong', 'N/A')}")
        print(f"   dshort: {info.get('dshort', 'N/A')}")
        print(f"   min_price_increment: {info.get('min_price_increment', 'N/A')}")
        print()
        
        # Получаем текущую цену
        print("💰 Получение текущей цены...")
        current_price = get_current_price(client, instrument['figi'])
        if current_price:
            print(f"   Текущая цена: {current_price:.2f} ₽")
        else:
            print("   ⚠️  Не удалось получить текущую цену")
            current_price = 2500.0  # Используем примерное значение
            print(f"   Используем примерное значение: {current_price:.2f} ₽")
        print()
        
        # Рассчитываем ГО
        print("🧮 Расчет ГО...")
        from bot.margin_rates import get_margin_for_position
        
        margin_long = get_margin_for_position(
            ticker=instrument['ticker'],
            quantity=1.0,
            entry_price=current_price,
            lot_size=info['lot_size'],
            dlong=info.get('dlong'),
            dshort=info.get('dshort'),
            is_long=True
        )
        
        margin_short = get_margin_for_position(
            ticker=instrument['ticker'],
            quantity=1.0,
            entry_price=current_price,
            lot_size=info['lot_size'],
            dlong=info.get('dlong'),
            dshort=info.get('dshort'),
            is_long=False
        )
        
        margin_per_lot = max(margin_long, margin_short) if margin_long > 0 and margin_short > 0 else (margin_long if margin_long > 0 else margin_short)
        
        print(f"   ГО для LONG: {margin_long:.2f} ₽")
        print(f"   ГО для SHORT: {margin_short:.2f} ₽")
        print(f"   ГО (максимальная): {margin_per_lot:.2f} ₽")
        print()
        
        # Проверка баланса
        balance = 5000.0  # Пример баланса
        print(f"💵 Проверка достаточности баланса:")
        print(f"   Баланс: {balance:.2f} ₽")
        print(f"   ГО за лот: {margin_per_lot:.2f} ₽")
        
        if margin_per_lot <= balance:
            max_lots = int(balance / margin_per_lot)
            print(f"   ✅ Достаточно баланса для открытия {max_lots} лот(ов)")
        else:
            print(f"   ❌ Недостаточно баланса для открытия 1 лота")
        
    except Exception as e:
        print(f"❌ Ошибка при получении данных из API: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Пример расчета с гипотетическими данными
    print("\n" + "=" * 80)
    print("ПРИМЕР 1: Расчет с гипотетическими данными")
    print("=" * 80)
    print()
    
    margin = calculate_margin_for_tbh6_example()
    
    print()
    print("=" * 80)
    print(f"ИТОГОВЫЙ РЕЗУЛЬТАТ: ГО = {margin:.2f} ₽ за лот")
    print("=" * 80)
    print()
    
    # Попытка получить реальные данные из API
    try:
        demonstrate_with_real_api_data()
    except Exception as e:
        print(f"⚠️  Не удалось получить реальные данные: {e}")
        print("   Используйте пример выше для понимания логики расчета")
