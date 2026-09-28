@echo off
REM Builds a single portable V2Scan.exe (no installer, no admin rights needed).
REM Run this ON WINDOWS, inside the v2scan folder, after:
REM   py -m venv venv
REM   venv\Scripts\activate
REM   pip install -r requirements.txt

pyinstaller ^
  --name V2Scan ^
  --onefile ^
  --windowed ^
  --add-data "gui;gui" ^
  main.py

echo.
echo Build complete. Your portable app is at: dist\V2Scan.exe
echo Copy that single file anywhere and double-click it -- no install required.
echo A "data" folder (saved channels) will be created next to it on first run.
pause
