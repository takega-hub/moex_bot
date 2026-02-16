"""
Автоматический расчет гарантийного обеспечения из данных API.
Пытается определить реальную маржу без ручного обновления из терминала.
"""
import logging
from typing import Dict, Optional, Tuple
from trading.client import TinkoffClient
from bot.margin_rates import MARGIN_PER_LOT, POINT_VALUE, get_margin_for_position

logger = logging.getLogger(__name__)


def calculate_point_value_from_api(
    instrument_info: Dict,
    current_price: float,
    lot_size: float
) -> Optional[float]:
    """
    Попытаться вычислить стоимость пункта цены из данных API.
    
    Возможные способы:
    1. Если известна формула: стоимость_пункта = ГО_из_терминала / (цена * dshort)
    2. Через basic_asset_size (если доступно)
    3. Через другие поля API
    
    Args:
        instrument_info: Информация об инструменте из API
        current_price: Текущая цена
        lot_size: Размер лота
    
    Returns:
        Стоимость пункта или None
    """
    # Способ 1: Если есть значение ГО в словаре, можем вычислить стоимость пункта обратно
    ticker = instrument_info.get('ticker', '').upper()
    if ticker in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker] > 0:
        known_margin = MARGIN_PER_LOT[ticker]
        dshort = instrument_info.get('dshort')
        dlong = instrument_info.get('dlong')
        
        # Пробуем обратный расчет: стоимость_пункта = ГО / (цена * dshort)
        if dshort and dshort > 0 and current_price > 0:
            calculated_point_value = known_margin / (current_price * dshort)
            # Проверяем разумность значения (обычно от 1 до 10000)
            if 0.1 < calculated_point_value < 100000:
                logger.debug(f"[{ticker}] Calculated point value from known margin: {calculated_point_value:.2f}")
                return calculated_point_value
        
        if dlong and dlong > 0 and current_price > 0:
            calculated_point_value = known_margin / (current_price * dlong)
            if 0.1 < calculated_point_value < 100000:
                logger.debug(f"[{ticker}] Calculated point value from known margin (dlong): {calculated_point_value:.2f}")
                return calculated_point_value
    
    # Способ 2: Если стоимость пункта уже известна
    if ticker in POINT_VALUE and POINT_VALUE[ticker] > 0:
        return POINT_VALUE[ticker]
    
    # Способ 3: Попробовать через basic_asset_size (если доступно)
    # basic_asset_size может содержать размер базового актива в единицах
    # Но это не всегда соответствует стоимости пункта
    
    return None


def auto_calculate_margin_from_api(
    ticker: str,
    instrument_info: Dict,
    current_price: float,
    lot_size: float = 1.0,
    is_long: bool = True
) -> Tuple[Optional[float], str]:
    """
    Автоматически рассчитать маржу из данных API.
    
    Пробует различные способы:
    1. Использовать значение из словаря (если есть)
    2. Расчет через стоимость пункта (если удалось определить)
    3. Использовать процентный коэффициент (fallback)
    
    Args:
        ticker: Тикер инструмента
        instrument_info: Информация об инструменте из API
        current_price: Текущая цена
        lot_size: Размер лота
        is_long: True для LONG позиции
    
    Returns:
        Tuple (margin_per_lot, source_description)
        - margin_per_lot: Рассчитанная маржа или None
        - source_description: Описание источника расчета
    """
    ticker_upper = ticker.upper()
    
    # Способ 1: Использовать значение из словаря (самый надежный)
    if ticker_upper in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker_upper] > 0:
        margin = MARGIN_PER_LOT[ticker_upper]
        return margin, "dictionary (verified from terminal)"
    
    # Способ 2: Попытаться определить стоимость пункта и использовать формулу
    point_value = calculate_point_value_from_api(instrument_info, current_price, lot_size)
    
    if point_value and point_value > 0:
        dlong = instrument_info.get('dlong')
        dshort = instrument_info.get('dshort')
        
        if is_long and dlong and dlong > 0:
            calculated_margin = point_value * current_price * dlong
            if calculated_margin > 0:
                logger.info(f"[{ticker}] ✅ Auto-calculated margin via formula: {calculated_margin:.2f} ₽ (point_value={point_value:.2f}, price={current_price:.2f}, dlong={dlong:.4f})")
                return calculated_margin, f"formula (point_value * price * dlong)"
        
        if not is_long and dshort and dshort > 0:
            calculated_margin = point_value * current_price * dshort
            if calculated_margin > 0:
                logger.info(f"[{ticker}] ✅ Auto-calculated margin via formula: {calculated_margin:.2f} ₽ (point_value={point_value:.2f}, price={current_price:.2f}, dshort={dshort:.4f})")
                return calculated_margin, f"formula (point_value * price * dshort)"
    
    # Способ 3: Использовать стандартную функцию (процентный fallback)
    margin = get_margin_for_position(
        ticker=ticker,
        quantity=1.0,
        entry_price=current_price,
        lot_size=lot_size,
        dlong=instrument_info.get('dlong'),
        dshort=instrument_info.get('dshort'),
        is_long=is_long
    )
    
    if margin > 0:
        return margin, "percentage_fallback"
    
    return None, "unknown"


