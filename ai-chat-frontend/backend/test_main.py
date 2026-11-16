import os
import tempfile
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.testclient import TestClient
from google.genai import types

from backend import main
from backend import storage


class ChatRequestTests(unittest.TestCase):
    def test_strips_message_and_history_content(self) -> None:
        request = main.ChatRequest(
            message="  hello  ",
            history=[{"role": "user", "content": "  earlier message  "}],
        )

        self.assertEqual(request.message, "hello")
        self.assertEqual(request.history[0].content, "earlier message")

    def test_rejects_blank_message(self) -> None:
        with self.assertRaises(ValidationError):
            main.ChatRequest(message="   ")

    def test_requires_timezone_for_client_datetime(self) -> None:
        request = main.ChatRequest(
            message="Schedule for tomorrow",
            client_datetime="2026-11-14T20:16:18-05:00",
        )
        self.assertEqual(request.client_datetime.isoformat(), "2026-11-14T20:16:18-05:00")

        with self.assertRaises(ValidationError):
            main.ChatRequest(
                message="Schedule for tomorrow",
                client_datetime="2026-11-14T20:16:18",
            )


class ChatEndpointTests(unittest.TestCase):
    def tearDown(self) -> None:
        main._genai_client = None

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("backend.main.genai.Client")
    def test_sends_conversation_and_returns_reply(self, client_factory: Mock) -> None:
        client = client_factory.return_value
        client.models.generate_content.return_value.text = "A useful answer"
        client.models.generate_content.return_value.candidates = []
        request = main.ChatRequest(
            message="What next?",
            history=[
                {"role": "user", "content": "I finished the lab."},
                {"role": "model", "content": "Great work."},
            ],
            client_datetime="2026-11-14T20:16:18-05:00",
        )

        result = main.chat(request, user={"id": "test-user"})

        self.assertEqual(result, {"reply": "A useful answer", "pending_conflict": None})
        client_factory.assert_called_once_with(api_key="test-key")
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], main.MODEL_NAME)
        self.assertEqual(
            call["config"].thinking_config.thinking_budget,
            main.THINKING_BUDGET,
        )
        self.assertEqual(
            call["config"].tool_config.function_calling_config.mode,
            "AUTO",
        )
        self.assertTrue(
            call["config"].system_instruction.startswith(main.CALENDAR_SYSTEM_INSTRUCTION)
        )
        self.assertIn(
            "Current user-local date and time: 2026-11-14T20:16:18-05:00",
            call["config"].system_instruction,
        )
        self.assertEqual(
            [(item.role, item.parts[0].text) for item in call["contents"]],
            [
                ("user", "I finished the lab."),
                ("model", "Great work."),
                ("user", "What next?"),
            ],
        )
        self.assertNotIn("calendar", str(call["contents"]).casefold())

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("backend.main.genai.Client")
    def test_returns_plain_text_from_a_normal_model_candidate(self, client_factory: Mock) -> None:
        client = client_factory.return_value
        client.models.generate_content.return_value.candidates = [
            SimpleNamespace(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="Hello! How can I help?")],
                )
            )
        ]

        result = main.chat(main.ChatRequest(message="Hello"), user={"id": "test-user"})

        self.assertEqual(result["reply"], "Hello! How can I help?")

    @patch.dict(os.environ, {}, clear=True)
    def test_reports_missing_api_key(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            main.get_genai_client()

        self.assertEqual(raised.exception.status_code, 503)


class AccountAndCalendarEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {"NEXUS_DATABASE_PATH": os.path.join(self.temp_dir.name, "test.sqlite3")},
        )
        self.env_patch.start()
        self.client = TestClient(main.app)
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def register(self, email: str = "person@example.com") -> dict[str, str]:
        response = self.client.post(
            "/api/auth/register",
            json={
                "email": email,
                "display_name": "Test Person",
                "password": "a secure sample password",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        user = response.json()["user"]
        self.assertNotIn("password_hash", user)
        self.assertIn("httponly", response.headers["set-cookie"].casefold())
        return user

    @staticmethod
    def event(
        title: str,
        time: str = "10:00",
        event_date: str = "2026-11-18",
    ) -> dict[str, str]:
        return {
            "title": title,
            "date": event_date,
            "time": time,
            "type": "appointment",
            "notes": "",
        }

    def test_registration_login_and_calendar_data_are_user_scoped(self) -> None:
        first_user = self.register()
        self.assertEqual(self.client.get("/api/auth/me").json()["user"], first_user)

        created = self.client.post(
            "/api/calendar/events",
            json=self.event("Private exam"),
        )
        self.assertEqual(created.status_code, 201)
        event_id = created.json()["event"]["id"]

        self.client.post("/api/auth/logout")
        second_user = self.register("other@example.com")
        self.assertNotEqual(first_user["id"], second_user["id"])
        self.assertEqual(self.client.get("/api/calendar/events").json()["events"], [])
        self.assertEqual(
            self.client.delete(f"/api/calendar/events/{event_id}").status_code,
            404,
        )

        self.client.post("/api/auth/logout")
        login = self.client.post(
            "/api/auth/login",
            json={"email": "person@example.com", "password": "a secure sample password"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(
            self.client.get("/api/calendar/events").json()["events"][0]["title"],
            "Private exam",
        )

    def test_calendar_rejects_non_quarter_hour_starts(self) -> None:
        self.register()

        response = self.client.post(
            "/api/calendar/events",
            json=self.event("Invalid slot", "10:05"),
        )

        self.assertEqual(response.status_code, 422)

    def test_calendar_can_mark_an_event_done_and_undo_it(self) -> None:
        self.register()
        created = self.client.post(
            "/api/calendar/events",
            json=self.event("Submit checklist"),
        ).json()["event"]

        completed = self.client.patch(
            f"/api/calendar/events/{created['id']}/completion",
            json={"completed": True},
        )
        self.assertEqual(completed.status_code, 200)
        self.assertTrue(completed.json()["event"]["completed"])
        self.assertTrue(self.client.get("/api/calendar/events").json()["events"][0]["completed"])

        reopened = self.client.patch(
            f"/api/calendar/events/{created['id']}/completion",
            json={"completed": False},
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertFalse(reopened.json()["event"]["completed"])

    def test_calendar_validates_duration_in_15_minute_increments(self) -> None:
        self.register()
        start = (date.today() + timedelta(days=2)).isoformat()

        valid = self.client.post(
            "/api/calendar/events",
            json={
                **self.event("Long appointment"),
                "date": start,
                "duration_minutes": 45,
            },
        )
        self.assertEqual(valid.status_code, 201, valid.text)
        self.assertEqual(valid.json()["event"]["duration_minutes"], 45)

        invalid = self.client.post(
            "/api/calendar/events",
            json={
                **self.event("Invalid duration"),
                "date": start,
                "duration_minutes": 20,
            },
        )
        self.assertEqual(invalid.status_code, 422)

    def test_calendar_creates_and_returns_weekly_occurrences(self) -> None:
        self.register()
        start = date.today() + timedelta(days=2)
        response = self.client.post(
            "/api/calendar/events",
            json={
                **self.event("Weekly lab"),
                "date": start.isoformat(),
                "duration_minutes": 45,
                "recurrence": {
                    "frequency": "weekly",
                    "interval": 1,
                    "weekdays": [start.weekday()],
                },
            },
        )
        self.assertEqual(response.status_code, 201, response.text)

        through = (start + timedelta(days=15)).isoformat()
        events = self.client.get(
            f"/api/calendar/events?date_from={start.isoformat()}&date_to={through}",
        ).json()["events"]
        self.assertEqual(len(events), 3)
        self.assertTrue(all(event["duration_minutes"] == 45 for event in events))
        self.assertTrue(all(event["recurrence"]["frequency"] == "weekly" for event in events))

    def test_calendar_api_applies_occurrence_and_following_scopes(self) -> None:
        self.register()
        start = date.today() + timedelta(days=2)
        start_key = start.isoformat()
        created = self.client.post(
            "/api/calendar/events",
            json={
                **self.event("Daily session"),
                "date": start_key,
                "recurrence": {"frequency": "daily"},
            },
        )
        self.assertEqual(created.status_code, 201, created.text)

        through = (start + timedelta(days=4)).isoformat()
        events = self.client.get(
            f"/api/calendar/events?date_from={start_key}&date_to={through}",
        ).json()["events"]
        updated = self.client.put(
            f"/api/calendar/events/{events[1]['id']}?scope=this_occurrence",
            json={
                **self.event("Changed once", event_date=events[1]["date"]),
                "duration_minutes": 30,
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        deleted = self.client.delete(
            f"/api/calendar/events/{events[2]['id']}?scope=following",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        remaining = self.client.get(
            f"/api/calendar/events?date_from={start_key}&date_to={through}",
        ).json()["events"]
        self.assertEqual(
            [(event["date"], event["title"]) for event in remaining],
            [(start_key, "Daily session"), (events[1]["date"], "Changed once")],
        )

    def test_calendar_conflicts_wait_for_an_explicit_resolution(self) -> None:
        self.register()
        self.client.post("/api/calendar/events", json=self.event("Existing"))

        response = self.client.post(
            "/api/calendar/events",
            json=self.event("Proposed"),
        )
        self.assertEqual(response.status_code, 409)
        proposal = response.json()["detail"]
        self.assertEqual(len(self.client.get("/api/calendar/events").json()["events"]), 1)

        result = self.client.post(
            f"/api/calendar/proposals/{proposal['proposal_id']}/resolve",
            json={"resolution": "overlap"},
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["resolution"], "overlap")
        self.assertEqual(len(self.client.get("/api/calendar/events").json()["events"]), 2)

    def test_calendar_routes_require_a_session(self) -> None:
        response = self.client.get("/api/calendar/events")

        self.assertEqual(response.status_code, 401)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_chat_looks_up_only_related_events_when_the_model_calls_the_tool(self) -> None:
        user = self.register()
        storage.create_or_propose_event(
            user["id"],
            {
                "title": "Network exam",
                "date": "2026-11-18",
                "time": "10:00",
                "type": "appointment",
                "notes": "Bring a calculator",
            },
        )
        storage.create_or_propose_event(
            user["id"],
            {
                "title": "Dentist",
                "date": "2026-11-19",
                "time": "11:00",
                "type": "appointment",
                "notes": "",
            },
        )
        lookup_call = types.FunctionCall(
            name="lookup_calendar_events",
            args={"query": "network exam"},
        )
        tool_response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=lookup_call)],
                    )
                )
            ],
            text=None,
        )
        final_response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="Your network exam is on November 18.")],
                    )
                )
            ],
            text="Your network exam is on November 18.",
        )
        client = Mock()
        client.models.generate_content.side_effect = [tool_response, final_response]

        with patch("backend.main.get_genai_client", return_value=client):
            result = main.chat(
                main.ChatRequest(message="When is my network exam?"),
                user=user,
            )

        self.assertIn("November 18", result["reply"])
        self.assertIsNone(result["pending_conflict"])
        self.assertEqual(client.models.generate_content.call_count, 2)
        follow_up = client.models.generate_content.call_args_list[1].kwargs["contents"]
        response_part = follow_up[-1].parts[0].function_response
        self.assertEqual(follow_up[-1].role, "user")
        self.assertEqual(response_part.response["events"][0]["title"], "Network exam")
        self.assertNotIn("notes", response_part.response["events"][0])
        self.assertNotIn("Dentist", str(response_part.response))

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_gemini_schedule_conflict_returns_user_resolution_options(self) -> None:
        user = self.register()
        meeting_date = (date.today() + timedelta(days=1)).isoformat()
        self.client.post(
            "/api/calendar/events",
            json={
                **self.event("Four-hour meeting", "05:00", meeting_date),
                "duration_minutes": 240,
            },
        )
        create_call = types.FunctionCall(
            name="create_calendar_event",
            args={
                "title": "Coffee break",
                "date": meeting_date,
                "time": "08:00",
                "duration_minutes": 15,
                "type": "appointment",
            },
        )
        tool_response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=create_call)],
                    )
                )
            ],
            text=None,
        )
        final_response = SimpleNamespace(
            candidates=[],
            text="There is a conflict. Please choose a resolution.",
        )
        client = Mock()
        client.models.generate_content.side_effect = [tool_response, final_response]

        with patch("backend.main.get_genai_client", return_value=client):
            result = main.chat(
                main.ChatRequest(message="Schedule a 15-minute coffee break at 8 AM tomorrow."),
                user=user,
            )

        self.assertEqual(result["pending_conflict"]["title"], "Coffee break")
        self.assertEqual(len(result["pending_conflict"]["conflicts"]), 1)
        self.assertEqual(
            result["pending_conflict"]["conflicts"][0]["title"],
            "Four-hour meeting",
        )
        self.assertEqual(
            result["pending_conflict"]["conflicts"][0]["duration_minutes"],
            240,
        )
        self.assertEqual(
            result["pending_conflict"]["conflicts"][0]["time"],
            "05:00",
        )
        self.assertEqual(result["pending_conflict"]["duration_minutes"], 15)
        self.assertEqual(
            result["reply"],
            "I found a calendar conflict. Nothing has been changed. "
            "Review the event times and choose how to proceed below.",
        )
        self.assertEqual(client.models.generate_content.call_count, 1)
        self.assertEqual(len(self.client.get("/api/calendar/events").json()["events"]), 1)

        resolution = self.client.post(
            f"/api/calendar/proposals/{result['pending_conflict']['proposal_id']}/resolve",
            json={"resolution": "reject"},
        )
        self.assertEqual(resolution.json()["status"], "rejected")
        self.assertEqual(len(self.client.get("/api/calendar/events").json()["events"]), 1)

    def test_gemini_calendar_tool_creates_a_recurring_45_minute_event(self) -> None:
        user = self.register()
        start = date.today() + timedelta(days=2)
        result, pending = main._calendar_function_result(
            "create_calendar_event",
            {
                "title": "Weekly study session",
                "date": start.isoformat(),
                "time": "10:00",
                "duration_minutes": 45,
                "recurrence": {
                    "frequency": "weekly",
                    "interval": 1,
                    "weekdays": [start.weekday()],
                },
            },
            user["id"],
        )

        self.assertIsNone(pending)
        self.assertEqual(result["status"], "created")
        self.assertGreater(result["occurrence_count"], 1)
        self.assertEqual(result["event"]["date"], start.isoformat())
        self.assertEqual(result["event"]["recurrence"]["frequency"], "weekly")
        events = storage.list_events(
            user["id"],
            start.isoformat(),
            (start + timedelta(days=15)).isoformat(),
        )
        self.assertEqual(len(events), 3)
        self.assertTrue(all(event["duration_minutes"] == 45 for event in events))

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_chat_confirms_successful_schedule_without_second_model_call(self) -> None:
        user = self.register()
        event_date = (date.today() + timedelta(days=1)).isoformat()
        create_call = types.FunctionCall(
            name="create_calendar_event",
            args={
                "title": "Project meeting",
                "date": event_date,
                "time": "05:00",
                "duration_minutes": 240,
                "type": "appointment",
            },
        )
        tool_response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=create_call)],
                    )
                )
            ],
            text=None,
        )
        client = Mock()
        client.models.generate_content.return_value = tool_response

        with patch("backend.main.get_genai_client", return_value=client):
            result = main.chat(
                main.ChatRequest(message="Schedule a four-hour project meeting."),
                user=user,
            )

        self.assertEqual(
            result["reply"],
            f'Scheduled "Project meeting" on {event_date} at 05:00 for 4 hours.',
        )
        self.assertIsNone(result["pending_conflict"])
        client.models.generate_content.assert_called_once()
        events = self.client.get("/api/calendar/events").json()["events"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["duration_minutes"], 240)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_chat_marks_lookup_result_done_without_looping(self) -> None:
        user = self.register()
        created = self.client.post(
            "/api/calendar/events",
            json=self.event("Tuesday meeting", "10:30", "2026-11-17"),
        ).json()["event"]
        lookup_call = types.FunctionCall(
            name="lookup_calendar_events",
            args={"query": "meeting", "date_from": "2026-11-17", "date_to": "2026-11-17"},
        )
        lookup_response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=lookup_call)],
                    )
                )
            ],
            text=None,
        )
        mark_call = types.FunctionCall(
            name="mark_calendar_event_done",
            args={"event_id": created["id"], "completed": True},
        )
        mark_response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=mark_call)],
                    )
                )
            ],
            text=None,
        )
        client = Mock()
        client.models.generate_content.side_effect = [lookup_response, mark_response]

        with patch("backend.main.get_genai_client", return_value=client):
            result = main.chat(
                main.ChatRequest(message="Check off the meeting on Tuesday as done."),
                user=user,
            )

        self.assertEqual(
            result["reply"],
            'marked "Tuesday meeting" as done on 2026-11-17 at 10:30.',
        )
        self.assertEqual(client.models.generate_content.call_count, 2)
        first_config = client.models.generate_content.call_args_list[0].kwargs["config"]
        second_config = client.models.generate_content.call_args_list[1].kwargs["config"]
        self.assertEqual(
            first_config.tool_config.function_calling_config.allowed_function_names,
            ["lookup_calendar_events"],
        )
        self.assertEqual(
            second_config.tool_config.function_calling_config.allowed_function_names,
            ["mark_calendar_event_done"],
        )
        self.assertTrue(
            self.client.get("/api/calendar/events").json()["events"][0]["completed"]
        )

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    def test_chat_cannot_remove_an_event_without_a_lookup_result(self) -> None:
        user = self.register()
        created = self.client.post(
            "/api/calendar/events",
            json=self.event("Important exam"),
        ).json()["event"]
        remove_call = types.FunctionCall(
            name="remove_calendar_event",
            args={"event_id": created["id"]},
        )
        tool_response = SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=types.Content(
                        role="model",
                        parts=[types.Part(function_call=remove_call)],
                    )
                )
            ],
            text=None,
        )
        final_response = SimpleNamespace(candidates=[], text="I found the event.")
        client = Mock()
        client.models.generate_content.side_effect = [tool_response, final_response]

        with patch("backend.main.get_genai_client", return_value=client):
            main.chat(
                main.ChatRequest(message="Remove my important exam."),
                user=user,
            )

        events = storage.list_events(user["id"])
        self.assertEqual([event["title"] for event in events], ["Important exam"])
        tool_result = client.models.generate_content.call_args_list[1].kwargs["contents"][-1]
        self.assertIn("Look up the requested event first", str(tool_result.parts[0].function_response.response))


if __name__ == "__main__":
    unittest.main()
