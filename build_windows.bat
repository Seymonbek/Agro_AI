@echo off
setlocal

if not exist .venv (
  py -m venv .venv
)

call .venv\Scripts\activate
if errorlevel 1 exit /b 1

python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 exit /b 1

python -m pip install -r requirements-windows.txt
if errorlevel 1 exit /b 1

REM PyTorch CPU wheels from official PyTorch index for Windows packaging reliability.
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 exit /b 1

REM CLIP dependency for YOLOWorld without requiring a local git installation.
python -m pip install https://github.com/ultralytics/CLIP/archive/81ff68ed7ffcac3b40484c914f104f816757308d.zip
if errorlevel 1 exit /b 1

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller --noconfirm FlowerRoverControl.spec
if errorlevel 1 exit /b 1

copy /Y config.example.json dist\FlowerRoverControl\config.example.json >nul
copy /Y windows\START_FLOWER_ROVER.bat dist\FlowerRoverControl\START_FLOWER_ROVER.bat >nul
copy /Y windows\DOCTOR_CHECK.bat dist\FlowerRoverControl\DOCTOR_CHECK.bat >nul

if not exist dist\FlowerRoverControl\config.json (
  copy /Y config.example.json dist\FlowerRoverControl\config.json >nul
)

echo.
echo Running packaging smoke test...
dist\FlowerRoverControl\FlowerRoverControl.exe doctor --skip-cameras --skip-esp32
if errorlevel 1 exit /b 1

echo.
echo Build tayyor: dist\FlowerRoverControl\
echo Ishga tushirish uchun START_FLOWER_ROVER.bat yoki FlowerRoverControl.exe ni oching.
echo Doctor tekshiruvi uchun DOCTOR_CHECK.bat ni ishga tushiring.
if exist dist\FlowerRoverControl\.cache\clip\ViT-B-32.pt (
  echo CLIP cache bundled: yes
) else (
  echo CLIP cache bundled: no
  echo Internet kerak bo'lishi mumkin, birinchi ishga tushirishda model cache yuklanadi.
)
