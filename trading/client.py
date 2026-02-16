"""Tinkoff Invest API client for trading operations."""
import os
import time
from typing import Any, Dict, Optional, List
from datetime import datetime, timedelta
import pandas as pd

try:
    from t_tech.invest import Client, CandleInterval, InstrumentIdType
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
    from t_tech.invest.schemas import Candle, HistoricCandle
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("[tinkoff] ⚠️ WARNING: t-tech-investments library not installed.")
    print("[tinkoff]   Install with: pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple")

from utils.logger import logger


class TinkoffClient:
    """
    Client for Tinkoff Invest API.
    Wrapper around t-tech-investments library for trading operations.
    """
    
    def __init__(self, token: Optional[str] = None, sandbox: bool = False):
        """
        Initialize Tinkoff client.
        
        Args:
            token: Tinkoff Invest API token (if None, reads from TINKOFF_TOKEN env var)
            sandbox: Use sandbox mode (default: False)
        """
        if not TINKOFF_AVAILABLE:
            raise ImportError(
                "t-tech-investments library is not installed. "
                "Install with: pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple"
            )
        
        self.token = token or os.getenv("TINKOFF_TOKEN", "").strip()
        self.sandbox = sandbox
        
        if not self.token:
            logger.warning("[tinkoff] ⚠️ WARNING: TINKOFF_TOKEN not found in environment variables!")
            logger.warning("[tinkoff]   Please set TINKOFF_TOKEN in .env file or environment")
        
        # Client will be initialized on first use
        self._client = None
        self._target = None
    
    def _get_client(self):
        """Create a new client instance for each use."""
        if not self.token:
            raise ValueError("TINKOFF_TOKEN is required. Set it in .env file or pass to constructor.")
        # Use target parameter instead of sandbox
        # INVEST_GRPC_API - боевой контур, INVEST_GRPC_API_SANDBOX - песочница
        if self._target is None:
            self._target = INVEST_GRPC_API_SANDBOX if self.sandbox else INVEST_GRPC_API
        return Client(self.token, target=self._target)
    
    def _convert_interval(self, interval: str) -> CandleInterval:
        """Convert interval string to Tinkoff CandleInterval."""
        interval_map = {
            "1min": CandleInterval.CANDLE_INTERVAL_1_MIN,
            "5min": CandleInterval.CANDLE_INTERVAL_5_MIN,
            "15min": CandleInterval.CANDLE_INTERVAL_15_MIN,
            "1hour": CandleInterval.CANDLE_INTERVAL_HOUR,
            "day": CandleInterval.CANDLE_INTERVAL_DAY,
        }
        return interval_map.get(interval.lower(), CandleInterval.CANDLE_INTERVAL_1_MIN)
    
    def get_candles(
        self,
        figi: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "1min"
    ) -> List[Dict[str, Any]]:
        """
        Get historical candles for instrument.
        
        Args:
            figi: Instrument FIGI
            from_date: Start date
            to_date: End date
            interval: Candle interval ("1min", "5min", "15min", "1hour", "day")
        
        Returns:
            List of candle dictionaries with keys: time, open, high, low, close, volume
        """
        try:
            candle_interval = self._convert_interval(interval)
            
            # Normalize dates (remove timezone if present)
            if from_date.tzinfo:
                from_date = from_date.replace(tzinfo=None)
            if to_date.tzinfo:
                to_date = to_date.replace(tzinfo=None)
            
            candles = []
            logger.debug(f"[get_candles] Starting for {figi}, from {from_date.date()} to {to_date.date()}, interval={interval}")
            with self._get_client() as client:
                # Tinkoff API может ограничивать количество свечей за запрос
                # Разбиваем на батчи по дням для надежности
                current_from = from_date
                day_count = 0
                total_days = (to_date - from_date).days + 1
                
                while current_from < to_date:
                    current_to = min(current_from + timedelta(days=1), to_date)
                    day_count += 1
                    
                    try:
                        logger.debug(f"[get_candles] Requesting candles for {figi}, day {day_count}/{total_days}: {current_from.date()}")
                        response = client.market_data.get_candles(
                            figi=figi,
                            from_=current_from,
                            to=current_to,
                            interval=candle_interval
                        )
                        logger.debug(f"[get_candles] Received {len(response.candles) if response.candles else 0} candles for {current_from.date()}")
                        
                        for candle in response.candles:
                            candles.append({
                                "time": candle.time,
                                "open": float(candle.open.units) + float(candle.open.nano) / 1e9,
                                "high": float(candle.high.units) + float(candle.high.nano) / 1e9,
                                "low": float(candle.low.units) + float(candle.low.nano) / 1e9,
                                "close": float(candle.close.units) + float(candle.close.nano) / 1e9,
                                "volume": candle.volume,
                            })
                    except Exception as e:
                        logger.warning(f"Error getting candles for {figi} from {current_from} to {current_to}: {e}")
                    
                    current_from = current_to
                    time.sleep(0.1)  # Rate limiting
            
            return candles
        except Exception as e:
            logger.error(f"Error getting candles for {figi}: {e}")
            return []
    
    def find_instrument(
        self,
        ticker: str,
        instrument_type: Optional[str] = "futures",
        prefer_perpetual: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Find instrument by ticker.
        
        Args:
            ticker: Instrument ticker (e.g., "Si-3.25")
            instrument_type: Filter by type ("futures", "shares", "bonds", etc.)
            prefer_perpetual: If True, prefer perpetual futures
        
        Returns:
            Dict with instrument info: figi, ticker, name, instrument_type
        """
        try:
            logger.debug(f"[find_instrument] Starting search for ticker={ticker}, type={instrument_type}")
            with self._get_client() as client:
                # Сначала пробуем использовать find_instrument для быстрого поиска
                try:
                    from t_tech.invest.schemas import InstrumentType
                    instrument_kind = None
                    if instrument_type == "futures":
                        instrument_kind = InstrumentType.INSTRUMENT_TYPE_FUTURES
                    elif instrument_type == "shares":
                        instrument_kind = InstrumentType.INSTRUMENT_TYPE_SHARE
                    elif instrument_type == "bonds":
                        instrument_kind = InstrumentType.INSTRUMENT_TYPE_BOND
                    
                    # Пробуем поиск по точному тикеру
                    logger.debug(f"[find_instrument] Calling client.instruments.find_instrument() for {ticker}...")
                    find_response = client.instruments.find_instrument(
                        query=ticker,
                        instrument_kind=instrument_kind,
                        api_trade_available_flag=True
                    )
                    logger.debug(f"[find_instrument] find_instrument() completed, found {len(find_response.instruments) if find_response.instruments else 0} instruments")
                    
                    if find_response.instruments:
                        # Найдены инструменты, берем первый подходящий по тикеру
                        for inst in find_response.instruments:
                            if inst.ticker.upper() == ticker.upper():
                                logger.info(f"Found instrument via find_instrument: {inst.ticker} ({inst.figi})")
                                return {
                                    "figi": inst.figi,
                                    "ticker": inst.ticker,
                                    "name": inst.name,
                                    "instrument_type": instrument_type
                                }
                        
                        # Если точного совпадения нет, но есть результаты, берем первый
                        if find_response.instruments:
                            inst = find_response.instruments[0]
                            logger.info(f"Found instrument via find_instrument (partial match): {inst.ticker} ({inst.figi})")
                            return {
                                "figi": inst.figi,
                                "ticker": inst.ticker,
                                "name": inst.name,
                                "instrument_type": instrument_type
                            }
                except Exception as e:
                    logger.debug(f"find_instrument failed, falling back to full list: {e}")
                
                # Fallback: перебор всех инструментов
                if instrument_type == "futures":
                    # Ищем фьючерсы
                    logger.debug(f"[find_instrument] Fallback: Searching through all futures for ticker: {ticker}")
                    logger.debug(f"[find_instrument] Calling client.instruments.futures()...")
                    response = client.instruments.futures()
                    logger.debug(f"[find_instrument] futures() completed, Total futures found: {len(response.instruments)}")
                    
                    # Сначала ищем точное совпадение
                    matching_instruments = []
                    for instrument in response.instruments:
                        if instrument.ticker.upper() == ticker.upper():
                            matching_instruments.append(instrument)
                    
                    if matching_instruments:
                        # Если prefer_perpetual, ищем бессрочные контракты
                        if prefer_perpetual:
                            for instrument in matching_instruments:
                                if "perpetual" in instrument.name.lower():
                                    logger.info(f"Found perpetual future: {instrument.ticker} ({instrument.figi})")
                                    return {
                                        "figi": instrument.figi,
                                        "ticker": instrument.ticker,
                                        "name": instrument.name,
                                        "instrument_type": "futures"
                                    }
                        
                        # Возвращаем первый найденный
                        instrument = matching_instruments[0]
                        logger.info(f"Found future: {instrument.ticker} ({instrument.figi})")
                        return {
                            "figi": instrument.figi,
                            "ticker": instrument.ticker,
                            "name": instrument.name,
                            "instrument_type": "futures"
                        }
                    
                    # Если не нашли, выводим список доступных тикеров для отладки
                    available_tickers = [inst.ticker for inst in response.instruments[:20]]
                    logger.warning(f"Available futures tickers (first 20): {available_tickers}")
                    
                    # Также пробуем поиск по частичному совпадению
                    partial_matches = []
                    ticker_upper = ticker.upper()
                    for instrument in response.instruments:
                        if ticker_upper in instrument.ticker.upper() or instrument.ticker.upper() in ticker_upper:
                            partial_matches.append(instrument)
                    
                    if partial_matches:
                        logger.info(f"Found {len(partial_matches)} partial matches for '{ticker}':")
                        for inst in partial_matches[:5]:
                            logger.info(f"  {inst.ticker} - {inst.name}")
                        # Возвращаем первый частичный матч
                        instrument = partial_matches[0]
                        return {
                            "figi": instrument.figi,
                            "ticker": instrument.ticker,
                            "name": instrument.name,
                            "instrument_type": "futures"
                        }
                
                # Поиск акций
                elif instrument_type == "shares":
                    response = client.instruments.shares()
                    for instrument in response.instruments:
                        if instrument.ticker.upper() == ticker.upper():
                            return {
                                "figi": instrument.figi,
                                "ticker": instrument.ticker,
                                "name": instrument.name,
                                "instrument_type": "shares"
                            }
                
                # Поиск облигаций
                elif instrument_type == "bonds":
                    response = client.instruments.bonds()
                    for instrument in response.instruments:
                        if instrument.ticker.upper() == ticker.upper():
                            return {
                                "figi": instrument.figi,
                                "ticker": instrument.ticker,
                                "name": instrument.name,
                                "instrument_type": "bonds"
                            }
            
            logger.warning(f"[find_instrument] Instrument {ticker} ({instrument_type}) not found")
            return None
        except Exception as e:
            logger.error(f"[find_instrument] Error finding instrument {ticker}: {e}", exc_info=True)
            return None
    
    def get_kline_df(
        self,
        figi: str,
        interval: str,
        limit: int = 200,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Get candles as DataFrame (compatible with BybitClient interface).
        
        Args:
            figi: Instrument FIGI
            interval: Candle interval
            limit: Number of candles to retrieve
            start: Start time (optional)
            end: End time (optional, defaults to now)
        
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if end is None:
            end = datetime.now()
        
        if start is None:
            # Calculate start based on limit and interval
            interval_map = {
                "1min": timedelta(minutes=1),
                "5min": timedelta(minutes=5),
                "15min": timedelta(minutes=15),
                "1hour": timedelta(hours=1),
                "day": timedelta(days=1),
            }
            delta = interval_map.get(interval.lower(), timedelta(minutes=1))
            start = end - (delta * limit)
        
        candles = self.get_candles(figi, start, end, interval)
        
        if not candles:
            return pd.DataFrame()
        
        # Convert to DataFrame
        rows = []
        for candle in candles:
            # Convert time to timestamp (milliseconds)
            if isinstance(candle["time"], datetime):
                ts = int(candle["time"].timestamp() * 1000)
            else:
                ts = int(pd.Timestamp(candle["time"]).timestamp() * 1000)
            
            rows.append({
                "timestamp": ts,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            })
        
        df = pd.DataFrame(rows)
        df = df.sort_values("timestamp").reset_index(drop=True)
        
        # Limit to requested number
        if len(df) > limit:
            df = df.tail(limit).reset_index(drop=True)
        
        return df
    
    def get_position_info(self, figi: Optional[str] = None) -> Dict[str, Any]:
        """
        Get open positions.
        
        Args:
            figi: Instrument FIGI (optional, if None returns all positions)
        
        Returns:
            Dict with position information
        """
        try:
            logger.debug(f"[get_position_info] Starting, figi={figi}")
            with self._get_client() as client:
                logger.debug("[get_position_info] Calling client.users.get_accounts()...")
                accounts = client.users.get_accounts()
                logger.debug(f"[get_position_info] get_accounts() completed, found {len(accounts.accounts) if accounts.accounts else 0} accounts")
                
                if not accounts.accounts:
                    logger.warning("[get_position_info] No accounts found")
                    return {"retCode": -1, "retMsg": "No accounts found", "result": {"list": []}}
                
                account_id = accounts.accounts[0].id
                logger.debug(f"[get_position_info] Calling client.operations.get_portfolio() for account_id={account_id}...")
                response = client.operations.get_portfolio(account_id=account_id)
                logger.debug(f"[get_position_info] get_portfolio() completed, found {len(response.positions) if response.positions else 0} positions")
                
                # Логируем поля портфеля для диагностики доступного баланса
                portfolio_info = {}
                if hasattr(response, 'total_amount_portfolio'):
                    try:
                        total = float(response.total_amount_portfolio.units) + float(response.total_amount_portfolio.nano) / 1e9
                        portfolio_info['total_amount_portfolio'] = total
                    except:
                        pass
                if hasattr(response, 'available_withdrawal_draw_limit'):
                    try:
                        available = float(response.available_withdrawal_draw_limit.units) + float(response.available_withdrawal_draw_limit.nano) / 1e9
                        portfolio_info['available_withdrawal_draw_limit'] = available
                    except:
                        pass
                if hasattr(response, 'available_amount'):
                    try:
                        available = float(response.available_amount.units) + float(response.available_amount.nano) / 1e9
                        portfolio_info['available_amount'] = available
                    except:
                        pass
                if portfolio_info:
                    logger.info(f"📊 Portfolio-level info: {portfolio_info}")
                
                positions = []
                total_blocked_margin = 0.0  # Общая замороженная маржа из валютной позиции
                
                for position in response.positions:
                    if figi is None or position.figi == figi:
                        pos_data = {
                            "figi": position.figi,
                            "quantity": float(position.quantity.units) + float(position.quantity.nano) / 1e9,
                            "average_price": float(position.average_position_price.units) + float(position.average_position_price.nano) / 1e9,
                            "current_price": float(position.current_price.units) + float(position.current_price.nano) / 1e9,
                        }
                        
                        # Для валютной позиции (RUB000UTSTOM) blocked_lots содержит общую замороженную маржу
                        if position.figi == "RUB000UTSTOM":
                            # Currency position - логируем только на debug уровне
                            logger.debug(f"🔍 Found currency position RUB000UTSTOM, checking margin-related fields...")
                            
                            # Логируем все поля, связанные с маржой (только на debug уровне)
                            margin_fields = {}
                            for attr_name in ['blocked_lots', 'blocked', 'initial_margin', 'current_margin', 'quantity']:
                                if hasattr(position, attr_name):
                                    attr_value = getattr(position, attr_name)
                                    margin_fields[attr_name] = {
                                        'type': type(attr_value).__name__,
                                        'value': str(attr_value)[:100] if attr_value is not None else 'None'
                                    }
                                    # Если это MoneyValue объект, извлекаем значение
                                    if attr_value is not None and hasattr(attr_value, 'units') and hasattr(attr_value, 'nano'):
                                        try:
                                            value = float(attr_value.units) + float(attr_value.nano) / 1e9
                                            margin_fields[attr_name]['extracted_value'] = value
                                        except (ValueError, TypeError):
                                            pass
                            
                            logger.debug(f"📊 Currency position margin fields: {margin_fields}")
                            
                            if hasattr(position, 'blocked_lots'):
                                try:
                                    blocked_lots = position.blocked_lots
                                    logger.debug(f"blocked_lots type: {type(blocked_lots)}, value: {blocked_lots}")
                                    if hasattr(blocked_lots, 'units') and hasattr(blocked_lots, 'nano'):
                                        total_blocked_margin = float(blocked_lots.units) + float(blocked_lots.nano) / 1e9
                                        pos_data["blocked_margin"] = total_blocked_margin
                                        if total_blocked_margin > 0:
                                            logger.info(f"✅ Found total blocked margin in currency position: {total_blocked_margin:.2f} руб")
                                        else:
                                            logger.debug(f"⚠️ blocked_lots is 0.00 руб - this may indicate no frozen margin OR API issue")
                                    else:
                                        logger.warning(f"⚠️ blocked_lots exists but doesn't have units/nano attributes. Type: {type(blocked_lots)}")
                                except (AttributeError, TypeError) as e:
                                    logger.warning(f"Error parsing blocked_lots for currency: {e}, type: {type(position.blocked_lots) if hasattr(position, 'blocked_lots') else 'N/A'}")
                            else:
                                logger.warning(f"Currency position RUB000UTSTOM found but no blocked_lots attribute. Available attributes: {[attr for attr in dir(position) if not attr.startswith('_')]}")
                        
                        # Добавляем информацию о гарантийном обеспечении (марже), если доступна
                        # Для фьючерсов это важная информация для понимания распределения депозита
                        # Проверяем, что поле существует и является объектом MoneyValue, а не bool
                        if hasattr(position, 'initial_margin') and position.initial_margin is not None:
                            try:
                                initial_margin = position.initial_margin
                                # Проверяем, что это объект с атрибутами units и nano, а не bool
                                if hasattr(initial_margin, 'units') and hasattr(initial_margin, 'nano'):
                                    pos_data["initial_margin"] = float(initial_margin.units) + float(initial_margin.nano) / 1e9
                            except (AttributeError, TypeError) as e:
                                logger.debug(f"Error parsing initial_margin for {position.figi}: {e}")
                        
                        if hasattr(position, 'current_margin') and position.current_margin is not None:
                            try:
                                current_margin = position.current_margin
                                if hasattr(current_margin, 'units') and hasattr(current_margin, 'nano'):
                                    pos_data["current_margin"] = float(current_margin.units) + float(current_margin.nano) / 1e9
                            except (AttributeError, TypeError) as e:
                                logger.debug(f"Error parsing current_margin for {position.figi}: {e}")
                        
                        if hasattr(position, 'blocked') and position.blocked is not None:
                            try:
                                blocked = position.blocked
                                if hasattr(blocked, 'units') and hasattr(blocked, 'nano'):
                                    pos_data["blocked"] = float(blocked.units) + float(blocked.nano) / 1e9
                            except (AttributeError, TypeError) as e:
                                logger.debug(f"Error parsing blocked for {position.figi}: {e}")
                        
                        # Вариационная маржа (текущий PnL по позиции)
                        if hasattr(position, 'expected_yield') and position.expected_yield is not None:
                            try:
                                expected_yield = position.expected_yield
                                if hasattr(expected_yield, 'units') and hasattr(expected_yield, 'nano'):
                                    pos_data["expected_yield"] = float(expected_yield.units) + float(expected_yield.nano) / 1e9
                            except (AttributeError, TypeError) as e:
                                logger.debug(f"Error parsing expected_yield for {position.figi}: {e}")
                        
                        # Стоимость позиции
                        if hasattr(position, 'current_nkd') and position.current_nkd is not None:
                            try:
                                current_nkd = position.current_nkd
                                if hasattr(current_nkd, 'units') and hasattr(current_nkd, 'nano'):
                                    pos_data["current_nkd"] = float(current_nkd.units) + float(current_nkd.nano) / 1e9
                            except (AttributeError, TypeError) as e:
                                logger.debug(f"Error parsing current_nkd for {position.figi}: {e}")
                        
                        positions.append(pos_data)
                
                result = {
                    "retCode": 0,
                    "result": {
                        "list": positions,
                        "total_blocked_margin": total_blocked_margin  # Общая замороженная маржа
                    }
                }
                
                if total_blocked_margin > 0:
                    logger.debug(f"Total blocked margin from API: {total_blocked_margin:.2f} руб")
                
                return result
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return {"retCode": -1, "retMsg": str(e), "result": {"list": []}}
    
    def get_wallet_balance(self) -> Dict[str, Any]:
        """Get wallet balance and available funds."""
        import signal
        
        try:
            with self._get_client() as client:
                # Добавляем таймаут для вызова get_accounts
                logger.debug("[get_wallet_balance] Calling get_accounts()...")
                try:
                    accounts = client.users.get_accounts()
                    logger.debug(f"[get_wallet_balance] get_accounts() completed, found {len(accounts.accounts) if accounts.accounts else 0} accounts")
                except Exception as e:
                    logger.error(f"[get_wallet_balance] Error calling get_accounts(): {e}", exc_info=True)
                    return {"retCode": -1, "retMsg": f"Error getting accounts: {str(e)}", "result": {"list": []}}
                
                if not accounts.accounts:
                    return {"retCode": -1, "retMsg": "No accounts found", "result": {"list": []}}
                
                account_id = accounts.accounts[0].id
                logger.debug(f"[get_wallet_balance] Calling get_portfolio() for account_id={account_id}...")
                try:
                    portfolio = client.operations.get_portfolio(account_id=account_id)
                    logger.debug("[get_wallet_balance] get_portfolio() completed")
                except Exception as e:
                    logger.error(f"[get_wallet_balance] Error calling get_portfolio(): {e}", exc_info=True)
                    return {"retCode": -1, "retMsg": f"Error getting portfolio: {str(e)}", "result": {"list": []}}
                
                # Get total amount
                total_amount = float(portfolio.total_amount_portfolio.units) + float(portfolio.total_amount_portfolio.nano) / 1e9
                
                # Get available funds (not locked in positions)
                # Try to get available_withdrawal_draw_limit or available_amount
                available_amount = total_amount
                if hasattr(portfolio, 'available_withdrawal_draw_limit'):
                    available_amount = float(portfolio.available_withdrawal_draw_limit.units) + float(portfolio.available_withdrawal_draw_limit.nano) / 1e9
                elif hasattr(portfolio, 'available_amount'):
                    available_amount = float(portfolio.available_amount.units) + float(portfolio.available_amount.nano) / 1e9
                
                # If available is 0 or negative, use total as fallback but log warning
                if available_amount <= 0:
                    logger.warning(f"Available funds is {available_amount}, using total amount {total_amount} as fallback")
                    available_amount = total_amount
                
                return {
                    "retCode": 0,
                    "result": {
                        "list": [{
                            "coin": [{
                                "coin": "RUB",
                                "walletBalance": str(total_amount),
                                "availableBalance": str(available_amount)  # Available funds for trading
                            }]
                        }]
                    }
                }
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return {"retCode": -1, "retMsg": str(e), "result": {"list": []}}
    
    def place_order(
        self,
        figi: str,
        quantity: int,
        direction: str,  # "Buy" or "Sell"
        order_type: str = "Market",
        price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Place order.
        
        Args:
            figi: Instrument FIGI
            quantity: Quantity (in lots for futures)
            direction: "Buy" or "Sell"
            order_type: "Market" or "Limit"
            price: Price for limit orders
        
        Returns:
            Order response
        """
        try:
            from t_tech.invest import OrderDirection, OrderType
            
            with self._get_client() as client:
                accounts = client.users.get_accounts()
                if not accounts.accounts:
                    return {"retCode": -1, "retMsg": "No accounts found"}
                
                account_id = accounts.accounts[0].id
                
                direction_enum = OrderDirection.ORDER_DIRECTION_BUY if direction == "Buy" else OrderDirection.ORDER_DIRECTION_SELL
                order_type_enum = OrderType.ORDER_TYPE_MARKET if order_type == "Market" else OrderType.ORDER_TYPE_LIMIT
                
                if order_type == "Market":
                    response = client.orders.post_order(
                        figi=figi,
                        quantity=quantity,
                        direction=direction_enum,
                        account_id=account_id,
                        order_type=order_type_enum
                    )
                else:
                    if price is None:
                        return {"retCode": -1, "retMsg": "Price required for limit orders"}
                    response = client.orders.post_order(
                        figi=figi,
                        quantity=quantity,
                        price=price,
                        direction=direction_enum,
                        account_id=account_id,
                        order_type=order_type_enum
                    )
                
                return {
                    "retCode": 0,
                    "result": {
                        "orderId": response.order_id,
                        "executedOrderPrice": float(response.executed_order_price.units) + float(response.executed_order_price.nano) / 1e9,
                    }
                }
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"retCode": -1, "retMsg": str(e)}
    
    def get_instrument_info(self, figi: str) -> Optional[Dict[str, Any]]:
        """
        Get full instrument information including margin requirements.
        
        Args:
            figi: Instrument FIGI
            
        Returns:
            Dict with instrument info including margin-related fields
        """
        try:
            logger.debug(f"[get_instrument_info] Starting for {figi}")
            with self._get_client() as client:
                response = client.instruments.get_instrument_by(id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, id=figi)
                instrument = response.instrument
                
                info = {
                    "figi": figi,
                    "ticker": getattr(instrument, 'ticker', ''),
                    "name": getattr(instrument, 'name', ''),
                }
                
                # Lot size
                if hasattr(instrument, 'lot'):
                    info['lot'] = float(instrument.lot)
                else:
                    info['lot'] = 1.0
                
                # Price step (минимальный шаг цены)
                if hasattr(instrument, 'min_price_increment'):
                    inc = instrument.min_price_increment
                    if hasattr(inc, 'units') and hasattr(inc, 'nano'):
                        info['min_price_increment'] = float(inc.units) + float(inc.nano) / 1e9
                    else:
                        info['min_price_increment'] = 0.01
                else:
                    info['min_price_increment'] = 0.01
                
                # Стоимость шага цены (min_price_increment_amount) - ЭТО РЕАЛЬНАЯ СТОИМОСТЬ ПУНКТА!
                # Формула: стоимость пункта = min_price_increment_amount
                if hasattr(instrument, 'min_price_increment_amount'):
                    inc_amount = instrument.min_price_increment_amount
                    if hasattr(inc_amount, 'units') and hasattr(inc_amount, 'nano'):
                        info['min_price_increment_amount'] = float(inc_amount.units) + float(inc_amount.nano) / 1e9
                        logger.debug(f"[get_instrument_info] {figi} min_price_increment_amount (стоимость пункта): {info['min_price_increment_amount']:.2f} руб")
                    elif hasattr(inc_amount, 'units'):
                        info['min_price_increment_amount'] = float(inc_amount.units)
                else:
                    info['min_price_increment_amount'] = None
                
                # Извлекаем коэффициенты гарантийного обеспечения (dlong, dshort)
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
                
                # dlong - гарантийное обеспечение для LONG позиции
                if hasattr(instrument, 'dlong'):
                    dlong = extract_money_value(instrument.dlong)
                    if dlong is not None:
                        info['dlong'] = dlong
                        logger.debug(f"[get_instrument_info] {figi} dlong (LONG margin): {dlong:.2f} руб")
                
                # dshort - гарантийное обеспечение для SHORT позиции
                if hasattr(instrument, 'dshort'):
                    dshort = extract_money_value(instrument.dshort)
                    if dshort is not None:
                        info['dshort'] = dshort
                        logger.debug(f"[get_instrument_info] {figi} dshort (SHORT margin): {dshort:.2f} руб")
                
                # dlong_client - гарантийное обеспечение для клиента (LONG)
                if hasattr(instrument, 'dlong_client'):
                    dlong_client = extract_money_value(instrument.dlong_client)
                    if dlong_client is not None:
                        info['dlong_client'] = dlong_client
                
                # dshort_client - гарантийное обеспечение для клиента (SHORT)
                if hasattr(instrument, 'dshort_client'):
                    dshort_client = extract_money_value(instrument.dshort_client)
                    if dshort_client is not None:
                        info['dshort_client'] = dshort_client
                
                # klong, kshort - коэффициенты для расчета маржи
                if hasattr(instrument, 'klong'):
                    klong = extract_money_value(instrument.klong)
                    if klong is not None:
                        info['klong'] = klong
                
                if hasattr(instrument, 'kshort'):
                    kshort = extract_money_value(instrument.kshort)
                    if kshort is not None:
                        info['kshort'] = kshort
                
                # Логируем все поля инструмента для диагностики маржи
                margin_related_fields = {}
                for attr_name in dir(instrument):
                    if not attr_name.startswith('_') and any(keyword in attr_name.lower() for keyword in ['margin', 'lot', 'price', 'step', 'min', 'initial', 'blocked']):
                        try:
                            attr_value = getattr(instrument, attr_name)
                            if attr_value is not None:
                                margin_related_fields[attr_name] = {
                                    'type': type(attr_value).__name__,
                                    'value': str(attr_value)[:200]
                                }
                                # Если это MoneyValue или Quotation, извлекаем значение
                                if hasattr(attr_value, 'units') and hasattr(attr_value, 'nano'):
                                    try:
                                        value = float(attr_value.units) + float(attr_value.nano) / 1e9
                                        margin_related_fields[attr_name]['extracted_value'] = value
                                    except (ValueError, TypeError):
                                        pass
                        except Exception as e:
                            margin_related_fields[attr_name] = {'error': str(e)}
                
                if margin_related_fields:
                    logger.debug(f"📊 Instrument {figi} margin-related fields: {list(margin_related_fields.keys())}")
                    info['margin_fields'] = margin_related_fields
                
                return info
        except Exception as e:
            logger.error(f"Error getting instrument info for {figi}: {e}")
            return None
    
    def get_qty_step(self, figi: str) -> float:
        """Get quantity step (lot size) for instrument."""
        try:
            logger.debug(f"[get_qty_step] Starting for {figi}")
            with self._get_client() as client:
                # Get instrument info
                logger.debug(f"[get_qty_step] Calling client.instruments.get_instrument_by() for {figi}...")
                response = client.instruments.get_instrument_by(id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, id=figi)
                logger.debug(f"[get_qty_step] get_instrument_by() completed for {figi}")
                instrument = response.instrument
                
                if hasattr(instrument, 'lot'):
                    return float(instrument.lot)
                return 1.0  # Default
        except Exception as e:
            logger.warning(f"Error getting lot size for {figi}: {e}")
            return 1.0
    
    def get_price_step(self, figi: str) -> float:
        """Get price step (min price increment) for instrument."""
        try:
            with self._get_client() as client:
                response = client.instruments.get_instrument_by(id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI, id=figi)
                instrument = response.instrument
                
                if hasattr(instrument, 'min_price_increment'):
                    inc = instrument.min_price_increment
                    return float(inc.units) + float(inc.nano) / 1e9
                return 0.01  # Default
        except Exception as e:
            logger.warning(f"Error getting price step for {figi}: {e}")
            return 0.01
    
    def get_futures_margin(self, figi: str) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о марже для фьючерса через get_futures_margin API.
        
        Этот метод возвращает актуальные данные о марже, включая:
        - min_price_increment_amount (стоимость пункта)
        - initial_margin (начальная маржа)
        - другие параметры маржи
        
        Args:
            figi: FIGI инструмента
            
        Returns:
            Dict с данными о марже или None при ошибке
        """
        try:
            logger.debug(f"[get_futures_margin] Getting margin info for {figi}")
            with self._get_client() as client:
                try:
                    margin_response = client.instruments.get_futures_margin(figi=figi)
                    
                    def quotation_to_float(quotation) -> Optional[float]:
                        """Преобразование Quotation в float"""
                        if quotation is None:
                            return None
                        if hasattr(quotation, 'units') and hasattr(quotation, 'nano'):
                            return float(quotation.units) + float(quotation.nano) / 1_000_000_000
                        try:
                            return float(quotation)
                        except:
                            return None
                    
                    margin_info = {}
                    
                    # ВАЖНО: Используем initial_margin_on_buy/sell напрямую - это готовые значения ГО для 1 лота
                    # Эти значения обновляются биржей каждый день после клиринга
                    # Пробуем прямой доступ к полям ответа
                    for attr_name in ['initial_margin_on_buy', 'initial_margin_on_sell']:
                        if hasattr(margin_response, attr_name):
                            value = getattr(margin_response, attr_name)
                            float_value = quotation_to_float(value)
                            if float_value is not None and float_value > 0:
                                margin_info[attr_name] = float_value
                                logger.info(f"[get_futures_margin] {figi} {attr_name}: {float_value:.2f} ₽ (ГО для {'LONG' if 'buy' in attr_name else 'SHORT'})")
                    
                    # Если не получилось через прямой доступ, пробуем через initial_margin_response
                    if 'initial_margin_on_buy' not in margin_info or 'initial_margin_on_sell' not in margin_info:
                        if hasattr(margin_response, 'initial_margin_response'):
                            initial_margin = margin_response.initial_margin_response
                            
                            # Пробуем получить initial_margin_on_buy/sell из вложенного объекта
                            for attr_name in ['initial_margin_on_buy', 'initial_margin_on_sell']:
                                if hasattr(initial_margin, attr_name) and attr_name not in margin_info:
                                    value = getattr(initial_margin, attr_name)
                                    float_value = quotation_to_float(value)
                                    if float_value is not None and float_value > 0:
                                        margin_info[attr_name] = float_value
                                        logger.info(f"[get_futures_margin] {figi} {attr_name} (из initial_margin_response): {float_value:.2f} ₽")
                    
                    # Извлекаем min_price_increment_amount (стоимость пункта) для справки
                    if hasattr(margin_response, 'min_price_increment_amount'):
                        point_value = quotation_to_float(margin_response.min_price_increment_amount)
                        if point_value is not None:
                            margin_info['min_price_increment_amount'] = point_value
                            logger.debug(f"[get_futures_margin] {figi} min_price_increment_amount: {point_value:.6f} ₽")
                    
                    # Пробуем получить initial_margin_response (старый формат, если есть)
                    if hasattr(margin_response, 'initial_margin_response'):
                        initial_margin = margin_response.initial_margin_response
                        
                        # Извлекаем min_price_increment_amount (стоимость пункта)
                        if hasattr(initial_margin, 'min_price_increment_amount'):
                            point_value = quotation_to_float(initial_margin.min_price_increment_amount)
                            if point_value is not None and 'min_price_increment_amount' not in margin_info:
                                margin_info['min_price_increment_amount'] = point_value
                                logger.debug(f"[get_futures_margin] {figi} min_price_increment_amount: {point_value:.6f} ₽")
                        
                        # Извлекаем initial_margin (начальная маржа) - fallback
                        if hasattr(initial_margin, 'initial_margin') and 'initial_margin_on_buy' not in margin_info:
                            initial_margin_value = quotation_to_float(initial_margin.initial_margin)
                            if initial_margin_value is not None:
                                margin_info['initial_margin'] = initial_margin_value
                                logger.debug(f"[get_futures_margin] {figi} initial_margin: {initial_margin_value:.2f} ₽")
                    
                    # Пробуем прямой доступ к полям ответа (fallback)
                    for attr_name in ['min_price_increment_amount', 'initial_margin', 'margin']:
                        if hasattr(margin_response, attr_name) and attr_name not in margin_info:
                            value = getattr(margin_response, attr_name)
                            if hasattr(value, 'units') and hasattr(value, 'nano'):
                                float_value = quotation_to_float(value)
                                if float_value is not None:
                                    margin_info[attr_name] = float_value
                                    logger.debug(f"[get_futures_margin] {figi} {attr_name}: {float_value:.6f} ₽")
                    
                    if margin_info:
                        logger.info(f"[get_futures_margin] {figi} ✅ Получена информация о марже: {margin_info}")
                        return margin_info
                    else:
                        logger.warning(f"[get_futures_margin] {figi} ⚠️ Не удалось извлечь данные о марже из ответа")
                        return None
                        
                except AttributeError as e:
                    logger.warning(f"[get_futures_margin] {figi} ⚠️ Метод get_futures_margin недоступен или вернул неожиданный формат: {e}")
                    return None
                except Exception as e:
                    logger.error(f"[get_futures_margin] {figi} ❌ Ошибка при получении маржи: {e}", exc_info=True)
                    return None
        except Exception as e:
            logger.error(f"[get_futures_margin] {figi} ❌ Ошибка при создании клиента: {e}")
            return None
    
    def round_price(self, price: float, figi: str) -> float:
        """Round price to minimum increment."""
        try:
            step = self.get_price_step(figi)
            if step > 0:
                return round(price / step) * step
            return price
        except Exception as e:
            logger.warning(f"Error rounding price: {e}")
            return price
