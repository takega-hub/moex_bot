#!/usr/bin/env python3
"""
Скрипт для получения данных ГО и стоимости пункта для BBM6.
"""
import os
import sys
from dotenv import load_dotenv
from trading.client import TinkoffClient
from bot.margin_rates import get_margin_for_position, MARGIN_PER_LOT, POINT_VALUE

load_dotenv()

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

def get_current_price(client: TinkoffClient, figi: str) -> float:
    """Получить текущую цену."""
    try:
        from datetime import datetime, timedelta, timezone
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=1)
        
        candles = client.get_candles(figi, from_date, to_date, interval="1min")
        if candles:
            return float(candles[-1]['close'])
    except:
        pass
    return 0.0

def main():
    """Главная функция."""
    ticker = "BBM6"
    
    print(f"\n{'='*80}")
    print(f"🔍 ПОЛУЧЕНИЕ ДАННЫХ ПО ГО И СТОИМОСТИ ПУНКТА ДЛЯ {ticker}")
    print(f"{'='*80}\n")
    
    try:
        client = TinkoffClient()
        
        # Поиск инструмента
        print(f"1️⃣ Поиск инструмента {ticker}...")
        instrument = client.find_instrument(ticker, instrument_type="futures")
        if not instrument:
            print(f"   ❌ Инструмент {ticker} не найден")
            return
        
        figi = instrument['figi']
        print(f"   ✅ Найден: {instrument.get('name', 'N/A')}")
        print(f"   ✅ FIGI: {figi}\n")
        
        # Получаем информацию об инструменте напрямую из API для детального анализа
        print("2️⃣ Информация об инструменте из API:")
        print("   Получение данных напрямую из API...")
        
        # Получаем через get_instrument_info
        inst_info = client.get_instrument_info(figi)
        if not inst_info:
            print(f"   ❌ Не удалось получить информацию об инструменте")
            return
        
        # Также получаем сырые данные напрямую из API для детального анализа
        try:
            with client._get_client() as tinkoff_client:
                from t_tech.invest import InstrumentIdType
                response = tinkoff_client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=figi
                )
                instrument_raw = response.instrument
                
                # Ищем все поля, связанные со стоимостью пункта
                print("\n   🔍 Детальный анализ полей инструмента из API:")
                point_related_fields = []
                for attr_name in dir(instrument_raw):
                    if attr_name.startswith('_'):
                        continue
                    attr_lower = attr_name.lower()
                    # Ищем поля, связанные со стоимостью пункта
                    if any(kw in attr_lower for kw in ['point', 'tick', 'step', 'increment', 'amount', 'value', 'cost']):
                        try:
                            attr_value = getattr(instrument_raw, attr_name)
                            if not callable(attr_value):
                                point_related_fields.append((attr_name, attr_value))
                        except:
                            pass
                
                if point_related_fields:
                    print("      Найдены поля, связанные со стоимостью пункта:")
                    for field_name, field_value in point_related_fields:
                        if field_value is not None:
                            if hasattr(field_value, 'units') and hasattr(field_value, 'nano'):
                                value = float(field_value.units) + float(field_value.nano) / 1e9
                                print(f"         {field_name}: {value:.6f} (units={field_value.units}, nano={field_value.nano})")
                            else:
                                print(f"         {field_name}: {field_value}")
        except Exception as e:
            print(f"   ⚠️ Не удалось получить детальную информацию: {e}")
        
        print(f"   Название: {inst_info.get('name', 'N/A')}")
        print(f"   Тикер: {inst_info.get('ticker', 'N/A')}")
        print(f"   Лот: {inst_info.get('lot', 1.0)}")
        
        # Коэффициенты маржи
        dlong = inst_info.get('dlong')
        dshort = inst_info.get('dshort')
        klong = inst_info.get('klong')
        kshort = inst_info.get('kshort')
        
        print(f"\n   Коэффициенты маржи из API:")
        if dlong is not None:
            print(f"      dlong: {dlong:.6f}")
        if dshort is not None:
            print(f"      dshort: {dshort:.6f}")
        if klong is not None:
            print(f"      klong: {klong:.6f}")
        if kshort is not None:
            print(f"      kshort: {kshort:.6f}")
        
        # Данные о стоимости пункта
        min_price_increment = inst_info.get('min_price_increment')
        min_price_increment_amount = inst_info.get('min_price_increment_amount')
        
        print(f"\n   📊 Данные о стоимости пункта из API:")
        if min_price_increment is not None:
            print(f"      min_price_increment (шаг цены): {min_price_increment:.6f} пунктов")
        if min_price_increment_amount is not None:
            print(f"      ✅ min_price_increment_amount (стоимость пункта): {min_price_increment_amount:.2f} ₽")
            print(f"         💡 Это реальная стоимость одного пункта цены!")
        else:
            print(f"      ⚠️ min_price_increment_amount отсутствует в API")
            print(f"         💡 Нужно проверить в терминале Tinkoff или добавить в словарь POINT_VALUE")
        
        # Получаем текущую цену
        print(f"\n3️⃣ Получение текущей цены...")
        current_price = get_current_price(client, figi)
        if current_price > 0:
            print(f"   ✅ Текущая цена: {current_price:.4f} пунктов")
            print(f"      ⚠️ ВАЖНО: Это цена в пунктах, а не в рублях!")
        else:
            print(f"   ⚠️ Не удалось получить текущую цену")
            current_price = 100.0  # Используем примерную цену для расчетов
        
        # Рассчитываем стоимость лота, если известна стоимость пункта из API
        lot_size = inst_info.get('lot', 1.0)
        # ИСПОЛЬЗУЕМ ТОЛЬКО ДАННЫЕ ИЗ API, НЕ ИСПОЛЬЗУЕМ СЛОВАРЬ!
        point_value_from_api = min_price_increment_amount if min_price_increment_amount and min_price_increment_amount > 0 else None
        
        if point_value_from_api and point_value_from_api > 0 and current_price > 0:
            print(f"\n   💰 Расчет стоимости лота (только из API):")
            print(f"      Цена в пунктах: {current_price:.4f}")
            print(f"      Стоимость пункта из API: {point_value_from_api:.2f} ₽")
            print(f"      Размер лота: {lot_size}")
            lot_value = current_price * point_value_from_api * lot_size
            print(f"      ✅ Стоимость лота = {current_price:.4f} * {point_value_from_api:.2f} * {lot_size} = {lot_value:.2f} ₽")
        elif current_price > 0:
            print(f"\n   ⚠️ Не удалось рассчитать стоимость лота")
            print(f"      ❌ min_price_increment_amount отсутствует в API")
            print(f"      💡 Нужно проверить в терминале Tinkoff или документации MOEX")
        
        # Проверяем наличие в словаре
        print(f"\n4️⃣ Проверка словаря маржи:")
        ticker_upper = ticker.upper()
        dict_margin = MARGIN_PER_LOT.get(ticker_upper, 0.0)
        dict_point_value = POINT_VALUE.get(ticker_upper, 0.0)
        
        if dict_margin > 0:
            print(f"   ✅ Найдено в MARGIN_PER_LOT: {dict_margin:.2f} ₽/лот")
        else:
            print(f"   ⚠️ Нет в MARGIN_PER_LOT")
        
        if dict_point_value > 0:
            print(f"   ✅ Найдено в POINT_VALUE: {dict_point_value:.2f} ₽")
        else:
            print(f"   ⚠️ Нет в POINT_VALUE")
        
        # Расчет маржи через функцию
        print(f"\n5️⃣ Расчет маржи через get_margin_for_position:")
        if current_price > 0:
            # ИСПОЛЬЗУЕМ ТОЛЬКО ДАННЫЕ ИЗ API, НЕ ИСПОЛЬЗУЕМ СЛОВАРЬ!
            point_value = min_price_increment_amount if min_price_increment_amount and min_price_increment_amount > 0 else None
            
            if not point_value:
                print(f"   ⚠️ Не удалось получить стоимость пункта из API")
                print(f"      Расчет маржи будет использовать fallback методы")
            
            calculated_margin_long = get_margin_for_position(
                ticker=ticker_upper,
                quantity=1.0,
                entry_price=current_price,
                lot_size=inst_info.get('lot', 1.0),
                dlong=dlong,
                dshort=dshort,
                is_long=True,
                point_value=point_value
            )
            print(f"   Рассчитанная маржа (1 лот, LONG): {calculated_margin_long:.2f} ₽")
            
            calculated_margin_short = get_margin_for_position(
                ticker=ticker_upper,
                quantity=1.0,
                entry_price=current_price,
                lot_size=inst_info.get('lot', 1.0),
                dlong=dlong,
                dshort=dshort,
                is_long=False,
                point_value=point_value
            )
            print(f"   Рассчитанная маржа (1 лот, SHORT): {calculated_margin_short:.2f} ₽")
            
            # Расчет через формулу: ГО = point_value * price * dlong/dshort (ТОЛЬКО ИЗ API!)
            if point_value and point_value > 0:
                print(f"\n   📐 Расчет через формулу ГО = point_value * price * dlong/dshort (из API):")
                if dlong and dlong > 0:
                    margin_long_formula = point_value * current_price * dlong
                    print(f"      LONG: {point_value:.2f} ₽ * {current_price:.4f} пт. * {dlong:.6f} = {margin_long_formula:.2f} ₽")
                if dshort and dshort > 0:
                    margin_short_formula = point_value * current_price * dshort
                    print(f"      SHORT: {point_value:.2f} ₽ * {current_price:.4f} пт. * {dshort:.6f} = {margin_short_formula:.2f} ₽")
            else:
                print(f"\n   ⚠️ Не удалось рассчитать ГО по формуле (нет point_value из API)")
        
        # Рекомендации
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
        
        # Показываем стоимость пункта ТОЛЬКО из API
        if min_price_increment_amount and min_price_increment_amount > 0:
            print(f"\n   ✅ Стоимость пункта найдена в API: {min_price_increment_amount:.2f} ₽")
            print(f"      💡 Это значение можно добавить в bot/margin_rates.py:")
            print(f"      POINT_VALUE[\"{ticker_upper}\"] = {min_price_increment_amount:.2f}")
        else:
            print(f"\n   ❌ Стоимость пункта НЕ найдена в API (min_price_increment_amount отсутствует)")
            print(f"      💡 Проверьте в терминале Tinkoff или документации MOEX")
            print(f"      💡 Если найдете значение, добавьте в bot/margin_rates.py:")
            print(f"      POINT_VALUE[\"{ticker_upper}\"] = <стоимость_пункта>")
        
        print()
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
