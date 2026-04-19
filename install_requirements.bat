@echo off
setlocal EnableExtensions
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul

set "PYTHON_CMD="
call :detect_python
if not defined PYTHON_CMD (
    echo Python 3.13+ was not found. Installing Python 3.13 with winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo winget is not available. Install Python 3.13 manually, then run this script again.
        popd >nul
        exit /b 1
    )
    winget install --id Python.Python.3.13 -e --scope user --accept-package-agreements --accept-source-agreements
    call :detect_python
)

if not defined PYTHON_CMD (
    echo Python 3.13+ is still unavailable. Install it manually, then run this script again.
    popd >nul
    exit /b 1
)

echo Using %PYTHON_CMD%
echo.
echo Installing runtime requirements from "%SCRIPT_DIR%requirements.txt"...
REM The detected interpreter runs the same flow as:
REM python -m ensurepip --upgrade
REM python -m pip install --upgrade pip
REM python -m pip install -r requirements.txt
call %PYTHON_CMD% -m ensurepip --upgrade >nul 2>&1
call %PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    popd >nul
    exit /b 1
)

set "PIP_USER_FLAG=--user"
if defined VIRTUAL_ENV set "PIP_USER_FLAG="
if defined PIP_USER_FLAG (
    call %PYTHON_CMD% -m pip install %PIP_USER_FLAG% -r "%SCRIPT_DIR%requirements.txt"
) else (
    call %PYTHON_CMD% -m pip install -r "%SCRIPT_DIR%requirements.txt"
)
if errorlevel 1 (
    echo Failed to install the required Python packages.
    popd >nul
    exit /b 1
)

call %PYTHON_CMD% -c "import PySide6"
if errorlevel 1 (
    echo PySide6 import verification failed.
    popd >nul
    exit /b 1
)

echo.
echo Setup complete.
echo Launch commands:
echo   py Tweakify.py
echo   Tweakify.pyw
popd >nul
exit /b 0

:detect_python
set "PYTHON_CMD="
call :try_python "py -3.13"
if defined PYTHON_CMD exit /b 0
call :try_python "py"
if defined PYTHON_CMD exit /b 0
call :try_python "python"
exit /b 0

:try_python
set "CANDIDATE=%~1"
call %CANDIDATE% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 13) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PYTHON_CMD=%CANDIDATE%"
exit /b 0
