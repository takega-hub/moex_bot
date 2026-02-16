"""
Проверка различных формул для расчета ГО NRG6
"""
# Данные из терминала для NRG6:
KNOWN_MARGIN = 64.28  # ГО из терминала
CURRENT_PRICE = 3.058  # Цена из терминала
POINT_VALUE = 76.62  # Стоимость пункта из терминала
DSHORT = 0.611  # Из API
DLONG = 0.274  # Из API
KLONG = 2.0  # Из API
KSHORT = 2.0  # Из API
MIN_PRICE_INCREMENT = 0.001  # Шаг цены из API

print("="*80)
print("ПРОВЕРКА ФОРМУЛ ДЛЯ РАСЧЕТА ГО NRG6")
print("="*80)
print(f"\nИзвестные данные:")
print(f"  ГО из терминала: {KNOWN_MARGIN:.2f} ₽")
print(f"  Цена: {CURRENT_PRICE:.2f} пт.")
print(f"  Стоимость пункта: {POINT_VALUE:.2f} ₽")
print(f"  dshort: {DSHORT:.6f}")
print(f"  dlong: {DLONG:.6f}")
print(f"  kshort: {KSHORT:.2f}")
print(f"  klong: {KLONG:.2f}")
print(f"  min_price_increment: {MIN_PRICE_INCREMENT:.6f}")

print(f"\n{'='*80}")
print("ВАРИАНТЫ ФОРМУЛ:")
print(f"{'='*80}\n")

# Вариант 1: point_value * price * dshort
formula1 = POINT_VALUE * CURRENT_PRICE * DSHORT
diff1 = abs(formula1 - KNOWN_MARGIN)
print(f"1. point_value * price * dshort")
print(f"   = {POINT_VALUE:.2f} * {CURRENT_PRICE:.2f} * {DSHORT:.6f}")
print(f"   = {formula1:.2f} ₽")
print(f"   Разница с терминалом: {diff1:.2f} ₽ ({diff1/KNOWN_MARGIN*100:.1f}%)")

# Вариант 2: point_value * price * dlong
formula2 = POINT_VALUE * CURRENT_PRICE * DLONG
diff2 = abs(formula2 - KNOWN_MARGIN)
print(f"\n2. point_value * price * dlong")
print(f"   = {POINT_VALUE:.2f} * {CURRENT_PRICE:.2f} * {DLONG:.6f}")
print(f"   = {formula2:.2f} ₽")
print(f"   Разница с терминалом: {diff2:.2f} ₽ ({diff2/KNOWN_MARGIN*100:.1f}%)")

# Вариант 3: point_value * price * dshort / kshort
formula3 = POINT_VALUE * CURRENT_PRICE * DSHORT / KSHORT
diff3 = abs(formula3 - KNOWN_MARGIN)
print(f"\n3. point_value * price * dshort / kshort")
print(f"   = {POINT_VALUE:.2f} * {CURRENT_PRICE:.2f} * {DSHORT:.6f} / {KSHORT:.2f}")
print(f"   = {formula3:.2f} ₽")
print(f"   Разница с терминалом: {diff3:.2f} ₽ ({diff3/KNOWN_MARGIN*100:.1f}%)")

# Вариант 4: point_value * price * dlong / klong
formula4 = POINT_VALUE * CURRENT_PRICE * DLONG / KLONG
diff4 = abs(formula4 - KNOWN_MARGIN)
print(f"\n4. point_value * price * dlong / klong")
print(f"   = {POINT_VALUE:.2f} * {CURRENT_PRICE:.2f} * {DLONG:.6f} / {KLONG:.2f}")
print(f"   = {formula4:.2f} ₽")
print(f"   Разница с терминалом: {diff4:.2f} ₽ ({diff4/KNOWN_MARGIN*100:.1f}%)")

# Вариант 5: Обратный расчет - какая должна быть стоимость пункта?
# Если ГО = point_value * price * dshort, то:
# point_value = ГО / (price * dshort)
calculated_point_value = KNOWN_MARGIN / (CURRENT_PRICE * DSHORT)
print(f"\n5. Обратный расчет: какая должна быть стоимость пункта?")
print(f"   point_value = ГО / (price * dshort)")
print(f"   = {KNOWN_MARGIN:.2f} / ({CURRENT_PRICE:.2f} * {DSHORT:.6f})")
print(f"   = {KNOWN_MARGIN:.2f} / {CURRENT_PRICE * DSHORT:.6f}")
print(f"   = {calculated_point_value:.2f} ₽")
print(f"   Реальная стоимость пункта из терминала: {POINT_VALUE:.2f} ₽")
print(f"   Разница: {abs(calculated_point_value - POINT_VALUE):.2f} ₽")

# Вариант 6: Может быть формула с min_price_increment?
# point_value = min_price_increment * multiplier?
multiplier = POINT_VALUE / MIN_PRICE_INCREMENT
print(f"\n6. Связь min_price_increment и стоимости пункта:")
print(f"   multiplier = point_value / min_price_increment")
print(f"   = {POINT_VALUE:.2f} / {MIN_PRICE_INCREMENT:.6f}")
print(f"   = {multiplier:.0f}")
print(f"   То есть: point_value = min_price_increment * {multiplier:.0f}")

# Вариант 7: Может быть формула с kshort/klong?
print(f"\n7. Проверка с kshort/klong:")
formula7_short = POINT_VALUE * CURRENT_PRICE * DSHORT / KSHORT
formula7_long = POINT_VALUE * CURRENT_PRICE * DLONG / KLONG
print(f"   SHORT: {formula7_short:.2f} ₽ (разница: {abs(formula7_short - KNOWN_MARGIN):.2f} ₽)")
print(f"   LONG: {formula7_long:.2f} ₽ (разница: {abs(formula7_long - KNOWN_MARGIN):.2f} ₽)")

# Вариант 8: Может быть формула: ГО = point_value * (price / min_price_increment) * dshort?
price_in_points = CURRENT_PRICE / MIN_PRICE_INCREMENT
formula8 = POINT_VALUE * price_in_points * DSHORT
diff8 = abs(formula8 - KNOWN_MARGIN)
print(f"\n8. point_value * (price / min_price_increment) * dshort")
print(f"   = {POINT_VALUE:.2f} * ({CURRENT_PRICE:.2f} / {MIN_PRICE_INCREMENT:.6f}) * {DSHORT:.6f}")
print(f"   = {POINT_VALUE:.2f} * {price_in_points:.0f} * {DSHORT:.6f}")
print(f"   = {formula8:.2f} ₽")
print(f"   Разница с терминалом: {diff8:.2f} ₽ ({diff8/KNOWN_MARGIN*100:.1f}%)")

print(f"\n{'='*80}")
print("ВЫВОД:")
print(f"{'='*80}")
print(f"Для NRG6 ни одна из стандартных формул не дает точное значение ГО.")
print(f"Поэтому используем словарь MARGIN_PER_LOT с известным значением: {KNOWN_MARGIN:.2f} ₽")
print(f"И словарь POINT_VALUE с известной стоимостью пункта: {POINT_VALUE:.2f} ₽")
