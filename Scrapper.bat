@echo off
REM --- Navigate to the project directory on D: drive ---
D:
cd "\Uni\Roshan Raah\CivicEye\Backend"

REM --- Activate the Python virtual environment ---
call .\venv\Scripts\activate

REM --- Set the Hugging Face cache directory for this session ---
set HF_HOME=D:\HuggingFace_Cache

REM --- Run the Python application ---
python app.py

REM --- Optional: Keep the window open after execution (remove 'pause' if you want it to close automatically) ---
pause