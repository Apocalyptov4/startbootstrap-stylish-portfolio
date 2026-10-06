"""Turn a tailored resume into files to send: a Word document and a printable web page (Save as PDF).

Both use a plain one-column layout with standard headings, which applicant-tracking
systems read reliably. The Word file is written with the standard library only.
"""

from __future__ import annotations

import html
import io
import zipfile
from xml.sax.saxutils import escape


# ------------------------------------------------------------------ shared layout

def _blocks(r: dict):
    """The resume as a list of (kind, text) blocks, in reading order."""
    yield "name", r.get("name") or ""
    if r.get("headline"):
        yield "headline", r["headline"]
    contact = [c for c in r.get("contact") or [] if c]
    if contact:
        yield "contact", "  |  ".join(contact)
    if r.get("summary"):
        yield "heading", "Summary"
        yield "para", r["summary"]
    if r.get("skills"):
        yield "heading", "Skills"
        yield "para", ", ".join(r["skills"])
    if r.get("experience"):
        yield "heading", "Experience"
        for job in r["experience"]:
            title = " — ".join(x for x in (job.get("title"), job.get("organization")) if x)
            yield "role", title
            meta = "  |  ".join(x for x in (job.get("location"), job.get("dates")) if x)
            if meta:
                yield "meta", meta
            for b in job.get("bullets") or []:
                yield "bullet", b
    if r.get("education"):
        yield "heading", "Education"
        for ed in r["education"]:
            yield "role", " — ".join(x for x in (ed.get("credential"), ed.get("school")) if x)
            if ed.get("dates"):
                yield "meta", ed["dates"]
            for d in ed.get("details") or []:
                yield "bullet", d
    for sec in r.get("other_sections") or []:
        if sec.get("items"):
            yield "heading", sec.get("heading") or "More"
            for item in sec["items"]:
                yield "bullet", item


# ------------------------------------------------------------------ Word (.docx)

_STYLE = {  # kind -> (size in half-points, bold, space before, space after, indent twips)
    "name": (36, True, 0, 40, 0),
    "headline": (24, False, 0, 40, 0),
    "contact": (20, False, 0, 160, 0),
    "heading": (24, True, 200, 60, 0),
    "para": (21, False, 0, 80, 0),
    "role": (22, True, 120, 0, 0),
    "meta": (20, False, 0, 40, 0),
    "bullet": (21, False, 0, 40, 360),
    "letter": (22, False, 0, 160, 0),
}


def _para(kind: str, text: str) -> str:
    size, bold, before, after, indent = _STYLE[kind]
    if kind == "bullet":
        text = "•\t" + text
    ind = f'<w:ind w:left="{indent}" w:hanging="{indent // 2}"/>' if indent else ""
    tabs = f'<w:tabs><w:tab w:val="left" w:pos="{indent}"/></w:tabs>' if indent else ""
    border = ('<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="888888"/></w:pBdr>'
              if kind == "heading" else "")
    rpr = f'<w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr>'
    runs = []
    for i, part in enumerate(text.split("\t")):
        if i:
            runs.append(f"<w:r>{rpr}<w:tab/></w:r>")
        if part:
            runs.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(part)}</w:t></w:r>')
    return (f'<w:p><w:pPr>{tabs}{border}<w:spacing w:before="{before}" w:after="{after}"/>{ind}</w:pPr>'
            f'{"".join(runs)}</w:p>')


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        f'{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1008" w:right="1080" w:bottom="1008" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>'
        "</w:sectPr></w:body></w:document>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault>'
        '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>'
        '<w:sz w:val="21"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="264" '
        'w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults></w:styles>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
    return buf.getvalue()


def resume_docx(resume: dict) -> bytes:
    return _docx([_para(kind, text) for kind, text in _blocks(resume) if text])


def cover_letter_docx(resume: dict) -> bytes:
    paras = [_para("name", resume.get("name") or "")]
    contact = "  |  ".join(c for c in resume.get("contact") or [] if c)
    if contact:
        paras.append(_para("contact", contact))
    for chunk in (resume.get("cover_letter") or "").split("\n"):
        if chunk.strip():
            paras.append(_para("letter", chunk.strip()))
    return _docx(paras)


# ------------------------------------------------------------------ printable page

_PAGE_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #e9ecef; font: 10.5pt/1.4 Calibri, "Segoe UI", Arial, sans-serif; color: #111; }
.bar { position: sticky; top: 0; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; padding: 10px 16px;
       background: #fff; border-bottom: 1px solid #ccc; font-family: system-ui, sans-serif; font-size: 14px; }
.bar button, .bar a { font: inherit; padding: 7px 12px; border-radius: 8px; border: 1px solid #bbb; background: #fff;
       color: #111; text-decoration: none; cursor: pointer; }
.bar .primary { background: #2563eb; border-color: #2563eb; color: #fff; }
.bar span { color: #555; margin-left: auto; }
.page { background: #fff; width: min(8.5in, 100%); margin: 16px auto; padding: 0.6in 0.7in; box-shadow: 0 2px 12px rgba(0,0,0,.15); }
h1 { font-size: 20pt; margin: 0; }
.headline { font-size: 12pt; margin: 2px 0 0; }
.contact { font-size: 10pt; color: #333; margin: 4px 0 10px; }
h2 { font-size: 12pt; margin: 14px 0 4px; padding-bottom: 2px; border-bottom: 1px solid #888; text-transform: uppercase; letter-spacing: .04em; }
.role { font-weight: 700; margin-top: 8px; }
.meta { color: #333; font-size: 10pt; }
ul { margin: 2px 0 0; padding-left: 18px; }
li { margin: 1px 0; }
p { margin: 0 0 6px; }
.letter p { margin: 0 0 12px; font-size: 11pt; }
@media print {
  body { background: #fff; }
  .bar { display: none; }
  .page { margin: 0; padding: 0; width: auto; box-shadow: none; }
  @page { size: letter; margin: 0.6in 0.7in; }
}
"""


def resume_html(resume: dict, page_title: str, docx_url: str, letter: bool = False) -> str:
    e = html.escape
    parts, in_list = [], False
    if letter:
        parts.append(f"<h1>{e(resume.get('name') or '')}</h1>")
        contact = "  |  ".join(c for c in resume.get("contact") or [] if c)
        if contact:
            parts.append(f'<div class="contact">{e(contact)}</div>')
        parts.append('<div class="letter">' + "".join(
            f"<p>{e(p.strip())}</p>" for p in (resume.get("cover_letter") or "").split("\n") if p.strip()) + "</div>")
    else:
        for kind, text in _blocks(resume):
            if kind != "bullet" and in_list:
                parts.append("</ul>")
                in_list = False
            if not text:
                continue
            if kind == "bullet":
                if not in_list:
                    parts.append("<ul>")
                    in_list = True
                parts.append(f"<li>{e(text)}</li>")
            else:
                tag = {"name": "h1", "heading": "h2"}.get(kind, "div")
                cls = "" if kind in ("name", "heading") else f' class="{kind}"'
                if kind == "para":
                    tag, cls = "p", ""
                parts.append(f"<{tag}{cls}>{e(text)}</{tag}>")
        if in_list:
            parts.append("</ul>")
    what = "cover letter" if letter else "resume"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(page_title)}</title><style>{_PAGE_CSS}</style></head>
<body>
<div class="bar">
  <button class="primary" onclick="window.print()">Save as PDF / Print</button>
  <a href="{e(docx_url)}">Download Word file</a>
  <span>In the print window, choose “Save as PDF” to get a PDF {what}.</span>
</div>
<main class="page">{''.join(parts)}</main>
</body></html>"""
