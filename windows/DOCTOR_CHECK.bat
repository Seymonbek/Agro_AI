@echo off
setlocal
cd /d "%~dp0"

if not exist "config.json" (
  if exist "config.example.json" (
    copy /Y "config.example.json" "config.json" >nul
  )
)

echo Running doctor check...
echo.
"%~dp0FlowerRoverControl.exe" doctor
echo.
pause

endlocal
