"""Script to find optimal trading instruments based on lot cost, volatility, and volume."""
import argparse
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import pandas as pd
import numpy as np
from dotenv import load_dotenv

from trading.client import TinkoffClient
from data.collector import DataCollector
from utils.logger import logger

# Load environment variables
load_dotenv()


def is_metal_future(instrument) -> bool:
    """
    Проверяет, является ли фьючерс фьючерсом на металл.
    
    Args:
        instrument: Объект инструмента из API
        
    Returns:
        True если это фьючерс на металл
    """
    name_lower = instrument.name.lower()
    ticker_upper = instrument.ticker.upper()
    basic_asset = getattr(instrument, 'basic_asset', '').lower()
    
    # Ключевые слова для металлов
    metal_keywords = [
        'серебро', 'silver', 'silv', 'si-', 's1', 'sv',
        'золото', 'gold', 'au-', 'gld',
        'платина', 'platinum', 'plt', 'pt-',
        'палладий', 'palladium', 'pall', 'pd-',
        'медь', 'copper', 'cu-',
        'алюминий', 'aluminum', 'al-'
    ]
    
    # Проверяем по названию, тикеру и базовому активу
    for keyword in metal_keywords:
        if keyword in name_lower or keyword in ticker_upper.lower() or keyword in basic_asset:
            return True
    
    return False


def is_stock_future(instrument) -> bool:
    """
    Проверяет, является ли фьючерс фьючерсом на акцию.
    
    Args:
        instrument: Объект инструмента из API
        
    Returns:
        True если это фьючерс на акцию
    """
    name_lower = instrument.name.lower()
    ticker_upper = instrument.ticker.upper()
    basic_asset = getattr(instrument, 'basic_asset', '').lower()
    asset_type = getattr(instrument, 'asset_type', '').lower()
    
    # Фьючерсы на акции обычно имеют asset_type = 'share' или содержат тикер акции
    if asset_type == 'share' or 'акция' in name_lower:
        return True
    
    # Популярные тикеры акций на MOEX
    stock_tickers = [
        'SBER', 'GAZP', 'LKOH', 'GMKN', 'NVTK', 'YNDX', 'ROSN',
        'MGNT', 'TATN', 'SNGS', 'CHMF', 'ALRS', 'PLZL', 'MOEX',
        'AFKS', 'AFLT', 'AKRN', 'APTK', 'BANE', 'BELU', 'FIVE',
        'FIXP', 'HYDR', 'IRAO', 'MTSS', 'NLMK', 'POLY', 'RTKM',
        'SBERP', 'SGZH', 'TRNFP', 'UPRO', 'VTBR', 'FEES', 'PHOR'
    ]
    
    # Проверяем, содержит ли тикер или базовый актив тикер акции
    for stock_ticker in stock_tickers:
        if stock_ticker in ticker_upper or stock_ticker in basic_asset.upper():
            return True
    
    return False


def get_all_futures(client: TinkoffClient, filter_metals: bool = True, filter_stocks: bool = True) -> List[Dict[str, Any]]:
    """
    Get list of available futures from Tinkoff API, filtered by type.
    
    Args:
        client: TinkoffClient instance
        filter_metals: If True, include metal futures
        filter_stocks: If True, include stock futures
    
    Returns:
        List of dictionaries with figi, ticker, name, basic_asset, asset_type
    """
    futures = []
    try:
        with client._get_client() as tinkoff_client:
            logger.info("Fetching all futures from Tinkoff API...")
            response = tinkoff_client.instruments.futures()
            
            for instrument in response.instruments:
                # Пропускаем инструменты, недоступные для торговли через API
                if not getattr(instrument, 'api_trade_available_flag', False):
                    continue
                
                # Фильтруем по типу
                is_metal = is_metal_future(instrument)
                is_stock = is_stock_future(instrument)
                
                if (filter_metals and is_metal) or (filter_stocks and is_stock):
                    futures.append({
                        "figi": instrument.figi,
                        "ticker": instrument.ticker,
                        "name": instrument.name,
                        "basic_asset": getattr(instrument, 'basic_asset', ''),
                        "asset_type": getattr(instrument, 'asset_type', ''),
                        "is_metal": is_metal,
                        "is_stock": is_stock
                    })
            
            logger.info(f"Found {len(futures)} futures (metals: {sum(1 for f in futures if f['is_metal'])}, stocks: {sum(1 for f in futures if f['is_stock'])})")
    except Exception as e:
        logger.error(f"Error fetching futures: {e}", exc_info=True)
    
    return futures


