# Инициализация git репозитория
Write-Host "Инициализация git репозитория..." -ForegroundColor Green
git init

Write-Host "`nДобавление файлов..." -ForegroundColor Green
git add .

Write-Host "`nСоздание коммита..." -ForegroundColor Green
git commit -m "Initial commit: MOEX trading bot with ML models"

Write-Host "`nГотово! Репозиторий инициализирован и файлы закоммичены." -ForegroundColor Green
Write-Host "`nЕсли нужно отправить на удаленный репозиторий, выполните:" -ForegroundColor Yellow
Write-Host "git remote add origin <URL_вашего_репозитория>" -ForegroundColor Cyan
Write-Host "git push -u origin main" -ForegroundColor Cyan
