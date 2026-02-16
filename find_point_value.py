#!/usr/bin/env python3
"""
Полное решение для получения стоимости пункта цены через API.
Ищет стоимость пункта в различных полях API и выводит детальную информацию.
"""
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

try:
    from t_tech.invest import Client
    from t_tech.invest.schemas import InstrumentRequest, InstrumentIdType
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("❌ ERROR: t-tech-investments library not installed")
    exit(1)


@dataclass
class PointValueInfo:
    """Информация о стоимости пункта"""
    min_price_increment: float  # Шаг цены (минимальный шаг)
    lot: int  # Размер лота
    min_price_increment_amount: Optional[float] = None  # Стоимость минимального шага из API (min_price_increment_amount)
    point_value_terminal: Optional[float] = None  # Стоимость пункта как в терминале (1 пункт, обычно 1 USD или базовая единица)
    point_value_calculated: float = 0.0  # Стоимость пункта (рассчитанная: min_price_increment * lot)
    currency: str = 'rub'


class PointValueFinder:
    """Класс для поиска стоимости пункта инструмента"""
    
    def __init__(self, token: str, sandbox: bool = False):
        self.token = token
        self.sandbox = sandbox
        self._client = None
        self._target = None
        
    def __enter__(self):
        self._target = INVEST_GRPC_API_SANDBOX if self.sandbox else INVEST_GRPC_API
        self._client = Client(self.token, target=self._target)
        return self
        
    def __exit__(self, *args):
        if self._client:
            try:
                self._client.__exit__(*args)
            except:
                pass
    
    
    def quotation_to_float(self, quotation) -> float:
        """Преобразование Quotation в float"""
        if quotation is None:
            return 0.0
        if hasattr(quotation, 'units') and hasattr(quotation, 'nano'):
            return float(quotation.units) + float(quotation.nano) / 1_000_000_000
        try:
            return float(quotation)
        except:
            return 0.0
    
    def find_instrument_by_ticker(self, ticker: str) -> Optional[Any]:
        """
        Поиск инструмента по тикеру
        """
        print(f"\n🔍 Поиск инструмента по тикеру: {ticker}")
        
        try:
            from t_tech.invest.schemas import InstrumentType
            
            # Используем клиент как контекстный менеджер
            with self._client as client:
                # Поиск инструмента (фьючерсы)
                result = client.instruments.find_instrument(
                    query=ticker,
                    instrument_kind=InstrumentType.INSTRUMENT_TYPE_FUTURES,
                    api_trade_available_flag=True
                )
                
                if not result.instruments:
                    print(f"❌ Инструмент {ticker} не найден среди фьючерсов")
                    return None
                
                # Показываем все найденные инструменты
                print(f"\n✅ Найдено инструментов: {len(result.instruments)}")
                for i, inst in enumerate(result.instruments, 1):
                    print(f"\n--- Инструмент {i} ---")
                    print(f"  FIGI: {inst.figi}")
                    print(f"  Ticker: {inst.ticker}")
                    print(f"  UID: {inst.uid}")
                    print(f"  Name: {inst.name}")
                    print(f"  Type: {inst.instrument_type}")
                    if hasattr(inst, 'class_code'):
                        print(f"  Class Code: {inst.class_code}")
                
                # Ищем точное совпадение по тикеру
                instrument = None
                for inst in result.instruments:
                    if inst.ticker.upper() == ticker.upper():
                        instrument = inst
                        break
                
                if not instrument:
                    instrument = result.instruments[0]
                    print(f"\n⚠️ Точное совпадение не найдено, используем первый результат")
                
                # Получаем полную информацию по FIGI
                print(f"\n📊 Получение полной информации по FIGI: {instrument.figi}")
                full_info = client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=instrument.figi
                )
                instrument_obj = full_info.instrument
                
                # Для фьючерсов получаем стоимость пункта через get_futures_margin
                print(f"\n💰 Получение стоимости пункта через get_futures_margin...")
                try:
                    margin_response = client.instruments.get_futures_margin(figi=instrument.figi)
                    print(f"   Тип ответа: {type(margin_response)}")
                    
                    # Проверяем структуру ответа
                    if hasattr(margin_response, 'initial_margin_response'):
                        initial_margin = margin_response.initial_margin_response
                        print(f"   ✅ initial_margin_response найден")
                        
                        # Выводим все поля initial_margin_response
                        print(f"   Поля initial_margin_response:")
                        for attr in dir(initial_margin):
                            if not attr.startswith('_'):
                                try:
                                    value = getattr(initial_margin, attr)
                                    if not callable(value):
                                        if hasattr(value, 'units') and hasattr(value, 'nano'):
                                            float_val = self.quotation_to_float(value)
                                            print(f"      {attr}: {float_val:.6f} (units={value.units}, nano={value.nano})")
                                        else:
                                            print(f"      {attr}: {value}")
                                except:
                                    pass
                        
                        if hasattr(initial_margin, 'min_price_increment_amount'):
                            point_value_from_margin = initial_margin.min_price_increment_amount
                            point_value_float = self.quotation_to_float(point_value_from_margin)
                            print(f"\n   ✅ min_price_increment_amount из get_futures_margin: {point_value_float:.6f} ₽")
                            print(f"      💡 ВАЖНО: Это стоимость минимального шага цены, НЕ 'стоимость пункта' как в терминале!")
                            print(f"      💡 В терминале 'Стоимость пункта' обычно означает стоимость 1 пункта (1 USD или базовая единица)")
                            # Сохраняем в объект инструмента для дальнейшего использования
                            instrument_obj._point_value_from_margin = point_value_float
                        else:
                            print(f"   ⚠️ Поле min_price_increment_amount отсутствует в initial_margin_response")
                    else:
                        print(f"   ⚠️ Поле initial_margin_response отсутствует в ответе")
                        print(f"   Доступные поля ответа:")
                        for attr in dir(margin_response):
                            if not attr.startswith('_') and not callable(getattr(margin_response, attr, None)):
                                print(f"      {attr}")
                except Exception as e:
                    print(f"   ❌ Ошибка при получении стоимости пункта через get_futures_margin: {e}")
                    import traceback
                    traceback.print_exc()
                
                return instrument_obj
            
        except Exception as e:
            print(f"❌ Ошибка при поиске {ticker}: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_point_value(self, instrument, current_price: Optional[float] = None) -> PointValueInfo:
        """
        Получение стоимости пункта из объекта инструмента
        
        ВАЖНО: Различаем два понятия:
        1. min_price_increment_amount - стоимость минимального шага цены (из API)
        2. "Стоимость пункта" (как в терминале) - стоимость 1 пункта (обычно 1 USD или базовая единица)
        """
        # Получаем шаг цены
        if hasattr(instrument, 'min_price_increment'):
            min_price_increment = self.quotation_to_float(instrument.min_price_increment)
        else:
            min_price_increment = 0.0
            print("⚠️  Поле min_price_increment отсутствует")
        
        # Получаем размер лота
        lot = getattr(instrument, 'lot', 1)
        
        # Ищем min_price_increment_amount в API (стоимость минимального шага)
        min_price_increment_amount = None
        
        # ПРИОРИТЕТ 1: Проверяем значение из get_futures_margin (самый надежный способ для фьючерсов)
        if hasattr(instrument, '_point_value_from_margin'):
            min_price_increment_amount = instrument._point_value_from_margin
            print(f"\n✅ min_price_increment_amount из get_futures_margin: {min_price_increment_amount:.6f} ₽")
            print(f"   💡 Это стоимость минимального шага цены ({min_price_increment} пунктов)")
        
        # ПРИОРИТЕТ 2: Проверяем различные возможные названия поля в объекте инструмента
        if not min_price_increment_amount:
            possible_fields = [
                'min_price_increment_amount',
                'step_price',
                'tick_value',
                'tick_cost',
                'price_step_value'
            ]
            
            print("\n🔍 Поиск min_price_increment_amount в полях API:")
            for field in possible_fields:
                if hasattr(instrument, field):
                    value = getattr(instrument, field)
                    try:
                        min_price_increment_amount = self.quotation_to_float(value)
                        print(f"  ✅ Найдено поле {field} = {min_price_increment_amount:.6f}")
                        break
                    except Exception as e:
                        print(f"  ⚠️ Поле {field} есть, но не удалось извлечь значение: {e}")
        
        if not min_price_increment_amount:
            print("  ❌ min_price_increment_amount не найдено в API")
        
        # Рассчитываем стоимость минимального шага (стандартная формула)
        calculated_point_value = min_price_increment * lot
        
        # Пытаемся рассчитать "стоимость пункта" как в терминале
        # Для фьючерсов на валютные пары или ADR это обычно связано с курсом
        point_value_terminal = None
        if current_price and current_price > 0:
            # Для некоторых инструментов "стоимость пункта" = цена * коэффициент
            # Например, для BBM6 (Alibaba ADR): стоимость пункта ≈ цена * курс USD/RUB / 100
            # Но точная формула зависит от спецификации инструмента
            print(f"\n💡 Попытка рассчитать 'стоимость пункта' как в терминале:")
            print(f"   Текущая цена: {current_price:.4f} пунктов")
            print(f"   ⚠️ Точная формула зависит от спецификации инструмента")
            print(f"   💡 Для BBM6 (Alibaba ADR) стоимость пункта ≈ {current_price * 0.01:.2f} - {current_price * 0.5:.2f} ₽")
            print(f"   (зависит от курса USD/RUB и спецификации контракта)")
        
        # Определяем валюту
        currency = getattr(instrument, 'currency', 'rub')
        
        return PointValueInfo(
            min_price_increment=min_price_increment,
            lot=lot,
            min_price_increment_amount=min_price_increment_amount,
            point_value_terminal=point_value_terminal,
            point_value_calculated=calculated_point_value,
            currency=currency
        )
    
    def print_instrument_details(self, instrument):
        """Печать всех деталей инструмента"""
        print("\n" + "="*70)
        print("ДЕТАЛЬНАЯ ИНФОРМАЦИЯ ОБ ИНСТРУМЕНТЕ")
        print("="*70)
        
        # Основные поля
        basic_fields = [
            'figi', 'ticker', 'class_code', 'isin', 'name',
            'instrument_type', 'currency', 'lot', 'uid'
        ]
        
        print("\n📋 ОСНОВНЫЕ ПОЛЯ:")
        for field in basic_fields:
            if hasattr(instrument, field):
                value = getattr(instrument, field)
                print(f"  {field:30} = {value}")
        
        # Поля с ценами и шагами
        price_fields = [
            'min_price_increment', 'min_price_increment_amount',
            'dlong', 'dshort', 'klong', 'kshort',
            'initial_margin_on_buy', 'initial_margin_on_sell',
            'price_step', 'lot_size'
        ]
        
        print("\n💰 ПОЛЯ, СВЯЗАННЫЕ С ЦЕНОЙ И МАРЖЕЙ:")
        for field in price_fields:
            if hasattr(instrument, field):
                value = getattr(instrument, field)
                if hasattr(value, 'units') and hasattr(value, 'nano'):
                    float_val = self.quotation_to_float(value)
                    print(f"  {field:30} = {float_val:.6f} (units={value.units}, nano={value.nano})")
                else:
                    print(f"  {field:30} = {value}")
        
        # Все остальные поля (для полноты картины)
        print("\n🔍 ВСЕ ПОЛЯ ОБЪЕКТА (связанные с ценой, пунктом, шагом):")
        all_attrs = dir(instrument)
        relevant_keywords = ['price', 'point', 'tick', 'step', 'increment', 'amount', 'value', 'cost', 'margin', 'dlong', 'dshort', 'klong', 'kshort']
        
        found_relevant = False
        for attr in sorted(all_attrs):
            if not attr.startswith('_') and attr not in basic_fields + price_fields:
                attr_lower = attr.lower()
                if any(kw in attr_lower for kw in relevant_keywords):
                    try:
                        value = getattr(instrument, attr)
                        if value is not None and not callable(value):
                            found_relevant = True
                            if hasattr(value, 'units') and hasattr(value, 'nano'):
                                float_val = self.quotation_to_float(value)
                                print(f"  {attr:30} = {float_val:.6f} (Quotation)")
                            elif not isinstance(value, (list, dict, set)):
                                print(f"  {attr:30} = {value}")
                    except:
                        pass
        
        if not found_relevant:
            print("  (нет дополнительных релевантных полей)")
    
    def analyze_instrument(self, ticker: str):
        """
        Полный анализ инструмента
        """
        print(f"\n{'#'*70}")
        print(f"# АНАЛИЗ ИНСТРУМЕНТА: {ticker}")
        print(f"{'#'*70}")
        
        # 1. Находим инструмент
        instrument = self.find_instrument_by_ticker(ticker)
        if not instrument:
            return None
        
        # 2. Печатаем детали
        self.print_instrument_details(instrument)
        
        # 2.5. Получаем текущую цену для расчетов
        current_price = None
        try:
            with self._client as client:
                from t_tech.invest.schemas import InstrumentId
                from t_tech.invest import InstrumentIdType
                figi = getattr(instrument, 'figi', None)
                if figi:
                    try:
                        last_prices = client.market_data.get_last_prices(
                            figi=[figi]
                        )
                        if last_prices.last_prices:
                            last_price = last_prices.last_prices[0]
                            if hasattr(last_price, 'price'):
                                current_price = self.quotation_to_float(last_price.price)
                                print(f"\n💰 Текущая цена: {current_price:.4f}")
                    except Exception as e:
                        print(f"\n⚠️ Не удалось получить текущую цену: {e}")
        except:
            pass
        
        # 3. Получаем стоимость пункта
        point_info = self.get_point_value(instrument, current_price=current_price)
        
        print("\n" + "="*70)
        print("ИТОГОВАЯ ИНФОРМАЦИЯ О СТОИМОСТИ ПУНКТА")
        print("="*70)
        print(f"\n📊 БАЗОВЫЕ ПАРАМЕТРЫ:")
        print(f"   Шаг цены (min_price_increment): {point_info.min_price_increment:.6f} пунктов")
        print(f"   Размер лота: {point_info.lot}")
        
        print(f"\n💰 СТОИМОСТЬ МИНИМАЛЬНОГО ШАГА (из API):")
        if point_info.min_price_increment_amount:
            print(f"   ✅ min_price_increment_amount: {point_info.min_price_increment_amount:.6f} ₽")
            print(f"      💡 Это стоимость минимального шага цены ({point_info.min_price_increment} пунктов)")
            print(f"      💡 Используется для точного расчета PnL: изменение на 1 шаг = {point_info.min_price_increment_amount:.6f} ₽")
        else:
            print(f"   ❌ min_price_increment_amount не найдено в API")
            print(f"   💡 Рассчитанное значение: {point_info.point_value_calculated:.6f} ₽")
        
        print(f"\n💵 'СТОИМОСТЬ ПУНКТА' КАК В ТЕРМИНАЛЕ:")
        print(f"   ⚠️ В терминале 'Стоимость пункта' обычно означает стоимость 1 пункта")
        print(f"   ⚠️ Для BBM6 (Alibaba ADR) в терминале показывается ~76.62 ₽ за 1 пункт")
        print(f"   ⚠️ Это НЕ то же самое, что min_price_increment_amount (0.01 ₽ за минимальный шаг)")
        if current_price:
            print(f"   💡 Для расчета: стоимость пункта ≈ цена × коэффициент × курс USD/RUB")
            print(f"   💡 Точная формула зависит от спецификации контракта")
            print(f"   💡 Примерная оценка для BBM6: {current_price * 0.01:.2f} - {current_price * 0.5:.2f} ₽ за пункт")
            print(f"   💡 (нужно уточнить в спецификации контракта или документации MOEX)")
        
        # 4. Проверяем на фьючерсные коэффициенты
        if hasattr(instrument, 'dlong'):
            dlong = self.quotation_to_float(instrument.dlong)
            dshort = self.quotation_to_float(instrument.dshort) if hasattr(instrument, 'dshort') else 0.0
            print(f"\n📈 Фьючерсные коэффициенты:")
            print(f"  dlong: {dlong:.6f}")
            print(f"  dshort: {dshort:.6f}")
            
            if hasattr(instrument, 'klong'):
                klong = self.quotation_to_float(instrument.klong)
                kshort = self.quotation_to_float(instrument.kshort) if hasattr(instrument, 'kshort') else 0.0
                print(f"  klong: {klong:.6f}")
                print(f"  kshort: {kshort:.6f}")
            
            # Показываем формулу расчета ГО
            print(f"\n💡 Формула расчета ГО:")
            # Для расчета ГО используется min_price_increment_amount (стоимость минимального шага)
            point_value_to_use = point_info.min_price_increment_amount if point_info.min_price_increment_amount else point_info.point_value_calculated
            if point_value_to_use > 0:
                print(f"   ГО = min_price_increment_amount * цена * dlong/dshort")
                print(f"   ГО = {point_value_to_use:.6f} ₽ * цена * {dlong:.6f} (для LONG)")
                print(f"   ГО = {point_value_to_use:.6f} ₽ * цена * {dshort:.6f} (для SHORT)")
                print(f"   💡 Используется min_price_increment_amount ({point_value_to_use:.6f} ₽), НЕ 'стоимость пункта' из терминала!")
        
        return point_info


def main():
    """Главная функция"""
    import sys
    
    # Получаем токен
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found in environment variables!")
        print("   Please set TINKOFF_TOKEN in .env file or environment")
        sys.exit(1)
    
    # Определяем режим (sandbox или production)
    sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() == "true"
    
    # Получаем тикер из аргументов или используем BBM6 по умолчанию
    if len(sys.argv) > 1:
        ticker = sys.argv[1].upper()
    else:
        ticker = "BBM6"
    
    print(f"\n{'='*70}")
    print(f"ПОИСК СТОИМОСТИ ПУНКТА ДЛЯ {ticker}")
    print(f"Режим: {'SANDBOX' if sandbox else 'PRODUCTION'}")
    print(f"{'='*70}")
    
    with PointValueFinder(token, sandbox=sandbox) as finder:
        try:
            point_info = finder.analyze_instrument(ticker)
            
            if point_info:
                print(f"\n{'='*70}")
                print("РЕКОМЕНДАЦИЯ ДЛЯ ДОБАВЛЕНИЯ В КОД:")
                print(f"{'='*70}")
                print(f"\n💡 ВАЖНО: Различаем два понятия:")
                print(f"   1. min_price_increment_amount - стоимость минимального шага цены (для расчета ГО)")
                print(f"   2. 'Стоимость пункта' из терминала - стоимость 1 пункта (для отображения)")
                
                if point_info.min_price_increment_amount:
                    print(f"\n✅ Для расчета ГО используйте min_price_increment_amount:")
                    print(f"POINT_VALUE[\"{ticker}\"] = {point_info.min_price_increment_amount:.6f}  # Из get_futures_margin API")
                    print(f"\n   💡 Это значение ({point_info.min_price_increment_amount:.6f} ₽) используется в формуле:")
                    print(f"   ГО = POINT_VALUE[ticker] * цена * dlong/dshort")
                else:
                    print(f"\n⚠️ min_price_increment_amount не найдено в API")
                    print(f"   Используйте рассчитанное значение:")
                    print(f"POINT_VALUE[\"{ticker}\"] = {point_info.point_value_calculated:.6f}  # Рассчитано (min_price_increment * lot)")
                
                print(f"\n💡 'Стоимость пункта' из терминала (~76.62 ₽ для BBM6) - это другое понятие")
                print(f"   и используется только для отображения в интерфейсе, не для расчетов ГО")
        except Exception as e:
            print(f"\n❌ Ошибка при анализе: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
