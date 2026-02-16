"""
Модуль для расчета маржи для активных инструментов при запуске бота.
"""
import logging
from typing import Dict, Optional
from data.storage import DataStorage
from trading.client import TinkoffClient
from bot.margin_rates import get_margin_for_position

logger = logging.getLogger(__name__)


async def calculate_margins_for_instruments(
    tinkoff: TinkoffClient,
    storage: DataStorage,
    instruments: list[str]
) -> Dict[str, float]:
    """
    Рассчитать маржу для всех активных инструментов.
    
    Args:
        tinkoff: TinkoffClient instance
        storage: DataStorage instance
        instruments: Список тикеров активных инструментов
    
    Returns:
        Словарь {ticker: margin_per_lot}
    """
    margins = {}
    
    if not instruments:
        logger.warning("No active instruments to calculate margins for")
        return margins
    
    logger.info(f"📊 Calculating margins for {len(instruments)} active instruments...")
    
    for ticker in instruments:
        try:
            # Получаем информацию об инструменте
            instrument_info = storage.get_instrument_by_ticker(ticker)
            if not instrument_info:
                logger.warning(f"[{ticker}] Instrument info not found in storage")
                continue
            
            figi = instrument_info["figi"]
            
            # Получаем текущую цену
            current_price = 0.0
            try:
                df = storage.get_candles(figi=figi, interval="15min", limit=1)
                if not df.empty:
                    current_price = float(df.iloc[-1]["close"])
            except Exception as e:
                logger.debug(f"[{ticker}] Error getting price from storage: {e}")
            
            # Если цена не получена, используем примерную
            if current_price <= 0:
                price_estimates = {
                    "NGG6": 3.0,
                    "PTH6": 2049.7,
                    "NRG6": 3.0,
                    "SVH6": 78.68,  # Из терминала
                    "S1H6": 77.0,
                    "VBH6": 8500.0,
                    "SRH6": 31000.0,
                    "GLDRUBF": 12200.0,
                }
                current_price = price_estimates.get(ticker.upper(), 100.0)
                logger.debug(f"[{ticker}] Using estimated price: {current_price:.2f}")
            
            # Получаем lot_size (синхронный метод, вызываем через asyncio.to_thread)
            lot_size = 1.0
            try:
                import asyncio
                lot_size = await asyncio.to_thread(tinkoff.get_qty_step, figi)
                if lot_size <= 0:
                    lot_size = 1.0
            except Exception as e:
                logger.debug(f"[{ticker}] Error getting lot_size: {e}")
            
            # Получаем dlong/dshort из API (синхронный метод, вызываем через asyncio.to_thread)
            api_dlong = None
            api_dshort = None
            try:
                import asyncio
                inst_info = await asyncio.to_thread(tinkoff.get_instrument_info, figi)
                if inst_info:
                    api_dlong = inst_info.get('dlong')
                    api_dshort = inst_info.get('dshort')
            except Exception as e:
                logger.debug(f"[{ticker}] Error getting instrument info: {e}")
            
                    # Рассчитываем маржу для LONG и SHORT (берем максимальную)
                    # Используем автоматический расчет стоимости пункта для похожих инструментов
                    margin_long = get_margin_for_position(
                        ticker=ticker,
                        quantity=1.0,
                        entry_price=current_price,
                        lot_size=lot_size,
                        dlong=api_dlong,
                        dshort=api_dshort,
                        is_long=True,
                        auto_calculate_point_value_flag=True
                    )
                    
                    margin_short = get_margin_for_position(
                        ticker=ticker,
                        quantity=1.0,
                        entry_price=current_price,
                        lot_size=lot_size,
                        dlong=api_dlong,
                        dshort=api_dshort,
                        is_long=False,
                        auto_calculate_point_value_flag=True
                    )
            
            # Берем максимальную маржу
            margin_per_lot = max(margin_long, margin_short) if margin_long > 0 and margin_short > 0 else (margin_long if margin_long > 0 else margin_short)
            
            if margin_per_lot > 0:
                margins[ticker] = margin_per_lot
                logger.info(f"[{ticker}] ✅ Margin calculated: {margin_per_lot:.2f} ₽/лот (price: {current_price:.2f}, lot_size: {lot_size:.0f})")
            else:
                logger.warning(f"[{ticker}] ⚠️ Could not calculate margin")
        
        except Exception as e:
            logger.error(f"[{ticker}] ❌ Error calculating margin: {e}", exc_info=True)
    
    logger.info(f"📊 Margin calculation complete: {len(margins)}/{len(instruments)} instruments")
    return margins
