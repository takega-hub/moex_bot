"""Простой скрипт для проверки get_risk_rates"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from t_tech.invest import AsyncClient
from t_tech.invest.schemas import RiskRatesRequest

load_dotenv()

async def main():
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    if not token:
        print("❌ Токен не найден")
        return
    
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NRG6"
    
    async with AsyncClient(token) as client:
        # Находим инструмент
        response = await client.instruments.find_instrument(query=ticker)
        if not response.instruments:
            print(f"❌ Инструмент {ticker} не найден")
            return
        
        instrument = response.instruments[0]
        uid = instrument.uid
        print(f"✅ Найден {ticker}: UID={uid}\n")
        
        # Получаем risk rates
        request = RiskRatesRequest()
        request.instrument_id = [uid]
        
        try:
            r = await client.instruments.get_risk_rates(request=request)
            print("📊 Результаты get_risk_rates:\n")
            for i in r.instrument_risk_rates:
                print(f"instrument_uid: {i.instrument_uid}")
                print(f"short_risk_rate: {i.short_risk_rate}")
                print(f"long_risk_rate: {i.long_risk_rate}")
                print(f"\nВсе атрибуты:")
                for attr in dir(i):
                    if not attr.startswith('_'):
                        try:
                            val = getattr(i, attr)
                            if not callable(val):
                                print(f"  {attr}: {val}")
                        except:
                            pass
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
