@echo off
rem Genera panel\dist\RyxPanel.exe (Windows; requiere Python y pyinstaller)
cd /d "%~dp0.."
python -m PyInstaller --noconfirm --onefile --windowed --name RyxPanel ^
  --distpath panel\dist --workpath panel\build --specpath panel\build panel\ryx_panel.py
echo.
echo Listo: panel\dist\RyxPanel.exe
pause