def get_current_price(client: TinkoffClient, figi: str) -> Optional[float]:
    """
    Get current price for instrument by fetching last candle.
    Использует приоритет: 1min -> 5min -> 15min -> 1hour для получения самой свежей цены.
    
    Args:
        client: TinkoffClient instance
        figi: Instrument FIGI
    
    Returns:
        Current price or None if error
    """
    try:
        # Получаем последние свечи для самой актуальной цены
        to_date = datetime.now()
        from_date = to_date - timedelta(hours=2)  # Достаточно 2 часов для получения свежих данных
        
        # Приоритет: сначала 1-минутные свечи (самые свежие)
        intervals = ["1min", "5min", "15min", "1hour"]
        
        for interval in intervals:
            try:
                candles = client.get_candles(figi, from_date, to_date, interval=interval)
                if candles:
                    # Используем последнюю свечу (самую свежую)
                    last_candle = candles[-1]
                    price = last_candle["close"]
                    if price and price > 0:
                        logger.debug(f"Got current price for {figi} from {interval} candles: {price:.2f}")
                        return price
            except Exception as e:
                logger.debug(f"Failed to get {interval} candles for {figi}: {e}")
                continue
        
        logger.warning(f"No candles found for {figi} to get current price")
        return None
    except Exception as e:
        logger.warning(f"Error getting current price for {figi}: {e}")
        return None


def get_instrument_info(client: TinkoffClient, figi: str) -> Dict[str, Any]:
    """
    Get instrument information (lot size, price step, dlong, dshort, min_price_increment).
    
    Args:
        client: TinkoffClient instance
        figi: Instrument FIGI
    
    Returns:
        Dict with lot_size, price_step, dlong, dshort, min_price_increment
    """
    try:
        lot_size = client.get_qty_step(figi)
        price_step = client.get_price_step(figi)
        
        # Получаем дополнительную информацию из API (dlong, dshort, min_price_increment)
        dlong = None
        dshort = None
        min_price_increment = None
        
        try:
            with client._get_client() as tinkoff_client:
                from t_tech.invest import InstrumentIdType
                response = tinkoff_client.instruments.get_instrument_by(
                    id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                    id=figi
                )
                instrument = response.instrument
                
                # Извлекаем dlong, dshort
                if hasattr(instrument, 'dlong') and instrument.dlong:
                    dlong = float(instrument.dlong.units) + float(instrument.dlong.nano) / 1e9
                if hasattr(instrument, 'dshort') and instrument.dshort:
                    dshort = float(instrument.dshort.units) + float(instrument.dshort.nano) / 1e9
                
                # Извлекаем min_price_increment (это и есть стоимость пункта)
                if hasattr(instrument, 'min_price_increment') and instrument.min_price_increment:
                    min_price_increment = float(instrument.min_price_increment.units) + float(instrument.min_price_increment.nano) / 1e9
        except Exception as e:
            logger.debug(f"Could not get additional instrument info for {figi}: {e}")
        
        return {
            "lot_size": lot_size,
            "price_step": price_step,
            "dlong": dlong,
            "dshort": dshort,
            "min_price_increment": min_price_increment
        }
    except Exception as e:
        logger.warning(f"Error getting instrument info for {figi}: {e}")
        return {
            "lot_size": 1.0,
            "price_step": 0.01,
            "dlong": None,
            "dshort": None,
            "min_price_increment": None
        }


def calculate_volatility(df: pd.DataFrame, current_price: float) -> float:
    """
    Calculate daily volatility percentage from historical data.
    
    Uses ATR (Average True Range) method normalized by current price.
    
    Args:
        df: DataFrame with columns: open, high, low, close
        current_price: Current price of instrument
    
    Returns:
        Daily volatility as percentage
    """
    if df.empty or len(df) < 2:
        return 0.0
    
    try:
        # Calculate True Range
        df = df.copy()
        df['prev_close'] = df['close'].shift(1)
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['prev_close'])
        df['tr3'] = abs(df['low'] - df['prev_close'])
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        
        # Calculate ATR (14 period, or use all available data if less)
        period = min(14, len(df) - 1)
        if period > 0:
            atr = df['tr'].tail(period).mean()
        else:
            atr = df['tr'].mean()
        
        # Convert to daily volatility percentage
        if current_price > 0:
            volatility_pct = (atr / current_price) * 100
        else:
            volatility_pct = 0.0
        
        return volatility_pct
    except Exception as e:
        logger.warning(f"Error calculating volatility: {e}")
        # Fallback: use standard deviation of daily returns
        try:
            df['returns'] = df['close'].pct_change()
            daily_std = df['returns'].std() * 100
            return abs(daily_std) if not np.isnan(daily_std) else 0.0
        except:
            return 0.0


