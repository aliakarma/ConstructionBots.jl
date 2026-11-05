@echo off
rem Experiment Lab launcher for Windows: double-click this file. The first time, it installs everything (see setup.ps1).
cd /d "%~dp0"
if not exist "..\dashboard\.venv\.setup-complete" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "..\setup.ps1"
    if errorlevel 1 (
        echo Setup stopped with an error, shown above. Running this file again continues where it stopped.
        pause
        exit /b 1
    )
)
echo Starting JupyterLab. Keep this window open while you work.
"..\dashboard\.venv\Scripts\python.exe" -m jupyter lab ConstructionBots_Experiment_Lab.ipynb
pause
