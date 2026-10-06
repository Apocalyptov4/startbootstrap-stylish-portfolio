"""Runs the tests for the browser code (tests/js) when Node.js is installed, and checks that the
website asks Claude exactly what the program does."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from jobscraper import tailor
from jobscraper.server import WEB_DIR

NODE = shutil.which("node")
HERE = Path(__file__).parent


@unittest.skipUnless(NODE, "Node.js isn't installed")
class BrowserCodeTests(unittest.TestCase):
    def node(self, *args, stdin=None):
        return subprocess.run([NODE, *args], input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_js_unit_tests(self):
        r = self.node("--test", str(HERE / "js" / "resume_tools.test.js"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_website_prompt_matches_the_program(self):
        job = {"title": "Cook", "company": "Diner & Co", "location": "", "url": "https://x"}
        resume, posting = "Jane Doe\nLine cook, 2020-2024 " + "x" * 40000, "We need a line cook. " * 50
        script = (f"const T = require({json.dumps(str(WEB_DIR / 'resume-tools.js'))});"
                  "const [cfg, resume, job, posting] = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
                  "process.stdout.write(T.tailorPrompt(cfg, resume, job, posting));")
        r = self.node("-e", script, stdin=json.dumps([tailor.browser_settings(), resume, job, posting]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, tailor._prompt(resume, job, posting))


if __name__ == "__main__":
    unittest.main()
