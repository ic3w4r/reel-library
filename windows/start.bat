@echo off
rem Build and start Reel Library (instamcp) in Docker, then open it in the browser.
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

echo Building and starting instamcp. The first build takes 5-10 minutes...
docker compose up -d --build
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
