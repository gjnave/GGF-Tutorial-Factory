@echo off
setlocal
set "FACTORY_ROOT=%~dp0"

if "%~2"=="" (
  echo Usage: generate-darla-a2v.bat tutorial.yaml output-folder [--only N]
  echo First run segment 1 as the proof: generate-darla-a2v.bat tutorial.yaml output-folder --only 1
  exit /b 2
)

if not exist "%FACTORY_ROOT%.venv\Scripts\python.exe" (
  echo Missing factory Python: %FACTORY_ROOT%.venv\Scripts\python.exe
  exit /b 1
)

pushd "%FACTORY_ROOT%" >nul
"%FACTORY_ROOT%.venv\Scripts\python.exe" -m scripts.generate_darla_ltx_a2v %*
set "DARLA_EXIT=%ERRORLEVEL%"
popd
exit /b %DARLA_EXIT%
