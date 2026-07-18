@echo off
rem PicoSeq を配布用の単一 exe にする。初回のみ PyInstaller を自動導入する。
cd /d "%~dp0"

py -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller を導入しています...
    py -m pip install pyinstaller
    if errorlevel 1 goto err
)

py -m PyInstaller --noconfirm --clean --onefile --windowed --name PicoSeq main.py
if errorlevel 1 goto err

echo.
echo 完成: dist\PicoSeq.exe
exit /b 0

:err
echo ビルドに失敗しました。インターネット接続と Python 環境を確認してください。
exit /b 1
