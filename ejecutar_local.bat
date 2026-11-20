@echo off
cd /d "%~dp0"
set DEBUG=1
if "%PORT%"=="" set PORT=8000
if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual e instalando dependencias...
  python -m venv .venv || exit /b 1
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
)
".venv\Scripts\python.exe" manage.py migrate || exit /b 1
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:%PORT%
