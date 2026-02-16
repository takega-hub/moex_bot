#!/usr/bin/env python3
"""
Скрипт для поиска формулы расчета ГО на основе известных данных.
Использование: python find_margin_formula.py --ticker ANH6
"""
import os
import sys
import argparse
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

from bot.margin_rates import MARGIN_PER_LOT, POINT_VALUE


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


def analyze_margin_formula(ticker: str = None, known_margin: float = None):
    """Анализировать формулу расчета маржи на основе известных данных."""
    
    print(f"\n{'='*80}")
    print(f"🔍 ПОИСК ФОРМУЛЫ РАСЧЕТА ГО")
    if ticker:
        print(f"   Инструмент: {ticker.upper()}")
    print(f"{'='*80}\n")
    
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found!")
        sys.exit(1)
    
    # Определяем список инструментов для анализа
    if ticker:
        tickers_to_analyze = [ticker.upper()]
        # Для конкретного тикера работаем даже без известной маржи
        require_known_margin = False
    else:
        # Анализируем все инструменты с известной маржей
        tickers_to_analyze = [t for t in MARGIN_PER_LOT.keys() if MARGIN_PER_LOT[t] > 0]
        require_known_margin = True
    
    known_data = {}
    
    with Client(token=token, target=INVEST_GRPC_API) as client:
        for ticker_name in tickers_to_analyze:
            print(f"📊 Получение данных для {ticker_name}...")
            
            # Получаем известную маржу из словаря или параметра
            if known_margin is not None and ticker_name == ticker.upper():
                # Используем значение из параметра командной строки
                margin_value = known_margin
                margin_source = "параметр --margin"
            else:
                # Используем значение из словаря
                margin_value = MARGIN_PER_LOT.get(ticker_name, 0.0)
                margin_source = "словарь MARGIN_PER_LOT"
            
            if require_known_margin and margin_value == 0:
                print(f"   ⚠️ Нет известной маржи для {ticker_name}, пропускаем")
                continue
            
            figi = get_instrument_figi(ticker_name, client)
            if not figi:
                print(f"   ❌ Не найден FIGI для {ticker_name}")
                continue
            
            # Получаем информацию об инструменте
            response = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi
            )
            instrument = response.instrument
            
            # Проверяем, есть ли методы для расчета маржи
            print(f"   🔍 Поиск методов API для расчета маржи...")
            operations_service = client.operations
            margin_methods = []
            for method_name in dir(operations_service):
                if not method_name.startswith('_') and callable(getattr(operations_service, method_name)):
                    if any(kw in method_name.lower() for kw in ['margin', 'guarantee', 'collateral', 'calculate', 'estimate', 'position']):
                        margin_methods.append(method_name)
            
            if margin_methods:
                print(f"      ✅ Найдены методы, связанные с маржой:")
                for method_name in margin_methods:
                    print(f"         - {method_name}")
            else:
                print(f"      ⚠️ Специальных методов для расчета маржи не найдено")
            
            # Получаем текущую цену
            current_price = get_current_price(figi, client)
            if current_price == 0:
                print(f"   ⚠️ Не удалось получить цену для {ticker_name}")
                continue
            
            # Извлекаем коэффициенты
            dlong = extract_money_value(getattr(instrument, 'dlong', None))
            dshort = extract_money_value(getattr(instrument, 'dshort', None))
            klong = extract_money_value(getattr(instrument, 'klong', None))
            kshort = extract_money_value(getattr(instrument, 'kshort', None))
            lot = float(getattr(instrument, 'lot', 1.0))
            
            # Ищем все поля, связанные с ГО и стоимостью пункта
            print(f"   🔍 Полный поиск всех полей API инструмента...")
            api_margin_fields = {}
            api_point_value_fields = {}
            all_numeric_fields = {}
            
            # Проверяем все атрибуты инструмента
            for attr_name in dir(instrument):
                if attr_name.startswith('_'):
                    continue
                
                try:
                    attr_value = getattr(instrument, attr_name)
                    if callable(attr_value):
                        continue
                    
                    attr_lower = attr_name.lower()
                    extracted = extract_money_value(attr_value)
                    
                    # Сохраняем все числовые поля
                    if extracted is not None:
                        all_numeric_fields[attr_name] = extracted
                    
                    # Ищем поля, связанные с маржой/ГО
                    if any(kw in attr_lower for kw in ['margin', 'guarantee', 'collateral', 'deposit', 'initial', 'blocked']):
                        if extracted is not None:
                            api_margin_fields[attr_name] = extracted
                        elif attr_value is not None:
                            api_margin_fields[attr_name] = str(attr_value)[:100]
                    
                    # Ищем поля, связанные со стоимостью пункта
                    # ВАЖНО: Для некоторых инструментов min_price_increment может быть 0 или неправильным
                    # Поэтому проверяем все поля, связанные со стоимостью пункта
                    if any(kw in attr_lower for kw in ['point', 'tick', 'step', 'increment', 'value']) and 'price' in attr_lower:
                        if extracted is not None:
                            # Сохраняем даже если 0, чтобы видеть, что поле есть
                            api_point_value_fields[attr_name] = extracted
                            # Дополнительно проверяем, если это min_price_increment и он равен 0
                            if attr_name == 'min_price_increment' and extracted == 0:
                                # Пробуем извлечь значение другим способом
                                try:
                                    if hasattr(attr_value, 'units'):
                                        units_val = float(attr_value.units) if attr_value.units else 0
                                        nano_val = float(attr_value.nano) / 1e9 if hasattr(attr_value, 'nano') and attr_value.nano else 0
                                        if units_val > 0 or nano_val > 0:
                                            api_point_value_fields[attr_name] = units_val + nano_val
                                except:
                                    pass
                except:
                    pass
            
            # Показываем найденные поля
            if api_margin_fields:
                print(f"      ✅ Найдены поля, связанные с ГО:")
                for field_name, field_value in api_margin_fields.items():
                    if isinstance(field_value, (int, float)):
                        print(f"         {field_name:35s} = {field_value:>15.2f} ₽")
                    else:
                        print(f"         {field_name:35s} = {field_value}")
            
            if api_point_value_fields:
                print(f"      ✅ Найдены поля, связанные со стоимостью пункта:")
                for field_name, field_value in api_point_value_fields.items():
                    if isinstance(field_value, (int, float)):
                        print(f"         {field_name:35s} = {field_value:>15.2f} ₽")
            
            # Показываем все числовые поля для анализа (кроме уже показанных)
            if all_numeric_fields:
                print(f"\n      📊 Все числовые поля инструмента (для анализа формулы):")
                shown_fields = set(api_margin_fields.keys()) | set(api_point_value_fields.keys())
                for field_name, field_value in sorted(all_numeric_fields.items()):
                    if field_name not in shown_fields:
                        # Показываем только значимые значения или известные коэффициенты
                        if abs(field_value) > 0.0001 or field_name in ['dlong', 'dshort', 'klong', 'kshort', 'lot']:
                            print(f"         {field_name:35s} = {field_value:>15.6f}")
            
            if not api_margin_fields and not api_point_value_fields:
                print(f"      ⚠️ Прямых полей для ГО и стоимости пункта не найдено в API")
                print(f"      💡 Нужно вычислять через формулу: ГО = point_value * price * dlong/dshort")
            
            # Используем min_price_increment как стоимость пункта, если найдена
            point_value_from_api = None
            if api_point_value_fields:
                # Приоритет: min_price_increment (это и есть стоимость пункта)
                if 'min_price_increment' in api_point_value_fields:
                    point_value_from_api = api_point_value_fields['min_price_increment']
                else:
                    # Используем первое найденное значение
                    point_value_from_api = list(api_point_value_fields.values())[0]
            
            known_data[ticker_name] = {
                "margin": margin_value,  # 0.0 если неизвестна
                "price": current_price,
                "dlong": dlong,
                "dshort": dshort,
                "klong": klong,
                "kshort": kshort,
                "lot": lot,
                "name": getattr(instrument, 'name', 'N/A'),
                "has_known_margin": margin_value > 0,
                "margin_source": margin_source,
                "api_margin_fields": api_margin_fields,
                "api_point_value_fields": api_point_value_fields,
                "point_value_from_api": point_value_from_api  # min_price_increment из API
            }
            
            print(f"   ✅ {ticker_name}: {known_data[ticker_name]['name']}")
            if margin_value > 0:
                print(f"      Маржа (из {margin_source}): {margin_value:.2f} ₽")
            else:
                print(f"      ⚠️ Маржа неизвестна - будут показаны все варианты расчета")
                print(f"      💡 Используйте --margin <значение> для сравнения с терминалом")
            print(f"      Цена: {current_price:.2f} ₽")
            print(f"      dlong: {dlong}, dshort: {dshort}")
            print(f"      klong: {klong}, kshort: {kshort}")
            print(f"      Лот: {lot}")
    
    if not known_data:
        print("❌ Нет данных для анализа")
        return
    
    print(f"\n{'='*80}")
    print(f"📐 АНАЛИЗ ФОРМУЛ РАСЧЕТА")
    print(f"{'='*80}\n")
    
    # Пробуем разные формулы для каждого инструмента
    formulas = [
        ("price * dlong", lambda d: d["price"] * d["dlong"] if d["dlong"] else None, "Прямая формула"),
        ("price * dshort", lambda d: d["price"] * d["dshort"] if d["dshort"] else None, "Прямая формула"),
        ("price * dlong * lot", lambda d: d["price"] * d["dlong"] * d["lot"] if d["dlong"] else None, "Прямая формула"),
        ("price * dshort * lot", lambda d: d["price"] * d["dshort"] * d["lot"] if d["dshort"] else None, "Прямая формула"),
        ("price * klong", lambda d: d["price"] * d["klong"] if d["klong"] else None, "Прямая формула"),
        ("price * kshort", lambda d: d["price"] * d["kshort"] if d["kshort"] else None, "Прямая формула"),
        ("price * klong * lot", lambda d: d["price"] * d["klong"] * d["lot"] if d["klong"] else None, "Прямая формула"),
        ("price * kshort * lot", lambda d: d["price"] * d["kshort"] * d["lot"] if d["kshort"] else None, "Прямая формула"),
        ("point_value * price * dlong", lambda d: (d.get("point_value", 0) * d["price"] * d["dlong"]) if d.get("point_value") and d["dlong"] else None, "Через стоимость пункта"),
        ("point_value * price * dshort", lambda d: (d.get("point_value", 0) * d["price"] * d["dshort"]) if d.get("point_value") and d["dshort"] else None, "Через стоимость пункта"),
    ]
    
    all_results = []
    
    for ticker_name, data in known_data.items():
        print(f"\n{'='*80}")
        print(f"📊 {ticker_name}: {data['name']}")
        print(f"{'='*80}")
        
        if data["has_known_margin"]:
            print(f"   Реальная маржа (из терминала): {data['margin']:.2f} ₽")
        else:
            print(f"   ⚠️ Маржа неизвестна - будут показаны все варианты расчета")
            print(f"   💡 После просмотра результатов сравните с терминалом и укажите правильное значение")
        
        print(f"   Текущая цена: {data['price']:.2f} ₽")
        print(f"   dlong: {data['dlong']}, dshort: {data['dshort']}")
        print(f"   klong: {data['klong']}, kshort: {data['kshort']}")
        print(f"   Лот: {data['lot']}")
        
        # Показываем данные из API (если найдены)
        if data.get('api_margin_fields'):
            print(f"\n   📡 Поля API, связанные с ГО:")
            for field_name, field_value in data['api_margin_fields'].items():
                if isinstance(field_value, (int, float)):
                    print(f"      {field_name:30s} = {field_value:>15.2f} ₽")
                else:
                    print(f"      {field_name:30s} = {field_value}")
        
        if data.get('api_point_value_fields'):
            print(f"\n   📡 Поля API, связанные со стоимостью пункта:")
            for field_name, field_value in data['api_point_value_fields'].items():
                if isinstance(field_value, (int, float)):
                    print(f"      {field_name:30s} = {field_value:>15.2f} ₽")
                    # Используем min_price_increment как стоимость пункта
                    if field_name == 'min_price_increment':
                        if field_value == 0:
                            print(f"      ⚠️ min_price_increment из API = 0 (неверно!)")
                            # Проверяем, есть ли значение в словаре POINT_VALUE
                            point_value_from_dict = POINT_VALUE.get(ticker_name)
                            if point_value_from_dict:
                                data["point_value"] = point_value_from_dict
                                print(f"      ✅ Используем стоимость пункта из словаря POINT_VALUE: {point_value_from_dict:.2f} ₽")
                            else:
                                print(f"      💡 Добавьте правильное значение в словарь POINT_VALUE для {ticker_name}")
                        else:
                            data["point_value"] = field_value
                            print(f"      ✅ Используем min_price_increment как стоимость пункта!")
                else:
                    print(f"      {field_name:30s} = {field_value}")
        
        # Используем point_value_from_api, если он есть и не равен 0
        if data.get('point_value_from_api') and not data.get('point_value'):
            if data['point_value_from_api'] > 0:
                data["point_value"] = data['point_value_from_api']
                print(f"\n   ✅ Используем стоимость пункта из API: {data['point_value_from_api']:.2f} ₽")
            else:
                # Если из API получили 0, проверяем словарь
                point_value_from_dict = POINT_VALUE.get(ticker_name)
                if point_value_from_dict:
                    data["point_value"] = point_value_from_dict
                    print(f"\n   ⚠️ min_price_increment из API = 0, используем словарь POINT_VALUE: {point_value_from_dict:.2f} ₽")
                else:
                    print(f"\n   ⚠️ min_price_increment из API = 0, и нет значения в словаре POINT_VALUE для {ticker_name}")
        
        # Специальный анализ для VBH6 (данные из терминала)
        if ticker_name == "VBH6":
            print(f"\n   📱 Данные из терминала (из изображения):")
            terminal_point_value = 1.0  # 1 ₽
            terminal_margin = 2049.73  # 2 049,73 ₽
            terminal_lot = 100
            terminal_price = 8881.0  # 8 881 пт.
            
            print(f"      Стоимость пункта цены: {terminal_point_value:.2f} ₽")
            print(f"      Гарантийное обеспечение: {terminal_margin:.2f} ₽")
            print(f"      Лотность: {terminal_lot}")
            print(f"      Цена: {terminal_price:.0f} пт.")
            
            # Проверяем формулу price * dshort
            print(f"\n   🔍 Анализ формулы для VBH6:")
            if data["dshort"]:
                calc_margin_dshort = terminal_price * data["dshort"]
                diff = abs(calc_margin_dshort - terminal_margin)
                diff_pct = (diff / terminal_margin * 100) if terminal_margin > 0 else 0
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1 else "✅" if diff < 10 else "❌"
                print(f"      {match} price * dshort = {terminal_price:.0f} * {data['dshort']:.6f} = {calc_margin_dshort:.2f} ₽")
                print(f"         Терминал ГО: {terminal_margin:.2f} ₽")
                print(f"         Разница: {diff:.2f} ₽ ({diff_pct:.2f}%)")
                if diff < 1:
                    print(f"         ✅✅✅ ФОРМУЛА РАБОТАЕТ! ГО = price * dshort")
            
            if data["dlong"]:
                calc_margin_dlong = terminal_price * data["dlong"]
                diff = abs(calc_margin_dlong - terminal_margin)
                diff_pct = (diff / terminal_margin * 100) if terminal_margin > 0 else 0
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1 else "✅" if diff < 10 else "❌"
                print(f"      {match} price * dlong = {terminal_price:.0f} * {data['dlong']:.6f} = {calc_margin_dlong:.2f} ₽")
                print(f"         Терминал ГО: {terminal_margin:.2f} ₽")
                print(f"         Разница: {diff:.2f} ₽ ({diff_pct:.2f}%)")
            
            # Проверяем формулу через стоимость пункта
            if data.get('point_value_from_api'):
                print(f"\n      Проверка через стоимость пункта из API:")
                if data["dshort"]:
                    calc_margin = data['point_value_from_api'] * terminal_price * data["dshort"]
                    diff = abs(calc_margin - terminal_margin)
                    diff_pct = (diff / terminal_margin * 100) if terminal_margin > 0 else 0
                    match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1 else "✅" if diff < 10 else "❌"
                    print(f"      {match} point_value * price * dshort = {data['point_value_from_api']:.2f} * {terminal_price:.0f} * {data['dshort']:.6f} = {calc_margin:.2f} ₽")
                    print(f"         Разница: {diff:.2f} ₽ ({diff_pct:.2f}%)")
        
        # Специальный анализ для OJH6 (данные из терминала)
        if ticker_name == "OJH6" and not data["has_known_margin"]:
            print(f"\n   📱 Данные из терминала (из изображения):")
            terminal_point_value = 7719.44
            terminal_margin = 3752.15
            terminal_lot = 100
            terminal_price = 1.835
            
            print(f"      Стоимость пункта цены: {terminal_point_value:,.2f} ₽")
            print(f"      Гарантийное обеспечение: {terminal_margin:,.2f} ₽")
            print(f"      Лотность: {terminal_lot}")
            print(f"      Цена: {terminal_price:.3f} пт.")
            
            # Пробуем найти связь
            print(f"\n   🔍 Анализ связи данных из терминала:")
            if data["dlong"]:
                calc_margin_dlong = terminal_point_value * terminal_price * data["dlong"]
                diff = abs(calc_margin_dlong - terminal_margin)
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1 else "✅" if diff < 10 else "❌"
                print(f"      {match} point_value * price * dlong = {terminal_point_value:.2f} * {terminal_price:.3f} * {data['dlong']:.6f} = {calc_margin_dlong:.2f} ₽")
                print(f"         Разница с терминалом: {diff:.2f} ₽ ({diff/terminal_margin*100:.2f}%)")
            
            if data["dshort"]:
                calc_margin_dshort = terminal_point_value * terminal_price * data["dshort"]
                diff = abs(calc_margin_dshort - terminal_margin)
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1 else "✅" if diff < 10 else "❌"
                print(f"      {match} point_value * price * dshort = {terminal_point_value:.2f} * {terminal_price:.3f} * {data['dshort']:.6f} = {calc_margin_dshort:.2f} ₽")
                print(f"         Разница с терминалом: {diff:.2f} ₽ ({diff/terminal_margin*100:.2f}%)")
            
            # Обратный расчет: point_value из ГО
            if data["dlong"]:
                calc_point_value = terminal_margin / (terminal_price * data["dlong"])
                diff = abs(calc_point_value - terminal_point_value)
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1 else "✅" if diff < 10 else "❌"
                print(f"\n      Обратный расчет point_value из ГО:")
                print(f"      {match} point_value = ГО / (price * dlong) = {terminal_margin:.2f} / ({terminal_price:.3f} * {data['dlong']:.6f}) = {calc_point_value:.4f}")
                print(f"         Терминал point_value: {terminal_point_value:.2f} (разница: {diff:.2f} ₽)")
        
        # Проверяем, есть ли стоимость пункта в словаре
        point_value_from_dict = POINT_VALUE.get(ticker_name, None)
        if point_value_from_dict:
            data["point_value"] = point_value_from_dict
            print(f"   Стоимость пункта (из словаря): {point_value_from_dict:.2f}")
        
        # Вычисляем стоимость пункта из известной маржи (если она известна)
        if data["has_known_margin"] and data["dlong"]:
            point_value_calc_dlong = data["margin"] / (data["price"] * data["dlong"])
            data["point_value_calc_dlong"] = point_value_calc_dlong
            print(f"   Стоимость пункта (вычисленная через dlong): {point_value_calc_dlong:.4f}")
        
        if data["has_known_margin"] and data["dshort"]:
            point_value_calc_dshort = data["margin"] / (data["price"] * data["dshort"])
            data["point_value_calc_dshort"] = point_value_calc_dshort
            print(f"   Стоимость пункта (вычисленная через dshort): {point_value_calc_dshort:.4f}")
        
        print(f"\n   📐 Варианты расчета маржи:")
        best_formula = None
        best_diff = float('inf')
        best_result = None
        
        for formula_name, formula_func, formula_type in formulas:
            try:
                result = formula_func(data)
                if result is not None:
                    if data["has_known_margin"]:
                        # Сравниваем с известной маржой
                        diff = abs(result - data["margin"])
                        diff_pct = (diff / data["margin"] * 100) if data["margin"] > 0 else 0
                        
                        if diff < 0.01:
                            match = "✅✅✅"
                        elif diff < 1.0:
                            match = "✅✅"
                        elif diff < 10.0:
                            match = "✅"
                        else:
                            match = "❌"
                        
                        print(f"      {match} {formula_name:35s} = {result:>12.2f} ₽ | разница: {diff:>8.2f} ₽ ({diff_pct:>6.2f}%)")
                        
                        if diff < best_diff:
                            best_diff = diff
                            best_formula = formula_name
                            best_result = result
                    else:
                        # Просто показываем результат без сравнения
                        print(f"      📊 {formula_name:35s} = {result:>12.2f} ₽")
            except (TypeError, ZeroDivisionError, KeyError):
                pass
        
        # Пробуем с вычисленной стоимостью пункта (только если маржа известна)
        if data["has_known_margin"]:
            print(f"\n   🔍 Расчет через вычисленную стоимость пункта:")
            if data.get("point_value_calc_dlong"):
                calc_margin_dlong = data["point_value_calc_dlong"] * data["price"] * data["dlong"]
                diff = abs(calc_margin_dlong - data["margin"])
                diff_pct = (diff / data["margin"] * 100) if data["margin"] > 0 else 0
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1.0 else "✅"
                print(f"      {match} point_value_calc_dlong * price * dlong = {calc_margin_dlong:>12.2f} ₽ | разница: {diff:>8.2f} ₽ ({diff_pct:>6.2f}%)")
            
            if data.get("point_value_calc_dshort"):
                calc_margin_dshort = data["point_value_calc_dshort"] * data["price"] * data["dshort"]
                diff = abs(calc_margin_dshort - data["margin"])
                diff_pct = (diff / data["margin"] * 100) if data["margin"] > 0 else 0
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1.0 else "✅"
                print(f"      {match} point_value_calc_dshort * price * dshort = {calc_margin_dshort:>12.2f} ₽ | разница: {diff:>8.2f} ₽ ({diff_pct:>6.2f}%)")
        
        if best_formula and data["has_known_margin"]:
            print(f"\n   🎯 ЛУЧШАЯ ФОРМУЛА: {best_formula}")
            print(f"      Результат: {best_result:.2f} ₽ (разница: {best_diff:.2f} ₽)")
        elif not data["has_known_margin"]:
            print(f"\n   💡 Сравните результаты выше с терминалом и укажите правильное значение ГО")
            print(f"   💡 Затем можно будет определить, какая формула работает")
        
        all_results.append({
            "ticker": ticker_name,
            "best_formula": best_formula,
            "best_diff": best_diff,
            "best_result": best_result,
            "real_margin": data["margin"]
        })
    
    # Итоговый вывод
    print(f"\n{'='*80}")
    print(f"📊 ИТОГОВЫЕ РЕЗУЛЬТАТЫ")
    print(f"{'='*80}\n")
    
    for result in all_results:
        if result["best_formula"]:
            print(f"   {result['ticker']:8s}: {result['best_formula']:35s} | "
                  f"результат: {result['best_result']:>10.2f} ₽ | "
                  f"реальная: {result['real_margin']:>10.2f} ₽ | "
                  f"разница: {result['best_diff']:>8.2f} ₽")
    
    # Ищем общую формулу
    print(f"\n{'='*80}")
    print(f"🔍 АНАЛИЗ ОБЩЕЙ ФОРМУЛЫ")
    print(f"{'='*80}\n")
    
    # Собираем все данные для анализа
    analysis_data = []
    for ticker_name, data in known_data.items():
        if data["has_known_margin"] and data["price"] > 0:
            margin_rate = data["margin"] / data["price"]
            
            point_value_dlong = None
            point_value_dshort = None
            if data["dlong"]:
                point_value_dlong = data["margin"] / (data["price"] * data["dlong"])
            if data["dshort"]:
                point_value_dshort = data["margin"] / (data["price"] * data["dshort"])
            
            analysis_data.append({
                "ticker": ticker_name,
                "name": data["name"],
                "price": data["price"],
                "margin": data["margin"],
                "margin_rate": margin_rate,
                "dlong": data["dlong"],
                "dshort": data["dshort"],
                "klong": data["klong"],
                "kshort": data["kshort"],
                "point_value_dlong": point_value_dlong,
                "point_value_dshort": point_value_dshort,
            })
    
    if analysis_data:
        print("📊 СВОДНАЯ ТАБЛИЦА ДАННЫХ:\n")
        print(f"{'Тикер':<8} {'Название':<30} {'Цена':>10} {'ГО':>12} {'ГО/цена':>10} {'dlong':>10} {'dshort':>10} {'point_v(dl)':>12} {'point_v(ds)':>12}")
        print("-" * 120)
        
        for item in analysis_data:
            pv_dl = f"{item['point_value_dlong']:.2f}" if item['point_value_dlong'] else "N/A"
            pv_ds = f"{item['point_value_dshort']:.2f}" if item['point_value_dshort'] else "N/A"
            print(f"{item['ticker']:<8} {item['name'][:28]:<30} {item['price']:>10.2f} {item['margin']:>12.2f} "
                  f"{item['margin_rate']:>10.4f} {item['dlong']:>10.6f} {item['dshort']:>10.6f} "
                  f"{pv_dl:>12} {pv_ds:>12}")
        
        print(f"\n{'='*80}")
        print(f"💡 АНАЛИЗ ЗАКОНОМЕРНОСТЕЙ")
        print(f"{'='*80}\n")
        
        # Анализируем зависимости
        print("1️⃣ Анализ зависимости ГО от цены:")
        for item in analysis_data:
            print(f"   {item['ticker']}: ГО/цена = {item['margin_rate']:.4f} ({item['margin_rate']*100:.2f}%)")
        
        print(f"\n2️⃣ Анализ стоимости пункта:")
        print("   Стоимость пункта через dlong:")
        for item in analysis_data:
            if item['point_value_dlong']:
                print(f"      {item['ticker']}: {item['point_value_dlong']:.4f}")
        
        print("   Стоимость пункта через dshort:")
        for item in analysis_data:
            if item['point_value_dshort']:
                print(f"      {item['ticker']}: {item['point_value_dshort']:.4f}")
        
        print(f"\n3️⃣ Проверка гипотез:")
        
        # Гипотеза 1: ГО = price * dlong (простая формула)
        print("\n   Гипотеза 1: ГО = price * dlong")
        for item in analysis_data:
            if item['dlong']:
                calc = item['price'] * item['dlong']
                diff = abs(calc - item['margin'])
                diff_pct = (diff / item['margin'] * 100) if item['margin'] > 0 else 0
                match = "✅" if diff_pct < 1 else "❌"
                print(f"      {match} {item['ticker']}: {calc:.2f} vs {item['margin']:.2f} (разница: {diff:.2f} ₽, {diff_pct:.2f}%)")
        
        # Гипотеза 2: ГО = price * dshort
        print("\n   Гипотеза 2: ГО = price * dshort")
        for item in analysis_data:
            if item['dshort']:
                calc = item['price'] * item['dshort']
                diff = abs(calc - item['margin'])
                diff_pct = (diff / item['margin'] * 100) if item['margin'] > 0 else 0
                match = "✅" if diff_pct < 1 else "❌"
                print(f"      {match} {item['ticker']}: {calc:.2f} vs {item['margin']:.2f} (разница: {diff:.2f} ₽, {diff_pct:.2f}%)")
        
        # Гипотеза 3: ГО = point_value * price * dlong (где point_value вычисляется)
        print("\n   Гипотеза 3: ГО = point_value * price * dlong (где point_value = ГО_известный / (price * dlong))")
        print("   Это точная формула, так как point_value вычисляется из известного ГО")
        for item in analysis_data:
            if item['point_value_dlong']:
                calc = item['point_value_dlong'] * item['price'] * item['dlong']
                diff = abs(calc - item['margin'])
                match = "✅✅✅" if diff < 0.01 else "✅✅" if diff < 1 else "✅"
                print(f"      {match} {item['ticker']}: {calc:.2f} vs {item['margin']:.2f} (разница: {diff:.2f} ₽)")
        
        print(f"\n{'='*80}")
        print(f"📝 ВЫВОДЫ")
        print(f"{'='*80}\n")
        
        print("Универсальная формула расчета ГО:")
        print("  ГО = point_value * price * dlong (для LONG)")
        print("  ГО = point_value * price * dshort (для SHORT)")
        print("\nПроблема: point_value различается для каждого инструмента!")
        print("  - NCM6: point_value ≈ 0.737")
        print("  - ANH6: point_value ≈ 6.73")
        print("  - W4H6: point_value ≈ 1.008")
        print("  - BMJ6: point_value ≈ 77.5")
        print("\n💡 Вывод: point_value зависит от типа инструмента и базового актива.")
        print("   Для автоматического расчета нужно:")
        print("   1. Либо знать point_value для каждого инструмента (из терминала)")
        print("   2. Либо использовать значение ГО напрямую из словаря MARGIN_PER_LOT")
        print("   3. Либо вычислять point_value из похожих инструментов (автоматический расчет)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Поиск формулы расчета ГО для инструментов',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Анализ конкретного инструмента
  python find_margin_formula.py --ticker ANH6
  
  # Анализ всех инструментов с известной маржей
  python find_margin_formula.py
        """
    )
    parser.add_argument('--ticker', type=str, help='Тикер инструмента для анализа (например, ANH6, NCM6)')
    parser.add_argument('--margin', type=float, help='Значение ГО из терминала для сравнения (например, --margin 2746.1)')
    
    args = parser.parse_args()
    
    analyze_margin_formula(ticker=args.ticker, known_margin=args.margin)
