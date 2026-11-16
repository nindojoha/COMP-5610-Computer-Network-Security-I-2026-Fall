import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from backend import storage


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {"NEXUS_DATABASE_PATH": os.path.join(self.temp_dir.name, "test.sqlite3")},
        )
        self.env_patch.start()
        self.owner = storage.create_user("owner@example.com", "Owner", "correct horse battery")
        self.other = storage.create_user("other@example.com", "Other", "another strong password")

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def event(
        title: str,
        time: str = "10:00",
        event_date: str = "2026-11-18",
        duration_minutes: int = 15,
    ) -> dict[str, object]:
        return {
            "title": title,
            "date": event_date,
            "time": time,
            "type": "appointment",
            "notes": "",
            "duration_minutes": duration_minutes,
        }

    def test_password_hash_and_session_token_are_not_stored_in_plaintext(self) -> None:
        user = storage.get_user_by_email("owner@example.com")
        self.assertIsNotNone(user)
        self.assertNotEqual(user["password_hash"], "correct horse battery")
        self.assertTrue(storage.verify_password("correct horse battery", user["password_hash"]))
        self.assertFalse(storage.verify_password("wrong password", user["password_hash"]))

        token = storage.create_session(self.owner["id"])
        self.assertEqual(storage.get_user_for_session(token)["id"], self.owner["id"])
        self.assertIsNone(storage.get_user_for_session("not-a-session-token"))

    def test_calendar_events_are_isolated_by_user(self) -> None:
        created = storage.create_or_propose_event(self.owner["id"], self.event("Exam"))
        event_id = created["event"]["id"]

        self.assertEqual(len(storage.list_events(self.owner["id"])), 1)
        self.assertEqual(storage.list_events(self.other["id"]), [])
        self.assertIsNone(storage.get_event(self.other["id"], event_id))
        self.assertFalse(storage.delete_event(self.other["id"], event_id))

    def test_document_vectors_are_searchable_and_isolated_by_user(self) -> None:
        document = storage.create_document(
            self.owner["id"],
            "notes.txt",
            "stored.txt",
            "text/plain",
            20,
            "hash",
            [
                ("network security concepts", [1.0, 0.0]),
                ("calendar planning", [0.0, 1.0]),
            ],
        )

        matches = storage.search_document_chunks(self.owner["id"], [1.0, 0.0])
        self.assertEqual(matches[0]["document_id"], document["id"])
        self.assertIn("network security", matches[0]["content"])
        self.assertEqual(storage.search_document_chunks(self.other["id"], [1.0, 0.0]), [])

    def test_document_listing_and_delete_are_user_scoped(self) -> None:
        document = storage.create_document(
            self.owner["id"],
            "syllabus.txt",
            "stored.txt",
            "text/plain",
            12,
            "hash",
            [("course schedule", [1.0])],
        )

        self.assertEqual(storage.list_documents(self.owner["id"])[0]["name"], "syllabus.txt")
        self.assertEqual(storage.list_documents(self.other["id"]), [])
        self.assertIsNone(storage.delete_document(self.other["id"], document["id"]))
        self.assertIsNotNone(storage.delete_document(self.owner["id"], document["id"]))
        self.assertEqual(storage.list_documents(self.owner["id"]), [])

    def test_adjacent_quarter_hour_slots_do_not_conflict(self) -> None:
        storage.create_or_propose_event(self.owner["id"], self.event("First", "10:00"))

        result = storage.create_or_propose_event(
            self.owner["id"],
            self.event("Next slot", "10:15"),
        )

        self.assertEqual(result["status"], "saved")

    def test_event_durations_detect_same_day_and_midnight_overlaps(self) -> None:
        storage.create_or_propose_event(
            self.owner["id"],
            self.event("Long event", "10:00", duration_minutes=45),
        )
        conflict = storage.create_or_propose_event(
            self.owner["id"],
            self.event("Overlap", "10:30"),
        )
        self.assertEqual(conflict["status"], "conflict")

        adjacent = storage.create_or_propose_event(
            self.owner["id"],
            self.event("Adjacent", "10:45"),
        )
        self.assertEqual(adjacent["status"], "saved")

        next_day = (date.fromisoformat("2026-11-18") + timedelta(days=1)).isoformat()
        storage.create_or_propose_event(
            self.owner["id"],
            self.event("Late event", "23:45", duration_minutes=30),
        )
        midnight_conflict = storage.create_or_propose_event(
            self.owner["id"],
            self.event("Midnight overlap", "00:00", next_day),
        )
        self.assertEqual(midnight_conflict["status"], "conflict")

    def test_daily_series_can_edit_one_occurrence_following_and_entire_series(self) -> None:
        start = (date.today() + timedelta(days=2)).isoformat()
        created = storage.create_or_propose_event(
            self.owner["id"],
            {
                **self.event("Study session", event_date=start),
                "recurrence": {"frequency": "daily", "interval": 1, "weekdays": []},
            },
        )
        self.assertEqual(created["status"], "saved")

        end = (date.fromisoformat(start) + timedelta(days=4)).isoformat()
        occurrences = storage.list_events(self.owner["id"], start, end)
        self.assertEqual(len(occurrences), 5)

        second = occurrences[1]
        changed_once = storage.create_or_propose_event(
            self.owner["id"],
            {**self.event("One changed occurrence", event_date=second["date"]), "time": second["time"]},
            target_id=second["id"],
            scope="this_occurrence",
        )
        self.assertEqual(changed_once["status"], "saved")
        occurrences = storage.list_events(self.owner["id"], start, end)
        self.assertEqual(occurrences[0]["title"], "Study session")
        self.assertEqual(occurrences[1]["title"], "One changed occurrence")
        self.assertEqual(occurrences[2]["title"], "Study session")

        third = occurrences[2]
        split = storage.create_or_propose_event(
            self.owner["id"],
            {
                **self.event("Future sessions", event_date=third["date"]),
                "recurrence": {"frequency": "daily", "interval": 1, "weekdays": []},
            },
            target_id=third["id"],
            scope="following",
        )
        self.assertEqual(split["status"], "saved")
        occurrences = storage.list_events(self.owner["id"], start, end)
        self.assertEqual(
            [event["title"] for event in occurrences],
            ["Study session", "One changed occurrence", "Future sessions", "Future sessions", "Future sessions"],
        )

        last = occurrences[-1]
        updated_series = storage.create_or_propose_event(
            self.owner["id"],
            {
                **self.event("Entire updated series", event_date=occurrences[2]["date"]),
                "recurrence": {"frequency": "daily", "interval": 1, "weekdays": []},
            },
            target_id=last["id"],
            scope="series",
        )
        self.assertEqual(updated_series["status"], "saved")
        occurrences = storage.list_events(self.owner["id"], start, end)
        self.assertEqual(
            [event["title"] for event in occurrences],
            [
                "Study session",
                "One changed occurrence",
                "Entire updated series",
                "Entire updated series",
                "Entire updated series",
            ],
        )

    def test_recurring_conflicts_are_resolved_once_for_the_whole_series(self) -> None:
        start = date.today() + timedelta(days=2)
        conflict_date = (start + timedelta(days=2)).isoformat()
        storage.create_or_propose_event(
            self.owner["id"],
            self.event("Existing event", "10:30", conflict_date),
        )
        proposal = storage.create_or_propose_event(
            self.owner["id"],
            {
                **self.event("Daily event", "10:00", start.isoformat(), 45),
                "recurrence": {"frequency": "daily", "interval": 1, "weekdays": []},
            },
        )
        self.assertEqual(proposal["status"], "conflict")
        self.assertEqual(proposal["conflict_count"], 1)
        self.assertGreater(proposal["occurrence_count"], 1)
        self.assertEqual(len(storage.list_events(self.owner["id"], conflict_date, conflict_date)), 1)

        resolved = storage.resolve_calendar_action(
            self.owner["id"],
            proposal["proposal_id"],
            "override",
        )
        self.assertEqual(resolved["status"], "saved")
        self.assertEqual(resolved["resolution"], "override")
        events = storage.list_events(self.owner["id"], conflict_date, conflict_date)
        self.assertEqual([event["title"] for event in events], ["Daily event"])
        self.assertEqual(events[0]["duration_minutes"], 45)

    def test_monthly_and_yearly_series_generate_calendar_date_occurrences(self) -> None:
        monthly = storage.create_or_propose_event(
            self.owner["id"],
            {
                **self.event("Monthly review", "12:00", "2026-01-15"),
                "recurrence": {"frequency": "monthly", "interval": 1, "weekdays": []},
            },
        )
        yearly = storage.create_or_propose_event(
            self.owner["id"],
            {
                **self.event("Yearly review", "14:00", "2026-11-20"),
                "recurrence": {"frequency": "yearly", "interval": 1, "weekdays": []},
            },
        )

        self.assertEqual(monthly["status"], "saved")
        self.assertEqual(yearly["status"], "saved")
        monthly_dates = [
            event["date"]
            for event in storage.list_events(self.owner["id"], "2026-01-01", "2026-04-30")
            if event["title"] == "Monthly review"
        ]
        yearly_dates = [
            event["date"]
            for event in storage.list_events(self.owner["id"], "2026-11-20", "2027-11-20")
            if event["title"] == "Yearly review"
        ]
        self.assertEqual(
            monthly_dates,
            ["2026-01-15", "2026-02-15", "2026-03-15", "2026-04-15"],
        )
        self.assertEqual(yearly_dates, ["2026-11-20", "2027-11-20"])

    def test_deleting_following_occurrences_preserves_earlier_series_entries(self) -> None:
        start = (date.today() + timedelta(days=2)).isoformat()
        storage.create_or_propose_event(
            self.owner["id"],
            {
                **self.event("Daily series", event_date=start),
                "recurrence": {"frequency": "daily", "interval": 1, "weekdays": []},
            },
        )
        second_date = (date.fromisoformat(start) + timedelta(days=1)).isoformat()
        second = storage.list_events(self.owner["id"], second_date, second_date)[0]

        self.assertTrue(storage.delete_event(self.owner["id"], second["id"], "following"))
        remaining = storage.list_events(
            self.owner["id"],
            start,
            (date.fromisoformat(start) + timedelta(days=3)).isoformat(),
        )
        self.assertEqual([event["date"] for event in remaining], [start])

    def test_existing_database_events_are_migrated_with_default_duration(self) -> None:
        database_path = os.path.join(self.temp_dir.name, "legacy.sqlite3")
        owner_id = "legacy-user"
        database = sqlite3.connect(database_path)
        try:
            database.executescript(
                """
                CREATE TABLE users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE events (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    title TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    type TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            database.execute(
                """INSERT INTO users VALUES (?, ?, ?, ?, ?)""",
                (owner_id, "legacy@example.com", "Legacy", "hash", "2026-01-01"),
            )
            database.execute(
                """INSERT INTO events
                   (id, user_id, title, date, time, type, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("legacy-event", owner_id, "Existing", "2026-11-18", "10:00", "appointment", "", "2026-01-01"),
            )
            database.commit()
        finally:
            database.close()

        with patch.dict(os.environ, {"NEXUS_DATABASE_PATH": database_path}):
            events = storage.list_events(owner_id)

        self.assertEqual(events[0]["id"], "legacy-event")
        self.assertEqual(events[0]["duration_minutes"], 15)
        self.assertIsNone(events[0]["recurrence"])

    def test_conflict_requires_user_resolution(self) -> None:
        storage.create_or_propose_event(self.owner["id"], self.event("Existing"))
        proposal = storage.create_or_propose_event(
            self.owner["id"],
            self.event("Proposed"),
        )

        self.assertEqual(proposal["status"], "conflict")
        self.assertEqual(len(storage.list_events(self.owner["id"])), 1)
        self.assertEqual(
            storage.resolve_calendar_action(
                self.other["id"],
                proposal["proposal_id"],
                "override",
            )["status"],
            "not_found",
        )

        resolved = storage.resolve_calendar_action(
            self.owner["id"],
            proposal["proposal_id"],
            "override",
        )
        self.assertEqual(resolved["status"], "saved")
        self.assertEqual([event["title"] for event in storage.list_events(self.owner["id"])], ["Proposed"])

    def test_overlap_preserves_both_events_and_reject_preserves_existing_event(self) -> None:
        storage.create_or_propose_event(self.owner["id"], self.event("Existing"))
        overlap = storage.create_or_propose_event(self.owner["id"], self.event("Overlap"))
        storage.resolve_calendar_action(self.owner["id"], overlap["proposal_id"], "overlap")
        self.assertEqual(len(storage.list_events(self.owner["id"])), 2)

        rejected = storage.create_or_propose_event(self.owner["id"], self.event("Rejected"))
        storage.resolve_calendar_action(self.owner["id"], rejected["proposal_id"], "reject")
        self.assertEqual(len(storage.list_events(self.owner["id"])), 2)

    def test_new_conflict_after_prompt_requires_a_fresh_user_decision(self) -> None:
        storage.create_or_propose_event(self.owner["id"], self.event("First"))
        first_proposal = storage.create_or_propose_event(
            self.owner["id"],
            self.event("Proposed"),
        )
        second_proposal = storage.create_or_propose_event(
            self.owner["id"],
            self.event("Concurrent event"),
        )
        storage.resolve_calendar_action(
            self.owner["id"],
            second_proposal["proposal_id"],
            "overlap",
        )

        result = storage.resolve_calendar_action(
            self.owner["id"],
            first_proposal["proposal_id"],
            "override",
        )

        self.assertEqual(result["status"], "conflict")
        self.assertNotEqual(result["proposal_id"], first_proposal["proposal_id"])
        self.assertEqual(len(result["conflicts"]), 2)
        self.assertEqual(len(storage.list_events(self.owner["id"])), 2)

    def test_related_event_lookup_returns_relevant_results(self) -> None:
        storage.create_or_propose_event(self.owner["id"], self.event("Network exam"))
        storage.create_or_propose_event(self.owner["id"], self.event("Dentist", "11:00"))

        results = storage.find_related_events(self.owner["id"], "network exam")

        self.assertEqual([event["title"] for event in results], ["Network exam"])


if __name__ == "__main__":
    unittest.main()
