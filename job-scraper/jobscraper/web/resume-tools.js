"use strict";
// Resume helpers that run in the browser, in the program and on the website alike:
//   - the free match check: which important words from a job ad are on your resume
//   - reading the text of a Word (.docx) file
//   - the Word file and the printable page of a tailored resume and cover letter
// No libraries. Tests: tests/js/resume_tools.test.js (run with `node --test tests/js`).

const ResumeTools = (() => {
  // ---------------------------------------------------------------- match check
  // No AI involved. It picks the words and two-word phrases the ad uses most (the title counts
  // extra), ignores filler words, and looks for each in the resume. It's a rough guide to what an
  // applicant-tracking system or a recruiter skimming for keywords would notice.

  const STOPWORDS = new Set(`
a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each etc few for from further had has have having he her here hers
him his how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours
out over own same she should so some such than that the their theirs them then there these they this those through
to too under until up very was we were what when where which while who whom why will with would you your yours
able across ad ads apply applicant applicants applications based benefits candidate candidates company day days
description duties employer employment equal etc every experience full get great help hiring hour hours include
including join job jobs looking make may must need needed new opportunity part pay per plus position preferred
provide required requirements responsibilities role salary seeking shift skills strong team time us using well
within work working year years yr yrs week weekly active lbs permanent contract jobs ability excellent require requires
`.split(/\s+/).filter(Boolean));
  // Same thing, written differently. Each group counts as found if any of its forms is on the resume.
  const ALIASES = [
    ["registered nurse", "rn"], ["licensed practical nurse", "lpn"], ["certified nursing assistant", "cna"],
    ["electronic health record", "ehr", "emr"], ["medical surgical", "med surg"], ["commercial driver", "cdl"],
    ["customer service", "customer support"], ["microsoft excel", "excel"], ["point of sale", "pos"],
    ["javascript", "js"], ["kubernetes", "k8s"],
  ];
  // Category names like "Healthcare & Nursing Jobs" and "Full Time" aren't things a resume should say.
  const NOT_SKILLS = new Set(["full time", "part time", "permanent", "contract", "temporary", "internship"]);
  const WORD_RE = /[a-z][a-z0-9+#.\-/]*[a-z0-9+#]|[a-z]/g;

  const words = (text) => (String(text || "").toLowerCase().match(WORD_RE) || []).filter((w) => w.length > 1);

  function stem(word) {
    for (const suffix of ["ing", "ed", "es", "s"]) {
      if (word.length > suffix.length + 3 && word.endsWith(suffix)) return word.slice(0, -suffix.length);
    }
    return word;
  }

  // Word runs between punctuation, so phrases never span "Associate - Night" or "picking, packing".
  const chunks = (text) => String(text || "").toLowerCase().split(/[,.;:!?()[\]|&•–—]|\s-\s|\n/).map(words);
  const useful = (w) => !STOPWORDS.has(w) && w.length > 2 && !/^\d+$/.test(w) && !w.startsWith("$");
  // "med/surg" and "med-surg" both become "med", "surg".
  const parts = (text) => words(text).flatMap((w) => w.split(/[-/]/)).filter(Boolean);

  function keywords(title, description, tags = [], limit = 15) {
    const singles = new Map();
    const pairs = new Map();
    const add = (map, key, n) => map.set(key, (map.get(key) || 0) + n);
    for (const [weight, text] of [[3, title], [1, description], [2, (tags || []).join(" | ")]]) {
      for (const chunk of chunks(text)) {
        for (const w of chunk) if (useful(w)) add(singles, w, weight);
        for (let i = 0; i + 1 < chunk.length; i++) {
          if (useful(chunk[i]) && useful(chunk[i + 1])) add(pairs, `${chunk[i]} ${chunk[i + 1]}`, weight);
        }
      }
    }
    // A two-word phrase counts when it's in the title or repeated; then it stands in for its words.
    const scored = new Map([...pairs].filter(([, n]) => n >= 2).map(([p, n]) => [p, n * 1.5]));
    const inPhrase = new Set([...scored.keys()].flatMap((p) => p.split(" ")));
    for (const [w, n] of singles) if (!inPhrase.has(w)) scored.set(w, n);
    return [...scored].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
      .slice(0, limit).map(([t]) => t);
  }

  function inText(term, resumeStems) {
    const norm = parts(term).join(" ");
    const forms = ALIASES.find((g) => g.includes(norm)) || [norm];
    return forms.some((form) => form.split(" ").every((w) => resumeStems.has(stem(w))));
  }

  /** {score, found, missing, checked}: how many of the ad's key words are on the resume. */
  function match(resumeText, title, description, tags = []) {
    const usable = (tags || []).filter((t) => {
      const lower = String(t).toLowerCase();
      return !lower.endsWith(" jobs") && !NOT_SKILLS.has(lower.replace(/-/g, " "));
    });
    const terms = keywords(title, description, usable);
    const stems = new Set(parts(resumeText).map(stem));
    const found = terms.filter((t) => inText(t, stems));
    const missing = terms.filter((t) => !found.includes(t));
    const score = terms.length ? Math.round((100 * found.length) / terms.length) : 0;
    return { score, found, missing, checked: terms.length };
  }

  // ---------------------------------------------------------------- zip files (.docx is a zip)

  const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });

  function crc32(bytes) {
    let c = 0xffffffff;
    for (const b of bytes) c = CRC_TABLE[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  }

  /** A zip file (stored, not compressed) from [[name, text], ...]. */
  function zip(files) {
    const enc = new TextEncoder();
    const local = [];
    const central = [];
    let offset = 0;
    for (const [name, text] of files) {
      const nameBytes = enc.encode(name);
      const data = enc.encode(text);
      const crc = crc32(data);
      const header = (sig, extra) => {
        const h = new DataView(new ArrayBuffer(extra));
        h.setUint32(0, sig, true);
        return h;
      };
      const lh = header(0x04034b50, 30);
      lh.setUint16(4, 20, true);
      lh.setUint16(10, 0, true);      // time
      lh.setUint16(12, 0x21, true);   // date: 1980-01-01
      lh.setUint32(14, crc, true);
      lh.setUint32(18, data.length, true);
      lh.setUint32(22, data.length, true);
      lh.setUint16(26, nameBytes.length, true);
      const ch = header(0x02014b50, 46);
      ch.setUint16(4, 20, true);
      ch.setUint16(6, 20, true);
      ch.setUint16(14, 0x21, true);
      ch.setUint32(16, crc, true);
      ch.setUint32(20, data.length, true);
      ch.setUint32(24, data.length, true);
      ch.setUint16(28, nameBytes.length, true);
      ch.setUint32(42, offset, true);
      local.push(new Uint8Array(lh.buffer), nameBytes, data);
      central.push(new Uint8Array(ch.buffer), nameBytes);
      offset += 30 + nameBytes.length + data.length;
    }
    const centralSize = central.reduce((n, b) => n + b.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);
    end.setUint16(8, files.length, true);
    end.setUint16(10, files.length, true);
    end.setUint32(12, centralSize, true);
    end.setUint32(16, offset, true);
    const out = new Uint8Array(offset + centralSize + 22);
    let pos = 0;
    for (const b of [...local, ...central, new Uint8Array(end.buffer)]) { out.set(b, pos); pos += b.length; }
    return out;
  }

  /** One file's bytes from a zip, or null if it isn't there. */
  async function unzipEntry(bytes, wanted) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let end = -1;
    for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) {
      if (view.getUint32(i, true) === 0x06054b50) { end = i; break; }
    }
    if (end < 0) throw new Error("not a zip file");
    const count = view.getUint16(end + 10, true);
    let p = view.getUint32(end + 16, true);
    const dec = new TextDecoder();
    for (let i = 0; i < count; i++) {
      if (view.getUint32(p, true) !== 0x02014b50) throw new Error("damaged zip file");
      const method = view.getUint16(p + 10, true);
      const size = view.getUint32(p + 20, true);
      const nameLen = view.getUint16(p + 28, true);
      const skip = nameLen + view.getUint16(p + 30, true) + view.getUint16(p + 32, true);
      const at = view.getUint32(p + 42, true);
      const name = dec.decode(bytes.subarray(p + 46, p + 46 + nameLen));
      p += 46 + skip;
      if (name !== wanted) continue;
      const start = at + 30 + view.getUint16(at + 26, true) + view.getUint16(at + 28, true);
      const data = bytes.subarray(start, start + size);
      if (method === 0) return data;
      if (method !== 8) throw new Error("unsupported zip compression");
      const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    }
    return null;
  }

  // ---------------------------------------------------------------- reading Word files

  const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'" };
  const unescapeXml = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|\w+);/gi, (m, e) =>
    e[0] === "#" ? String.fromCodePoint(e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10))
      : ENTITIES[e] ?? m);

  /** The text of a Word document, one line per paragraph. */
  async function docxText(bytes) {
    let xml;
    try {
      const data = await unzipEntry(bytes, "word/document.xml");
      if (!data) throw new Error("no document");
      xml = new TextDecoder().decode(data);
    } catch {
      throw new Error("That Word file couldn't be opened.");
    }
    // Walk the tags in order: text runs, tabs and line breaks inside runs, and a new line after each
    // paragraph. Text boxes come once (their old-Word "fallback" copy is skipped), and tab-stop settings
    // (<w:tabs><w:tab/>) aren't mistaken for tabs.
    let out = "";
    let inText = false, inTabs = 0, inFallback = 0;
    const tagRe = /<(\/?)([\w:]+)[^>]*?(\/?)>|([^<]+)/g;
    for (const m of xml.matchAll(tagRe)) {
      if (m[4] !== undefined) {
        if (inText && !inFallback) out += unescapeXml(m[4]);
        continue;
      }
      const [, closing, tag, selfClosing] = m;
      if (tag === "mc:Fallback") inFallback += closing ? -1 : selfClosing ? 0 : 1;
      if (inFallback) continue;
      if (tag === "w:t") inText = !closing && !selfClosing;
      else if (tag === "w:tabs") inTabs += closing ? -1 : selfClosing ? 0 : 1;
      else if (tag === "w:tab" && !closing && !inTabs) out += "\t";
      else if ((tag === "w:br" || tag === "w:cr") && !closing) out += "\n";
      else if (tag === "w:p" && (closing || selfClosing)) out += "\n";
    }
    return out;
  }

  // ---------------------------------------------------------------- tailored resume layout

  /** The resume as [kind, text] blocks, in reading order. */
  function blocks(r) {
    const out = [["name", r.name || ""]];
    const join = (sep, items) => items.filter(Boolean).join(sep);
    if (r.headline) out.push(["headline", r.headline]);
    const contact = join("  |  ", r.contact || []);
    if (contact) out.push(["contact", contact]);
    if (r.summary) out.push(["heading", "Summary"], ["para", r.summary]);
    if (r.skills?.length) out.push(["heading", "Skills"], ["para", r.skills.join(", ")]);
    if (r.experience?.length) {
      out.push(["heading", "Experience"]);
      for (const job of r.experience) {
        out.push(["role", join(" — ", [job.title, job.organization])]);
        const meta = join("  |  ", [job.location, job.dates]);
        if (meta) out.push(["meta", meta]);
        for (const b of job.bullets || []) out.push(["bullet", b]);
      }
    }
    if (r.education?.length) {
      out.push(["heading", "Education"]);
      for (const ed of r.education) {
        out.push(["role", join(" — ", [ed.credential, ed.school])]);
        if (ed.dates) out.push(["meta", ed.dates]);
        for (const d of ed.details || []) out.push(["bullet", d]);
      }
    }
    for (const sec of r.other_sections || []) {
      if (sec.items?.length) {
        out.push(["heading", sec.heading || "More"]);
        for (const item of sec.items) out.push(["bullet", item]);
      }
    }
    return out;
  }

  const letterParagraphs = (r) => String(r.cover_letter || "").split("\n").map((p) => p.trim()).filter(Boolean);
  const contactLine = (r) => (r.contact || []).filter(Boolean).join("  |  ");

  // ---------------------------------------------------------------- Word (.docx)

  const STYLE = { // kind -> [size in half-points, bold, space before, space after, indent in twips]
    name: [36, true, 0, 40, 0],
    headline: [24, false, 0, 40, 0],
    contact: [20, false, 0, 160, 0],
    heading: [24, true, 200, 60, 0],
    para: [21, false, 0, 80, 0],
    role: [22, true, 120, 0, 0],
    meta: [20, false, 0, 40, 0],
    bullet: [21, false, 0, 40, 360],
    letter: [22, false, 0, 160, 0],
  };
  const escapeXml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

  function para(kind, text) {
    const [size, bold, before, after, indent] = STYLE[kind];
    if (kind === "bullet") text = "•\t" + text;
    const ind = indent ? `<w:ind w:left="${indent}" w:hanging="${indent / 2}"/>` : "";
    const tabs = indent ? `<w:tabs><w:tab w:val="left" w:pos="${indent}"/></w:tabs>` : "";
    const border = kind === "heading" ? '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="888888"/></w:pBdr>' : "";
    const rpr = `<w:rPr>${bold ? "<w:b/>" : ""}<w:sz w:val="${size}"/><w:szCs w:val="${size}"/></w:rPr>`;
    const runs = text.split("\t").map((part, i) =>
      (i ? `<w:r>${rpr}<w:tab/></w:r>` : "") + (part ? `<w:r>${rpr}<w:t xml:space="preserve">${escapeXml(part)}</w:t></w:r>` : ""));
    return `<w:p><w:pPr>${tabs}${border}<w:spacing w:before="${before}" w:after="${after}"/>${ind}</w:pPr>${runs.join("")}</w:p>`;
  }

  const XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
  const W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
  const REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships";
  const DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";

  function docx(paragraphs) {
    const document = `${XML}<w:document xmlns:w="${W_NS}"><w:body>${paragraphs.join("")}` +
      '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>' +
      '<w:pgMar w:top="1008" w:right="1080" w:bottom="1008" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>' +
      "</w:sectPr></w:body></w:document>";
    const styles = `${XML}<w:styles xmlns:w="${W_NS}"><w:docDefaults><w:rPrDefault>` +
      '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>' +
      '<w:sz w:val="21"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="264" ' +
      'w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults></w:styles>';
    const types = `${XML}<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">` +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/word/document.xml" ' +
      'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
      '<Override PartName="/word/styles.xml" ' +
      'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>';
    const rels = `${XML}<Relationships xmlns="${REL_NS}">` +
      `<Relationship Id="rId1" Type="${DOC_REL}/officeDocument" Target="word/document.xml"/></Relationships>`;
    const docRels = `${XML}<Relationships xmlns="${REL_NS}">` +
      `<Relationship Id="rId1" Type="${DOC_REL}/styles" Target="styles.xml"/></Relationships>`;
    return zip([
      ["[Content_Types].xml", types],
      ["_rels/.rels", rels],
      ["word/_rels/document.xml.rels", docRels],
      ["word/document.xml", document],
      ["word/styles.xml", styles],
    ]);
  }

  const DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  const resumeDocx = (r) => docx(blocks(r).filter(([, text]) => text).map(([kind, text]) => para(kind, text)));

  function coverLetterDocx(r) {
    const paras = [para("name", r.name || "")];
    if (contactLine(r)) paras.push(para("contact", contactLine(r)));
    for (const p of letterParagraphs(r)) paras.push(para("letter", p));
    return docx(paras);
  }

  // ---------------------------------------------------------------- printable page

  const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;" })[c]);

  /** The inside of the printable page (the app adds the paper look and the print styles). */
  function resumeHtml(r, letter = false) {
    const e = escapeHtml;
    if (letter) {
      return `<h1>${e(r.name || "")}</h1>` + (contactLine(r) ? `<div class="contact">${e(contactLine(r))}</div>` : "") +
        `<div class="letter">${letterParagraphs(r).map((p) => `<p>${e(p)}</p>`).join("")}</div>`;
    }
    const out = [];
    let inList = false;
    for (const [kind, text] of blocks(r)) {
      if (kind !== "bullet" && inList) { out.push("</ul>"); inList = false; }
      if (!text) continue;
      if (kind === "bullet") {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push(`<li>${e(text)}</li>`);
      } else if (kind === "name") out.push(`<h1>${e(text)}</h1>`);
      else if (kind === "heading") out.push(`<h2>${e(text)}</h2>`);
      else if (kind === "para") out.push(`<p>${e(text)}</p>`);
      else out.push(`<div class="${kind}">${e(text)}</div>`);
    }
    if (inList) out.push("</ul>");
    return out.join("");
  }

  // ---------------------------------------------------------------- tailoring request

  let settings;
  /** The tailoring settings from jobscraper/tailor.py (served as tailor.json): request, system, prices, limits. */
  function tailorSettings() {
    settings ||= fetch("tailor.json").then((r) => {
      if (!r.ok) throw new Error("Resume tailoring isn't set up here.");
      return r.json();
    }).catch((e) => { settings = null; throw e; });
    return settings;
  }

  /** The message for Claude: the resume, then the job posting (same as _prompt in tailor.py). */
  function tailorPrompt(cfg, resumeText, job, posting) {
    const facts = [["Title", job.title], ["Company", job.company], ["Location", job.location]]
      .filter(([, v]) => v).map(([label, v]) => `${label}: ${v}`).join("\n");
    return `<resume>\n${resumeText.slice(0, cfg.max_resume_chars)}\n</resume>\n\n` +
      `<job_posting>\n${facts}\n\n${posting.slice(0, cfg.max_posting_chars)}\n</job_posting>\n\n` +
      "Tailor the resume to this job posting, following the rules.";
  }

  /** "Jane Doe - Resume - Acme Health" (add the extension yourself). */
  function fileName(record, what) {
    const name = record.resume?.name || "Resume";
    const company = record.job?.company || record.job?.title || "";
    return [name, what, company].filter(Boolean).join(" - ").replace(/[\\/:*?"<>|\r\n]+/g, "").slice(0, 120);
  }

  return {
    match, keywords, tailorSettings, tailorPrompt, docxText, unzipEntry, zip, crc32, blocks, resumeDocx, coverLetterDocx, resumeHtml, fileName, DOCX_TYPE,
  };
})();

if (typeof module !== "undefined") module.exports = ResumeTools;
