@echo off
REM Starts the AI gateway for the RTS AI Commander on http://127.0.0.1:8765
REM First run creates ai\.venv and installs requirements. Ollama must be running with llama3.1:8b pulled.
REM The game now starts the gateway itself (AiServiceLauncher + StreamingAssets/ai_services.json); this script is for manual use.
REM First run: install the CUDA build of torch BEFORE requirements (see README), otherwise laya pulls the CPU-only torch.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Creating virtual environment...
    py -3 -m venv .venv || python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)

if not exist "rag\index\index.json" (
    ".venv\Scripts\python.exe" -m rag.build_index || goto :error
)

set PYTHONIOENCODING=utf-8
echo [run] AI gateway on http://127.0.0.1:8765  (Ctrl+C to stop)
".venv\Scripts\python.exe" -m gateway
goto :eof

:error
echo [error] Setup failed. See the messages above.
REM The game starts this script hidden (RTS_NO_PAUSE=1); only wait for a key when a person double-clicked it
if not defined RTS_NO_PAUSE pause
exit /b 1
