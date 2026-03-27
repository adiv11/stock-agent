@echo off
cd /d "c:\Users\aa\Downloads\stock-agent-main\stock-agent-main"

:: Try 'py' first (standard Windows launcher)
py --version >nul 2>&1
if %errorlevel% == 0 (
    echo [Using py command]
    py stock_agent.py
    goto end
)

:: Try 'python'
python --version >nul 2>&1
if %errorlevel% == 0 (
    echo [Using python command]
    python stock_agent.py
    goto end
)

:: Try 'python3'
python3 --version >nul 2>&1
if %errorlevel% == 0 (
    echo [Using python3 command]
    python3 stock_agent.py
    goto end
)

echo ❌ ERROR: Python was not found on your system.
echo Please install it from python.org and check "Add Python to PATH".

:end
pause
