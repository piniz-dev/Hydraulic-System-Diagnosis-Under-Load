@echo off
setlocal
cd /d "%~dp0"
set PYTHONUNBUFFERED=1

where python >nul 2>&1
if errorlevel 1 (
  echo Python non trovato nel PATH.
  pause
  exit /b 1
)

echo Scarico il dataset, se non e' gia' presente...
python -c "import comune; comune.scarica_dataset()"
if errorlevel 1 (
  echo Download del dataset fallito.
  pause
  exit /b 1
)

for /f "usebackq tokens=1,2" %%a in (`python -c "import comune; c=comune.cfg['api']; print(c['host'], c['porta'])"`) do (
  set "HOST=%%a"
  set "PORT=%%b"
)

powershell -NoProfile -Command "try { Invoke-WebRequest http://%HOST%:%PORT%/stats -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo Avvio API e worker...
  start "API operatore" cmd /k python -u api.py
  start "Worker" cmd /k python -u worker.py 1
) else (
  echo API gia' attiva.
)
echo Pagina: http://%HOST%:%PORT%/

echo Attendo la pagina operatore...
set /a TRIES=0
:attesa
set /a TRIES+=1
powershell -NoProfile -Command "try { Invoke-WebRequest http://%HOST%:%PORT%/stats -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 goto pronta
if %TRIES% GEQ 40 (
  echo La pagina non risponde su http://%HOST%:%PORT%/
  pause
  exit /b 1
)
powershell -NoProfile -Command "Start-Sleep -Seconds 1"
goto attesa

:pronta
start "" "http://%HOST%:%PORT%/"
for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "TAG=lancio-%%t"
echo Invio 20 cicli a 2 al secondo, tag %TAG%
python replay.py %TAG% 2 20
if errorlevel 1 (
  echo Invio dei cicli fallito.
  pause
  exit /b 1
)

echo.
echo Fatto. Risultati su http://%HOST%:%PORT%/
echo Per fermare il programma chiudi le finestre "API operatore" e "Worker".
pause
endlocal
