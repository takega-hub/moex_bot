"""
Расчет гарантийного обеспечения (ГО) для фьючерсов MOEX.

ГО рассчитывается по формуле: ГО = point_value × price × dlong/dshort
где point_value = min_price_increment из API.

ВАЖНО: Словарь MARGIN_PER_LOT больше не используется в расчетах.
Все значения рассчитываются динамически из данных API.
"""
import logging
import asyncio
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Справочник гарантийного обеспечения за лот
# Используется как приоритетный источник ГО (проверяется первым)
# Значения обновляются автоматически из API при старте бота
MARGIN_PER_LOT: Dict[str, float] = {
}

# Коэффициенты маржи в процентах от стоимости позиции (fallback)
# Используются, если формула через point_value не работает
MARGIN_RATE_PCT: Dict[str, float] = {
}


# Справочник стоимости пункта цены для инструментов (из терминала)
# Используется для расчета маржи по формуле: ГО = стоимость_пункта * цена * dlong/dshort
# ВАЖНО: Формула работает не для всех инструментов, требует валидации!
# ВАЖНО: Для некоторых инструментов min_price_increment из API НЕ равен реальной стоимости пункта!
# Например, для GAZPF: min_price_increment = 0.01, но реальная стоимость пункта = 100 ₽
POINT_VALUE: Dict[str, float] = {}

def auto_calculate_point_value(
    ticker: str,
    known_margin: float,
    current_price: float,
    dlong: Optional[float] = None,
    dshort: Optional[float] = None
) -> Optional[float]:
    """
    Автоматически вычислить стоимость пункта из известной маржи.
    
    Формула обратного расчета:
    стоимость_пункта = ГО / (цена * dlong/dshort)
    
    Args:
        ticker: Тикер инструмента
        known_margin: Известная маржа из терминала или словаря
        current_price: Текущая цена
        dlong: Коэффициент dlong из API
        dshort: Коэффициент dshort из API
    
    Returns:
        Стоимость пункта или None
    """
    if current_price <= 0 or known_margin <= 0:
        return None
    
    # Пробуем через dshort (обычно более точный для SHORT)
    if dshort and dshort > 0:
        point_value = known_margin / (current_price * dshort)
        # Проверяем разумность (обычно от 0.1 до 100000)
        if 0.1 < point_value < 100000:
            logger.debug(f"[{ticker}] Auto-calculated point value from margin: {point_value:.2f} (via dshort)")
            return point_value
    
    # Пробуем через dlong
    if dlong and dlong > 0:
        point_value = known_margin / (current_price * dlong)
        if 0.1 < point_value < 100000:
            logger.debug(f"[{ticker}] Auto-calculated point value from margin: {point_value:.2f} (via dlong)")
            return point_value
    
    return None


