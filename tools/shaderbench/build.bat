@echo off
rem Builds out\shaderbench\shaderbench.exe with MSVC (found through vswhere).
setlocal
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -property installationPath`) do set "VS=%%i"
if not defined VS echo Visual Studio not found & exit /b 1
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
set "OUT=%~dp0..\..\out\shaderbench"
if not exist "%OUT%" mkdir "%OUT%"
cl /nologo /O2 /EHsc /W3 /std:c++17 /Fo"%OUT%\\" /Fe"%OUT%\shaderbench.exe" "%~dp0shaderbench.cpp" d3d11.lib d3dcompiler.lib dxguid.lib
exit /b %ERRORLEVEL%