def calculate_avg_volume(df: pd.DataFrame, lot_size: float, current_price: float) -> Dict[str, float]:
    """
    Calculate average trading volume.
    
    Args:
        df: DataFrame with volume column
        lot_size: Lot size for instrument
        current_price: Current price
    
    Returns:
        Dict with avg_volume_lots and avg_volume_rub
    """
    if df.empty:
        return {"avg_volume_lots": 0.0, "avg_volume_rub": 0.0}
    
    try:
        # Calculate daily volumes
        # Group by date if we have timestamp column
        if 'timestamp' in df.columns:
            df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.date
        elif 'time' in df.columns:
            df['date'] = pd.to_datetime(df['time']).dt.date
        else:
            # Use index as date if no timestamp
            df['date'] = df.index
        
        daily_volumes = df.groupby('date')['volume'].sum()
        avg_volume = daily_volumes.mean()
        
        # For Tinkoff API, volume is typically in units (contracts), not lots
        # Convert to lots (divide by lot_size)
        # Note: Some instruments might have volume already in lots, but we'll convert anyway
        avg_volume_lots = avg_volume / lot_size if lot_size > 0 else avg_volume
        
        # Calculate volume in rubles: volume_lots * lot_size * price
        # This gives us the total value traded
        avg_volume_rub = avg_volume_lots * lot_size * current_price if current_price > 0 else 0.0
        
        return {
            "avg_volume_lots": float(avg_volume_lots),
            "avg_volume_rub": float(avg_volume_rub)
        }
    except Exception as e:
        logger.warning(f"Error calculating average volume: {e}")
        return {"avg_volume_lots": 0.0, "avg_volume_rub": 0.0}


def get_account_balance(client: TinkoffClient) -> Optional[float]:
    """
    Get account balance from API.
    
    Args:
        client: TinkoffClient instance
    
    Returns:
        Account balance in RUB or None if error
    """
    try:
        with client._get_client() as tinkoff_client:
            accounts = tinkoff_client.users.get_accounts()
            if not accounts.accounts:
                logger.warning("No accounts found")
                return None
            
            account_id = accounts.accounts[0].id
            portfolio = tinkoff_client.operations.get_portfolio(account_id=account_id)
            
            # Получаем общий баланс портфеля
            if hasattr(portfolio, 'total_amount_portfolio') and portfolio.total_amount_portfolio:
                balance = float(portfolio.total_amount_portfolio.units) + float(portfolio.total_amount_portfolio.nano) / 1e9
                return balance
            
            # Альтернативный способ - через валюты
            if hasattr(portfolio, 'total_amount_currencies') and portfolio.total_amount_currencies:
                balance = float(portfolio.total_amount_currencies.units) + float(portfolio.total_amount_currencies.nano) / 1e9
                return balance
    except Exception as e:
        logger.warning(f"Error getting account balance: {e}")
    return None