def get_margin_for_position(
    ticker: str, 
    quantity: float, 
    entry_price: float, 
    lot_size: float = 1.0,
    dlong: Optional[float] = None,
    dshort: Optional[float] = None,
    is_long: bool = True,
    point_value: Optional[float] = None
) -> float:
    """
    Получить гарантийное обеспечение для позиции.
    
    Приоритет расчета:
    1. Справочник MARGIN_PER_LOT (если есть значение) - ВЫСШИЙ ПРИОРИТЕТ!
    2. Расчет через стоимость пункта: ГО = point_value * цена * dlong/dshort (если point_value передан)
    3. Расчет через POINT_VALUE словарь (если есть)
    4. Процент от стоимости позиции (fallback)
    
    Args:
        ticker: Тикер инструмента
        quantity: Количество лотов
        entry_price: Цена входа
        lot_size: Размер лота
        dlong: Коэффициент dlong из API (опционально)
        dshort: Коэффициент dshort из API (опционально)
        is_long: True для LONG позиции, False для SHORT
        point_value: Стоимость пункта (min_price_increment из API, опционально)
        
    Returns:
        Гарантийное обеспечение в рублях
    """
    ticker_upper = ticker.upper()
    
    # 1. Сначала проверяем справочник MARGIN_PER_LOT (ВЫСШИЙ ПРИОРИТЕТ!)
    if ticker_upper in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker_upper] > 0:
        margin_per_lot = MARGIN_PER_LOT[ticker_upper]
        return margin_per_lot * quantity
    
    # 2. Пробуем расчет через переданную стоимость пункта
    # ВАЖНО: Если point_value из API = 0 или None, используем словарь POINT_VALUE
    if point_value and point_value > 0 and entry_price > 0:
        if is_long and dlong and dlong > 0:
            margin_per_lot = point_value * entry_price * dlong
            return margin_per_lot * quantity
        elif not is_long and dshort and dshort > 0:
            margin_per_lot = point_value * entry_price * dshort
            return margin_per_lot * quantity
    
    # 2. Пробуем расчет через стоимость пункта цены из словаря POINT_VALUE
    # (используется, если point_value из API = 0, None или не передан)
    if ticker_upper in POINT_VALUE and entry_price > 0:
        point_value = POINT_VALUE[ticker_upper]
        
        # Используем dlong для LONG, dshort для SHORT
        if is_long and dlong is not None and dlong > 0:
            margin_per_lot = point_value * entry_price * dlong
            return margin_per_lot * quantity
        elif not is_long and dshort is not None and dshort > 0:
            margin_per_lot = point_value * entry_price * dshort
            return margin_per_lot * quantity
    
    # 3. Fallback: используем процент от стоимости позиции
    if ticker_upper in MARGIN_RATE_PCT:
        margin_rate = MARGIN_RATE_PCT[ticker_upper] / 100.0
    else:
        margin_rate = 0.12  # 12% по умолчанию
    
    position_value = entry_price * quantity * lot_size
    return position_value * margin_rate


def update_margin_per_lot(ticker: str, margin_per_lot: float):
    """
    Обновить гарантийное обеспечение за лот для инструмента.
    
    ВАЖНО: Эта функция больше не используется в расчетах.
    Все значения рассчитываются динамически из API.
    Оставлена для совместимости.
    
    Args:
        ticker: Тикер инструмента
        margin_per_lot: Гарантийное обеспечение за лот в рублях
    """
    ticker_upper = ticker.upper()
    MARGIN_PER_LOT[ticker_upper] = margin_per_lot


def calculate_max_lots(
    balance: float,
    current_price: float,
    point_value: Optional[float] = None,
    dlong: Optional[float] = None,
    dshort: Optional[float] = None,
    is_long: bool = True,
    margin_per_lot: Optional[float] = None,
    safety_buffer: float = 0.9  # Используем 90% баланса для безопасности
) -> int:
    """
    Рассчитать максимальное количество лотов, которое можно купить на текущий баланс.
    
    Формула: max_lots = (balance * safety_buffer) / margin_per_lot
    
    где margin_per_lot рассчитывается как:
    - Если известна margin_per_lot напрямую - используем её
    - Иначе: margin_per_lot = point_value * current_price * dlong/dshort
    
    Args:
        balance: Текущий баланс в рублях
        current_price: Текущая цена инструмента
        point_value: Стоимость пункта (min_price_increment из API)
        dlong: Коэффициент dlong из API
        dshort: Коэффициент dshort из API
        is_long: True для LONG позиции, False для SHORT
        margin_per_lot: Прямое значение ГО за лот (если известно)
        safety_buffer: Коэффициент безопасности (0.9 = использовать 90% баланса)
    
    Returns:
        Максимальное количество лотов (целое число, минимум 0)
    """
    if balance <= 0:
        return 0
    
    # Если известна маржа за лот напрямую - используем её
    if margin_per_lot and margin_per_lot > 0:
        available_balance = balance * safety_buffer
        max_lots = int(available_balance / margin_per_lot)
        return max(0, max_lots)
    
    # Иначе рассчитываем через формулу: ГО = point_value * price * dlong/dshort
    if point_value and point_value > 0 and current_price > 0:
        if is_long and dlong and dlong > 0:
            margin_per_lot = point_value * current_price * dlong
        elif not is_long and dshort and dshort > 0:
            margin_per_lot = point_value * current_price * dshort
        else:
            # Если нет нужного коэффициента, возвращаем 0
            return 0
        
        if margin_per_lot > 0:
            available_balance = balance * safety_buffer
            max_lots = int(available_balance / margin_per_lot)
            return max(0, max_lots)
    
    # Если не хватает данных для расчета - возвращаем 0
    return 0


