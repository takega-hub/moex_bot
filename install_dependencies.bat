@echo off
echo Установка зависимостей в виртуальное окружение...
echo.

REM Активируем виртуальное окружение и устанавливаем зависимости
call venv\Scripts\activate.bat

echo Обновление pip...
python -m pip install --upgrade pip

echo.
echo Установка зависимостей из requirements.txt...
python -m pip install -r requirements.txt

echo.
echo Установка t-tech-investments из специального репозитория...
python -m pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple

echo.
echo Установка завершена!
pause
