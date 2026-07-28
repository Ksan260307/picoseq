@echo off
rem Build PicoSeq for distribution. Installs PyInstaller on first run.
rem
rem NOTE: keep this file ASCII-only. cmd.exe reads .bat with the console
rem code page, so UTF-8 Japanese here gets mis-decoded and can split
rem commands in half (it did). The Japanese explanation lives in README.md.
rem
rem Two builds, same contents:
rem   dist\PicoSeq\PicoSeq.exe   folder build. starts fast (measured 1.7-1.9 s)
rem   dist\PicoSeq-portable.exe  single file. easy to carry, slower to start
rem                              (unpacks itself every launch: 5.1-5.7 s)
rem Ship the folder build as a zip for normal distribution.
cd /d "%~dp0"

py -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    py -m pip install pyinstaller
    if errorlevel 1 goto err
)

echo [1/2] Building the folder version (fast start)...
py -m PyInstaller --noconfirm --clean --onedir --windowed --name PicoSeq main.py
if errorlevel 1 goto err

echo [2/2] Building the single-file version...
py -m PyInstaller --noconfirm --onefile --windowed --name PicoSeq-portable main.py
if errorlevel 1 goto err

echo.
echo Done:
echo   dist\PicoSeq\PicoSeq.exe   (folder, fast start)
echo   dist\PicoSeq-portable.exe  (single file)
exit /b 0

:err
echo Build failed. Check your internet connection and Python setup.
exit /b 1