def get_margin_per_lot_from_api_data(
    ticker: str,
    current_price: float,
    point_value: Optional[float] = None,
    min_price_increment_amount: Optional[float] = None,
    dlong: Optional[float] = None,
    dshort: Optional[float] = None,
    is_long: bool = True
) -> Optional[float]:
    """
    Получить ГО за один лот из данных API.
    
    Приоритет:
    1. Справочник MARGIN_PER_LOT (если есть значение)
    2. Формула: point_value * current_price * dlong/dshort
       - ВАЖНО: point_value должен быть min_price_increment_amount (стоимость шага цены)!
       - Если min_price_increment_amount из API доступен, используем его
       - Если point_value из API = 0 или None, используем словарь POINT_VALUE
    
    Args:
        ticker: Тикер инструмента
        current_price: Текущая цена
        point_value: Стоимость пункта (min_price_increment из API, может быть 0 или неправильным!)
        min_price_increment_amount: Стоимость шага цены из API (РЕАЛЬНАЯ стоимость пункта!)
        dlong: Коэффициент dlong из API
        dshort: Коэффициент dshort из API
        is_long: True для LONG, False для SHORT
    
    Returns:
        ГО за один лот в рублях или None (если недостаточно данных)
    """
    ticker_upper = ticker.upper()
    
    # 1. Сначала проверяем справочник MARGIN_PER_LOT (приоритет!)
    if ticker_upper in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker_upper] > 0:
        return MARGIN_PER_LOT[ticker_upper]
    
    # 2. ВАЖНО: min_price_increment_amount - это реальная стоимость пункта из API!
    # Используем его в первую очередь, если доступен
    if min_price_increment_amount and min_price_increment_amount > 0:
        point_value = min_price_increment_amount
        logger.debug(f"[{ticker}] Используем min_price_increment_amount из API: {point_value:.2f} ₽ (реальная стоимость пункта)")
    # 3. Если point_value из API = 0 или None, используем словарь POINT_VALUE
    elif not point_value or point_value == 0:
        if ticker_upper in POINT_VALUE and POINT_VALUE[ticker_upper] > 0:
            point_value = POINT_VALUE[ticker_upper]
            logger.debug(f"[{ticker}] Используем стоимость пункта из словаря POINT_VALUE: {point_value:.2f} ₽ (min_price_increment из API был 0 или неправильным)")
    
    # 4. Рассчитываем через формулу, если есть все необходимые данные
    if point_value and point_value > 0 and current_price > 0:
        # ВАЖНО: Для некоторых инструментов (например, NRG6) правильная формула может использовать dlong вместо dshort
        # Проверяем, какая формула ближе к известному значению из словаря (если есть)
        if ticker_upper in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker_upper] > 0:
            known_margin = MARGIN_PER_LOT[ticker_upper]
            margin_long = point_value * current_price * dlong if (dlong and dlong > 0) else 0
            margin_short = point_value * current_price * dshort if (dshort and dshort > 0) else 0
            
            # Выбираем формулу, которая дает более точный результат
            if margin_long > 0 and margin_short > 0:
                diff_long = abs(margin_long - known_margin)
                diff_short = abs(margin_short - known_margin)
                if diff_long < diff_short:
                    logger.debug(f"[{ticker}] Используем dlong (точнее: {diff_long:.2f} vs {diff_short:.2f})")
                    return margin_long
                else:
                    logger.debug(f"[{ticker}] Используем dshort (точнее: {diff_short:.2f} vs {diff_long:.2f})")
                    return margin_short
            elif margin_long > 0:
                return margin_long
            elif margin_short > 0:
                return margin_short
        else:
            # Если нет известного значения, используем стандартную логику
            if is_long and dlong and dlong > 0:
                return point_value * current_price * dlong
            elif not is_long and dshort and dshort > 0:
                return point_value * current_price * dshort
    
    return None


