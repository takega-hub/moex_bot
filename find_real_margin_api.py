#!/usr/bin/env python3
"""
Скрипт для поиска способа получения реального гарантийного обеспечения через API.
Пробует различные методы и поля API.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

try:
    from t_tech.invest import Client, InstrumentIdType
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
    from t_tech.invest.schemas import InstrumentType
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("❌ ERROR: t-tech-investments library not installed")
    sys.exit(1)


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
        from t_tech.invest import CandleInterval
        from datetime import datetime, timedelta, timezone
        
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


def explore_instrument_api(ticker: str, client: Client):
    """Исследовать все возможные способы получения маржи через API."""
    print(f"\n{'='*80}")
    print(f"🔍 ИССЛЕДОВАНИЕ API ДЛЯ {ticker}")
    print(f"{'='*80}\n")
    
    # Получаем FIGI
    figi = get_instrument_figi(ticker, client)
    if not figi:
        print(f"❌ Не найден FIGI для {ticker}")
        return
    
    print(f"✅ FIGI: {figi}\n")
    
    # 1. Получаем информацию об инструменте
    print("1️⃣ Информация об инструменте (get_instrument_by):")
    try:
        response = client.instruments.get_instrument_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi
        )
        instrument = response.instrument
        
        print(f"   Название: {getattr(instrument, 'name', 'N/A')}")
        print(f"   Тикер: {getattr(instrument, 'ticker', 'N/A')}")
        print(f"   Лот: {getattr(instrument, 'lot', 'N/A')}")
        
        # Ищем все поля, связанные с маржой
        print(f"\n   Поля, связанные с маржой:")
        margin_fields = {}
        for attr_name in dir(instrument):
            if attr_name.startswith('_'):
                continue
            attr_lower = attr_name.lower()
            if any(kw in attr_lower for kw in ['margin', 'guarantee', 'collateral', 'deposit', 'dlong', 'dshort', 'klong', 'kshort', 'initial', 'blocked']):
                try:
                    attr_value = getattr(instrument, attr_name)
                    if not callable(attr_value):
                        extracted = extract_money_value(attr_value)
                        if extracted is not None:
                            margin_fields[attr_name] = extracted
                            print(f"      {attr_name:25s} = {extracted:>15.4f} руб")
                        else:
                            print(f"      {attr_name:25s} = {str(attr_value)[:50]}")
                except:
                    pass
        
        # Получаем текущую цену
        current_price = get_current_price(figi, client)
        if current_price > 0:
            print(f"\n   Текущая цена: {current_price:.4f} руб")
            
            # Пробуем расчеты
            if 'klong' in margin_fields:
                klong = margin_fields['klong']
                lot = float(getattr(instrument, 'lot', 1.0))
                calc1 = current_price * klong
                calc2 = current_price * klong * lot
                print(f"\n   Расчеты через klong:")
                print(f"      price * klong = {current_price:.4f} * {klong:.2f} = {calc1:.2f} руб")
                print(f"      price * klong * lot = {calc1:.2f} * {lot:.0f} = {calc2:.2f} руб")
            
            if 'dlong' in margin_fields:
                dlong = margin_fields['dlong']
                lot = float(getattr(instrument, 'lot', 1.0))
                calc1 = dlong * lot
                print(f"\n   Расчеты через dlong:")
                print(f"      dlong * lot = {dlong:.4f} * {lot:.0f} = {calc1:.2f} руб")
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
    
    # 2. Пробуем получить через портфель (если есть открытая позиция)
    print(f"\n2️⃣ Информация из портфеля (get_portfolio):")
    try:
        accounts_response = client.users.get_accounts()
        if accounts_response.accounts:
            account_id = accounts_response.accounts[0].id
            portfolio_response = client.operations.get_portfolio(account_id=account_id)
            
            # Ищем позицию по этому инструменту
            found = False
            for position in portfolio_response.positions:
                if position.figi == figi:
                    found = True
                    print(f"   ✅ Найдена позиция для {ticker}")
                    
                    # Извлекаем все поля, связанные с маржой
                    print(f"\n   Поля позиции, связанные с маржой:")
                    for attr_name in dir(position):
                        if attr_name.startswith('_'):
                            continue
                        attr_lower = attr_name.lower()
                        if any(kw in attr_lower for kw in ['margin', 'guarantee', 'collateral', 'deposit', 'initial', 'current', 'blocked']):
                            try:
                                attr_value = getattr(position, attr_name)
                                if not callable(attr_value):
                                    extracted = extract_money_value(attr_value)
                                    if extracted is not None:
                                        print(f"      {attr_name:25s} = {extracted:>15.2f} руб")
                                    else:
                                        print(f"      {attr_name:25s} = {str(attr_value)[:50]}")
                            except:
                                pass
                    break
            
            if not found:
                print(f"   ⚠️ Нет открытой позиции для {ticker}")
                print(f"   💡 Для получения margin requirements нужна открытая позиция")
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
    
    # 3. Пробуем найти методы для расчета маржи
    print(f"\n3️⃣ Поиск методов для расчета маржи:")
    try:
        # Проверяем, есть ли специальные методы в operations service
        operations_service = client.operations
        print(f"   Доступные методы в operations:")
        for attr_name in dir(operations_service):
            if not attr_name.startswith('_') and callable(getattr(operations_service, attr_name)):
                if any(kw in attr_name.lower() for kw in ['margin', 'guarantee', 'collateral', 'calculate', 'estimate']):
                    print(f"      - {attr_name}")
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
    
    # 4. Сравнение с терминалом и поиск формулы
    print(f"\n4️⃣ Сравнение с терминалом и поиск формулы:")
    terminal_data_dict = {
        "NGG6": {"margin": 7667.72, "point_value": 0.0, "lot": 100, "price": 3.0},
        "PTH6": {"margin": 33860.23, "point_value": 77.19, "lot": 1, "price": 2049.7},
        "NRG6": {"margin": 0.0, "point_value": 0.0, "lot": 1, "price": 3.0},
        "SVH6": {"margin": 0.0, "point_value": 0.0, "lot": 1, "price": 78.0},
        "S1H6": {"margin": 1558.96, "point_value": 0.0, "lot": 1, "price": 77.0},
    }
    
    ticker_upper = ticker.upper()
    if ticker_upper in terminal_data_dict:
        terminal_data = terminal_data_dict[ticker_upper]
        terminal_margin = terminal_data["margin"]
        terminal_point_value = terminal_data.get("point_value", 0.0)
        terminal_lot = terminal_data.get("lot", 1.0)
        terminal_price = terminal_data.get("price", current_price)
        
        if terminal_margin > 0:
            print(f"   📱 Данные из терминала:")
            print(f"      Гарантийное обеспечение: {terminal_margin:.2f} ₽")
            if terminal_point_value > 0:
                print(f"      Стоимость пункта цены: {terminal_point_value:.2f} ₽")
            print(f"      Лотность: {terminal_lot}")
            print(f"      Цена: {terminal_price:.2f} ₽")
            
            # Пробуем найти формулу
            print(f"\n   🔍 Поиск формулы расчета ГО:")
            
            # Вариант 1: через dlong и реальную лотность
            if 'dlong' in margin_fields:
                dlong = margin_fields['dlong']
                api_lot = float(getattr(instrument, 'lot', 1.0))
                
                # Пробуем с API lot
                calc1 = dlong * api_lot
                diff1 = abs(calc1 - terminal_margin)
                match1 = "✅" if diff1 < 10 else "❌"
                print(f"      {match1} dlong * api_lot = {dlong:.4f} * {api_lot:.0f} = {calc1:.2f} ₽ (разница: {diff1:.2f} ₽)")
                
                # Пробуем с реальной лотностью из терминала
                if terminal_lot != api_lot:
                    calc2 = dlong * terminal_lot
                    diff2 = abs(calc2 - terminal_margin)
                    match2 = "✅" if diff2 < 10 else "❌"
                    print(f"      {match2} dlong * terminal_lot = {dlong:.4f} * {terminal_lot:.0f} = {calc2:.2f} ₽ (разница: {diff2:.2f} ₽)")
            
            # Вариант 2: через цену и klong
            if terminal_price > 0 and 'klong' in margin_fields:
                klong = margin_fields['klong']
                api_lot = float(getattr(instrument, 'lot', 1.0))
                
                calc1 = terminal_price * klong * api_lot
                diff1 = abs(calc1 - terminal_margin)
                match1 = "✅" if diff1 < 100 else "❌"
                print(f"      {match1} price * klong * api_lot = {terminal_price:.2f} * {klong:.2f} * {api_lot:.0f} = {calc1:.2f} ₽ (разница: {diff1:.2f} ₽)")
                
                if terminal_lot != api_lot:
                    calc2 = terminal_price * klong * terminal_lot
                    diff2 = abs(calc2 - terminal_margin)
                    match2 = "✅" if diff2 < 100 else "❌"
                    print(f"      {match2} price * klong * terminal_lot = {terminal_price:.2f} * {klong:.2f} * {terminal_lot:.0f} = {calc2:.2f} ₽ (разница: {diff2:.2f} ₽)")
            
            # Вариант 3: через стоимость пункта цены
            if terminal_point_value > 0:
                print(f"\n   💡 Расчеты через стоимость пункта цены:")
                margin_points = terminal_margin / terminal_point_value
                print(f"      ГО / стоимость_пункта = {terminal_margin:.2f} / {terminal_point_value:.2f} = {margin_points:.2f} пунктов")
                
                # Может быть, пункты маржи = цена * коэффициент?
                if terminal_price > 0:
                    points_per_price = margin_points / terminal_price
                    print(f"      пункты_маржи / цена = {margin_points:.2f} / {terminal_price:.2f} = {points_per_price:.4f}")
                    
                    if 'klong' in margin_fields:
                        klong = margin_fields['klong']
                        if abs(points_per_price - klong) < 0.1:
                            print(f"      ✅ ВОЗМОЖНО: пункты_маржи = цена * klong")
                            print(f"         Тогда: ГО = стоимость_пункта * цена * klong")
                            calc = terminal_point_value * terminal_price * klong
                            diff = abs(calc - terminal_margin)
                            match = "✅" if diff < 10 else "❌"
                            print(f"         {match} Проверка: {terminal_point_value:.2f} * {terminal_price:.2f} * {klong:.2f} = {calc:.2f} ₽ (разница: {diff:.2f} ₽)")
            
            # Ищем общую формулу
            print(f"\n   📐 Поиск общей формулы:")
            if terminal_price > 0:
                margin_rate = terminal_margin / terminal_price
                print(f"      ГО / цена = {terminal_margin:.2f} / {terminal_price:.2f} = {margin_rate:.4f} ({margin_rate*100:.2f}%)")
                
                if 'klong' in margin_fields:
                    klong = margin_fields['klong']
                    ratio = terminal_margin / (terminal_price * klong)
                    print(f"      ГО / (цена * klong) = {terminal_margin:.2f} / ({terminal_price:.2f} * {klong:.2f}) = {ratio:.4f}")
                    
                    if abs(ratio - terminal_lot) < 0.1:
                        print(f"      ✅ НАЙДЕНА ФОРМУЛА: ГО = цена * klong * lot_size")
                        print(f"         где lot_size = {ratio:.0f} (реальная лотность из терминала)")
                    elif terminal_point_value > 0:
                        # Пробуем через стоимость пункта
                        ratio2 = terminal_margin / (terminal_point_value * terminal_price)
                        print(f"      ГО / (стоимость_пункта * цена) = {terminal_margin:.2f} / ({terminal_point_value:.2f} * {terminal_price:.2f}) = {ratio2:.4f}")
                        
                        if abs(ratio2 - klong) < 0.1:
                            print(f"      ✅ ВОЗМОЖНАЯ ФОРМУЛА: ГО = стоимость_пункта * цена * klong")


def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Find real margin through API')
    parser.add_argument('ticker', help='Ticker to check (e.g., PTH6, NGG6)')
    parser.add_argument('--sandbox', action='store_true', help='Use sandbox API')
    
    args = parser.parse_args()
    
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found!")
        sys.exit(1)
    
    target = INVEST_GRPC_API_SANDBOX if args.sandbox else INVEST_GRPC_API
    
    with Client(token=token, target=target) as client:
        explore_instrument_api(args.ticker.upper(), client)


if __name__ == "__main__":
    main()
