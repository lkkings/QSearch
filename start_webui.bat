@echo off
REM QSearch WebUI Startup Script (Windows)

echo ====================================
echo QSearch WebUI Startup
echo ====================================
echo.

REM Set database root directory
set QSEARCH_DATABASES_ROOT=databases
echo [1/3] Database directory: %QSEARCH_DATABASES_ROOT%

REM Activate virtual environment
if exist .venv\Scripts\activate.bat (
    echo [2/3] Activating virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo [2/3] WARNING: Virtual environment not found at .venv\Scripts\
    echo       Trying to use global Python environment...
)

REM Start Streamlit
echo [3/3] Starting Streamlit WebUI...
echo.
streamlit run src/qsearch/webui/app.py

pause
