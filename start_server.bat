@echo off
echo Iniciando el entorno virtual y el servidor FastAPI...

REM Activa el entorno virtual. Asume que se llama "venv"
call venv\Scripts\activate

REM Inicia el servidor FastAPI en segundo plano
start /B python -m uvicorn app:app --host 127.0.0.1 --port 8000

REM Espera un momento para que el servidor se inicie
timeout /t 5 >nul

REM Abre el navegador automáticamente
start "" "http://127.0.0.1:8000"

echo Servidor iniciado. No cierre esta ventana.
pause