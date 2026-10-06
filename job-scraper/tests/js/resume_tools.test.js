// Tests for jobscraper/web/resume-tools.js. Run: node --test tests/js/resume_tools.test.js
// (tests/test_browser_code.py runs them with the Python tests when Node.js is installed.)
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const T = require("../../jobscraper/web/resume-tools.js");

const TAILORED = {
  name: "Jane Doe", contact: ["jane@example.com", "(609) 555-0100"], headline: "Warehouse Associate",
  summary: "Warehouse associate with three years of order picking & forklift work.",
  skills: ["Forklift", "RF scanners"],
  experience: [{ title: "Warehouse Associate", organization: "Acme Logistics", location: "Burlington, NJ",
    dates: "2021-2024", bullets: ["Picked and packed orders <fast>", "Operated forklifts"] }],
  education: [], other_sections: [{ heading: "Certifications", items: ["OSHA 10"] }],
  cover_letter: "Dear Hiring Manager,\nI would like to apply.\nJane Doe",
  changes: ["Put forklift work first"], gaps: ["The posting asks for a CDL. Add it only if you have one."],
};

test("match finds key words, aliases and ignores category names", () => {
  const m = T.match("RN with 3 years in med-surg. BLS certified. Epic EMR charting, patient assessment.",
    "Registered Nurse - Med/Surg",
    "Seeking a Registered Nurse (RN) for our medical-surgical unit. BLS and Epic EHR required. Patient assessment.",
    ["Healthcare & Nursing Jobs", "Full Time"]);
  assert.ok(m.found.includes("registered nurse"));   // "RN" counts
  assert.ok(m.found.includes("med/surg"));           // "med-surg" counts
  assert.ok(![...m.found, ...m.missing].includes("healthcare"));
  assert.ok(m.score >= 60);
  assert.equal(m.checked, m.found.length + m.missing.length);
  assert.deepEqual(T.match("anything", "", "", []), { score: 0, found: [], missing: [], checked: 0 });
});

test("Word files are valid zips with escaped text, and read back", async () => {
  const resume = T.resumeDocx(TAILORED);
  const letter = T.coverLetterDocx(TAILORED);
  for (const name of ["[Content_Types].xml", "_rels/.rels", "word/_rels/document.xml.rels", "word/document.xml", "word/styles.xml"]) {
    assert.ok(await T.unzipEntry(resume, name), name);
  }
  const xml = new TextDecoder().decode(await T.unzipEntry(resume, "word/document.xml"));
  assert.ok(xml.includes("&lt;fast&gt;"));
  const text = await T.docxText(resume);
  assert.ok(text.split("\n").includes("•\tOperated forklifts"));  // no stray tab from tab-stop settings
  assert.ok((await T.docxText(letter)).includes("I would like to apply."));
  assert.equal(T.crc32(new TextEncoder().encode("123456789")), 0xcbf43926);
});

test("reads a real (compressed) Word file with a text box, table and tabs", async () => {
  const bytes = new Uint8Array(fs.readFileSync(path.join(__dirname, "..", "fixtures", "resume.docx")));
  const lines = (await T.docxText(bytes)).split("\n");
  assert.equal(lines.filter((l) => l.includes("555-0100")).length, 1);  // the text box comes once
  assert.ok(lines.includes("Warehouse Associate\t2021 & 2024"));
  assert.ok(lines.includes("•\tPicked <fast> orders"));
  assert.ok(lines.includes("Forklift certified"));
  assert.ok(lines.includes("Café work, — customer service"));
  await assert.rejects(T.docxText(new TextEncoder().encode("not a zip")), /couldn't be opened/);
});

test("printable page is escaped and the letter is split into paragraphs", () => {
  const page = T.resumeHtml(TAILORED);
  assert.ok(page.startsWith("<h1>Jane Doe</h1><div class=\"headline\">Warehouse Associate</div>"));
  assert.ok(page.includes("<li>Picked and packed orders &lt;fast&gt;</li>"));
  assert.ok(page.includes("<h2>Certifications</h2><ul><li>OSHA 10</li></ul>"));
  const letter = T.resumeHtml(TAILORED, true);
  assert.ok(letter.includes("<p>I would like to apply.</p>"));
  assert.ok(!letter.includes("Warehouse Associate"));
});

test("file names are safe for every operating system", () => {
  const rec = { resume: { name: "Jane Doe" }, job: { company: "Acme: Shipping/Receiving?" } };
  assert.equal(T.fileName(rec, "Resume"), "Jane Doe - Resume - Acme ShippingReceiving");
  assert.equal(T.fileName({ resume: {}, job: { title: "Cook" } }, "Cover Letter"), "Resume - Cover Letter - Cook");
});
