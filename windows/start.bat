@echo off
rem Start Reel Library in Docker (downloading the latest release first), then open it in the browser.
rem Run it again any time to update to the newest release: your library is kept.
cd /d "%~dp0.."

rem Port for the web app: INSTAMCP_PORT in the .env file next to docker-compose.yml, else 8090.
set INSTAMCP_PORT=8090
if exist .env for /f "usebackq tokens=1,* delims==" %%a in (".env") do if /i "%%a"=="INSTAMCP_PORT" set INSTAMCP_PORT=%%b

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker isn't running. Start Docker Desktop, wait until it says "Engine running", then run this again.
  pause
  exit /b 1
)

echo Downloading the latest Reel Library release (a 1-2 GB download the first time)...
docker compose pull --ignore-pull-failures
echo Starting Reel Library...
docker compose up -d
if errorlevel 1 (
  echo.
  echo Starting failed. See the messages above.
  echo If it says "ports are not available" or "Only one usage of each socket address",
  echo port %INSTAMCP_PORT% is taken on this PC. Pick another one, e.g. 8095:
  echo   echo INSTAMCP_PORT=8095^> "%CD%\.env"
  echo then run this file again.
  pause
  exit /b 1
)

echo Waiting for the app to come up...
for /l %%i in (1,1,60) do (
  curl -s -o nul http://127.0.0.1:%INSTAMCP_PORT%/api/health && goto ready
  timeout /t 2 /nobreak >nul
)
echo The app didn't answer yet. Check the logs with: docker logs instamcp
pause
exit /b 1

:ready
echo Reel Library is running at http://localhost:%INSTAMCP_PORT%
start "" http://localhost:%INSTAMCP_PORT%
