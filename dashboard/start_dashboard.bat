@echo off
rem ConstructionLab launcher for Windows: double-click this file. The first time, it installs everything (see setup.ps1).
cd /d "%~dp0"
if not exist ".venv\.setup-complete" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "..\setup.ps1"
    if errorlevel 1 (
        echo Setup stopped with an error, shown above. Running this file again continues where it stopped.
        pause
        exit /b 1
    )
)
echo Starting ConstructionLab. Your browser opens automatically (normally at http://localhost:8501). Keep this window open while you work.
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
pause
