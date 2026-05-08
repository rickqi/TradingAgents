@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

:: Check .env exists
if not exist ".env" (
    echo [ERROR] .env file not found!
    echo Please copy .env.example to .env and fill in your API keys:
    echo     copy .env.example .env
    pause
    exit /b 1
)

:: Check venv exists, create if missing
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Virtual environment not found, creating...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [INFO] Virtual environment created.
)

:: Activate venv
call .venv\Scripts\activate.bat

:: Check if tradingagents is installed (quick check for langchain)
python -c "import langchain_core" 2>nul
if errorlevel 1 (
    echo [INFO] Dependencies not installed, running pip install . ...
    pip install .
    if errorlevel 1 (
        echo [ERROR] pip install failed.
        pause
        exit /b 1
    )
    echo [INFO] Dependencies installed.
)

:: Launch CLI
echo.
echo ============================================================
echo   TradingAgents v0.2.4  -  Multi-Agents LLM Trading
echo ============================================================
echo.
python -m cli.main %*

:: Keep window open if launched by double-click
if "%1"=="" pause
