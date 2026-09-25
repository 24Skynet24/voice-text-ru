# ВНИМАНИЕ: этот файл обязан храниться в UTF-8 **с BOM**.
# Windows PowerShell 5.1 без BOM читает .ps1 в системной кодировке ANSI,
# кириллица превращается в мусор, и скрипт перестаёт разбираться.
# Наличие BOM проверяется тестом tests/test_build_files.py.

<#
.SYNOPSIS
    Сборка production-версии Voice Text RU (ТЗ §39).

.DESCRIPTION
    Выполняет полный цикл: иконка → PyInstaller → (необязательно) установщик Inno Setup.
    Результат:
      dist\VoiceTextRU\Voice Text RU.exe          — готовое приложение
      dist\installer\VoiceTextRU-<версия>-setup.exe — установщик, если найден ISCC

.PARAMETER SkipInstaller
    Не собирать установщик, даже если Inno Setup установлен.

.PARAMETER Python
    Путь к интерпретатору Python с установленными зависимостями.
    По умолчанию используется .venv в корне проекта.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File build\build.ps1
#>

[CmdletBinding()]
param(
    [switch]$SkipInstaller,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDir = Join-Path $projectRoot "build"
$distDir = Join-Path $projectRoot "dist"

if (-not $Python) {
    $Python = Join-Path $projectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $Python)) {
    throw "Интерпретатор Python не найден: $Python. Создайте окружение: python -m venv .venv"
}

Write-Host "== Voice Text RU: сборка ==" -ForegroundColor Cyan
Write-Host "Проект : $projectRoot"
Write-Host "Python : $Python"

# --- 1. Проверка зависимостей -------------------------------------------------
Write-Host "`n[1/4] Проверка зависимостей..." -ForegroundColor Cyan
& $Python -c "import PySide6, faster_whisper, sounddevice, numpy, PyInstaller"
if ($LASTEXITCODE -ne 0) {
    throw "Не все зависимости установлены. Выполните: $Python -m pip install -r requirements-dev.txt"
}

# --- 2. Иконка ----------------------------------------------------------------
Write-Host "`n[2/4] Создание иконки..." -ForegroundColor Cyan
& $Python (Join-Path $buildDir "make_icon.py")
if ($LASTEXITCODE -ne 0) { throw "Не удалось создать иконку" }

# --- 3. PyInstaller -----------------------------------------------------------
Write-Host "`n[3/4] Сборка приложения (занимает несколько минут)..." -ForegroundColor Cyan
Push-Location $projectRoot
try {
    & $Python -m PyInstaller (Join-Path $buildDir "voicetext_ru.spec") --noconfirm --clean --distpath $distDir --workpath (Join-Path $projectRoot "build\_work")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller завершился с ошибкой" }
}
finally {
    Pop-Location
}

$exePath = Join-Path $distDir "VoiceTextRU\Voice Text RU.exe"
if (-not (Test-Path $exePath)) { throw "Исполняемый файл не создан: $exePath" }

$sizeMb = [math]::Round((Get-ChildItem (Join-Path $distDir "VoiceTextRU") -Recurse |
        Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "Приложение собрано: $exePath ($sizeMb МБ)" -ForegroundColor Green

# --- 4. Установщик ------------------------------------------------------------
Write-Host "`n[4/4] Сборка установщика..." -ForegroundColor Cyan
if ($SkipInstaller) {
    Write-Host "Пропущено по параметру -SkipInstaller" -ForegroundColor Yellow
    exit 0
}

$iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if (-not $iscc) {
    foreach ($candidate in @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $candidate) { $iscc = $candidate; break }
    }
}
else {
    $iscc = $iscc.Source
}

if (-not $iscc) {
    Write-Host "Inno Setup не найден — установщик не собран." -ForegroundColor Yellow
    Write-Host "Готовое приложение лежит в: $(Join-Path $distDir 'VoiceTextRU')"
    Write-Host "Чтобы собрать установщик, установите Inno Setup 6: https://jrsoftware.org/isdl.php"
    exit 0
}

& $iscc (Join-Path $buildDir "installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup завершился с ошибкой" }

Write-Host "`nГотово. Установщик: $(Join-Path $distDir 'installer')" -ForegroundColor Green
