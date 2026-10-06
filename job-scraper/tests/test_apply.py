"""Tests for stored resumes and AI tailoring with a fake Claude. The match check and the Word and printable
versions are made in the browser; their tests are in tests/js (run by test_browser_code.py)."""

import base64
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from jobscraper import tailor
from jobscraper.resumes import ResumeError, ResumeStore, docx_text, extract_text
from jobscraper.server import Store
from jobscraper.tailor import TailorError

RESUME = """Jane Doe
jane@example.com | (609) 555-0100 | Vincentown, NJ
Warehouse Associate, Acme Logistics, Burlington NJ, 2021-2024
- Picked and packed orders, operated forklifts, used RF scanners
- Kept inventory counts accurate
Certifications: OSHA 10, forklift certified
"""

TAILORED = {
    "name": "Jane Doe", "contact": ["jane@example.com", "(609) 555-0100"], "headline": "Warehouse Associate",
    "summary": "Warehouse associate with three years of order picking & forklift work.",
    "skills": ["Forklift", "RF scanners"],
    "experience": [{"title": "Warehouse Associate", "organization": "Acme Logistics", "location": "Burlington, NJ",
                    "dates": "2021-2024", "bullets": ["Picked and packed orders <fast>", "Operated forklifts"]}],
    "education": [], "other_sections": [{"heading": "Certifications", "items": ["OSHA 10"]}],
    "cover_letter": "Dear Hiring Manager,\nI would like to apply.\nJane Doe",
    "changes": ["Put forklift work first"], "gaps": ["The posting asks for a CDL. Add it only if you have one."],
}


