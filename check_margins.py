#!/usr/bin/env python3
"""
Скрипт для автоматической проверки расчета маржи для всех активных инструментов.
Сравнивает значения из API (dlong/dshort) с текущими значениями в словаре.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

try:
    from t_tech.invest import Client, InstrumentIdType
    from t_tech.invest.constants import INVEST_GRPC_API, INVEST_GRPC_API_SANDBOX
    from t_tech.invest.schemas import InstrumentType
    TINKOFF_AVAILABLE = True
except ImportError:
    TINKOFF_AVAILABLE = False
    print("❌ ERROR: t-tech-investments library not installed")
    print("Install with: pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple")
    sys.exit(1)

from bot.margin_rates import MARGIN_PER_LOT, MARGIN_RATE_PCT


def setup_logging():
    """Настройка логирования."""
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)


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
    try:
        find_response = client.instruments.find_instrument(
            query=ticker,
            instrument_kind=InstrumentType.INSTRUMENT_TYPE_FUTURES,
            api_trade_available_flag=True
        )
        
        if not find_response.instruments:
            return None
        
        # Ищем точное совпадение
        for inst in find_response.instruments:
            if inst.ticker.upper() == ticker.upper():
                return inst.figi
        
        # Если точного совпадения нет, берем первый
        if find_response.instruments:
            return find_response.instruments[0].figi
        
        return None
    except Exception as e:
        print(f"   ⚠️ Error finding instrument {ticker}: {e}")
        return None


def get_instrument_margin_info(figi: str, ticker: str, client: Client) -> Optional[Dict[str, Any]]:
    """Получить информацию о марже для инструмента."""
    try:
        response = client.instruments.get_instrument_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi
        )
        instrument = response.instrument
        
        info = {
            "ticker": ticker,
            "figi": figi,
            "name": getattr(instrument, 'name', ''),
            "lot": float(getattr(instrument, 'lot', 1.0)),
        }
        
        # Извлекаем коэффициенты маржи
        if hasattr(instrument, 'dlong'):
            dlong = extract_money_value(instrument.dlong)
            if dlong is not None:
                info['dlong'] = dlong
        
        if hasattr(instrument, 'dshort'):
            dshort = extract_money_value(instrument.dshort)
            if dshort is not None:
                info['dshort'] = dshort
        
        if hasattr(instrument, 'dlong_client'):
            dlong_client = extract_money_value(instrument.dlong_client)
            if dlong_client is not None:
                info['dlong_client'] = dlong_client
        
        if hasattr(instrument, 'dshort_client'):
            dshort_client = extract_money_value(instrument.dshort_client)
            if dshort_client is not None:
                info['dshort_client'] = dshort_client
        
        if hasattr(instrument, 'klong'):
            klong = extract_money_value(instrument.klong)
            if klong is not None:
                info['klong'] = klong
        
        if hasattr(instrument, 'kshort'):
            kshort = extract_money_value(instrument.kshort)
            if kshort is not None:
                info['kshort'] = kshort
        
        return info
    except Exception as e:
        print(f"   ❌ Error getting margin info for {ticker} ({figi}): {e}")
        return None


def load_active_instruments() -> List[str]:
    """Загрузить список активных инструментов из runtime_state.json."""
    state_file = Path("runtime_state.json")
    if not state_file.exists():
        print("⚠️ runtime_state.json not found, using empty list")
        return []
    
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
            active = state.get("active_instruments", [])
            if active:
                print(f"✅ Loaded {len(active)} active instruments from runtime_state.json")
                return active
            else:
                print("⚠️ No active instruments in runtime_state.json")
                return []
    except Exception as e:
        print(f"❌ Error loading runtime_state.json: {e}")
        return []


def get_balance(client: Client) -> Dict[str, float]:
    """Получить баланс счета."""
    try:
        from t_tech.invest.schemas import AccountId, AccountType
        
        # Получаем список счетов
        accounts_response = client.users.get_accounts()
        if not accounts_response.accounts:
            return {"total": 0.0, "available": 0.0}
        
        # Используем первый счет
        account_id = accounts_response.accounts[0].id
        
        # Получаем портфель
        portfolio_response = client.operations.get_portfolio(account_id=account_id)
        portfolio = portfolio_response.portfolio
        
        total_amount = 0.0
        available_amount = 0.0
        
        if hasattr(portfolio, 'total_amount_portfolio'):
            total = portfolio.total_amount_portfolio
            if hasattr(total, 'units') and hasattr(total, 'nano'):
                total_amount = float(total.units) + float(total.nano) / 1e9
        
        if hasattr(portfolio, 'available_withdrawal_draw_limit'):
            available = portfolio.available_withdrawal_draw_limit
            if hasattr(available, 'units') and hasattr(available, 'nano'):
                available_amount = float(available.units) + float(available.nano) / 1e9
        
        # Также пробуем получить из позиций
        positions = portfolio_response.positions if hasattr(portfolio_response, 'positions') else []
        for pos in positions:
            if hasattr(pos, 'figi') and pos.figi == "RUB000UTSTOM":  # Валюта RUB
                if hasattr(pos, 'quantity'):
                    qty = extract_money_value(pos.quantity) if hasattr(pos.quantity, 'units') else float(pos.quantity) if pos.quantity else 0.0
                    if qty > 0:
                        total_amount = qty
                        # Пробуем получить доступный баланс
                        if hasattr(pos, 'available'):
                            avail = extract_money_value(pos.available) if hasattr(pos.available, 'units') else float(pos.available) if pos.available else 0.0
                            if avail > 0:
                                available_amount = avail
        
        return {"total": total_amount, "available": available_amount}
    except Exception as e:
        print(f"   ⚠️ Error getting balance: {e}")
        return {"total": 0.0, "available": 0.0}


def check_margins(sandbox: bool = False, instruments: Optional[List[str]] = None):
    """Проверить маржу для всех активных инструментов."""
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found in environment variables!")
        print("   Please set TINKOFF_TOKEN in .env file or environment")
        sys.exit(1)
    
    target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
    
    # Загружаем активные инструменты
    if instruments is None:
        instruments = load_active_instruments()
    
    if not instruments:
        print("❌ No instruments to check. Add instruments to runtime_state.json or pass via --instruments")
        sys.exit(1)
    
    print(f"\n{'='*80}")
    print(f"📊 ПРОВЕРКА МАРЖИ ДЛЯ {len(instruments)} АКТИВНЫХ ИНСТРУМЕНТОВ")
    print(f"{'='*80}\n")
    print(f"Using {'SANDBOX' if sandbox else 'REAL'} API\n")
    
    results = []
    
    with Client(token=token, target=target) as client:
        # Получаем баланс
        print("💰 Получение баланса счета...")
        balance_info = get_balance(client)
        total_balance = balance_info.get("total", 0.0)
        available_balance = balance_info.get("available", 0.0)
        print(f"   Общий баланс: {total_balance:.2f} ₽")
        print(f"   Доступный баланс: {available_balance:.2f} ₽\n")
        
        for ticker in instruments:
            print(f"🔍 Checking {ticker}...")
            
            # Получаем FIGI
            figi = get_instrument_figi(ticker, client)
            if not figi:
                print(f"   ❌ Could not find FIGI for {ticker}")
                results.append({
                    "ticker": ticker,
                    "status": "error",
                    "error": "FIGI not found"
                })
                continue
            
            print(f"   ✅ Found FIGI: {figi}")
            
            # Получаем информацию о марже
            margin_info = get_instrument_margin_info(figi, ticker, client)
            if not margin_info:
                print(f"   ❌ Could not get margin info for {ticker}")
                results.append({
                    "ticker": ticker,
                    "status": "error",
                    "error": "Margin info not available"
                })
                continue
            
            # Сравниваем с текущими значениями в словаре
            ticker_upper = ticker.upper()
            dict_margin = MARGIN_PER_LOT.get(ticker_upper, 0.0)
            dict_rate = MARGIN_RATE_PCT.get(ticker_upper, 0.0)
            
            api_dlong = margin_info.get('dlong', 0.0)
            api_dshort = margin_info.get('dshort', 0.0)
            lot_size = margin_info.get('lot', 1.0)
            
            # ВАЖНО: Проверяем гипотезу, что dlong/dshort могут быть в единицах базового актива
            # Для NGG6: лотность = 100, значит если dlong = 0.33, то реальная маржа = 0.33 * 100 = 33 руб
            # Но в терминале показано 7 667,72 ₽ - это намного больше!
            # Возможно, нужно использовать другой расчет или другое поле
            
            # Пробуем разные варианты расчета маржи
            margin_variants = {
                "dlong (as is)": api_dlong,
                "dlong * lot": api_dlong * lot_size if api_dlong > 0 else 0.0,
                "dshort (as is)": api_dshort,
                "dshort * lot": api_dshort * lot_size if api_dshort > 0 else 0.0,
            }
            
            # Если есть klong/kshort, пробуем расчет через них
            klong = margin_info.get('klong', 0.0)
            kshort = margin_info.get('kshort', 0.0)
            
            # Получаем текущую цену для расчета через коэффициенты
            try:
                from t_tech.invest import CandleInterval
                from datetime import datetime, timedelta, timezone
                to_date = datetime.now(timezone.utc)
                from_date = to_date - timedelta(days=1)
                candles_response = client.market_data.get_candles(
                    figi=figi,
                    from_=from_date,
                    to=to_date,
                    interval=CandleInterval.CANDLE_INTERVAL_1_MIN
                )
                current_price = 0.0
                if candles_response.candles:
                    last_candle = candles_response.candles[-1]
                    if hasattr(last_candle, 'close') and last_candle.close:
                        current_price = extract_money_value(last_candle.close)
                
                if current_price > 0 and klong > 0:
                    margin_variants["price * klong"] = current_price * klong
                    margin_variants["price * klong * lot"] = current_price * klong * lot_size
                if current_price > 0 and kshort > 0:
                    margin_variants["price * kshort"] = current_price * kshort
                    margin_variants["price * kshort * lot"] = current_price * kshort * lot_size
            except Exception as e:
                pass  # Не критично, если не удалось получить цену
            
            result = {
                "ticker": ticker,
                "figi": figi,
                "name": margin_info.get('name', ''),
                "lot": lot_size,
                "status": "ok",
                "api": {
                    "dlong": api_dlong,
                    "dshort": api_dshort,
                    "dlong_client": margin_info.get('dlong_client', 0.0),
                    "dshort_client": margin_info.get('dshort_client', 0.0),
                    "klong": margin_info.get('klong', 0.0),
                    "kshort": margin_info.get('kshort', 0.0),
                },
                "dictionary": {
                    "margin_per_lot": dict_margin,
                    "margin_rate_pct": dict_rate,
                },
                "margin_variants": margin_variants,
                "balance_check": {
                    "total_balance": total_balance,
                    "available_balance": available_balance,
                },
                "comparison": {}
            }
            
            # Сравнение для LONG позиции
            if api_dlong > 0:
                if dict_margin > 0:
                    diff = abs(api_dlong - dict_margin)
                    diff_pct = (diff / api_dlong * 100) if api_dlong > 0 else 0
                    result["comparison"]["long"] = {
                        "api": api_dlong,
                        "dict": dict_margin,
                        "diff": diff,
                        "diff_pct": diff_pct,
                        "match": diff < 0.01  # Считаем совпадением если разница < 1 копейки
                    }
                else:
                    result["comparison"]["long"] = {
                        "api": api_dlong,
                        "dict": 0.0,
                        "diff": api_dlong,
                        "diff_pct": 100.0,
                        "match": False,
                        "note": "No value in dictionary"
                    }
            
            # Сравнение для SHORT позиции
            if api_dshort > 0:
                if dict_margin > 0:
                    diff = abs(api_dshort - dict_margin)
                    diff_pct = (diff / api_dshort * 100) if api_dshort > 0 else 0
                    result["comparison"]["short"] = {
                        "api": api_dshort,
                        "dict": dict_margin,
                        "diff": diff,
                        "diff_pct": diff_pct,
                        "match": diff < 0.01
                    }
                else:
                    result["comparison"]["short"] = {
                        "api": api_dshort,
                        "dict": 0.0,
                        "diff": api_dshort,
                        "diff_pct": 100.0,
                        "match": False,
                        "note": "No value in dictionary"
                    }
            
            results.append(result)
            
            # Выводим результат
            print(f"   📊 Margin info:")
            print(f"      Лотность (lot): {lot_size}")
            print(f"      LONG (dlong):  {api_dlong:.2f} руб")
            print(f"      SHORT (dshort): {api_dshort:.2f} руб")
            
            # Показываем все варианты расчета маржи
            print(f"\n   🔍 ВАРИАНТЫ РАСЧЕТА МАРЖИ:")
            for variant_name, margin_value in margin_variants.items():
                if margin_value > 0:
                    print(f"      {variant_name:25s}: {margin_value:>10.2f} ₽/лот")
                    # Проверяем баланс для каждого варианта
                    if total_balance >= margin_value:
                        max_lots = int(total_balance / margin_value)
                        print(f"         {'':25s}  ✅ Достаточно для {max_lots} лот(ов)")
                    else:
                        print(f"         {'':25s}  ❌ НЕДОСТАТОЧНО! Нужно {margin_value:.2f} ₽, есть {total_balance:.2f} ₽")
            
            # Сравниваем с терминалом (если известны значения)
            # Для NGG6 из терминала: 7 667,72 ₽
            terminal_margin = None
            if ticker.upper() == "NGG6":
                terminal_margin = 7667.72
                print(f"\n   📱 ЗНАЧЕНИЕ ИЗ ТЕРМИНАЛА: {terminal_margin:.2f} ₽/лот")
                print(f"      Сравнение с вариантами:")
                for variant_name, margin_value in margin_variants.items():
                    if margin_value > 0:
                        diff = abs(margin_value - terminal_margin)
                        diff_pct = (diff / terminal_margin * 100) if terminal_margin > 0 else 0
                        if diff < 10.0:  # Разница меньше 10 руб - возможно совпадение
                            print(f"      ✅ {variant_name:25s}: {margin_value:>10.2f} ₽ (разница: {diff:.2f} ₽, {diff_pct:.1f}%)")
                        else:
                            print(f"      ❌ {variant_name:25s}: {margin_value:>10.2f} ₽ (разница: {diff:.2f} ₽, {diff_pct:.1f}%)")
            
            # Проверяем баланс для наиболее вероятного варианта
            # Пробуем найти значение, близкое к терминалу
            best_match = None
            best_diff = float('inf')
            for variant_name, margin_value in margin_variants.items():
                if margin_value > 0:
                    if terminal_margin:
                        diff = abs(margin_value - terminal_margin)
                        if diff < best_diff:
                            best_diff = diff
                            best_match = (variant_name, margin_value)
                    elif not best_match:  # Если нет терминального значения, берем первое ненулевое
                        best_match = (variant_name, margin_value)
            
            if best_match:
                variant_name, margin_value = best_match
                print(f"\n   💡 РЕКОМЕНДУЕМЫЙ ВАРИАНТ: {variant_name} = {margin_value:.2f} ₽/лот")
                if total_balance >= margin_value:
                    max_lots = int(total_balance / margin_value)
                    print(f"      ✅ Достаточно баланса для {max_lots} лот(ов)")
                else:
                    print(f"      ❌ НЕДОСТАТОЧНО БАЛАНСА!")
                    print(f"         Нужно: {margin_value:.2f} ₽")
                    print(f"         Есть:  {total_balance:.2f} ₽")
                    print(f"         Не хватает: {margin_value - total_balance:.2f} ₽")
            
            if dict_margin > 0:
                print(f"      Dictionary:   {dict_margin:.2f} руб/лот")
                if api_dlong > 0:
                    long_diff = abs(api_dlong - dict_margin)
                    if long_diff >= 0.01:
                        print(f"      ⚠️ LONG difference: {long_diff:.2f} руб ({long_diff/api_dlong*100:.1f}%)")
                    else:
                        print(f"      ✅ LONG matches dictionary")
                if api_dshort > 0:
                    short_diff = abs(api_dshort - dict_margin)
                    if short_diff >= 0.01:
                        print(f"      ⚠️ SHORT difference: {short_diff:.2f} руб ({short_diff/api_dshort*100:.1f}%)")
                    else:
                        print(f"      ✅ SHORT matches dictionary")
            else:
                print(f"      ⚠️ No value in dictionary (using fallback rate: {dict_rate}%)")
            
            print()
    
    # Итоговый отчет
    print(f"\n{'='*80}")
    print("📋 ИТОГОВЫЙ ОТЧЕТ")
    print(f"{'='*80}\n")
    
    print(f"{'Тикер':<10} {'LONG (API)':<12} {'SHORT (API)':<13} {'Словарь':<10} {'Статус':<20}")
    print("-" * 80)
    
    needs_update = []
    for result in results:
        if result["status"] != "ok":
            print(f"{result['ticker']:<10} {'ERROR':<12} {'ERROR':<13} {'-':<10} {result.get('error', 'Unknown'):<20}")
            continue
        
        ticker = result["ticker"]
        api_dlong = result["api"]["dlong"]
        api_dshort = result["api"]["dshort"]
        dict_margin = result["dictionary"]["margin_per_lot"]
        
        status = "✅ OK"
        if api_dlong > 0 and dict_margin > 0:
            if abs(api_dlong - dict_margin) >= 0.01:
                status = "⚠️ Нужно обновить"
                needs_update.append({
                    "ticker": ticker,
                    "current": dict_margin,
                    "api_long": api_dlong,
                    "api_short": api_dshort,
                    "recommended": api_dlong  # Используем LONG как основное значение
                })
        elif dict_margin == 0:
            status = "⚠️ Нет в словаре"
            needs_update.append({
                "ticker": ticker,
                "current": 0.0,
                "api_long": api_dlong,
                "api_short": api_dshort,
                "recommended": api_dlong
            })
        
        print(f"{ticker:<10} {api_dlong:>10.2f} руб {api_dshort:>11.2f} руб {dict_margin:>8.2f} руб {status:<20}")
    
    if needs_update:
        print(f"\n⚠️ НАЙДЕНО {len(needs_update)} ИНСТРУМЕНТОВ, ТРЕБУЮЩИХ ОБНОВЛЕНИЯ:\n")
        for item in needs_update:
            print(f"   {item['ticker']}:")
            print(f"      Текущее значение в словаре: {item['current']:.2f} руб")
            print(f"      API LONG (dlong):  {item['api_long']:.2f} руб")
            print(f"      API SHORT (dshort): {item['api_short']:.2f} руб")
            print(f"      Рекомендуемое значение: {item['recommended']:.2f} руб (для LONG)")
            print()
        
        print("💡 Для обновления словаря выполните:")
        print("   python update_margin_dict.py")
        print("\n   Или обновите вручную в bot/margin_rates.py:")
        for item in needs_update:
            print(f'   "{item["ticker"]}": {item["recommended"]:.2f},  # {item["api_long"]:.2f} LONG, {item["api_short"]:.2f} SHORT')
    else:
        print("\n✅ Все значения маржи соответствуют API!")
    
    return results


def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Check margin rates for active instruments')
    parser.add_argument('--sandbox', action='store_true', help='Use sandbox API')
    parser.add_argument('--instruments', nargs='+', help='Specific instruments to check (default: from runtime_state.json)')
    
    args = parser.parse_args()
    
    logger = setup_logging()
    
    results = check_margins(sandbox=args.sandbox, instruments=args.instruments)
    
    # Сохраняем результаты в JSON файл
    output_file = Path("margin_check_results.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 Результаты сохранены в {output_file}")


if __name__ == "__main__":
    main()
