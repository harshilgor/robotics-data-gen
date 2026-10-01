"""SQLite immutable records and reproducible Advisor snapshots."""
import json
import sqlite3
from contextlib import nullcontext
from .core import canonical, validate_annotation, validate_episode


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (identity TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS episodes (identity TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS feedback (identity TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshots (identity TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def _put(self, table, identity, value):
        payload = canonical(value)
        old = self.db.execute(f"SELECT payload FROM {table} WHERE identity=?", (identity,)).fetchone()
        if old:
            if old[0] != payload:
                raise ValueError(f"immutable {table} identity already exists with different content")
            return False
        self.db.execute(f"INSERT INTO {table} VALUES (?,?)", (identity, payload))
        return True

    def records(self, table):
        if table not in ("tasks", "episodes", "feedback", "snapshots"):
            raise ValueError("invalid table")
        return [json.loads(row[0]) for row in self.db.execute(f"SELECT payload FROM {table} ORDER BY identity")]

    def ingest(self, tasks=(), episodes=(), feedback=(), *, transactional=True):
        episodes = list(episodes)
        from .evaluation import enforce_development_membership
        enforce_development_membership(self, episodes)
        with self.db if transactional else nullcontext():
            for task in tasks:
                validate_annotation(task)
                self._put("tasks", canonical([task["family_id"], task["family_version"]]), task)
            registry = {(t["family_id"], t["family_version"]): t for t in self.records("tasks")}
            for episode in episodes:
                validate_episode(episode, registry)
                self._put("episodes", episode["episode_id"], episode)
            for item in feedback:
                if not isinstance(item.get("directive_id"), str) or not item["directive_id"] or not isinstance(item.get("feedback_id"), str) or not item["feedback_id"]:
                    raise ValueError("feedback requires directive_id and feedback_id")
                for key in ("requested", "generated", "validated", "scheduled", "executed_episodes"):
                    if type(item.get(key)) is not int or item[key] < 0:
                        raise ValueError(f"feedback {key} must be nonnegative integer")
                if not item["scheduled"] <= item["validated"] <= item["generated"]:
                    raise ValueError("scheduled <= validated <= generated required")
                if not any(s["directive"]["directive_id"] == item["directive_id"] for s in self.records("snapshots")):
                    raise ValueError("feedback references unknown directive")
                self._put("feedback", item["feedback_id"], item)

    def save_snapshot(self, snapshot):
        with self.db:
            self._put("snapshots", snapshot["snapshot_id"], snapshot)
