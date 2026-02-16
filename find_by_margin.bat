@echo off
echo Finding all instruments with GO <= 3000 RUB...
python find_optimal_instruments.py --balance 5000 --max-margin 3000 --no-volatility-filter --filter-metals --filter-stocks --limit 1000
pause
