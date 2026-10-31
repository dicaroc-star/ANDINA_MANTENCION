@echo off
setlocal
cd /d "%~dp0"
if not exist provision_user.py (
  echo Extrae TODO el ZIP antes de ejecutar este archivo.
  pause
  exit /b 1
)
py -c "import oracledb" >nul 2>&1
if errorlevel 1 (
  echo Primero ejecuta INICIAR.cmd para instalar el controlador o revisa Python.
  pause
  exit /b 1
)
py provision_user.py
echo.
echo Lee el resultado antes de cerrar.
pause
