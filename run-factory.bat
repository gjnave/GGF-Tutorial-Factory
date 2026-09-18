@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Tutorial Factory environment is missing.
  echo Run setup.bat first.
  pause
  exit /b 1
)

if "%~1"=="" (
  cls
  echo ========================================
  echo   GGF Tutorial Factory
  echo ========================================
  echo.
  echo 1. Build GrizzlyMax approved V2 tutorial
  echo 2. Guided Qt tutorial - new application
  echo 3. Rehearse an existing tutorial
  echo 4. Build an existing tutorial
  echo 5. Exit
  echo.
  set /p "CHOICE=Choose 1-5: "
  if "!CHOICE!"=="1" ".venv\Scripts\python.exe" -m factory.cli build --project grizzlymax --tutorial complete-workflow
  if "!CHOICE!"=="2" ".venv\Scripts\python.exe" -m factory.cli guided
  if "!CHOICE!"=="3" goto REHEARSE
  if "!CHOICE!"=="4" goto BUILD
  if "!CHOICE!"=="5" exit /b 0
) else (
  ".venv\Scripts\python.exe" -m factory.cli %*
)

goto FINISH

:REHEARSE
set /p "PROJECT=Project id: "
set /p "TUTORIAL=Tutorial id [getting-started]: "
if "%TUTORIAL%"=="" set "TUTORIAL=getting-started"
".venv\Scripts\python.exe" -m factory.cli rehearse --project "%PROJECT%" --tutorial "%TUTORIAL%"
goto FINISH

:BUILD
set /p "PROJECT=Project id: "
set /p "TUTORIAL=Tutorial id [getting-started]: "
if "%TUTORIAL%"=="" set "TUTORIAL=getting-started"
".venv\Scripts\python.exe" -m factory.cli build --project "%PROJECT%" --tutorial "%TUTORIAL%"

:FINISH
set "RESULT=%ERRORLEVEL%"
echo.
echo Tutorial Factory exit code: %RESULT%
if not "%RESULT%"=="0" pause
exit /b %RESULT%