def make_pdf(text: str) -> bytes:
    """A minimal valid one-page PDF containing `text` (for testing the PDF reader)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


FIXTURE_DOCX = (Path(__file__).parent / "fixtures" / "resume.docx").read_bytes()


class ExtractTests(unittest.TestCase):
    def test_text_word_and_pdf(self):
        self.assertIn("Acme Logistics", extract_text("cv.txt", RESUME.encode()))
        lines = extract_text("cv.docx", FIXTURE_DOCX).splitlines()
        self.assertEqual(sum("555-0100" in line for line in lines), 1)  # a text box comes once
        self.assertIn("Warehouse Associate\t2021 & 2024", lines)  # no stray tab from tab-stop settings
        self.assertIn("•\tPicked <fast> orders", lines)
        pdf_text = extract_text("cv.pdf", make_pdf("Jane Doe Warehouse Associate Acme Logistics forklift OSHA"))
        self.assertIn("Acme Logistics", pdf_text)

    def test_helpful_errors(self):
        with self.assertRaisesRegex(ResumeError, r"\.docx"):
            extract_text("cv.doc", b"x" * 100)
        with self.assertRaisesRegex(ResumeError, "PDF, Word"):
            extract_text("cv.png", b"x" * 100)
        with self.assertRaisesRegex(ResumeError, "No text"):
            extract_text("cv.txt", b"   ")
        with self.assertRaisesRegex(ResumeError, "couldn't be opened"):
            docx_text(b"not a zip")


class ResumeStoreTests(unittest.TestCase):
    def test_add_main_download_delete(self):
        with tempfile.TemporaryDirectory() as d:
            s = ResumeStore(Path(d))
            a = s.add("Jane Doe.txt", RESUME.encode())
            b = s.add_text(RESUME + "\nMore", "Second")
            listing = s.list()
            self.assertEqual(listing["main"], a["id"])          # first upload becomes main
            self.assertEqual([r["id"] for r in listing["resumes"]], [b["id"], a["id"]])
            self.assertEqual(s.file(a["id"])[1], RESUME.encode())
            s.set_main(b["id"])
            self.assertIn("More", s.text()[1])
            s.delete(b["id"])
            self.assertEqual(s.list()["main"], a["id"])
            self.assertEqual(ResumeStore(Path(d)).list()["main"], a["id"])  # saved to disk
            with self.assertRaises(ResumeError):
                s.text("../../etc")
            with self.assertRaisesRegex(ResumeError, "5 MB"):
                s.add("big.txt", b"x" * (6 * 1024 * 1024))


class FakeClient:
    """Stands in for anthropic.Anthropic: records the request, returns a canned response."""

    def __init__(self, text=json.dumps(TAILORED), stop_reason="end_turn"):
        self.calls = []
        response = SimpleNamespace(stop_reason=stop_reason, model=tailor.MODEL,
                                   content=[SimpleNamespace(type="text", text=text)],
                                   usage=SimpleNamespace(input_tokens=3000, output_tokens=4000))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self.calls.append(kw) or response))


class TailorTests(unittest.TestCase):
    job = {"title": "Picker", "company": "Shop & Co", "location": "Mount Laurel, NJ"}

    def test_success(self):
        client = FakeClient()
        out = tailor.tailor(RESUME, self.job, "Pick and pack orders.", "sk-ant-x", client=client)
        self.assertEqual(out["resume"]["name"], "Jane Doe")
        self.assertEqual(out["cost_usd"], 0.092)  # 3000 in x $4/M + 4000 out x $20/M
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual((call["fallbacks"], call["betas"]), ("default", ["server-side-fallback-2026-07-01"]))
        self.assertEqual(call["output_config"]["format"]["schema"], tailor.SCHEMA)
        self.assertIn("Never add", call["system"])
        content = call["messages"][0]["content"]
        self.assertIn("<resume>", content)
        self.assertIn("Company: Shop & Co", content)

    def test_schema_is_strict(self):
        def walk(node):
            if node.get("type") == "object":
                self.assertFalse(node["additionalProperties"])
                self.assertEqual(sorted(node["required"]), sorted(node["properties"]))
                for child in node["properties"].values():
                    walk(child)
            if node.get("type") == "array":
                walk(node["items"])
        walk(tailor.SCHEMA)

    def test_problems_become_readable_errors(self):
        with self.assertRaisesRegex(TailorError, "declined"):
            tailor.tailor(RESUME, self.job, "x", "k", client=FakeClient(stop_reason="refusal"))
        with self.assertRaisesRegex(TailorError, "cut off"):
            tailor.tailor(RESUME, self.job, "x", "k", client=FakeClient(stop_reason="max_tokens"))
        with self.assertRaisesRegex(TailorError, "couldn't be read"):
            tailor.tailor(RESUME, self.job, "x", "k", client=FakeClient(text="not json"))
        with self.assertRaisesRegex(TailorError, "Add your Anthropic API key"):
            tailor.tailor(RESUME, self.job, "x", "")

    def test_real_sdk_request_and_bad_key(self):
        """Run the real anthropic SDK against a fake network: the request it sends, and a 401."""
        import anthropic
        import httpx2

        seen = {}

        def ok(request):
            seen["headers"], seen["body"] = request.headers, json.loads(request.content)
            return httpx2.Response(200, json={
                "id": "msg_1", "type": "message", "role": "assistant", "model": tailor.MODEL,
                "content": [{"type": "text", "text": json.dumps(TAILORED)}], "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 20}})

        def denied(request):
            return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})

        def client(handler):
            return anthropic.Anthropic(api_key="sk-ant-test", max_retries=0,
                                       http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))

        out = tailor.tailor(RESUME, self.job, "Pick orders.", "", client=client(ok))
        self.assertEqual(out["resume"]["gaps"], TAILORED["gaps"])
        self.assertEqual(seen["headers"]["anthropic-beta"], "server-side-fallback-2026-07-01")
        self.assertEqual(seen["body"]["output_config"]["effort"], "medium")
        self.assertEqual(seen["body"]["fallbacks"], "default")
        with self.assertRaisesRegex(TailorError, "didn't accept the API key"):
            tailor.tailor(RESUME, self.job, "Pick orders.", "", client=client(denied))


class ApplyRouteTests(unittest.TestCase):
    """The app's HTTP routes, with a fake Claude plugged in."""

    def setUp(self):
        import threading

        from jobscraper.server import make_server

        from .test_jobscraper import FakeSession, RunTests
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name), session=FakeSession())
        self.store.set_config({**RunTests.config, "anthropic": {"api_key": "sk-ant-api03-secretsecret"}})
        self.store.refresh()
        self.store.desk.tailor_fn = lambda text, job, posting, key: {
            "resume": TAILORED, "model": tailor.MODEL, "cost_usd": 0.12, "usage": {}, "_key_seen": key}
        self.server = make_server(self.store, port=0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, path, body=None, headers=None):
        req = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with self.opener.open(req, timeout=10) as r:
                raw = r.read()
                return r.status, r.headers, (json.loads(raw) if "json" in r.headers["Content-Type"] else raw)
        except urllib.error.HTTPError as e:
            return e.code, e.headers, json.loads(e.read())

    def test_upload_tailor_download(self):
        status, _, listing = self.call("/api/resumes", {"filename": "Jane Doe.docx", "data": base64.b64encode(FIXTURE_DOCX).decode()})
        self.assertEqual(status, 200)
        rid = listing["main"]
        status, headers, original = self.call(f"/api/resumes/{rid}/download")
        self.assertEqual(original, FIXTURE_DOCX)
        self.assertIn("Jane Doe.docx", headers["Content-Disposition"])
        _, _, text = self.call(f"/api/resumes/{rid}/text")
        self.assertIn("Forklift certified", text["text"])
        self.assertEqual(self.call("/api/resumes/0123456789ab/text")[0], 404)

        job = next(j for j in self.store.state()["jobs"] if j["title"] == "Frontend Developer")

        status, _, err = self.call("/api/tailor", {"key": job["key"], "posting": "too short"})
        self.assertEqual(status, 400)
        self.assertIn("full job description", err["error"])
        posting = "We need a frontend developer who knows React and TypeScript well. " * 3
        status, _, rec = self.call("/api/tailor", {"key": job["key"], "posting": posting})
        self.assertEqual(status, 200)
        self.assertEqual(rec["job"]["title"], "Frontend Developer")
        self.assertEqual(rec["_key_seen"], "sk-ant-api03-secretsecret")  # the server passes the saved key to Claude

        _, _, versions = self.call(f"/api/tailored?key={urllib.request.quote(job['key'])}")
        self.assertEqual([v["id"] for v in versions], [rec["id"]])
        self.assertEqual(versions[0]["resume"], TAILORED)  # the browser makes the Word and PDF versions from this

        _, _, settings = self.call("/tailor.json")
        self.assertEqual(settings["request"]["model"], tailor.MODEL)
        self.assertEqual(settings["system"], tailor.SYSTEM)

    def test_key_never_reaches_the_page_and_other_hosts_are_refused(self):
        _, _, state = self.call("/api/state")
        self.assertNotIn("secretsecret", json.dumps(state))
        self.assertEqual(state["config"]["anthropic"], {"has_key": True})
        self.assertEqual(self.call("/api/resumes", headers={"Host": "evil.example:8765"})[0], 403)
        self.assertEqual(self.call("/api/resumes", headers={"Host": "localhost"})[0], 200)


if __name__ == "__main__":
    unittest.main()
