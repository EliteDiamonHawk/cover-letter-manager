@echo off
if "%~1"=="" (
  echo Usage: run_windows.bat "C:\Path\To\CoverLetters"
  exit /b 1
)
python main.py "%~1"
