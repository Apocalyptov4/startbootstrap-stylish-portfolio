"""Applying for a job in the program: your stored resumes and AI tailoring.

Everything is saved under the app's data folder on this computer:
  resumes/   the files you uploaded, plus their text
  tailored/  each tailored resume + cover letter, linked to the job it was made for

The match check and the Word and printable versions are made in the browser
(web/resume-tools.js), the same way on the website and in the program.
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import tailor
from .resumes import ResumeError, ResumeStore


class ApplyDesk:
    def __init__(self, data_dir: Path, get_api_key, find_job, tailor_fn=None):
        self.resumes = ResumeStore(data_dir)
        self.dir = Path(data_dir) / "tailored"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.get_api_key = get_api_key
        self.find_job = find_job
        self.tailor_fn = tailor_fn or tailor.tailor
        self.lock = threading.Lock()

    # ------------------------------------------------------------ resumes

    def add_resume(self, body: dict) -> dict:
        if not isinstance(body, dict):
            raise ResumeError("expected {filename, data} or {text}")
        if body.get("text"):
            self.resumes.add_text(str(body["text"]), str(body.get("name") or "Pasted resume"))
        else:
            try:
                data = base64.b64decode(str(body.get("data") or ""), validate=True)
            except (binascii.Error, ValueError):
                raise ResumeError("The file didn't arrive correctly. Try again.") from None
            self.resumes.add(str(body.get("filename") or ""), data)
        return self.resumes.list()

    # ------------------------------------------------------------ tailoring

    def _job_and_posting(self, body: dict) -> tuple[dict, str]:
        if not isinstance(body, dict) or not isinstance(body.get("key"), str):
            raise ResumeError("expected {key, posting}")
        job = self.find_job(body["key"])
        if not job:
            raise ResumeError("That job isn't in the list any more. Refresh and try again.")
        posting = str(body.get("posting") or "").strip() or job.get("description") or ""
        return job, posting

    def tailor(self, body: dict) -> dict:
        job, posting = self._job_and_posting(body)
        if len(posting) < 80:
            raise ResumeError("Paste the full job description first. The more of the ad Claude sees, the better the result.")
        entry, text = self.resumes.text(body.get("resume_id"))
        result = self.tailor_fn(text, job, posting, self.get_api_key())
        record = {
            "id": secrets.token_hex(8),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "job": {k: job.get(k, "") for k in ("key", "title", "company", "location", "url")},
            "resume_id": entry["id"],
            "resume_filename": entry["filename"],
            "posting": posting,
            **result,
        }
        with self.lock:
            (self.dir / f"{record['id']}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        return record

    # ------------------------------------------------------------ tailored versions

    def list_tailored(self, job_key: str | None = None) -> list[dict]:
        out = []
        for f in self.dir.glob("*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not job_key or r["job"].get("key") == job_key:
                out.append(r)
        return sorted(out, key=lambda r: r["created_at"], reverse=True)
