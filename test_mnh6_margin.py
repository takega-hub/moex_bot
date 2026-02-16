#!/usr/bin/env python3
"""Тестовый скрипт для проверки расчета ГО для MNH6."""
import os
from dotenv import load_dotenv
from trading.client import TinkoffClient
from find_optimal_instruments import get_instrument_info, get_current_price
from bot.margin_rates import get_margin_for_position, get_margin_per_lot_from_api_data

load_dotenv()

def test_mnh6_margin():
    """Проверить расчет ГО для MNH6."""
    print("=" * 80)
    print("ПРОВЕРКА РАСЧЕТА ГО ДЛЯ MNH6")
    print("=" * 80)
    print()
    
    try:
        client = TinkoffClient()
        
        # Ищем инструмент MNH6
        print("🔍 Поиск инструмента MNH6...")
        instrument = client.find_instrument("MNH6", instrument_type="futures")
        
        if not instrument:
            print("❌ Инструмент MNH6 не найден в API")
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
            return
        print()
        
        # Рассчитываем ГО через get_margin_per_lot_from_api_data
        print("🧮 Расчет ГО через get_margin_per_lot_from_api_data...")
        min_price_increment = info.get('min_price_increment')
        api_dlong = info.get('dlong')
        api_dshort = info.get('dshort')
        
        if min_price_increment and min_price_increment > 0:
            margin_long = get_margin_per_lot_from_api_data(
                ticker=instrument['ticker'],
                current_price=current_price,
                point_value=min_price_increment,
                dlong=api_dlong,
                dshort=api_dshort,
                is_long=True
            )
            
            margin_short = get_margin_per_lot_from_api_data(
                ticker=instrument['ticker'],
                current_price=current_price,
                point_value=min_price_increment,
                dlong=api_dlong,
                dshort=api_dshort,
                is_long=False
            )
            
            if margin_long or margin_short:
                margin_per_lot = max(margin_long or 0, margin_short or 0) if (margin_long and margin_short) else (margin_long or margin_short or 0)
                print(f"   ✅ ГО для LONG: {margin_long:.2f} ₽" if margin_long else "   ❌ ГО для LONG: не рассчитано")
                print(f"   ✅ ГО для SHORT: {margin_short:.2f} ₽" if margin_short else "   ❌ ГО для SHORT: не рассчитано")
                print(f"   ✅ ГО (максимальная): {margin_per_lot:.2f} ₽")
                print(f"   Формула: {min_price_increment} × {current_price:.2f} × {api_dshort or api_dlong} = {margin_per_lot:.2f} ₽")
            else:
                print("   ❌ Не удалось рассчитать через формулу")
                print(f"      Причина: margin_long={margin_long}, margin_short={margin_short}")
                print(f"      dlong={api_dlong}, dshort={api_dshort}, point_value={min_price_increment}")
        else:
            print("   ❌ min_price_increment не доступен")
        print()
        
        # Рассчитываем ГО через get_margin_for_position
        print("🧮 Расчет ГО через get_margin_for_position...")
        margin_long = get_margin_for_position(
            ticker=instrument['ticker'],
            quantity=1.0,
            entry_price=current_price,
            lot_size=info['lot_size'],
            dlong=api_dlong,
            dshort=api_dshort,
            is_long=True,
            point_value=min_price_increment
        )
        
        margin_short = get_margin_for_position(
            ticker=instrument['ticker'],
            quantity=1.0,
            entry_price=current_price,
            lot_size=info['lot_size'],
            dlong=api_dlong,
            dshort=api_dshort,
            is_long=False,
            point_value=min_price_increment
        )
        
        margin_per_lot = max(margin_long, margin_short) if margin_long > 0 and margin_short > 0 else (margin_long if margin_long > 0 else margin_short)
        
        print(f"   ГО для LONG: {margin_long:.2f} ₽")
        print(f"   ГО для SHORT: {margin_short:.2f} ₽")
        print(f"   ГО (максимальная): {margin_per_lot:.2f} ₽")
        print()
        
        # Итоговый результат (как в find_optimal_instruments.py)
        print("=" * 80)
        print("ИТОГОВЫЙ РЕЗУЛЬТАТ (как в find_optimal_instruments.py):")
        print("=" * 80)
        print(f"Инструмент: {instrument['ticker']} ({instrument['name']})")
        print(f"Текущая цена: {current_price:.2f} ₽")
        print(f"Лотность: {info['lot_size']}")
        print(f"Стоимость лота: {current_price * info['lot_size']:.2f} ₽")
        print(f"ГО за лот: {margin_per_lot:.2f} ₽")
        print()
        
        # Проверка баланса (пример)
        balance = 5000.0
        print(f"Проверка баланса (пример с балансом {balance:.2f} ₽):")
        if margin_per_lot <= balance:
            max_lots = int(balance / margin_per_lot)
            print(f"   ✅ Достаточно баланса для открытия {max_lots} лот(ов)")
        else:
            print(f"   ❌ Недостаточно баланса для открытия 1 лота")
        print()
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_mnh6_margin()