def try_determine_point_value_from_similar_instruments(
    ticker: str,
    instrument_info: Dict,
    similar_instruments: Dict[str, Dict]
) -> Optional[float]:
    """
    Попытаться определить стоимость пункта на основе похожих инструментов.
    
    Идея: если у похожих инструментов (например, другие фьючерсы на тот же актив)
    известна стоимость пункта, можно попробовать использовать похожее значение.
    
    Args:
        ticker: Тикер инструмента
        instrument_info: Информация об инструменте
        similar_instruments: Словарь {ticker: {point_value, ...}} для похожих инструментов
    
    Returns:
        Предполагаемая стоимость пункта или None
    """
    # Пока не реализовано - требует базы знаний о похожих инструментах
    return None


def auto_update_margin_from_api(
    tinkoff: TinkoffClient,
    ticker: str,
    figi: str,
    current_price: float
) -> Optional[float]:
    """
    Автоматически определить и обновить маржу для инструмента из API.
    
    Процесс:
    1. Получить информацию об инструменте из API
    2. Попытаться рассчитать маржу автоматически
    3. Если расчет успешен и значение разумное - можно использовать
    
    Args:
        tinkoff: TinkoffClient instance
        ticker: Тикер инструмента
        figi: FIGI инструмента
        current_price: Текущая цена
    
    Returns:
        Рассчитанная маржа или None
    """
    try:
        # Получаем информацию об инструменте
        instrument_info = tinkoff.get_instrument_info(figi)
        if not instrument_info:
            logger.warning(f"[{ticker}] Could not get instrument info from API")
            return None
        
        # Получаем lot_size
        lot_size = instrument_info.get('lot', 1.0)
        
        # Пробуем автоматически рассчитать маржу
        margin_long, source_long = auto_calculate_margin_from_api(
            ticker=ticker,
            instrument_info=instrument_info,
            current_price=current_price,
            lot_size=lot_size,
            is_long=True
        )
        
        margin_short, source_short = auto_calculate_margin_from_api(
            ticker=ticker,
            instrument_info=instrument_info,
            current_price=current_price,
            lot_size=lot_size,
            is_long=False
        )
        
        # Берем максимальную маржу
        margin = max(margin_long or 0, margin_short or 0) if (margin_long and margin_short) else (margin_long or margin_short)
        
        if margin and margin > 0:
            source = source_long if margin == margin_long else source_short
            logger.info(f"[{ticker}] Auto-calculated margin: {margin:.2f} ₽ (source: {source})")
            
            # Если маржа рассчитана через формулу и значение разумное, можно использовать
            # Но для надежности лучше все равно проверить в терминале
            if "formula" in source:
                logger.warning(f"[{ticker}] ⚠️ Margin calculated via formula - рекомендуется проверить в терминале!")
            
            return margin
        
        return None
    
    except Exception as e:
        logger.error(f"[{ticker}] Error in auto_update_margin_from_api: {e}", exc_info=True)
        return None
