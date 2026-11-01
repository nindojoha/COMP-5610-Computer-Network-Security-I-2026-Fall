# Nexus AI workspace

## Run locally

1. Add your Google AI Studio key as `GEMINI_API_KEY` in the project-root `.env` file. The `.env` file is loaded by the Python backend and is ignored by Git.
2. In PowerShell, create and activate a Python environment, then install the backend dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

3. Start the backend in one terminal:

   ```powershell
   python -m uvicorn backend.main:app --reload
   ```

4. Start the frontend in another terminal:

   ```powershell
   npm install
   npm run dev
   ```

The Vite development server proxies `/api` requests to the Python backend at `http://127.0.0.1:8000`. The chat endpoint is `POST /api/chat`; it accepts a message and the current conversation history and returns the Gemini response. The backend uses the `gemini-3.8-flash` model.

Run backend tests with:

```powershell
python -m unittest backend.test_main
```
