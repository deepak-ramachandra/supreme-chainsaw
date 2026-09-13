import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import httpx
import pytz
from utils import get_db

NYC = pytz.timezone("America/New_York")


class WorkoutManager:
    """Syncs workouts from Hevy into the local SQLite/Turso database and
    provides read access to the stored records."""

    HEVY_URL: str = "https://api.hevyapp.com/v1/"
    TIMEOUT: int = 30

    WORKOUT_UPSERT: str = """
    INSERT INTO workouts (workout_id, title, routine_id, description, start_time, end_time, workout_date, duration_min, updated_at, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(workout_id) DO UPDATE SET
      title        = excluded.title,
      routine_id   = excluded.routine_id,
      description  = excluded.description,
      start_time   = excluded.start_time,
      end_time     = excluded.end_time,
      workout_date = excluded.workout_date,
      duration_min = excluded.duration_min,
      updated_at   = excluded.updated_at,
      created_at   = excluded.created_at;
    """

    WORKOUT_SET_INSERT: str = """
    INSERT INTO workout_sets (workout_id, exercise_index, exercise_title, exercise_template_id, superset_id, set_index, set_type, weight_kg, reps, distance_meters, duration_seconds, rpe, custom_metric)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """

    def _headers(self) -> dict[str, str]:
        return {"accept": "application/json", "api-key": os.environ.get("HEVY", "")}

    def _get_workout_events(self, page: int, page_size: int, since: str) -> dict:
        """Hevy's change-feed endpoint - unlike a plain workout list, this
        only returns workouts created/updated since `since` (a UTC ISO
        datetime, e.g. '2026-08-01T00:00:00Z'), so a sync only has to pay
        for what changed."""
        with httpx.Client(timeout=self.TIMEOUT) as client:
            r = client.get(
                urljoin(self.HEVY_URL, "workouts/events"),
                headers=self._headers(),
                params={"page": page, "pageSize": page_size, "since": since},
            )
            r.raise_for_status()
            return r.json()

    @staticmethod
    def _workout_date(start_time: str) -> str:
        """NYC calendar date (YYYY-MM-DD) that a UTC ISO 8601 start_time falls on."""
        return datetime.fromisoformat(start_time).astimezone(NYC).date().isoformat()

    @classmethod
    def _workout_row(cls, w: dict[str, Any]) -> tuple:
        start, end = w["start_time"], w["end_time"]
        duration_min = round(
            (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
            / 60
        )
        return (
            w["id"],
            w["title"],
            w.get("routine_id"),
            w.get("description") or "",
            start,
            end,
            cls._workout_date(start),
            duration_min,
            w["updated_at"],
            w["created_at"],
        )

    @staticmethod
    def _set_rows(workout_id: str, exercises: list[dict[str, Any]]) -> list[tuple]:
        rows = []
        for ex in exercises:
            for s in ex["sets"]:
                rows.append(
                    (
                        workout_id,
                        ex["index"],
                        ex["title"],
                        ex.get("exercise_template_id"),
                        ex.get("superset_id"),
                        s["index"],
                        s.get("type"),
                        s.get("weight_kg"),
                        s.get("reps"),
                        s.get("distance_meters"),
                        s.get("duration_seconds"),
                        s.get("rpe"),
                        s.get("custom_metric"),
                    )
                )
        return rows

    def sync(self) -> dict[str, int]:
        """Pull all pages from Hevy's /workouts/events since the last saved
        cursor, upserting each 'updated' workout (+ its sets) and deleting
        each 'deleted' one, in a single DB transaction per page.

        Returns:
            dict with counts of added, modified, and removed workouts.
        """
        conn = get_db(sync=True)

        cur = conn.execute(
            "SELECT since_cursor FROM workout_sync_state WHERE id = 1"
        ).fetchone()
        since = cur[0] if cur else "1970-01-01T00:00:00Z"
        sync_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        result = dict(added=0, modified=0, removed=0)
        page, page_count = 1, 1
        while page <= page_count:
            data = self._get_workout_events(page, 10, since)
            page_count = data.get("page_count", page)

            if not data.get("events", []):
                break

            with conn:
                for event in data["events"]:
                    if event["type"] == "updated":
                        w = event["workout"]
                        existing = conn.execute(
                            "SELECT 1 FROM workouts WHERE workout_id = ?", (w["id"],)
                        ).fetchone()
                        conn.execute(self.WORKOUT_UPSERT, self._workout_row(w))
                        conn.execute(
                            "DELETE FROM workout_sets WHERE workout_id = ?", (w["id"],)
                        )
                        conn.executemany(
                            self.WORKOUT_SET_INSERT,
                            self._set_rows(w["id"], w["exercises"]),
                        )
                        result["modified" if existing else "added"] += 1
                    elif event["type"] == "deleted":
                        deleted = conn.execute(
                            "DELETE FROM workouts WHERE workout_id = ?", (event["id"],)
                        )
                        conn.execute(
                            "DELETE FROM workout_sets WHERE workout_id = ?",
                            (event["id"],),
                        )
                        if deleted.rowcount:
                            result["removed"] += 1

            page += 1

        with conn:
            conn.execute(
                "INSERT INTO workout_sync_state (id, since_cursor) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET since_cursor = excluded.since_cursor",
                (sync_started_at,),
            )

        conn.close()
        return result

    def _sets_for_workout(self, conn, workout_id: str) -> list[dict[str, Any]]:
        """Reassemble a workout's flat set rows back into nested exercises,
        the same shape Hevy's own API returns."""
        rows = conn.execute(
            "SELECT exercise_index, exercise_title, exercise_template_id, superset_id, "
            "set_index, set_type, weight_kg, reps, distance_meters, duration_seconds, rpe, custom_metric "
            "FROM workout_sets WHERE workout_id = ? ORDER BY exercise_index, set_index",
            (workout_id,),
        ).fetchall()

        exercises: dict[int, dict[str, Any]] = {}
        for (
            ex_idx,
            ex_title,
            ex_tmpl_id,
            superset_id,
            set_idx,
            set_type,
            weight_kg,
            reps,
            distance_m,
            duration_s,
            rpe,
            custom_metric,
        ) in rows:
            ex = exercises.setdefault(
                ex_idx,
                {
                    "index": ex_idx,
                    "title": ex_title,
                    "exercise_template_id": ex_tmpl_id,
                    "superset_id": superset_id,
                    "sets": [],
                },
            )
            ex["sets"].append(
                {
                    "index": set_idx,
                    "type": set_type,
                    "weight_kg": weight_kg,
                    "reps": reps,
                    "distance_meters": distance_m,
                    "duration_seconds": duration_s,
                    "rpe": rpe,
                    "custom_metric": custom_metric,
                }
            )
        return [exercises[k] for k in sorted(exercises)]

    def get_workouts_by_date_range(self, start_date: str, end_date: str) -> list[dict]:
        """Return already-synced workouts (with exercises/sets) whose NYC
        calendar date falls between start_date and end_date (inclusive,
        YYYY-MM-DD) - reads purely from the local DB, no Hevy call. Call
        sync() first to pick up anything new."""
        conn = get_db(sync=True)
        rows = conn.execute(
            "SELECT workout_id, title, routine_id, description, start_time, end_time, "
            "workout_date, duration_min, updated_at, created_at FROM workouts "
            "WHERE workout_date BETWEEN ? AND ? ORDER BY start_time",
            (start_date, end_date),
        ).fetchall()
        workouts = [
            {
                "workout_id": r[0],
                "title": r[1],
                "routine_id": r[2],
                "description": r[3],
                "start_time": r[4],
                "end_time": r[5],
                "workout_date": r[6],
                "duration_min": r[7],
                "updated_at": r[8],
                "created_at": r[9],
                "exercises": self._sets_for_workout(conn, r[0]),
            }
            for r in rows
        ]
        conn.close()
        return workouts

    def get_workout_count(self) -> int:
        """Total number of workouts stored locally (post-sync)."""
        conn = get_db(sync=True)
        row = conn.execute("SELECT COUNT(*) FROM workouts").fetchone()
        conn.close()
        return row[0]
