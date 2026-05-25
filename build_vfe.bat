@echo off
echo =======================================================
echo     COMPILING CIVA INS TRACKER PLATFORM (ONE-FILE)
echo =======================================================

:: 1. Clear out old build artifacts to avoid caching bugs
echo [*] Cleaning previous build caches...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: 1.5 Terminate running processes to unlock target file handles
echo Cleaning memory handles...
taskkill /F /IM VFE_civa_ins.exe >nul 2>&1
taskkill /F /IM VFEtray.exe >nul 2>&1

:: 2. Execute PyInstaller using the single file flag
echo [*] Compiling standalone executable via PyInstaller...
pyinstaller --clean --onefile --noconsole --add-binary "C:\MSFS 2024 SDK\SimConnect SDK\lib\SimConnect.dll;."  --icon="vfe.ico" vfe_civa_ins.py
if errorlevel 1 goto BUILD_FAILED

rem echo Running PyInstaller compilation...
rem pyinstaller --noconfirm --windowed --name="VFE_civa_ins" --uac-admin --hidden-import="SimConnect" --clean VFE_civa_ins.py

:: 3. Create a clean distribution package folder
echo [*] Structuring release folder...
set RELEASE_DIR=dist\VFE_civa_ins_Release
mkdir "%RELEASE_DIR%"

:: 4. Move your application binaries side-by-side
move dist\vfe_civa_ins.exe "%RELEASE_DIR%\"
copy ..\MouseOps\VFEtray.exe "%RELEASE_DIR%\"

echo =======================================================
echo     BUILD SUCCESSFUL!
echo =======================================================
echo  Your deployment folder is ready here: 
echo  %RELEASE_DIR%
echo =======================================================
pause
exit /b 0

:BUILD_FAILED
echo =======================================================
echo  ❌ ERROR: PyInstaller failed to compile the project.
echo =======================================================
pause
exit /b 1
