@echo off
setlocal
cd /d "%~dp0"
title DSC5003 Student Information System
echo Opening the local student information system. Press Ctrl+C to stop.
py -3 -c "import sys;sys.exit(sys.version_info[:2] < (3,9))" >nul 2>nul
if not errorlevel 1 (
    py -3 -X utf8 web_app.py
    goto done
)
for /d %%P in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%~fP\python.exe" (
        "%%~fP\python.exe" -X utf8 web_app.py
        goto done
    )
)
python -c "import sys;sys.exit(sys.version_info[:2] < (3,9))" >nul 2>nul
if errorlevel 1 (
    echo Python 3.9 or later is required. Install it and restart this launcher.
    pause
    exit /b 1
)
python -X utf8 web_app.py
:done
endlocal
pause
