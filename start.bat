@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  set PY=python
) else (
  set PY=py -3
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
if not exist ".env" (
  echo [2/3] Creating .env from .env.example...
  copy ".env.example" ".env" >nul
)
echo [2/3] Installing/updating dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
for /f "tokens=1,* delims==" %%A in ('findstr /b "HOST=" .env') do set HOST_VALUE=%%B
for /f "tokens=1,* delims==" %%A in ('findstr /b "PORT=" .env') do set PORT_VALUE=%%B
if "%HOST_VALUE%"=="" set HOST_VALUE=127.0.0.1
if "%PORT_VALUE%"=="" set PORT_VALUE=8000
rem HOST is a bind address, not a browsable URL. The app prints usable addresses on startup.
echo [3/3] Starting Personal Knowledge Agent...
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host "%HOST_VALUE%" --port "%PORT_VALUE%"
if errorlevel 1 goto :fail
goto :eof
:fail
echo.
echo Startup failed. Check the Python installation and network access for package installation.
pause
exit /b 1
