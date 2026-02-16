#!/usr/bin/env python3
"""
Анализ результатов проверки маржи и создание рекомендаций по обновлению словаря.
"""
import json
from pathlib import Path
from typing import Dict, List

def analyze_results():
    """Анализировать результаты проверки маржи."""
    results_file = Path("margin_check_results.json")
    if not results_file.exists():
        print("❌ Файл margin_check_results.json не найден!")
        print("   Запустите сначала: python check_margins.py")
        return
    
    with open(results_file, 'r', encoding='utf-8') as f:
        results = json.load(f)
    
    print("=" * 80)
    print("📊 АНАЛИЗ РЕЗУЛЬТАТОВ ПРОВЕРКИ МАРЖИ")
    print("=" * 80)
    print()
    
    issues = []
    recommendations = []
    
    for result in results:
        ticker = result["ticker"]
        api_dlong = result["api"]["dlong"]
        api_dshort = result["api"]["dshort"]
        dict_margin = result["dictionary"]["margin_per_lot"]
        
        print(f"🔍 {ticker}:")
        print(f"   API dlong:  {api_dlong:.4f} руб")
        print(f"   API dshort: {api_dshort:.4f} руб")
        print(f"   Словарь:    {dict_margin:.2f} руб")
        
        # Проверяем, есть ли проблема
        if dict_margin == 0:
            issues.append({
                "ticker": ticker,
                "issue": "Нет значения в словаре",
                "recommendation": f"Добавить значение из терминала для {ticker}"
            })
            print(f"   ⚠️ ПРОБЛЕМА: Нет значения в словаре!")
            print(f"   💡 РЕШЕНИЕ: Получите значение из терминала Tinkoff")
        elif abs(api_dlong - dict_margin) > 0.1 or abs(api_dshort - dict_margin) > 0.1:
            # Большая разница между API и словарем
            if dict_margin > 100:  # Если словарь содержит большое значение (из терминала)
                print(f"   ✅ Словарь содержит значение из терминала ({dict_margin:.2f} руб)")
                print(f"   ⚠️ API значения ({api_dlong:.4f}/{api_dshort:.4f}) НЕ соответствуют реальной марже")
            else:
                # Если словарь содержит маленькое значение, возможно оно неверное
                if api_dlong > 0 and api_dshort > 0:
                    # Используем большее значение из API
                    recommended = max(api_dlong, api_dshort)
                    if abs(recommended - dict_margin) > 0.05:
                        issues.append({
                            "ticker": ticker,
                            "issue": f"Разница между API и словарем: {abs(recommended - dict_margin):.2f} руб",
                            "recommendation": f"Проверить значение в терминале для {ticker}"
                        })
                        print(f"   ⚠️ ВНИМАНИЕ: Разница между API и словарем")
                        print(f"      Рекомендуемое (из API): {recommended:.4f} руб")
                        print(f"      Текущее (словарь): {dict_margin:.2f} руб")
        else:
            print(f"   ✅ Значения совпадают")
        
        print()
    
    # Итоговые рекомендации
    if issues:
        print("=" * 80)
        print("⚠️ НАЙДЕННЫЕ ПРОБЛЕМЫ:")
        print("=" * 80)
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue['ticker']}: {issue['issue']}")
            print(f"   💡 {issue['recommendation']}")
        print()
    
    # Создаем рекомендации по обновлению словаря
    print("=" * 80)
    print("💡 РЕКОМЕНДАЦИИ ПО ОБНОВЛЕНИЮ СЛОВАРЯ:")
    print("=" * 80)
    print()
    print("Для каждого инструмента:")
    print("1. Откройте терминал Tinkoff")
    print("2. Найдите инструмент и посмотрите 'Гарантийное обеспечение'")
    print("3. Обновите значение в bot/margin_rates.py")
    print()
    print("Текущие значения в словаре:")
    print()
    
    for result in results:
        ticker = result["ticker"]
        dict_margin = result["dictionary"]["margin_per_lot"]
        name = result.get("name", "")
        
        if dict_margin > 0:
            status = "✅" if dict_margin > 100 else "⚠️"
            print(f"{status} {ticker:6s} ({name[:30]:30s}): {dict_margin:>10.2f} ₽")
        else:
            print(f"❌ {ticker:6s} ({name[:30]:30s}): {'НЕТ ЗНАЧЕНИЯ':>10s}")
    
    print()
    print("=" * 80)
    print("📝 КОД ДЛЯ ОБНОВЛЕНИЯ СЛОВАРЯ:")
    print("=" * 80)
    print()
    print("Обновите bot/margin_rates.py:")
    print()
    
    for result in results:
        ticker = result["ticker"]
        dict_margin = result["dictionary"]["margin_per_lot"]
        name = result.get("name", "")
        
        if dict_margin == 0:
            print(f'    "{ticker}": 0.0,  # {name} - TODO: получить из терминала')
        else:
            print(f'    "{ticker}": {dict_margin:.2f},  # {name}')

if __name__ == "__main__":
    analyze_results()
