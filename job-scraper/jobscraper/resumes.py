"""Your resumes: stored on this computer only, in <data dir>/resumes.

Each upload keeps the original file (to attach to applications as-is) plus its
plain text (for the match score and for tailoring).
"""

from __future__ import annotations

import io
import json
import re
import secrets
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 5 * 1024 * 1024
ID_RE = re.compile(r"^[0-9a-f]{12}$")
TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


class ResumeError(ValueError):
    """A problem the person can fix (wrong file type, no text found, ...)."""


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        text = _pdf_text(data)
    elif ext == ".docx":
        text = docx_text(data)
    elif ext in (".txt", ".md"):
        text = data.decode("utf-8", errors="replace")
    elif ext == ".doc":
        raise ResumeError("Old .doc files can't be read. In Word, use File → Save As → Word Document (.docx).")
    else:
        raise ResumeError("Upload a PDF, Word (.docx) or text file.")
    text = re.sub(r"[ \t]+\n", "\n", text.replace("\r\n", "\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 40:
        raise ResumeError(
            "No text could be read from that file. If it's a scanned picture, upload the Word version "
            "or paste the text instead."
        )
    return text


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except BaseException as e:  # a broken optional crypto library can raise a non-Exception panic on import
        raise ResumeError(f"PDF reading isn't available on this computer ({type(e).__name__}). "
                          "Upload the Word version or paste the text instead.") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        raise ResumeError(f"That PDF couldn't be read ({type(e).__name__}).") from None


def docx_text(data: bytes) -> str:
    """The text of a Word (.docx) file, one line per paragraph, using only the standard library.

    Text boxes come once (their old-Word "fallback" copy is skipped), and tab-stop settings
    (<w:tabs><w:tab/>) aren't mistaken for tabs. Same rules as docxText in web/resume-tools.js.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ElementTree.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
        raise ResumeError("That Word file couldn't be opened.") from None
    out = []

    def walk(el, in_tabs=False):
        if el.tag == f"{MC}Fallback":
            return
        if el.tag == f"{W}t":
            out.append(el.text or "")
        elif el.tag == f"{W}tab" and not in_tabs:
            out.append("\t")
        elif el.tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
        for child in el:
            walk(child, in_tabs or el.tag == f"{W}tabs")
        if el.tag == f"{W}p":
            out.append("\n")

    walk(root)
    return "".join(out)


class ResumeStore:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "resumes"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.index_file = self.dir / "index.json"
        try:
            self.index = json.loads(self.index_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.index = {"main": None, "resumes": []}

    def _save(self):
        tmp = self.index_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.index, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.index_file)

    def list(self) -> dict:
        with self.lock:
            return {"main": self.index["main"], "resumes": [dict(r) for r in self.index["resumes"]]}

    def add(self, filename: str, data: bytes) -> dict:
        filename = Path(filename or "resume.txt").name[:120] or "resume.txt"
        if len(data) > MAX_BYTES:
            raise ResumeError("That file is over 5 MB. Resumes are usually much smaller; try saving it again.")
        text = extract_text(filename, data)
        rid = secrets.token_hex(6)
        ext = Path(filename).suffix.lower()
        (self.dir / f"{rid}{ext}").write_bytes(data)
        (self.dir / f"{rid}.txt.extracted").write_text(text, encoding="utf-8")
        entry = {
            "id": rid,
            "filename": filename,
            "ext": ext,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "chars": len(text),
            "preview": text[:300],
        }
        with self.lock:
            self.index["resumes"].insert(0, entry)
            if not self.index["main"]:
                self.index["main"] = rid
            self._save()
        return entry

    def add_text(self, text: str, name: str = "Pasted resume") -> dict:
        safe = re.sub(r"[^\w .-]", "", name).strip() or "Pasted resume"
        return self.add(f"{safe}.txt", text.encode("utf-8"))

    def _entry(self, rid: str) -> dict:
        if not ID_RE.match(rid or ""):
            raise ResumeError("Unknown resume.")
        for r in self.index["resumes"]:
            if r["id"] == rid:
                return r
        raise ResumeError("Unknown resume.")

    def text(self, rid: str | None = None) -> tuple[dict, str]:
        """(entry, plain text) for a resume, or the main one when rid is None."""
        with self.lock:
            rid = rid or self.index["main"]
            if not rid:
                raise ResumeError("Add your resume first (My resume, top right).")
            entry = dict(self._entry(rid))
        return entry, (self.dir / f"{rid}.txt.extracted").read_text(encoding="utf-8")

    def file(self, rid: str) -> tuple[dict, bytes]:
        with self.lock:
            entry = dict(self._entry(rid))
        return entry, (self.dir / f"{rid}{entry['ext']}").read_bytes()

    def set_main(self, rid: str) -> dict:
        with self.lock:
            self._entry(rid)
            self.index["main"] = rid
            self._save()
        return self.list()

    def delete(self, rid: str) -> dict:
        with self.lock:
            entry = self._entry(rid)
            self.index["resumes"].remove(entry)
            for f in (self.dir / f"{rid}{entry['ext']}", self.dir / f"{rid}.txt.extracted"):
                f.unlink(missing_ok=True)
            if self.index["main"] == rid:
                self.index["main"] = self.index["resumes"][0]["id"] if self.index["resumes"] else None
            self._save()
        return self.list()
