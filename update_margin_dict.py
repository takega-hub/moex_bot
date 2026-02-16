#!/usr/bin/env python3
"""
Скрипт для автоматического обновления словаря маржи на основе данных из API.
Использует результаты check_margins.py или получает данные напрямую из API.
"""
import os
import sys
import json
from pathlib import Path
from typing import Dict, List, Optional
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
        
        for inst in find_response.instruments:
            if inst.ticker.upper() == ticker.upper():
                return inst.figi
        
        if find_response.instruments:
            return find_response.instruments[0].figi
        
        return None
    except Exception as e:
        print(f"   ⚠️ Error finding instrument {ticker}: {e}")
        return None


def get_margin_from_api(ticker: str, client: Client) -> Optional[Dict[str, float]]:
    """Получить маржу из API для инструмента."""
    figi = get_instrument_figi(ticker, client)
    if not figi:
        return None
    
    try:
        response = client.instruments.get_instrument_by(
            id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
            id=figi
        )
        instrument = response.instrument
        
        result = {}
        if hasattr(instrument, 'dlong'):
            dlong = extract_money_value(instrument.dlong)
            if dlong is not None:
                result['dlong'] = dlong
        
        if hasattr(instrument, 'dshort'):
            dshort = extract_money_value(instrument.dshort)
            if dshort is not None:
                result['dshort'] = dshort
        
        return result if result else None
    except Exception as e:
        print(f"   ❌ Error getting margin for {ticker}: {e}")
        return None


def update_margin_dict(sandbox: bool = False, instruments: Optional[List[str]] = None, dry_run: bool = False):
    """Обновить словарь маржи."""
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ ERROR: TINKOFF_TOKEN not found!")
        sys.exit(1)
    
    target = INVEST_GRPC_API_SANDBOX if sandbox else INVEST_GRPC_API
    
    # Загружаем активные инструменты
    if instruments is None:
        state_file = Path("runtime_state.json")
        if state_file.exists():
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                instruments = state.get("active_instruments", [])
        else:
            instruments = []
    
    if not instruments:
        print("❌ No instruments specified")
        sys.exit(1)
    
    print(f"\n{'='*80}")
    print(f"🔄 ОБНОВЛЕНИЕ СЛОВАРЯ МАРЖИ")
    print(f"{'='*80}\n")
    print(f"Using {'SANDBOX' if sandbox else 'REAL'} API")
    if dry_run:
        print("🔍 DRY RUN MODE - изменения не будут сохранены\n")
    else:
        print("⚠️  БУДУТ ВНЕСЕНЫ ИЗМЕНЕНИЯ В bot/margin_rates.py\n")
    
    updates = {}
    
    with Client(token=token, target=target) as client:
        for ticker in instruments:
            print(f"🔍 Checking {ticker}...")
            margin_info = get_margin_from_api(ticker, client)
            if margin_info:
                dlong = margin_info.get('dlong', 0.0)
                dshort = margin_info.get('dshort', 0.0)
                print(f"   ✅ dlong: {dlong:.2f} руб, dshort: {dshort:.2f} руб")
                # Используем dlong как основное значение (для LONG позиций)
                if dlong > 0:
                    updates[ticker.upper()] = dlong
            else:
                print(f"   ⚠️ Could not get margin info")
    
    if not updates:
        print("\n❌ No updates available")
        return
    
    # Читаем текущий файл
    margin_file = Path("bot/margin_rates.py")
    if not margin_file.exists():
        print(f"❌ File {margin_file} not found")
        return
    
    with open(margin_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Обновляем значения
    lines = content.split('\n')
    new_lines = []
    in_margin_dict = False
    updated_count = 0
    
    for line in lines:
        if 'MARGIN_PER_LOT: Dict[str, float] = {' in line:
            in_margin_dict = True
            new_lines.append(line)
        elif in_margin_dict and line.strip().startswith('}'):
            in_margin_dict = False
            new_lines.append(line)
        elif in_margin_dict:
            # Проверяем, нужно ли обновить эту строку
            updated = False
            for ticker, new_value in updates.items():
                # Ищем строку с этим тикером
                if f'"{ticker}"' in line or f"'{ticker}'" in line:
                    # Обновляем значение
                    import re
                    # Заменяем значение после двоеточия
                    pattern = rf'("{ticker}"|' + rf"'{ticker}'" + r')\s*:\s*[\d.]+'
                    replacement = rf'\1: {new_value:.2f}'
                    new_line = re.sub(pattern, replacement, line)
                    new_lines.append(new_line)
                    updated = True
                    updated_count += 1
                    print(f"   ✅ Updated {ticker}: {new_value:.2f} руб")
                    break
            
            if not updated:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    new_content = '\n'.join(new_lines)
    
    if dry_run:
        print(f"\n📋 ПРЕДПРОСМОТР ИЗМЕНЕНИЙ ({updated_count} обновлений):\n")
        print("=" * 80)
        # Показываем diff
        old_lines = content.split('\n')
        new_lines_preview = new_content.split('\n')
        for i, (old_line, new_line) in enumerate(zip(old_lines, new_lines_preview)):
            if old_line != new_line:
                print(f"Line {i+1}:")
                print(f"  - {old_line}")
                print(f"  + {new_line}")
        print("=" * 80)
        print("\n💡 Для применения изменений запустите без --dry-run")
    else:
        # Сохраняем изменения
        backup_file = margin_file.with_suffix('.py.backup')
        with open(backup_file, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n💾 Создан backup: {backup_file}")
        
        with open(margin_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        print(f"✅ Обновлено {updated_count} значений в {margin_file}")
        print("\n⚠️  ВАЖНО: Проверьте изменения перед коммитом!")


def main():
    """Главная функция."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Update margin dictionary from API')
    parser.add_argument('--sandbox', action='store_true', help='Use sandbox API')
    parser.add_argument('--instruments', nargs='+', help='Specific instruments to update')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without saving')
    
    args = parser.parse_args()
    
    update_margin_dict(
        sandbox=args.sandbox,
        instruments=args.instruments,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
