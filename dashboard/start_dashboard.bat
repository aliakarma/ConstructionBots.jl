@echo off
rem ConstructionLab launcher for Windows: double-click this file.
rem The first time, it creates a private Python environment in dashboard\.venv and installs the dashboard's packages.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating the dashboard's Python environment ^(one time only^)...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo Could not create a Python environment. Install Python 3.11 or newer from python.org and try again.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
echo Starting ConstructionLab. Your browser opens automatically (normally at http://localhost:8501). Keep this window open while you work.
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
pause
