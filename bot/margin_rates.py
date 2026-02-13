"""
Справочник коэффициентов маржи для фьючерсов MOEX.
Коэффициенты обновляются на основе данных из терминала Tinkoff.
"""
from typing import Dict, Optional

# Справочник гарантийного обеспечения за лот для каждого инструмента
# Значения в рублях за 1 лот
# Обновляется на основе данных из терминала Tinkoff
MARGIN_PER_LOT: Dict[str, float] = {
    # Фьючерсы на серебро
    "S1H6": 1558.96,  # SILVM-3.26 Серебро (мини) - из терминала
    "SVH6": 0.0,  # TODO: обновить из терминала
    # Фьючерсы на газ
    "NRG6": 0.0,  # TODO: обновить из терминала
    # Фьючерсы на платину
    "PTH6": 0.0,  # TODO: обновить из терминала
    # Фьючерсы на газ природный
    "NGG6": 0.0,  # TODO: обновить из терминала
    # Другие инструменты
    "VBH6": 0.0,  # TODO: обновить из терминала
    "SRH6": 0.0,  # TODO: обновить из терминала
    "GLDRUBF": 0.0,  # TODO: обновить из терминала
}

# Коэффициенты маржи в процентах от стоимости позиции (fallback)
# Используются, если нет данных в MARGIN_PER_LOT
MARGIN_RATE_PCT: Dict[str, float] = {
    "S1H6": 20.2,  # ~1558.96 / (77.19 * 1) * 100
    "SVH6": 12.0,  # По умолчанию
    "NRG6": 12.0,
    "PTH6": 12.0,
    "NGG6": 12.0,
    "VBH6": 12.0,
    "SRH6": 12.0,
    "GLDRUBF": 12.0,
}


def get_margin_for_position(ticker: str, quantity: float, entry_price: float, lot_size: float = 1.0) -> float:
    """
    Получить гарантийное обеспечение для позиции.
    
    Args:
        ticker: Тикер инструмента
        quantity: Количество лотов
        entry_price: Цена входа
        lot_size: Размер лота
        
    Returns:
        Гарантийное обеспечение в рублях
    """
    ticker_upper = ticker.upper()
    
    # Сначала пробуем использовать справочник гарантийного обеспечения за лот
    if ticker_upper in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker_upper] > 0:
        margin_per_lot = MARGIN_PER_LOT[ticker_upper]
        return margin_per_lot * quantity
    
    # Fallback: используем процент от стоимости позиции
    if ticker_upper in MARGIN_RATE_PCT:
        margin_rate = MARGIN_RATE_PCT[ticker_upper] / 100.0
    else:
        margin_rate = 0.12  # 12% по умолчанию
    
    position_value = entry_price * quantity * lot_size
    return position_value * margin_rate


def update_margin_per_lot(ticker: str, margin_per_lot: float):
    """
    Обновить гарантийное обеспечение за лот для инструмента.
    
    Args:
        ticker: Тикер инструмента
        margin_per_lot: Гарантийное обеспечение за лот в рублях
    """
    ticker_upper = ticker.upper()
    MARGIN_PER_LOT[ticker_upper] = margin_per_lot
    
    # Автоматически обновляем процентный коэффициент, если известна цена
    # (это можно сделать позже, когда будет известна текущая цена)
