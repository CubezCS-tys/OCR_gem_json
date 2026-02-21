@echo off
REM OCR Correction Editor - Windows Launcher
REM Double-click this file to start the editor
REM Requires: Python 3 (https://www.python.org/downloads/)

SETLOCAL
set "SCRIPT_DIR=%~dp0"

REM Auto-detect data folder
if exist "%SCRIPT_DIR%..\output_final\" (
    set "DATA_DIR=%SCRIPT_DIR%..\output_final"
) else if exist "%SCRIPT_DIR%output_final\" (
    set "DATA_DIR=%SCRIPT_DIR%output_final"
) else (
    echo Could not auto-detect output_final folder.
    set /p DATA_DIR="Enter path to your output_final folder: "
    if not exist "!DATA_DIR!\" (
        echo ERROR: Folder not found.
        pause
        exit /b 1
    )
)

echo ======================================
echo    OCR Correction Editor
echo    Starting server...
echo    Data: %DATA_DIR%
echo ======================================
echo.
echo Press Ctrl+C to stop.
echo.

REM Try python3 first, then python
where python3 >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python3 "%SCRIPT_DIR%start_server.py" "%DATA_DIR%"
    goto :end
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python "%SCRIPT_DIR%start_server.py" "%DATA_DIR%"
    goto :end
)

REM Check common portable python locations on USB
if exist "%SCRIPT_DIR%python\python.exe" (
    "%SCRIPT_DIR%python\python.exe" "%SCRIPT_DIR%start_server.py" "%DATA_DIR%"
    goto :end
)

echo ERROR: Python 3 is required but not found.
echo.
echo Options:
echo   1. Install Python 3 from https://www.python.org/downloads/
echo   2. Place WinPython/Portable Python in a 'python' subfolder
echo.

:end
pause
