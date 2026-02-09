@echo off
chcp 65001 >nul
echo Инициализация git репозитория...
git init
echo.
echo Добавление файлов...
git add .
echo.
echo Создание коммита...
git commit -m "Initial commit: MOEX trading bot with ML models"
echo.
echo Готово! Репозиторий инициализирован и файлы закоммичены.
echo.
echo Если нужно отправить на удаленный репозиторий, выполните:
echo git remote add origin <URL_вашего_репозитория>
echo git push -u origin main
pause
