#!/usr/bin/env python3
"""
Анализ формулы расчета ГО на основе известных данных.
"""
print("\n" + "="*80)
print("🔍 АНАЛИЗ ФОРМУЛЫ РАСЧЕТА ГО")
print("="*80 + "\n")

# Известные данные
data = {
    "ANH6": {
        "margin": 2746.1,
        "price": 3071.5,
        "dlong": 0.1329,
        "dshort": 0.1158,
        "klong": 2.0,
        "kshort": 2.0,
        "lot": 1.0
    },
    "NCM6": {
        "margin": 2112.00,
        "price": 17600.0,
        "dlong": 0.1628,
        "dshort": 0.1757,
        "klong": 2.0,
        "kshort": 2.0,
        "lot": 1.0
    }
}

print("📊 ИЗВЕСТНЫЕ ДАННЫЕ:\n")
for ticker, d in data.items():
    print(f"{ticker}:")
    print(f"  Реальная маржа: {d['margin']:.2f} ₽")
    print(f"  Цена: {d['price']:.2f} ₽")
    print(f"  dlong: {d['dlong']:.6f}, dshort: {d['dshort']:.6f}")
    print(f"  klong: {d['klong']:.2f}, kshort: {d['kshort']:.2f}")
    print()

print("\n" + "="*80)
print("📐 ПРОВЕРКА РАЗЛИЧНЫХ ФОРМУЛ")
print("="*80 + "\n")

formulas = [
    ("price * dlong", lambda d: d["price"] * d["dlong"]),
    ("price * dshort", lambda d: d["price"] * d["dshort"]),
    ("price * dlong * lot", lambda d: d["price"] * d["dlong"] * d["lot"]),
    ("price * dshort * lot", lambda d: d["price"] * d["dshort"] * d["lot"]),
    ("price * klong", lambda d: d["price"] * d["klong"]),
    ("price * kshort", lambda d: d["price"] * d["kshort"]),
    ("price * klong * lot", lambda d: d["price"] * d["klong"] * d["lot"]),
    ("price * kshort * lot", lambda d: d["price"] * d["kshort"] * d["lot"]),
]

for formula_name, formula_func in formulas:
    print(f"\n📌 Формула: {formula_name}")
    all_match = True
    for ticker, d in data.items():
        result = formula_func(d)
        diff = abs(result - d["margin"])
        diff_pct = (diff / d["margin"] * 100) if d["margin"] > 0 else 0
        match = "✅" if diff < 1.0 else "❌"
        print(f"   {match} {ticker}: {result:>10.2f} ₽ (ожидается {d['margin']:.2f} ₽, разница: {diff:.2f} ₽, {diff_pct:.2f}%)")
        if diff >= 1.0:
            all_match = False
    
    if all_match:
        print(f"   🎯 ВСЕ СОВПАДАЮТ! Это правильная формула!")

print("\n" + "="*80)
print("🔍 ОБРАТНЫЙ РАСЧЕТ (поиск коэффициентов)")
print("="*80 + "\n")

for ticker, d in data.items():
    print(f"\n{ticker}:")
    
    # Процент от цены
    margin_rate = d["margin"] / d["price"]
    print(f"  ГО / цена = {d['margin']:.2f} / {d['price']:.2f} = {margin_rate:.4f} ({margin_rate*100:.2f}%)")
    
    # Стоимость пункта через dlong
    if d["dlong"] > 0:
        point_value_dlong = d["margin"] / (d["price"] * d["dlong"])
        print(f"  Стоимость пункта (через dlong): {point_value_dlong:.4f}")
        print(f"    Проверка: {point_value_dlong:.4f} * {d['price']:.2f} * {d['dlong']:.6f} = {point_value_dlong * d['price'] * d['dlong']:.2f} ₽")
    
    # Стоимость пункта через dshort
    if d["dshort"] > 0:
        point_value_dshort = d["margin"] / (d["price"] * d["dshort"])
        print(f"  Стоимость пункта (через dshort): {point_value_dshort:.4f}")
        print(f"    Проверка: {point_value_dshort:.4f} * {d['price']:.2f} * {d['dshort']:.6f} = {point_value_dshort * d['price'] * d['dshort']:.2f} ₽")
    
    # Попробуем найти связь с klong/kshort
    if d["klong"] > 0:
        klong_factor = d["margin"] / (d["price"] * d["klong"])
        print(f"  Коэффициент для klong: {klong_factor:.4f}")
        print(f"    Проверка: {klong_factor:.4f} * {d['price']:.2f} * {d['klong']:.2f} = {klong_factor * d['price'] * d['klong']:.2f} ₽")

print("\n" + "="*80)
print("💡 ВЫВОДЫ")
print("="*80 + "\n")

print("Если ни одна из простых формул не подходит, возможно:")
print("1. Нужна стоимость пункта (point_value) для каждого инструмента")
print("2. Формула: ГО = point_value * price * dlong/dshort")
print("3. Стоимость пункта нужно брать из терминала или вычислять из известных данных")
