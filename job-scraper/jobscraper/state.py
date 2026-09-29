"""Remember which postings were already shown, so repeated runs can report only new ones."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Job

FORGET_AFTER_DAYS = 90


class SeenStore:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.seen: dict[str, str] = {}
        if self.path.exists():
            self.seen = json.loads(self.path.read_text() or "{}")

    @staticmethod
    def key(job: Job) -> str:
        # Keyed on company+title rather than source id, so the same role picked up
        # from a different board on a later run doesn't count as new.
        return " | ".join(job.dedup_key)

    def filter_new(self, jobs: list[Job]) -> list[Job]:
        return [j for j in jobs if self.key(j) not in self.seen]

    def mark(self, shown: list[Job], still_listed: list[Job] = ()) -> None:
        """Record `shown` as seen and refresh already-seen jobs that are still listed,
        so only postings gone for FORGET_AFTER_DAYS are pruned."""
        now = datetime.now(timezone.utc).isoformat()
        for j in shown:
            self.seen[self.key(j)] = now
        for j in still_listed:
            if self.key(j) in self.seen:
                self.seen[self.key(j)] = now
        cutoff = (datetime.now(timezone.utc) - timedelta(days=FORGET_AFTER_DAYS)).isoformat()
        self.seen = {k: v for k, v in self.seen.items() if v >= cutoff}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.seen, indent=0, sort_keys=True))
        tmp.replace(self.path)
