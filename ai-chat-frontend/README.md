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

The Vite development server proxies `/api` requests to the Python backend at `http://127.0.0.1:8000`. The chat endpoint is `POST /api/chat`; it accepts a message and the current conversation history and returns the Gemini response. The backend uses the `gemini-2.5-flash` model.

On first use, create a Nexus account from the sign-in screen. Passwords are stored as scrypt hashes, sessions use HTTP-only cookies, and each account's calendar events are isolated in the backend SQLite database (`.nexus.sqlite3` by default). Set `NEXUS_DATABASE_PATH` to choose another database location. When serving over HTTPS, set `NEXUS_COOKIE_SECURE=true`.

The chat composer shows the browser's local date and time with its timezone. Each chat request includes that offset-aware timestamp as system context so Gemini can resolve relative dates such as "tomorrow" against the user's clock.

Calendar events must start on 15-minute boundaries and can last from 15 minutes up to 24 hours in 15-minute increments. Events can repeat daily, weekly on selected weekdays, monthly, or yearly; the calendar generates recurring occurrences one year ahead and extends the series as later dates are viewed. When editing or deleting a recurring event, choose this occurrence, this and following, or the entire series.

If a new event or recurring series conflicts with existing events, choose whether to override them, allow the overlaps, or reject the change. For a series, one choice applies to every conflict in the proposal. Gemini can schedule event durations and recurrence through its calendar tool, but does not receive the calendar on every chat request; event data is returned only for a specific lookup or scheduling operation, and lookups are limited to related events.

Run backend tests from `ai-chat-frontend` with:

```powershell
python -m unittest backend.test_main backend.test_storage
```

Notes
11/14/2026: Cannot specify day to schedule events on calendar and needed exact date to schedule events. That has been fixed but model now overrides its events without asking how to resolve conflicts.