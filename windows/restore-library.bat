@echo off
rem Restore a library backup (instamcp-library.tgz, made on the Mac with backup-library.sh)
rem into this PC's instamcp data volume. Run it BEFORE using the app on this PC:
rem it replaces this PC's library.
cd /d "%~dp0.."

if not exist instamcp-library.tgz (
  echo Put instamcp-library.tgz in %CD% first.
  pause
  exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
  echo Docker isn't running. Start Docker Desktop first.
  pause
  exit /b 1
)

echo This replaces the library on this PC with the backup.
set /p ok=Type YES to continue:
if /i not "%ok%"=="YES" exit /b 1

docker compose stop instamcp >nul 2>&1
docker volume create instamcp_instamcp-data >nul
docker run --rm -v instamcp_instamcp-data:/data -v "%CD%":/backup alpine ^
  sh -c "find /data -mindepth 1 -maxdepth 1 ! -name models -exec rm -rf {} + && tar xzf /backup/instamcp-library.tgz -C /data"
if errorlevel 1 (
  echo Restore failed. See the messages above.
  pause
  exit /b 1
)
echo Library restored. Now run windows\start.bat
pause