def analyze_instrument(
    client: TinkoffClient,
    collector: DataCollector,
    figi: str,
    ticker: str,
    name: str,
    balance: float,
    max_margin: float,
    volatility_min: float,
    volatility_max: float,
    period_days: int,
    stats: Optional[Dict[str, int]] = None,
    check_volatility: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Analyze single instrument.
    
    Args:
        client: TinkoffClient instance
        collector: DataCollector instance
        figi: Instrument FIGI
        ticker: Instrument ticker
        name: Instrument name
        balance: Account balance in RUB
        max_margin: Maximum margin (GO) in RUB per lot
        volatility_min: Minimum volatility threshold
        volatility_max: Maximum volatility threshold
        period_days: Analysis period in days
        stats: Optional dictionary to collect statistics
        check_volatility: If False, skip volatility filtering
    
    Returns:
        Dict with analysis results or None if doesn't meet criteria
    """
    try:
        logger.info(f"🔍 Analyzing {ticker} ({figi})...")
        
        # ========================================================================
        # ШАГ 1: Получение базовой информации об инструменте
        # ========================================================================
        # Get instrument info
        info = get_instrument_info(client, figi)
        lot_size = info["lot_size"]
        price_step = info["price_step"]
        api_dlong = info.get("dlong")
        api_dshort = info.get("dshort")
        min_price_increment = info.get("min_price_increment")  # Это стоимость пункта!
        
        # Get current price
        current_price = get_current_price(client, figi)
        if current_price is None or current_price <= 0:
            logger.warning(f"❌ {ticker}: cannot get current price - пропускаем")
            if stats is not None:
                stats["no_price"] += 1
            return None
        
        # Calculate lot value
        lot_value = current_price * lot_size
        
        # ========================================================================
        # ШАГ 2: Расчет ГО (гарантийного обеспечения) - ТОЛЬКО ФОРМУЛА
        # ========================================================================
        from bot.margin_rates import get_margin_per_lot_from_api_data, POINT_VALUE
        
        # ВАЖНО: Если min_price_increment из API = 0 или None, используем словарь POINT_VALUE
        if not min_price_increment or min_price_increment == 0:
            if ticker.upper() in POINT_VALUE and POINT_VALUE[ticker.upper()] > 0:
                min_price_increment = POINT_VALUE[ticker.upper()]
                logger.debug(f"{ticker}: Используем стоимость пункта из словаря POINT_VALUE: {min_price_increment:.2f} ₽ (min_price_increment из API был 0 или неправильным)")
        
        # Расчет ГО только через формулу: point_value * price * dlong/dshort
        # где point_value = min_price_increment из API или словаря
        margin_per_lot = None
        
        if min_price_increment and min_price_increment > 0:
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
                if margin_per_lot > 0:
                    logger.info(f"{ticker}: ✅ Calculated margin via formula: {margin_per_lot:.2f} ₽ (formula: {min_price_increment} × {current_price:.2f} × {api_dshort or api_dlong})")
            else:
                # Если формула не сработала, логируем причину и пропускаем инструмент
                logger.warning(
                    f"❌ {ticker}: Не удалось рассчитать ГО по формуле - "
                    f"margin_long={margin_long}, margin_short={margin_short}, "
                    f"dlong={api_dlong}, dshort={api_dshort}, point_value={min_price_increment}. "
                    f"Инструмент пропускается."
                )
        
        # Если ГО не рассчиталось по формуле, пропускаем инструмент
        if not margin_per_lot or margin_per_lot <= 0:
            logger.warning(
                f"❌ {ticker}: ГО не рассчитано по формуле. "
                f"Требуются: min_price_increment={min_price_increment}, "
                f"dlong={api_dlong}, dshort={api_dshort}, current_price={current_price}. "
                f"Инструмент пропускается."
            )
            if stats is not None:
                stats["no_margin_calc"] += 1
            return None
        
        # ========================================================================
        # ФИЛЬТРАЦИЯ ПО ГО И БАЛАНСУ (В ПЕРВУЮ ОЧЕРЕДЬ)
        # ========================================================================
        # ВАЖНО: Для фьючерсов нужно только ГО (гарантийное обеспечение)
        # Стоимость лота (lot_value) НЕ блокируется на счете - это только расчетная стоимость позиции
        # Для открытия позиции требуется только ГО
        
        # Проверка 1: Достаточно ли баланса для открытия хотя бы 1 лота?
        if margin_per_lot > balance:
            logger.info(
                f"❌ {ticker}: Фильтр по ГО/балансу НЕ ПРОЙДЕН - "
                f"ГО {margin_per_lot:.2f} ₽ > баланс {balance:.2f} ₽ "
                f"(недостаточно баланса для открытия 1 лота). "
                f"Стоимость лота: {lot_value:.2f} ₽ (не блокируется, только для справки)"
            )
            if stats is not None:
                stats["margin_too_high"] += 1
            return None
        
        # Проверка 2: ГО не превышает максимальное значение?
        if margin_per_lot > max_margin:
            logger.info(
                f"❌ {ticker}: Фильтр по ГО/балансу НЕ ПРОЙДЕН - "
                f"ГО {margin_per_lot:.2f} ₽ > максимальная маржа {max_margin:.2f} ₽"
            )
            if stats is not None:
                stats["margin_exceeds_limit"] += 1
            return None
        
        # Если обе проверки пройдены, продолжаем анализ
        logger.info(
            f"✅ {ticker}: Фильтр по ГО/балансу ПРОЙДЕН - "
            f"ГО {margin_per_lot:.2f} ₽ ({margin_per_lot/balance*100:.1f}% от баланса), "
            f"максимум лотов: {int(balance / margin_per_lot)}"
        )
        
        # ========================================================================
        # ШАГ 3: Сбор исторических данных (только для прошедших фильтр по ГО)
        # ========================================================================
        to_date = datetime.now()
        from_date = to_date - timedelta(days=period_days)
        
        logger.debug(f"📊 Collecting historical data for {ticker} from {from_date.date()} to {to_date.date()}")
        candles = collector.collect_candles(
            figi=figi,
            from_date=from_date,
            to_date=to_date,
            interval="1hour",  # Use hourly for volatility calculation
            save=False  # Don't save to avoid cluttering storage
        )
        
        if not candles or len(candles) < 10:
            logger.warning(f"Skipping {ticker}: insufficient historical data ({len(candles) if candles else 0} candles)")
            if stats is not None:
                stats["insufficient_data"] += 1
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(candles)
        if 'time' in df.columns:
            # Convert time to datetime if needed
            df['time'] = pd.to_datetime(df['time'])
            df['timestamp'] = df['time'].astype('int64') // 10**6  # Convert to milliseconds
        # Sort by time
        if 'time' in df.columns:
            df = df.sort_values('time').reset_index(drop=True)
        
        # Calculate volatility
        volatility = calculate_volatility(df, current_price)
        
        # Check volatility criterion (if enabled)
        if check_volatility:
            if volatility < volatility_min or volatility > volatility_max:
                logger.info(f"❌ {ticker}: Волатильность {volatility:.2f}% вне диапазона [{volatility_min}%, {volatility_max}%]")
                if stats is not None:
                    stats["volatility_out_of_range"] += 1
                return None
        
        # Calculate average volume
        volume_info = calculate_avg_volume(df, lot_size, current_price)
        
        # Calculate score (higher is better)
        # Score based on volume (higher volume = higher score)
        # and volatility closeness to middle of range
        volatility_mid = (volatility_min + volatility_max) / 2
        volatility_score = 1.0 - abs(volatility - volatility_mid) / volatility_mid
        volume_score = min(volume_info["avg_volume_rub"] / 1000000.0, 1.0)  # Normalize to 1M RUB
        score = (volume_score * 0.7 + volatility_score * 0.3) * 100
        
        # Рассчитываем максимальное количество лотов, которое можно открыть
        # Для каждого лота нужно только ГО (гарантийное обеспечение)
        # Стоимость лота не блокируется на счете - это только расчетная стоимость позиции
        max_lots = int(balance / margin_per_lot) if margin_per_lot > 0 else 0
        
        result = {
            "figi": figi,
            "ticker": ticker,
            "name": name,
            "current_price": current_price,
            "lot_size": lot_size,
            "price_step": price_step,
            "lot_value": lot_value,
            "margin_per_lot": margin_per_lot,
            "margin_pct_of_balance": (margin_per_lot / balance) * 100 if balance > 0 else 0,
            "max_lots_available": max_lots,
            "volatility_pct": volatility,
            "avg_volume_lots": volume_info["avg_volume_lots"],
            "avg_volume_rub": volume_info["avg_volume_rub"],
            "score": score,
            "date_analyzed": datetime.now().isoformat(),
            "analysis_period_days": period_days
        }
        
        logger.info(f"✓ {ticker}: margin={margin_per_lot:.2f} руб ({result['margin_pct_of_balance']:.1f}%), "
                   f"volatility={volatility:.2f}%, volume={volume_info['avg_volume_rub']:.0f} руб/день")
        
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing {ticker}: {e}", exc_info=True)
        return None


def filter_and_rank_instruments(results: List[Dict[str, Any]], limit: int = 50) -> List[Dict[str, Any]]:
    """
    Filter and rank instruments by priority.
    
    Priority:
    1. Volume (descending) - more liquid instruments preferred
    2. Volatility (closer to middle of range)
    3. Margin cost (lower is better for diversification)
    
    Args:
        results: List of analysis results
        limit: Maximum number of results to return
    
    Returns:
        Sorted and limited list of results
    """
    if not results:
        return []
    
    # Sort by score (descending), then by volume, then by margin
    sorted_results = sorted(
        results,
        key=lambda x: (
            -x.get("score", 0),  # Higher score first
            -x.get("avg_volume_rub", 0),  # Higher volume first
            x.get("margin_per_lot", float('inf'))  # Lower margin first
        )
    )
    
    return sorted_results[:limit]


def print_results(results: List[Dict[str, Any]]):
    """Print results to console as formatted table."""
    if not results:
        print("\n❌ No instruments found matching the criteria.")
        return
    
    print(f"\n{'='*120}")
    print(f"FOUND {len(results)} OPTIMAL INSTRUMENTS")
    print(f"{'='*120}\n")
    
    # Print header
    header = (
        f"{'Ticker':<12} {'Price':<10} {'Lot Size':<10} {'Lot Value':<12} "
        f"{'Margin':<10} {'Margin %':<10} {'Max Lots':<10} {'Volatility %':<12} "
        f"{'Avg Vol (lots)':<15} {'Avg Vol (RUB)':<15} {'Score':<8}"
    )
    print(header)
    print("-" * 140)
    
    # Print rows
    for r in results:
        row = (
            f"{r['ticker']:<12} {r['current_price']:>9.2f} {r['lot_size']:>9.1f} "
            f"{r['lot_value']:>11.2f} {r['margin_per_lot']:>9.2f} "
            f"{r['margin_pct_of_balance']:>9.1f}% {r.get('max_lots_available', 0):>9.0f} "
            f"{r['volatility_pct']:>11.2f}% "
            f"{r['avg_volume_lots']:>14.1f} {r['avg_volume_rub']:>14.0f} "
            f"{r['score']:>7.1f}"
        )
        print(row)
    
    print(f"\n{'='*120}\n")


def save_to_csv(results: List[Dict[str, Any]], filename: str):
    """Save results to CSV file."""
    if not results:
        logger.warning("No results to save")
        return
    
    try:
        df = pd.DataFrame(results)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"✓ Results saved to {filename}")
        print(f"✓ Results saved to {filename}")
    except Exception as e:
        logger.error(f"Error saving CSV: {e}", exc_info=True)
        print(f"❌ Error saving CSV: {e}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Find optimal trading instruments based on lot cost, volatility, and volume"
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=5000.0,
        help="Account balance in RUB (default: 5000)"
    )
    parser.add_argument(
        "--margin-pct",
        type=float,
        default=None,
        help="Maximum margin percentage of balance per lot (default: calculated from --max-margin)"
    )
    parser.add_argument(
        "--max-margin",
        type=float,
        default=None,
        help="Maximum margin (GO) in RUB per lot (default: 25%% of balance)"
    )
    parser.add_argument(
        "--volatility-min",
        type=float,
        default=1.0,
        help="Minimum daily volatility percentage (default: 1.0, use --no-volatility-filter to disable)"
    )
    parser.add_argument(
        "--volatility-max",
        type=float,
        default=5.0,
        help="Maximum daily volatility percentage (default: 5.0, use --no-volatility-filter to disable)"
    )
    parser.add_argument(
        "--no-volatility-filter",
        action="store_true",
        help="Disable volatility filtering"
    )
    parser.add_argument(
        "--period-days",
        type=int,
        default=30,
        help="Analysis period in days (default: 30)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV filename (default: optimal_instruments_YYYYMMDD_HHMMSS.csv)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of results (default: 50)"
    )
    parser.add_argument(
        "--filter-metals",
        action="store_true",
        default=True,
        help="Include metal futures (default: True)"
    )
    parser.add_argument(
        "--filter-stocks",
        action="store_true",
        default=True,
        help="Include stock futures (default: True)"
    )
    parser.add_argument(
        "--no-metals",
        action="store_true",
        help="Exclude metal futures"
    )
    parser.add_argument(
        "--no-stocks",
        action="store_true",
        help="Exclude stock futures"
    )
    
    args = parser.parse_args()
    
    # Обрабатываем флаги исключения
    filter_metals = args.filter_metals and not args.no_metals
    filter_stocks = args.filter_stocks and not args.no_stocks
    
    # Generate output filename if not provided
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output = f"optimal_instruments_{timestamp}.csv"
    
    # Calculate max margin
    if args.max_margin is not None:
        max_margin = args.max_margin
        margin_pct = (max_margin / args.balance * 100) if args.balance > 0 else 0
    elif args.margin_pct is not None:
        margin_pct = args.margin_pct
        max_margin = args.balance * (margin_pct / 100.0)
    else:
        # Default: 25% of balance
        margin_pct = 25.0
        max_margin = args.balance * 0.25
    
    print("\n" + "="*120)
    print("OPTIMAL INSTRUMENTS FINDER")
    print("="*120)
    print(f"Balance: {args.balance:.2f} RUB")
    print(f"Max margin (GO) per lot: {max_margin:.2f} RUB ({margin_pct:.1f}% of balance)")
    if args.no_volatility_filter:
        print(f"Volatility filter: DISABLED")
    else:
        print(f"Volatility range: {args.volatility_min}% - {args.volatility_max}%")
    print(f"Analysis period: {args.period_days} days")
    print(f"Filter metals: {filter_metals}")
    print(f"Filter stocks: {filter_stocks}")
    print(f"Max results: {args.limit}")
    print("="*120 + "\n")
    
    # Проверяем, что выбран хотя бы один тип
    if not filter_metals and not filter_stocks:
        print("❌ Error: At least one filter type (metals or stocks) must be enabled")
        return
    
    # Initialize clients
    try:
        client = TinkoffClient()
        collector = DataCollector(client=client)
    except Exception as e:
        logger.error(f"Failed to initialize clients: {e}", exc_info=True)
        print(f"❌ Error: {e}")
        return
    
    # Получаем баланс из API, если не указан
    if args.balance is None:
        print("📊 Получение баланса из API...")
        balance_from_api = get_account_balance(client)
        if balance_from_api is not None and balance_from_api > 0:
            args.balance = balance_from_api
            print(f"✅ Баланс из API: {args.balance:.2f} RUB")
        else:
            print("⚠️ Не удалось получить баланс из API, используем значение по умолчанию: 5000 RUB")
            args.balance = 5000.0
    
    # Get filtered futures
    futures = get_all_futures(client, filter_metals=filter_metals, filter_stocks=filter_stocks)
    if not futures:
        print("❌ No futures found or error fetching futures")
        return
    
    print(f"Analyzing {len(futures)} futures...\n")
    
    # Analyze each instrument
    results = []
    processed = 0
    stats = {
        "no_price": 0,
        "no_margin_calc": 0,
        "margin_too_high": 0,
        "margin_exceeds_limit": 0,
        "insufficient_data": 0,
        "volatility_out_of_range": 0,
        "passed_all_filters": 0
    }
    
    for future in futures:
        processed += 1
        print(f"[{processed}/{len(futures)}] ", end="", flush=True)
        
        result = analyze_instrument(
            client=client,
            collector=collector,
            figi=future["figi"],
            ticker=future["ticker"],
            name=future["name"],
            balance=args.balance,
            max_margin=max_margin,
            volatility_min=args.volatility_min,
            volatility_max=args.volatility_max,
            period_days=args.period_days,
            stats=stats,
            check_volatility=not args.no_volatility_filter
        )
        
        if result:
            results.append(result)
            stats["passed_all_filters"] += 1
    
    # Filter and rank
    ranked_results = filter_and_rank_instruments(results, limit=args.limit)
    
    # Print results
    print_results(ranked_results)
    
    # Print statistics
    print(f"\n{'='*120}")
    print("СТАТИСТИКА ФИЛЬТРАЦИИ:")
    print(f"{'='*120}")
    print(f"Всего проанализировано: {len(futures)}")
    print(f"Прошли все фильтры: {stats['passed_all_filters']}")
    print(f"Отфильтровано по причине:")
    print(f"  - Не удалось получить цену: {stats['no_price']}")
    print(f"  - Не удалось рассчитать ГО: {stats['no_margin_calc']}")
    print(f"  - ГО превышает баланс: {stats['margin_too_high']}")
    print(f"  - ГО превышает лимит ({max_margin:.2f} ₽): {stats['margin_exceeds_limit']}")
    print(f"  - Недостаточно исторических данных: {stats['insufficient_data']}")
    if not args.no_volatility_filter:
        print(f"  - Волатильность вне диапазона [{args.volatility_min}%-{args.volatility_max}%]: {stats['volatility_out_of_range']}")
    else:
        print(f"  - Фильтр по волатильности: ОТКЛЮЧЕН")
    print(f"{'='*120}\n")
    
    # Save to CSV
    if ranked_results:
        save_to_csv(ranked_results, args.output)
    
    print(f"\n✓ Analysis complete. Found {len(ranked_results)} optimal instruments out of {len(futures)} analyzed.")


if __name__ == "__main__":
    main()
