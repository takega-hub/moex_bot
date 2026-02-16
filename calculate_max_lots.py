"""
Скрипт для расчета максимального количества лотов на основе баланса и ГО.

Использует формулу: max_lots = balance / margin_per_lot
где margin_per_lot = point_value * price * dlong/dshort
"""
import os
import sys
import argparse
from dotenv import load_dotenv
from typing import Optional

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

from bot.margin_rates import (
    calculate_max_lots,
    get_margin_per_lot_from_api_data,
    MARGIN_PER_LOT
)


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


def get_instrument_figi(ticker: str, client: Client) -> Optional[str]:
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


def get_account_balance(client: Client, account_id: str) -> float:
    """Получить баланс счета."""
    try:
        portfolio = client.operations.get_portfolio(account_id=account_id)
        if hasattr(portfolio, 'total_amount_portfolio') and portfolio.total_amount_portfolio:
            return extract_money_value(portfolio.total_amount_portfolio)
        if hasattr(portfolio, 'total_amount_currencies') and portfolio.total_amount_currencies:
            return extract_money_value(portfolio.total_amount_currencies)
    except Exception as e:
        print(f"   ⚠️ Ошибка получения баланса: {e}")
    return 0.0


def calculate_max_lots_for_instrument(
    ticker: str,
    balance: Optional[float] = None,
    is_long: bool = True,
    safety_buffer: float = 0.9
):
    """Рассчитать максимальное количество лотов для инструмента."""
    
    print(f"\n{'='*80}")
    print(f"📊 РАСЧЕТ МАКСИМАЛЬНОГО КОЛИЧЕСТВА ЛОТОВ")
    print(f"   Инструмент: {ticker.upper()}")
    print(f"   Направление: {'LONG' if is_long else 'SHORT'}")
    print(f"{'='*80}\n")

    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found!")
        sys.exit(1)

    with Client(token=token, target=INVEST_GRPC_API) as client:
        # Получаем FIGI
        figi = get_instrument_figi(ticker, client)
        if not figi:
            print(f"❌ Не найден FIGI для {ticker}")
            return

        # Получаем информацию об инструменте
        response = client.instruments.get_instrument_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi
        )
        instrument = response.instrument

        # Получаем текущую цену
        current_price = get_current_price(figi, client)
        if current_price == 0:
            print(f"❌ Не удалось получить цену для {ticker}")
            return

        # Извлекаем коэффициенты
        dlong = extract_money_value(getattr(instrument, 'dlong', None))
        dshort = extract_money_value(getattr(instrument, 'dshort', None))
        lot = float(getattr(instrument, 'lot', 1.0))
        
        # Получаем стоимость пункта (min_price_increment)
        min_price_increment = extract_money_value(getattr(instrument, 'min_price_increment', None))
        point_value = min_price_increment if min_price_increment and min_price_increment > 0 else None

        # Получаем баланс (если не указан)
        if balance is None:
            accounts = client.users.get_accounts()
            if accounts.accounts:
                account_id = accounts.accounts[0].id
                balance = get_account_balance(client, account_id)
            else:
                print("❌ Не найден счет")
                return

        print(f"📈 Данные инструмента:")
        print(f"   Название: {getattr(instrument, 'name', 'N/A')}")
        print(f"   Текущая цена: {current_price:.2f} ₽")
        print(f"   Лотность: {lot}")
        print(f"   dlong: {dlong:.6f}")
        print(f"   dshort: {dshort:.6f}")
        if point_value:
            print(f"   Стоимость пункта (min_price_increment): {point_value:.2f} ₽")
        else:
            print(f"   ⚠️ Стоимость пункта не найдена в API")

        print(f"\n💰 Баланс: {balance:.2f} ₽")
        print(f"   Используем {safety_buffer*100:.0f}% баланса: {balance * safety_buffer:.2f} ₽")

        # Получаем ГО за лот
        margin_per_lot = get_margin_per_lot_from_api_data(
            ticker=ticker,
            current_price=current_price,
            point_value=point_value,
            dlong=dlong,
            dshort=dshort,
            is_long=is_long
        )

        if margin_per_lot:
            print(f"\n📊 ГО за один лот: {margin_per_lot:.2f} ₽")
            
            # Показываем расчет
            if ticker.upper() in MARGIN_PER_LOT and MARGIN_PER_LOT[ticker.upper()] > 0:
                print(f"   Источник: Справочник MARGIN_PER_LOT")
            elif point_value:
                if is_long:
                    print(f"   Расчет: point_value * price * dlong = {point_value:.2f} * {current_price:.2f} * {dlong:.6f} = {margin_per_lot:.2f} ₽")
                else:
                    print(f"   Расчет: point_value * price * dshort = {point_value:.2f} * {current_price:.2f} * {dshort:.6f} = {margin_per_lot:.2f} ₽")
            else:
                print(f"   ⚠️ Не удалось определить источник ГО")

            # Рассчитываем максимальное количество лотов
            max_lots = calculate_max_lots(
                balance=balance,
                current_price=current_price,
                point_value=point_value,
                dlong=dlong,
                dshort=dshort,
                is_long=is_long,
                margin_per_lot=margin_per_lot,
                safety_buffer=safety_buffer
            )

            print(f"\n✅ МАКСИМАЛЬНОЕ КОЛИЧЕСТВО ЛОТОВ: {max_lots}")
            print(f"   Формула: max_lots = (balance * {safety_buffer}) / margin_per_lot")
            print(f"   Расчет: ({balance:.2f} * {safety_buffer}) / {margin_per_lot:.2f} = {max_lots}")

            if max_lots > 0:
                total_margin = margin_per_lot * max_lots
                print(f"\n💡 При открытии {max_lots} лот(ов):")
                print(f"   Общее ГО: {total_margin:.2f} ₽")
                print(f"   Остаток баланса: {balance - total_margin:.2f} ₽")
            else:
                print(f"\n❌ Недостаточно баланса для открытия хотя бы 1 лота")
                print(f"   Нужно минимум: {margin_per_lot:.2f} ₽")
        else:
            print(f"\n❌ Не удалось рассчитать ГО за лот")
            print(f"   Нужны: point_value, price, dlong/dshort")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Рассчитать максимальное количество лотов на основе баланса',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Расчет для LONG позиции
  python calculate_max_lots.py --ticker WUH6

  # Расчет для SHORT позиции
  python calculate_max_lots.py --ticker WUH6 --short

  # Указать баланс вручную
  python calculate_max_lots.py --ticker WUH6 --balance 10000

  # Изменить коэффициент безопасности (по умолчанию 0.9 = 90%)
  python calculate_max_lots.py --ticker WUH6 --safety-buffer 0.8
        """
    )
    parser.add_argument('--ticker', type=str, required=True, help='Тикер инструмента (например, WUH6)')
    parser.add_argument('--balance', type=float, help='Баланс в рублях (если не указан, берется из API)')
    parser.add_argument('--short', action='store_true', help='Рассчитать для SHORT позиции (по умолчанию LONG)')
    parser.add_argument('--safety-buffer', type=float, default=0.9, help='Коэффициент безопасности (0.9 = использовать 90% баланса)')

    args = parser.parse_args()

    calculate_max_lots_for_instrument(
        ticker=args.ticker,
        balance=args.balance,
        is_long=not args.short,
        safety_buffer=args.safety_buffer
    )
