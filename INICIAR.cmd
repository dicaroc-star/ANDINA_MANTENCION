@echo off
setlocal
cd /d "%~dp0"
title AndinaMantencion V2 - Servidor Oracle
if not exist "%~dp0server.py" (
  echo Extrae TODO el ZIP antes de abrir INICIAR.cmd.
  echo Deben estar juntos server.py, schema.py, service.py y security.py.
  pause
  exit /b 1
)
py --version >nul 2>&1
if errorlevel 1 (
  echo No se encontro Python. Instala Python desde https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
py -c "import oracledb, PIL, qrcode, waitress" >nul 2>&1
if errorlevel 1 (
  echo Instalando las dependencias de AndinaMantencion...
  py -m pip install -r requirements.txt
  if errorlevel 1 (
    echo No se pudieron instalar las dependencias.
    pause
    exit /b 1
  )
)
py server.py
echo.
echo El servidor termino. Lee el mensaje anterior antes de cerrar esta ventana.
pause
