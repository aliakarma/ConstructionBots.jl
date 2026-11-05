@echo off
rem Double-click this file to install everything ConstructionBots needs. See setup.ps1.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 echo Setup stopped with an error, shown above. Running it again continues where it stopped.
pause
