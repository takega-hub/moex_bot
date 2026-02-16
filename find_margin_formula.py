#!/usr/bin/env python3
"""
Скрипт для поиска формулы расчета реального гарантийного обеспечения через API.
Анализирует данные из терминала и API, чтобы найти правильную формулу.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Данные из терминала
TERMINAL_DATA = {
    "NGG6": {
        "margin": 7667.72,
        "lot": 100,
        "price": 3.0,
        "point_value": None,  # Не указано в терминале
    },
    "PTH6": {
        "margin": 33860.23,
        "lot": 1,
        "price": 2049.7,
        "point_value": 77.19,
    },
    "S1H6": {
        "margin": 1558.96,
        "lot": 1,
        "price": 77.0,
        "point_value": None,
    },
}

# Данные из API (из margin_check_results.json)
API_DATA = {
    "NGG6": {"dlong": 0.33, "dshort": 0.6147, "klong": 2.0, "kshort": 2.0, "lot": 1.0},
    "PTH6": {"dlong": 0.2834, "dshort": 0.214, "klong": 2.0, "kshort": 2.0, "lot": 1.0},
    "S1H6": {"dlong": 0.276, "dshort": 0.2595, "klong": 2.0, "kshort": 2.0, "lot": 1.0},
}

def find_formula():
    """Найти формулу расчета маржи."""
    print("=" * 80)
    print("🔍 ПОИСК ФОРМУЛЫ РАСЧЕТА ГАРАНТИЙНОГО ОБЕСПЕЧЕНИЯ")
    print("=" * 80)
    print()
    
    for ticker, terminal in TERMINAL_DATA.items():
        if terminal["margin"] == 0:
            continue
        
        print(f"📊 {ticker}:")
        print(f"   Терминал: ГО = {terminal['margin']:.2f} ₽, цена = {terminal['price']:.2f}, лот = {terminal['lot']}")
        if terminal.get("point_value"):
            print(f"   Стоимость пункта = {terminal['point_value']:.2f} ₽")
        
        api = API_DATA.get(ticker, {})
        if not api:
            print(f"   ⚠️ Нет данных из API")
            continue
        
        print(f"   API: dlong = {api.get('dlong', 0):.4f}, dshort = {api.get('dshort', 0):.4f}")
        print(f"        klong = {api.get('klong', 0):.2f}, kshort = {api.get('kshort', 0):.2f}, lot = {api.get('lot', 1):.0f}")
        
        margin = terminal["margin"]
        price = terminal["price"]
        lot = terminal["lot"]
        point_value = terminal.get("point_value")
        dlong = api.get("dlong", 0)
        dshort = api.get("dshort", 0)
        klong = api.get("klong", 0)
        kshort = api.get("kshort", 0)
        api_lot = api.get("lot", 1.0)
        
        print(f"\n   🔬 Тестирование формул:")
        
        # Формула 1: через стоимость пункта (для PTH6)
        if point_value:
            calc_long = point_value * price * dlong
            calc_short = point_value * price * dshort
            diff_long = abs(calc_long - margin)
            diff_short = abs(calc_short - margin)
            
            match_long = "✅" if diff_long < 1.0 else "❌"
            match_short = "✅" if diff_short < 1.0 else "❌"
            
            print(f"      {match_long} LONG:  стоимость_пункта * цена * dlong = {point_value:.2f} * {price:.2f} * {dlong:.4f} = {calc_long:.2f} ₽ (разница: {diff_long:.2f} ₽)")
            print(f"      {match_short} SHORT: стоимость_пункта * цена * dshort = {point_value:.2f} * {price:.2f} * {dshort:.4f} = {calc_short:.2f} ₽ (разница: {diff_short:.2f} ₽)")
            
            if diff_short < 1.0:
                print(f"\n      ✅ НАЙДЕНА ФОРМУЛА ДЛЯ SHORT: ГО = стоимость_пункта * цена * dshort")
            if diff_long < 1.0:
                print(f"      ✅ НАЙДЕНА ФОРМУЛА ДЛЯ LONG: ГО = стоимость_пункта * цена * dlong")
        
        # Формула 2: через dlong/dshort и реальную лотность
        if lot != api_lot:
            calc_long = dlong * lot
            calc_short = dshort * lot
            diff_long = abs(calc_long - margin)
            diff_short = abs(calc_short - margin)
            
            match_long = "✅" if diff_long < 10.0 else "❌"
            match_short = "✅" if diff_short < 10.0 else "❌"
            
            print(f"      {match_long} LONG:  dlong * terminal_lot = {dlong:.4f} * {lot:.0f} = {calc_long:.2f} ₽ (разница: {diff_long:.2f} ₽)")
            print(f"      {match_short} SHORT: dshort * terminal_lot = {dshort:.4f} * {lot:.0f} = {calc_short:.2f} ₽ (разница: {diff_short:.2f} ₽)")
        
        # Формула 3: через цену и klong/kshort
        if klong > 0:
            calc_long = price * klong * lot
            calc_short = price * kshort * lot if kshort > 0 else 0
            diff_long = abs(calc_long - margin)
            diff_short = abs(calc_short - margin) if calc_short > 0 else 999999
            
            match_long = "✅" if diff_long < 100.0 else "❌"
            match_short = "✅" if diff_short < 100.0 else "❌"
            
            print(f"      {match_long} LONG:  цена * klong * lot = {price:.2f} * {klong:.2f} * {lot:.0f} = {calc_long:.2f} ₽ (разница: {diff_long:.2f} ₽)")
            if calc_short > 0:
                print(f"      {match_short} SHORT: цена * kshort * lot = {price:.2f} * {kshort:.2f} * {lot:.0f} = {calc_short:.2f} ₽ (разница: {diff_short:.2f} ₽)")
        
        # Формула 4: обратный расчет стоимости пункта
        if not point_value and dshort > 0:
            # Если известна формула ГО = стоимость_пункта * цена * dshort
            # То: стоимость_пункта = ГО / (цена * dshort)
            calculated_point_value = margin / (price * dshort)
            print(f"\n      💡 Обратный расчет стоимости пункта:")
            print(f"         стоимость_пункта = ГО / (цена * dshort) = {margin:.2f} / ({price:.2f} * {dshort:.4f}) = {calculated_point_value:.2f} ₽")
        
        print()
    
    print("=" * 80)
    print("💡 ВЫВОДЫ:")
    print("=" * 80)
    print()
    print("1. Для инструментов с известной стоимостью пункта (PTH6):")
    print("   ✅ ГО = стоимость_пункта * цена * dlong/dshort")
    print()
    print("2. Для других инструментов:")
    print("   ⚠️ Нужно либо:")
    print("      - Добавить стоимость пункта в словарь POINT_VALUE")
    print("      - Или использовать значения ГО из терминала в словаре MARGIN_PER_LOT")
    print()
    print("3. Проблема:")
    print("   ❌ API не возвращает стоимость пункта цены напрямую")
    print("   ❌ API возвращает неверные значения dlong/dshort (не соответствуют реальной марже)")
    print()
    print("4. Решение:")
    print("   ✅ Использовать словарь MARGIN_PER_LOT с значениями из терминала")
    print("   ✅ Для инструментов с известной стоимостью пункта - использовать формулу")
    print("   ✅ Регулярно обновлять словарь при изменении маржи")

if __name__ == "__main__":
    find_formula()