async def update_margins_from_api(
    tinkoff_client,
    instruments: list,
    storage=None
) -> Dict[str, float]:
    """
    Обновить словарь MARGIN_PER_LOT из API для всех активных инструментов при старте бота.
    
    Args:
        tinkoff_client: TinkoffClient instance
        instruments: Список тикеров инструментов
        storage: DataStorage instance (опционально, для получения текущей цены)
    
    Returns:
        Словарь с обновленными значениями ГО {ticker: margin_per_lot}
    """
    updated_margins = {}
    
    for ticker in instruments:
        try:
            # Получаем FIGI для тикера
            instrument_info_storage = None
            if storage:
                instrument_info_storage = storage.get_instrument_by_ticker(ticker)
            
            if not instrument_info_storage:
                logger.warning(f"[update_margins_from_api] Instrument {ticker} not found in storage")
                continue
            
            figi = instrument_info_storage["figi"]
            
            # Получаем текущую цену
            current_price = 0.0
            if storage:
                try:
                    df = storage.get_candles(figi=figi, interval="15min", limit=1)
                    if not df.empty:
                        current_price = float(df.iloc[-1]["close"])
                except:
                    pass
            
            # Если цена не получена, используем примерную
            if current_price <= 0:
                price_estimates = {
                    "NGG6": 3.0,
                    "PTH6": 2049.7,
                    "NRG6": 3.0,
                    "SVH6": 78.0,
                    "S1H6": 77.0,
                    "VBH6": 8500.0,
                    "SRH6": 31000.0,
                    "GLDRUBF": 12200.0,
                    "RLH6": 100.0,
                }
                current_price = price_estimates.get(ticker.upper(), 100.0)
            
            # Получаем информацию об инструменте из API
            inst_info = await asyncio.to_thread(tinkoff_client.get_instrument_info, figi)
            if not inst_info:
                logger.warning(f"[update_margins_from_api] Could not get instrument info for {ticker}")
                continue
            
            # Извлекаем данные
            api_dlong = inst_info.get('dlong')
            api_dshort = inst_info.get('dshort')
            min_price_increment = inst_info.get('min_price_increment')
            lot_size = inst_info.get('lot', 1.0)
            
            # ВАЖНО: Если min_price_increment из API = 0 или None, используем словарь POINT_VALUE
            if not min_price_increment or min_price_increment == 0:
                if ticker.upper() in POINT_VALUE and POINT_VALUE[ticker.upper()] > 0:
                    min_price_increment = POINT_VALUE[ticker.upper()]
                    logger.debug(f"[update_margins_from_api] {ticker}: Используем стоимость пункта из словаря POINT_VALUE: {min_price_increment:.2f} ₽ (min_price_increment из API был 0 или неправильным)")
            
            # Рассчитываем ГО используя правильную формулу
            margin_per_lot = None
            
            # Сначала пробуем через min_price_increment (из API или словаря)
            if min_price_increment and min_price_increment > 0 and current_price > 0:
                # Пробуем для LONG и SHORT, берем максимальную
                margin_long = get_margin_per_lot_from_api_data(
                    ticker=ticker,
                    current_price=current_price,
                    point_value=min_price_increment,
                    dlong=api_dlong,
                    dshort=api_dshort,
                    is_long=True
                )
                margin_short = get_margin_per_lot_from_api_data(
                    ticker=ticker,
                    current_price=current_price,
                    point_value=min_price_increment,
                    dlong=api_dlong,
                    dshort=api_dshort,
                    is_long=False
                )
                
                if margin_long or margin_short:
                    margin_per_lot = max(margin_long or 0, margin_short or 0) if (margin_long and margin_short) else (margin_long or margin_short or 0)
            
            # Если не получилось, используем стандартную функцию
            if not margin_per_lot or margin_per_lot <= 0:
                margin_long = get_margin_for_position(
                    ticker=ticker,
                    quantity=1.0,
                    entry_price=current_price,
                    lot_size=lot_size,
                    dlong=api_dlong,
                    dshort=api_dshort,
                    is_long=True
                )
                
                margin_short = get_margin_for_position(
                    ticker=ticker,
                    quantity=1.0,
                    entry_price=current_price,
                    lot_size=lot_size,
                    dlong=api_dlong,
                    dshort=api_dshort,
                    is_long=False
                )
                
                margin_per_lot = max(margin_long, margin_short) if margin_long > 0 and margin_short > 0 else (margin_long if margin_long > 0 else margin_short)
            
            # Обновляем словарь, если получили значение
            if margin_per_lot and margin_per_lot > 0:
                update_margin_per_lot(ticker, margin_per_lot)
                updated_margins[ticker.upper()] = margin_per_lot
                logger.info(f"[update_margins_from_api] ✅ {ticker}: ГО обновлено = {margin_per_lot:.2f} ₽")
            else:
                logger.warning(f"[update_margins_from_api] ⚠️ {ticker}: Не удалось рассчитать ГО")
        
        except Exception as e:
            logger.error(f"[update_margins_from_api] Ошибка для {ticker}: {e}", exc_info=True)
    
    return updated_margins


