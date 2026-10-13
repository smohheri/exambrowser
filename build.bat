@echo off
REM Build ExamBrowser.exe (single file, PySide6 + QtWebEngine) with PyInstaller.
REM config.json is bundled inside the exe. Output: dist\ExamBrowser.exe

setlocal
cd /d "%~dp0"

set PY=C:\anaconda2\python.exe

echo Cleaning and building from ExamBrowser.spec...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
"%PY%" -m PyInstaller --noconfirm --clean ExamBrowser.spec
if errorlevel 1 goto :error

echo.
echo BUILD OK -^> dist\ExamBrowser.exe (config.json bundled inside)
goto :eof

:error
echo.
echo BUILD FAILED
exit /b 1
