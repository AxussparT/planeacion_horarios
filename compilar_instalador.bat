@echo off
chcp 65001 > nul
echo ========================================================
echo        CONSTRUCCIÓN DEL INSTALADOR OFICIAL SAGA
echo ========================================================
echo.

cd /d "%~dp0"

echo [1/2] Compilando ejecutable con PyInstaller...
python -m PyInstaller --noconfirm --clean arrancar.spec
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Falló la compilación con PyInstaller.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [2/2] Generando instalador con Inno Setup...
set "ISCC_PATH=%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
if not exist "%ISCC_PATH%" (
    set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if not exist "%ISCC_PATH%" (
    set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if not exist "%ISCC_PATH%" (
    echo [ERROR] No se encontró ISCC.exe de Inno Setup.
    pause
    exit /b 1
)

"%ISCC_PATH%" "instalador\SAGA.iss"
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Falló la generación del instalador con Inno Setup.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================================
echo   ¡INSTALADOR GENERADO CON ÉXITO EN instalador\!
echo ========================================================
pause
