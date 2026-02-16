#!/bin/bash
# Скрипт для диагностики проблем запуска бота

echo "=== Проверка статуса сервиса ==="
sudo systemctl status moex_bot --no-pager -l

echo ""
echo "=== Последние 50 строк логов ==="
tail -n 50 /opt/moex_bot/logs/bot.log

echo ""
echo "=== Последние ошибки ==="
tail -n 20 /opt/moex_bot/logs/errors.log 2>/dev/null || echo "Файл errors.log не найден"

echo ""
echo "=== Проверка systemd журнала ==="
sudo journalctl -u moex_bot -n 50 --no-pager

echo ""
echo "=== Проверка процесса ==="
ps aux | grep -E "python.*run_bot|moex_bot" | grep -v grep

echo ""
echo "=== Проверка файлов ==="
ls -lh /opt/moex_bot/run_bot.py
ls -lh /opt/moex_bot/logs/bot.log
