@echo off
echo =======================================================
echo     COMPILING CIVA INS TRACKER PLATFORM (ONE-FILE)
echo =======================================================

:: 1. Clear out old build artifacts to avoid caching bugs
echo [*] Cleaning previous build caches...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: 2. Execute PyInstaller using the single file flag
echo [*] Compiling standalone executable via PyInstaller...
pyinstaller --clean --onefile --icon="vfe.ico" vfe_civa_ins.py
if errorlevel 1 goto BUILD_FAILED

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
