@echo off
setlocal
chcp 65001 >nul

set SKRYPT=main.py
set NAZWA_EXE=JEP_TimeTrack
set PYCMD=

REM --- 1. Wykrycie dostepnej komendy Pythona ---
py --version >nul 2>&1
if errorlevel 1 goto try_python
set PYCMD=py
goto python_ok

:try_python
python --version >nul 2>&1
if errorlevel 1 goto no_python
set PYCMD=python
goto python_ok

:no_python
echo [BLAD] Nie znaleziono Pythona w PATH.
echo Pobierz Pythona z https://www.python.org/downloads i zaznacz Add to PATH.
pause
exit /b 1

:python_ok
echo [i] Wykryto komende Pythona: %PYCMD%

REM --- 2. Sprawdzenie czy wszystkie wymagane pliki istnieja ---
if not exist "%SKRYPT%" goto brak_skryptu
if not exist "app.py" goto brak_app
if not exist "model" goto brak_model
if not exist "view" goto brak_view
goto pliki_ok

:brak_skryptu
echo [BLAD] Nie znaleziono pliku %SKRYPT% w tym folderze.
pause
exit /b 1

:brak_app
echo [BLAD] Brak pliku app.py w tym folderze.
pause
exit /b 1

:brak_model
echo [BLAD] Brak folderu model w tym katalogu.
pause
exit /b 1

:brak_view
echo [BLAD] Brak folderu view w tym katalogu.
pause
exit /b 1

:pliki_ok
REM --- 3. Instalacja wymaganych bibliotek ---
REM Program korzysta z requests i Pillow, nie z pandas ani selenium
echo [1/3] Instaluje wymagane biblioteki: requests, Pillow, pyinstaller
%PYCMD% -m pip install --upgrade pip >nul
%PYCMD% -m pip install --upgrade requests Pillow pyinstaller
if errorlevel 1 goto blad_pip
goto kompiluj

:blad_pip
echo [BLAD] Nie udalo sie zainstalowac wymaganych bibliotek.
pause
exit /b 1

:kompiluj
echo.
echo [2/3] Kompiluje %SKRYPT% do pliku exe
echo To moze potrwac kilka minut, prosze czekac.
echo.
%PYCMD% -m PyInstaller --noconfirm --onefile --windowed --name "%NAZWA_EXE%" --hidden-import "PIL._tkinter_finder" --hidden-import "PIL.Image" --hidden-import "PIL.ImageDraw" --hidden-import "PIL.ImageTk" --collect-submodules "PIL" --collect-submodules "model" --collect-submodules "view" "%SKRYPT%"
if errorlevel 1 goto blad_kompilacji
goto sukces

:blad_kompilacji
echo.
echo [BLAD] Kompilacja nie powiodla sie. Sprawdz komunikaty powyzej.
pause
exit /b 1

:sukces
echo.
echo [3/3] Gotowe!
echo Plik exe znajduje sie w folderze dist\%NAZWA_EXE%.exe
echo.

if exist "build" rmdir /s /q "build"
if exist "%NAZWA_EXE%.spec" del /q "%NAZWA_EXE%.spec"

echo Otwieram folder z gotowym plikiem...
start "" "dist"

pause
endlocal