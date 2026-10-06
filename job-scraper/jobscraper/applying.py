"""Applying for a job: your stored resumes, the free match check, and AI tailoring.

Everything is saved under the app's data folder on this computer:
  resumes/   the files you uploaded, plus their text
  tailored/  each tailored resume + cover letter, linked to the job it was made for
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import documents, tailor
from .match import match
from .resumes import ResumeError, ResumeStore

TAILORED_ID_RE = re.compile(r"^[0-9a-f]{16}$")


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

    # ------------------------------------------------------------ match + tailor

    def _job_and_posting(self, body: dict) -> tuple[dict, str]:
        if not isinstance(body, dict) or not isinstance(body.get("key"), str):
            raise ResumeError("expected {key, posting}")
        job = self.find_job(body["key"])
        if not job:
            raise ResumeError("That job isn't in the list any more. Refresh and try again.")
        posting = str(body.get("posting") or "").strip() or job.get("description") or ""
        return job, posting

    def match(self, body: dict) -> dict:
        job, posting = self._job_and_posting(body)
        entry, text = self.resumes.text(body.get("resume_id"))
        tags = job.get("tags") or []
        return {**match(text, job.get("title", ""), posting, tags), "resume": entry["filename"]}

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

    def tailored(self, tid: str) -> dict:
        if not TAILORED_ID_RE.match(tid or ""):
            raise ResumeError("Unknown tailored resume.")
        try:
            return json.loads((self.dir / f"{tid}.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ResumeError("Unknown tailored resume.") from None

    def list_tailored(self, job_key: str | None = None) -> list[dict]:
        out = []
        for f in self.dir.glob("*.json"):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if job_key and r["job"].get("key") != job_key:
                continue
            out.append({k: r[k] for k in ("id", "created_at", "job", "resume_filename", "cost_usd")}
                       | {"gaps": r["resume"].get("gaps", []), "changes": r["resume"].get("changes", []),
                          "cover_letter": r["resume"].get("cover_letter", "")})
        return sorted(out, key=lambda r: r["created_at"], reverse=True)

    def file_name(self, record: dict, what: str, ext: str) -> str:
        name = record["resume"].get("name") or "Resume"
        company = record["job"].get("company") or record["job"].get("title") or ""
        raw = " - ".join(x for x in (name, what, company) if x)
        return re.sub(r'[\\/:*?"<>|\r\n]+', "", raw)[:120] + ext

    def document(self, tid: str, kind: str) -> tuple[bytes, str, str]:
        """(content, content-type, download file name or "") for /tailored/<id>/<kind>."""
        r = self.tailored(tid)
        docx_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if kind == "resume.docx":
            return documents.resume_docx(r["resume"]), docx_type, self.file_name(r, "Resume", ".docx")
        if kind == "cover-letter.docx":
            return documents.cover_letter_docx(r["resume"]), docx_type, self.file_name(r, "Cover Letter", ".docx")
        if kind in ("resume", "letter"):
            letter = kind == "letter"
            page = documents.resume_html(
                r["resume"], self.file_name(r, "Cover Letter" if letter else "Resume", ""),
                f"/tailored/{tid}/{'cover-letter' if letter else 'resume'}.docx", letter=letter)
            return page.encode("utf-8"), "text/html; charset=utf-8", ""
        raise ResumeError("Unknown document.")
