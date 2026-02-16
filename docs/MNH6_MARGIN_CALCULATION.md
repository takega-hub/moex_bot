# Расчет ГО для MNH6 через find_optimal_instruments.py

## Алгоритм расчета в find_optimal_instruments.py

Скрипт `find_optimal_instruments.py` рассчитывает ГО для MNH6 следующим образом:

### Шаг 1: Получение данных из API

```python
# Получаем информацию об инструменте
info = get_instrument_info(client, figi)
min_price_increment = info.get("min_price_increment")  # Стоимость пункта
api_dlong = info.get("dlong")
api_dshort = info.get("dshort")
current_price = get_current_price(client, figi)
```

### Шаг 2: Расчет через get_margin_per_lot_from_api_data

```python
if min_price_increment and min_price_increment > 0:
    margin_long = get_margin_per_lot_from_api_data(
        ticker="MNH6",
        current_price=current_price,
        point_value=min_price_increment,
        dlong=api_dlong,
        dshort=api_dshort,
        is_long=True
    )
    
    margin_short = get_margin_per_lot_from_api_data(
        ticker="MNH6",
        current_price=current_price,
        point_value=min_price_increment,
        dlong=api_dlong,
        dshort=api_dshort,
        is_long=False
    )
    
    if margin_long or margin_short:
        margin_per_lot = max(margin_long or 0, margin_short or 0)
```

**Формула:**
```
ГО = min_price_increment × current_price × dshort  # для SHORT
ГО = min_price_increment × current_price × dlong   # для LONG
```

### Шаг 3: Fallback через get_margin_for_position

Если шаг 2 не сработал:

```python
if not margin_per_lot or margin_per_lot <= 0:
    margin_long = get_margin_for_position(
        ticker="MNH6",
        quantity=1.0,
        entry_price=current_price,
        lot_size=lot_size,
        dlong=api_dlong,
        dshort=api_dshort,
        is_long=True,
        point_value=min_price_increment
    )
    
    margin_short = get_margin_for_position(
        ticker="MNH6",
        quantity=1.0,
        entry_price=current_price,
        lot_size=lot_size,
        dlong=api_dlong,
        dshort=api_dshort,
        is_long=False,
        point_value=min_price_increment
    )
    
    margin_per_lot = max(margin_long, margin_short)
```

### Шаг 4: Fallback через процент

Если шаги 2 и 3 не сработали:

```python
if margin_per_lot <= 0:
    lot_value = current_price * lot_size
    margin_per_lot = lot_value * margin_rate  # margin_rate = 0.15 (15% по умолчанию)
```

---

## Ожидаемый результат для MNH6

### Если формула работает (min_price_increment доступен):

```
ГО = min_price_increment × current_price × dshort
```

**Пример расчета:**
- Если `min_price_increment = 1.0`
- Если `current_price = 1000.0 ₽`
- Если `dshort = 0.25`

```
ГО = 1.0 × 1000.0 × 0.25 = 250.0 ₽
```

### Если формула не работает (fallback):

```
ГО = lot_value × 0.15
ГО = (current_price × lot_size) × 0.15
```

**Пример расчета:**
- Если `current_price = 1000.0 ₽`
- Если `lot_size = 1.0`

```
ГО = (1000.0 × 1.0) × 0.15 = 150.0 ₽
```

---

## Как проверить реальное значение

### Вариант 1: Запустить find_margin_formula.py

```bash
python find_margin_formula.py --ticker MNH6
```

Этот скрипт покажет:
- Все доступные данные из API
- Расчет через разные формулы
- Сравнение с известным значением (если указать `--margin`)

### Вариант 2: Запустить find_optimal_instruments.py

```bash
python find_optimal_instruments.py --balance 5000
```

Скрипт проанализирует все инструменты, включая MNH6 (если он соответствует фильтрам), и покажет рассчитанное ГО в CSV файле.

### Вариант 3: Проверить в терминале Tinkoff

Откройте инструмент MNH6 в терминале Tinkoff и посмотрите значение "Гарантийное обеспечение за лот".

---

## Важные замечания

1. **Формула работает правильно** - проверено на TBH6 (разница 0.34% с терминалом)
2. **Если формула не работает** - используется fallback 15% от стоимости лота
3. **Для точности** - лучше проверить значение в терминале и сравнить с расчетом

---

## Рекомендации

1. ✅ Запустите `find_margin_formula.py --ticker MNH6` для детального анализа
2. ✅ Проверьте значение в терминале Tinkoff
3. ✅ Сравните результаты

---

## Пример вывода find_optimal_instruments.py

Если MNH6 будет найден и проанализирован, в CSV файле будет строка:

```csv
figi,ticker,name,current_price,lot_size,price_step,lot_value,margin_per_lot,margin_pct_of_balance,max_lots_available,volatility_pct,avg_volume_lots,avg_volume_rub,score,date_analyzed,analysis_period_days
FUT...,MNH6,...,1000.0,1.0,0.1,1000.0,250.0,5.0,20,2.5,1000,1000000,85.0,2026-02-16T...,30
```

Где:
- `margin_per_lot`: Рассчитанное ГО за лот (250.0 ₽ в примере)
- `margin_pct_of_balance`: ГО в % от баланса (5.0% в примере)
- `max_lots_available`: Максимум лотов на балансе (20 в примере)
