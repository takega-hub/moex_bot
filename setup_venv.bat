@echo off
echo Создание виртуального окружения...
echo.

REM Удаляем старое окружение, если существует
if exist venv (
    echo Удаление старого виртуального окружения...
    rmdir /s /q venv
)

REM Создаем новое виртуальное окружение
python -m venv venv

if errorlevel 1 (
    echo ОШИБКА: Не удалось создать виртуальное окружение!
    echo Убедитесь, что Python установлен и доступен в PATH.
    pause
    exit /b 1
)

echo Виртуальное окружение создано успешно!
echo.
echo Активируем окружение и обновляем pip...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo.
echo Установка зависимостей из requirements.txt...
python -m pip install -r requirements.txt

echo.
echo Установка t-tech-investments из специального репозитория...
python -m pip install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple

echo.
echo ========================================
echo Виртуальное окружение настроено!
echo ========================================
echo.
echo Для активации окружения в будущем используйте:
echo   venv\Scripts\activate.bat
echo.
pause
