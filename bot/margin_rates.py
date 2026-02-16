"""
Расчет гарантийного обеспечения (ГО) для фьючерсов MOEX.

ГО рассчитывается по формуле: ГО = point_value × price × dlong/dshort
где point_value = min_price_increment из API.

ВАЖНО: Словарь MARGIN_PER_LOT больше не используется в расчетах.
Все значения рассчитываются динамически из данных API.
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Справочник гарантийного обеспечения за лот (НЕ ИСПОЛЬЗУЕТСЯ в расчетах)
# Оставлен для совместимости и справки
# ВАЖНО: Все значения рассчитываются динамически из API через формулу
MARGIN_PER_LOT: Dict[str, float] = {
    # Фьючерсы на серебро
    "S1H6": 1574.5,  # SILVM-3.26 Серебро (мини) - из терминала (гарантийное обеспечение за лот, лотность=1)
    "SVH6": 15751.12,  # SILV-3.26 Серебро - из терминала (гарантийное обеспечение за лот, лотность=10)
    # Фьючерсы на газ
    "NRG6": 0.27,  # NGM-2.26 Природный газ (микро) - значительно увеличен для учета реальных требований биржи
    # Фьючерсы на платину
    "PTH6": 33860.23,  # PLT-3.26 Платина - из терминала (гарантийное обеспечение за лот)
    # Фьючерсы на газ природный
    "NGG6": 7667.72,  # NG-2.26 Природный газ - из терминала (гарантийное обеспечение за лот)
    # Фьючерсы на никель
    "NCM6": 2112.00,  # NICKEL-6.26 Никель - из терминала (гарантийное обеспечение за лот, лотность=1)
    # Фьючерсы на алюминий
    "ANH6": 2746.1,  # ALUM-3.26 Алюминий - из терминала (гарантийное обеспечение за лот, лотность=1)
    # Другие инструменты
    "VBH6": 0.0,  # TODO: обновить из терминала
    "SRH6": 0.0,  # TODO: обновить из терминала
    "GLDRUBF": 0.0,  # TODO: обновить из терминала
    # Фьючерсы на акции Т-Технологии
    "TBH6": 885.75,  # T-3.26 Т-Технологии - из терминала (гарантийное обеспечение за лот)
}

# Коэффициенты маржи в процентах от стоимости позиции (fallback)
# Используются, если формула через point_value не работает
MARGIN_RATE_PCT: Dict[str, float] = {
    "S1H6": 20.2,  # ~1558.96 / (77.19 * 1) * 100 (из терминала)
    "SVH6": 15.0,  # ~11.7 / 78.0 * 100 (из CSV)
    "NRG6": 50.0,  # Увеличен до 50% для учета реальных требований биржи (было 15%)
    "PTH6": 15.0,  # ~306.75 / 2045.0 * 100 (из CSV)
    "NGG6": 50.0,  # Увеличен до 50% для учета реальных требований биржи (было 15%)
    "NCM6": 12.0,  # ~2112.00 / 17600.0 * 100 ≈ 12% (из терминала)
    "ANH6": 89.4,  # ~2746.1 / 3071.5 * 100 ≈ 89.4% (из терминала)
    "VBH6": 12.0,  # По умолчанию
    "SRH6": 12.0,  # По умолчанию
    "GLDRUBF": 12.0,  # По умолчанию
}


# Справочник стоимости пункта цены для инструментов (из терминала)
# Используется для расчета маржи по формуле: ГО = стоимость_пункта * цена * dlong/dshort
# ВАЖНО: Формула работает не для всех инструментов, требует валидации!
POINT_VALUE: Dict[str, float] = {
    "PTH6": 77.19,  # PLT-3.26 Платина - из терминала
    "SVH6": 771.94,  # SILV-3.26 Серебро - из терминала (лотность=10)
    "S1H6": 77.19,  # SILVM-3.26 Серебро (мини) - из терминала (лотность=1)
    # TODO: добавить для других инструментов
}

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
    1. Расчет через стоимость пункта: ГО = point_value * цена * dlong/dshort (если point_value передан)
    2. Расчет через POINT_VALUE словарь (если есть)
    3. Процент от стоимости позиции (fallback)
    
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
    
    # 1. Пробуем расчет через переданную стоимость пункта (приоритет)
    if point_value and point_value > 0 and entry_price > 0:
        if is_long and dlong and dlong > 0:
            margin_per_lot = point_value * entry_price * dlong
            return margin_per_lot * quantity
        elif not is_long and dshort and dshort > 0:
            margin_per_lot = point_value * entry_price * dshort
            return margin_per_lot * quantity
    
    # 2. Пробуем расчет через стоимость пункта цены из словаря POINT_VALUE
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
    dlong: Optional[float] = None,
    dshort: Optional[float] = None,
    is_long: bool = True
) -> Optional[float]:
    """
    Получить ГО за один лот из данных API.
    
    Формула: point_value * current_price * dlong/dshort
    
    Args:
        ticker: Тикер инструмента
        current_price: Текущая цена
        point_value: Стоимость пункта (min_price_increment из API)
        dlong: Коэффициент dlong из API
        dshort: Коэффициент dshort из API
        is_long: True для LONG, False для SHORT
    
    Returns:
        ГО за один лот в рублях или None (если недостаточно данных)
    """
    # Рассчитываем через формулу
    if point_value and point_value > 0 and current_price > 0:
        if is_long and dlong and dlong > 0:
            return point_value * current_price * dlong
        elif not is_long and dshort and dshort > 0:
            return point_value * current_price * dshort
    
    return None