async def update_margin_for_instrument_from_api(
    tinkoff_client,
    ticker: str,
    figi: str,
    current_price: float,
    is_long: bool = True
) -> Optional[float]:
    """
    Обновить ГО для одного инструмента из API перед открытием позиции.
    
    Использует формулу: ГО = point_value * price * dlong/dshort
    ВАЖНО: Для некоторых инструментов (например, NRG6) правильная формула использует dlong,
    даже если это SHORT позиция. Функция автоматически выбирает более точную формулу.
    
    Args:
        tinkoff_client: TinkoffClient instance
        ticker: Тикер инструмента
        figi: FIGI инструмента
        current_price: Текущая цена инструмента
        is_long: True для LONG позиции, False для SHORT
    
    Returns:
        Обновленное значение ГО за лот или None (если не удалось рассчитать)
    """
    try:
        # Получаем информацию об инструменте из API
        inst_info = await asyncio.to_thread(tinkoff_client.get_instrument_info, figi)
        if not inst_info:
            logger.warning(f"[update_margin_for_instrument_from_api] Could not get instrument info for {ticker}")
            return None
        
        # Извлекаем данные из API
        api_dlong = inst_info.get('dlong')
        api_dshort = inst_info.get('dshort')
        min_price_increment = inst_info.get('min_price_increment')
        min_price_increment_amount = inst_info.get('min_price_increment_amount')  # РЕАЛЬНАЯ стоимость пункта!
        lot_size = inst_info.get('lot', 1.0)
        
        # ВАЖНО: Определяем стоимость пункта
        # Приоритет 1: min_price_increment_amount из API (если доступен)
        # Приоритет 2: Словарь POINT_VALUE (для инструментов, где API не возвращает правильное значение)
        # Приоритет 3: min_price_increment * lot (только если нет в словаре, но это может быть неверно!)
        point_value = None
        if min_price_increment_amount and min_price_increment_amount > 0:
            point_value = min_price_increment_amount
            logger.debug(f"[update_margin_for_instrument_from_api] {ticker}: Используем min_price_increment_amount из API: {point_value:.2f} ₽ (реальная стоимость пункта)")
        elif ticker.upper() in POINT_VALUE and POINT_VALUE[ticker.upper()] > 0:
            point_value = POINT_VALUE[ticker.upper()]
            logger.debug(f"[update_margin_for_instrument_from_api] {ticker}: Используем стоимость пункта из словаря POINT_VALUE: {point_value:.2f} ₽")
        elif min_price_increment and min_price_increment > 0:
            # Пробуем рассчитать: min_price_increment * lot (но это может быть неверно!)
            calculated_point_value = min_price_increment * lot_size
            logger.warning(f"[update_margin_for_instrument_from_api] {ticker}: Используем расчетную стоимость пункта: {calculated_point_value:.2f} ₽ (min_price_increment * lot). Это может быть неверно!")
            point_value = calculated_point_value
        else:
            logger.warning(f"[update_margin_for_instrument_from_api] {ticker}: Не удалось определить стоимость пункта (min_price_increment_amount отсутствует, нет в POINT_VALUE)")
            return None
        
        # Рассчитываем ГО используя формулу: point_value * price * dlong/dshort
        # ВАЖНО: Рассчитываем для ОБОИХ направлений (LONG и SHORT) и берем максимальное значение
        # Это гарантирует, что словарь будет содержать достаточное ГО для любого направления
        margin_per_lot = None
        
        if point_value and point_value > 0 and current_price > 0:
            # Рассчитываем для LONG и SHORT
            margin_long = 0
            margin_short = 0
            
            if api_dlong and api_dlong > 0:
                margin_long = point_value * current_price * api_dlong
            
            if api_dshort and api_dshort > 0:
                margin_short = point_value * current_price * api_dshort
            
            # ВАЖНО: Для некоторых инструментов (например, NRG6) правильная формула может использовать dlong вместо dshort
            # Проверяем, какая формула ближе к известному значению из словаря (если есть)
            ticker_upper = ticker.upper()
            if ticker_upper in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker_upper] > 0:
                known_margin = MARGIN_PER_LOT[ticker_upper]
                # Выбираем формулу, которая дает более точный результат
                if margin_long > 0 and margin_short > 0:
                    diff_long = abs(margin_long - known_margin)
                    diff_short = abs(margin_short - known_margin)
                    if diff_long < diff_short:
                        margin_per_lot = margin_long
                        logger.debug(f"[update_margin_for_instrument_from_api] {ticker}: Используем dlong (точнее: {diff_long:.2f} vs {diff_short:.2f})")
                    else:
                        margin_per_lot = margin_short
                        logger.debug(f"[update_margin_for_instrument_from_api] {ticker}: Используем dshort (точнее: {diff_short:.2f} vs {diff_long:.2f})")
                elif margin_long > 0:
                    margin_per_lot = margin_long
                elif margin_short > 0:
                    margin_per_lot = margin_short
                else:
                    margin_per_lot = 0
            else:
                # Если нет известного значения, берем максимальное (чтобы покрыть оба направления)
                if margin_long > 0 or margin_short > 0:
                    margin_per_lot = max(margin_long, margin_short)
        
        if margin_per_lot and margin_per_lot > 0:
            # Обновляем словарь MARGIN_PER_LOT
            ticker_upper = ticker.upper()
            old_margin = MARGIN_PER_LOT.get(ticker_upper, 0)
            MARGIN_PER_LOT[ticker_upper] = margin_per_lot
            
            # Рассчитываем оба значения для логирования
            margin_long = point_value * current_price * api_dlong if (api_dlong and api_dlong > 0) else 0
            margin_short = point_value * current_price * api_dshort if (api_dshort and api_dshort > 0) else 0
            
            if old_margin > 0 and abs(old_margin - margin_per_lot) > 0.01:
                logger.info(
                    f"[update_margin_for_instrument_from_api] {ticker}: "
                    f"Обновлено ГО: {old_margin:.2f} → {margin_per_lot:.2f} ₽/лот "
                    f"(LONG: {margin_long:.2f}, SHORT: {margin_short:.2f}, max) "
                    f"[цена: {current_price:.2f}, point_value: {point_value:.2f}, "
                    f"dlong: {api_dlong}, dshort: {api_dshort}]"
                )
            else:
                logger.info(
                    f"[update_margin_for_instrument_from_api] {ticker}: "
                    f"ГО обновлено: {margin_per_lot:.2f} ₽/лот "
                    f"(LONG: {margin_long:.2f}, SHORT: {margin_short:.2f}, max) "
                    f"[цена: {current_price:.2f}, point_value: {point_value:.2f}]"
                )
            
            return margin_per_lot
        else:
            logger.warning(
                f"[update_margin_for_instrument_from_api] {ticker}: "
                f"Не удалось рассчитать ГО из API данных "
                f"(цена: {current_price:.2f}, point_value: {point_value if point_value else 'N/A'}, "
                f"dlong: {api_dlong}, dshort: {api_dshort})"
            )
            return None
            
    except Exception as e:
        logger.error(f"[update_margin_for_instrument_from_api] {ticker}: Ошибка при обновлении ГО: {e}", exc_info=True)
        return None
