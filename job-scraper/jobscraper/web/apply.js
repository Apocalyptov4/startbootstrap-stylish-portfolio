"use strict";
// Applying for a job: your stored resumes, the free match check, AI tailoring, and the Word and
// printable (Save as PDF) versions of what Claude makes. Works the same in the program and on the website;
// only where things are kept differs:
//   program: on this computer, through the app's server (ServerDesk below)
//   website: in this browser (LocalDesk in resume-local.js)
// Uses helpers from app.js ($, esc, api, state, STATIC, renderDetail, setStatus, openSettings)
// and ResumeTools from resume-tools.js.

const ServerDesk = {
  list: () => api("/api/resumes"),
  add: (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(api("/api/resumes", { filename: file.name, data: String(reader.result).split(",")[1] || "" }));
    reader.onerror = () => reject(new Error("That file couldn't be read."));
    reader.readAsDataURL(file);
  }),
  addText: (text) => api("/api/resumes", { text, name: "Pasted resume" }),
  setMain: (id) => api(`/api/resumes/${id}/main`, {}),
  remove: (id) => api(`/api/resumes/${id}/delete`, {}),
  text: async (id) => (await api(`/api/resumes/${id}/text`)).text,
  async file(id) {
    const res = await fetch(`/api/resumes/${id}/download`);
    if (!res.ok) throw new Error("That resume couldn't be found.");
    const entry = apply.resumes?.resumes.find((r) => r.id === id);
    return { blob: await res.blob(), filename: entry?.filename || "resume" };
  },
  versions: (key) => api(`/api/tailored?key=${encodeURIComponent(key)}`),
  tailor: ({ job, posting, resume_id }) => api("/api/tailor", { key: job.key, posting, resume_id }),
  hasKey: () => !!state.data.config.anthropic?.has_key,
};
const desk = STATIC ? LocalDesk : ServerDesk;

const apply = { resumes: null, texts: {}, match: {}, versions: {}, busy: false, job: null, doc: null };

async function loadResumes() {
  apply.resumes = await desk.list();
  return apply.resumes;
}

function mainResume() {
  const r = apply.resumes;
  return r && r.resumes.find((x) => x.id === r.main);
}

async function resumeText(id) {
  id ||= apply.resumes?.main;
  apply.texts[id] ??= await desk.text(id);
  return apply.texts[id];
}

async function checkMatch(job, posting = "") {
  const text = await resumeText();
  return ResumeTools.match(text, job.title || "", posting || job.description || "", job.tags || []);
}

/** Puts a file in the person's Downloads folder. */
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ------------------------------------------------------------------ job details section

/** Called by renderDetail() in app.js after it draws a job. */
function renderApply(job) {
  const box = $("applyBox");
  if (!box || !apply.resumes) return;
  const main = mainResume();
  if (!main) {
    box.innerHTML = `<div class="apply-box"><h3>Apply with your resume</h3>
      <p class="muted">Add your resume to see how well it matches this job and to make a version tailored to it.</p>
      <div class="row"><button type="button" class="btn primary" data-apply="open-resumes">Add my resume</button></div></div>`;
    return;
  }
  const m = apply.match[job.key];
  let matchHtml;
  if (!m) matchHtml = `<p class="muted"><span class="spinner"></span>Checking your resume against this ad…</p>`;
  else if (m.error) matchHtml = `<p class="muted">${esc(m.error)}</p>`;
  else {
    matchHtml = `<div><b>${m.score}%</b> of the key words in this ad are on your resume</div>
      <div class="meter" role="img" aria-label="${m.score}% match"><span style="width:${m.score}%"></span></div>
      <div class="kw">${m.found.map((t) => `<span class="chip yes">✓ ${esc(t)}</span>`).join("")}${m.missing.map((t) => `<span class="chip no">${esc(t)}</span>`).join("")}</div>
      <p class="muted">Red words aren't on your resume. Only add the ones that are true for you.
        ${m.fromPaste ? "Checked against the description you pasted." : "Checked against the short preview of the ad. Paste the full ad in “Tailor my resume” for a better check."}</p>`;
  }
  const versions = apply.versions[job.key] || [];
  box.innerHTML = `<div class="apply-box">
    <h3>Your resume for this job</h3>
    ${matchHtml}
    <div class="row">
      <button type="button" class="btn primary" data-apply="tailor">Tailor my resume…</button>
      <button type="button" class="btn" data-apply="download" data-id="${esc(main.id)}" title="${esc(main.filename)}">Download my resume</button>
    </div>
    ${versions.length ? `<div><b>Made for this job</b><ul class="versions">${versions.map(versionItem).join("")}</ul></div>` : ""}
  </div>`;
}

function versionItem(v) {
  const when = new Date(v.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const id = esc(v.id);
  return `<li>${esc(when)}:
    <button type="button" class="link" data-apply="view" data-id="${id}">resume</button> ·
    <button type="button" class="link" data-apply="word" data-id="${id}">Word</button> ·
    <button type="button" class="link" data-apply="view" data-id="${id}" data-letter="1">cover letter</button> ·
    <button type="button" class="link" data-apply="word" data-id="${id}" data-letter="1">Word</button></li>`;
}

/** Called by selectJob() in app.js. */
async function onJobSelected(key) {
  if (!key) return;
  try {
    if (!apply.resumes) await loadResumes();
    const job = state.data.jobs.find((j) => j.key === key);
    const tasks = [desk.versions(key).then((v) => { apply.versions[key] = v; })];
    if (job && mainResume() && !apply.match[key]) {
      tasks.push(checkMatch(job).then((m) => { apply.match[key] = m; }, (e) => { apply.match[key] = { error: e.message }; }));
    }
    await Promise.all(tasks);
  } catch (e) {
    apply.match[key] = { error: e.message };
  }
  if (state.selected === key) renderDetail();
}

// ------------------------------------------------------------------ "My resume" window

async function openResumes() {
  showResumeError("");
  try {
    await loadResumes();
  } catch (e) {
    showResumeError(e.message);
  }
  renderResumeList();
  $("resumeDialog").showModal();
}

function showResumeError(message) {
  $("resumeError").textContent = message;
  $("resumeError").hidden = !message;
}

function renderResumeList() {
  const r = apply.resumes || { resumes: [] };
  $("resumeList").innerHTML = r.resumes.length ? r.resumes.map((x) => {
    const added = new Date(x.uploaded_at).toLocaleDateString(undefined, { dateStyle: "medium" });
    const isMain = x.id === r.main;
    return `<li>
      <span class="rname">${esc(x.filename)}<small>Added ${esc(added)}</small></span>
      ${isMain ? `<span class="chip main">Main</span>` : `<button type="button" class="btn small" data-apply="main" data-id="${esc(x.id)}">Use as main</button>`}
      <button type="button" class="btn small" data-apply="download" data-id="${esc(x.id)}">Download</button>
      <button type="button" class="btn small ghost" data-apply="delete" data-id="${esc(x.id)}">Delete</button>
    </li>`;
  }).join("") : `<li class="none">No resume yet. Add one below.</li>`;
}

async function resumeChanged(promise) {
  showResumeError("");
  try {
    apply.resumes = await promise;
    apply.match = {};  // scores depend on which resume is main
  } catch (e) {
    showResumeError(e.message);
  }
  renderResumeList();
  if (state.selected) onJobSelected(state.selected);
}

function uploadResume() {
  const file = $("resumeFile").files[0];
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) {
    showResumeError("That file is over 5 MB. Resumes are usually much smaller; try saving it again.");
    return;
  }
  $("resumeList").insertAdjacentHTML("afterbegin", `<li class="none"><span class="spinner"></span>Reading ${esc(file.name)}…</li>`);
  resumeChanged(desk.add(file));
  $("resumeFile").value = "";
}

function savePastedResume() {
  const text = $("resumeText").value.trim();
  if (text.length < 40) {
    showResumeError("Paste the whole resume first.");
    return;
  }
  resumeChanged(desk.addText(text));
  $("resumeText").value = "";
}

async function downloadResume(id) {
  try {
    const { blob, filename } = await desk.file(id);
    saveBlob(blob, filename);
  } catch (e) {
    alert(e.message);
  }
}

// ------------------------------------------------------------------ "Tailor my resume" window

function openTailor() {
  const job = state.data.jobs.find((j) => j.key === state.selected);
  if (!job) return;
  apply.job = job;
  $("tailorTitle").textContent = `Tailor my resume: ${job.title}`;
  renderTailorForm(job.description || "");
  $("tailorDialog").showModal();
}

function keySetup(hasKey) {
  const link = `<a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>`;
  if (!STATIC) {
    return hasKey ? "" : `<div class="callout warn"><h4>One-time setup: an Anthropic API key</h4>
      Tailoring here uses Claude, Anthropic's AI. Create a key at ${link}
      (pay as you go: roughly 10–30¢ per tailored resume), then paste it in Settings.
      <div class="row"><button type="button" class="btn" data-apply="settings">Open Settings</button></div></div>`;
  }
  if (hasKey) {
    return `<p class="muted">Using the Anthropic API key saved in this browser.
      <button type="button" class="link" data-apply="forget-key">Remove it</button></p>`;
  }
  return `<div class="callout warn"><h4>One-time setup: an Anthropic API key</h4>
    Tailoring here uses Claude, Anthropic's AI. Create a key at ${link}
    (pay as you go: roughly 10–30¢ per tailored resume) and paste it below. It's saved only in this browser
    on this device and only ever sent to Anthropic.
    <div class="row key-row"><input id="tailorKey" type="password" placeholder="sk-ant-…" autocomplete="off" aria-label="Anthropic API key">
      <button type="button" class="btn" data-apply="save-key">Save key</button></div></div>`;
}

function renderTailorForm(posting, error = "") {
  const job = apply.job;
  const hasKey = desk.hasKey();
  const resumes = apply.resumes?.resumes || [];
  $("tailorBody").innerHTML = `<div class="tailor-form">
    <p class="hint">Claude rewords and reorders what's <b>already on your resume</b> to fit this job at
      ${esc(job.company || "this employer")}, and writes a matching cover letter. It won't add any job, skill, license or
      degree you don't list. Anything the job asks for that your resume doesn't show is listed separately for you.</p>
    ${keySetup(hasKey)}
    <label class="field"><span>Job description</span>
      <textarea id="tailorPosting" rows="10">${esc(posting)}</textarea>
      <small class="muted">The job list only has a short preview. For the best result,
        <a href="${esc(safeUrl(job.url))}" target="_blank" rel="noopener noreferrer">open the job posting</a>,
        copy the whole description and paste it here.</small>
    </label>
    ${resumes.length > 1 ? `<label class="field"><span>Resume to start from</span><select id="tailorResume">${resumes.map((r) =>
      `<option value="${esc(r.id)}" ${r.id === apply.resumes.main ? "selected" : ""}>${esc(r.filename)}</option>`).join("")}</select></label>` : ""}
    <p class="form-error" ${error ? "" : "hidden"}>${esc(error)}</p>
    <div class="row">
      <button type="button" class="btn primary" data-apply="run" ${hasKey ? "" : "disabled"}>Tailor my resume</button>
      <button type="button" class="btn" data-apply="rematch">Re-check match with this description</button>
    </div>
    <div class="callout"><h4>Or use your Claude.ai account</h4>
      With a Claude plan you can do this in a chat at claude.ai instead, without an API key. This copies the same
      instructions, your resume and the job description; paste them into a new chat.
      <div class="row"><button type="button" class="btn" data-apply="copy-claude">Copy for Claude.ai</button>
        <a class="btn" href="https://claude.ai/new" target="_blank" rel="noopener">Open Claude.ai</a></div></div>
  </div>`;
}

function tailorError(message) {
  const el = document.querySelector("#tailorBody .form-error");
  el.textContent = message;
  el.hidden = !message;
}

async function runTailor() {
  if (apply.busy) return;
  const posting = $("tailorPosting").value;
  const resume_id = $("tailorResume")?.value;
  apply.busy = true;
  $("tailorBody").innerHTML = `<p><span class="spinner"></span>Claude is tailoring your resume. This usually takes a minute or two.</p>`;
  try {
    const record = await desk.tailor({ job: apply.job, posting, resume_id });
    apply.versions[apply.job.key] = [record, ...(apply.versions[apply.job.key] || [])];
    renderTailorResult(record);
  } catch (e) {
    renderTailorForm(posting, e.message);
  } finally {
    apply.busy = false;
    if (state.selected) renderDetail();
  }
}

async function rematch() {
  const posting = $("tailorPosting").value;
  const key = apply.job.key;
  try {
    apply.match[key] = { ...(await checkMatch(apply.job, posting)), fromPaste: true };
  } catch (e) {
    apply.match[key] = { error: e.message };
  }
  $("tailorDialog").close();
  renderDetail();
}

async function copyForClaudeAi(button) {
  const posting = $("tailorPosting").value.trim();
  if (posting.length < 80) return tailorError("Paste the full job description first.");
  try {
    const [cfg, text] = await Promise.all([ResumeTools.tailorSettings(), resumeText($("tailorResume")?.value)]);
    const message = `${cfg.system}\n\n${ResumeTools.tailorPrompt(cfg, text, apply.job, posting)}\n\n` +
      "Reply in four parts: the tailored resume, ready to copy into a document; the cover letter; the gaps; " +
      "and what you changed. Then offer to make the resume and cover letter into Word documents.";
    await navigator.clipboard.writeText(message);
    tailorError("");
    button.textContent = "Copied. Paste it into a new chat at claude.ai";
  } catch (e) {
    tailorError(e.name === "NotAllowedError" ? "This browser didn't allow copying. Try again." : e.message);
  }
}

function renderTailorResult(rec) {
  const r = rec.resume;
  const id = esc(rec.id);
  const list = (items) => `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  $("tailorBody").innerHTML = `<div class="tailor-result">
    <p><b>Done.</b> <span class="muted">This one cost about $${Number(rec.cost_usd).toFixed(2)}.</span></p>
    <div class="callout warn"><h4>Before you send it</h4>
      ${r.gaps?.length ? `The job asks for things your resume doesn't show. Don't claim them unless they're true:${list(r.gaps)}` : ""}
      Read the tailored resume once. You're the one sending it, so make sure every line is right.</div>
    <div class="row">
      <button type="button" class="btn primary" data-apply="view" data-id="${id}">Open resume (save as PDF)</button>
      <button type="button" class="btn" data-apply="word" data-id="${id}">Resume as Word</button>
      <button type="button" class="btn" data-apply="view" data-id="${id}" data-letter="1">Open cover letter</button>
      <button type="button" class="btn" data-apply="word" data-id="${id}" data-letter="1">Cover letter as Word</button>
    </div>
    ${r.changes?.length ? `<div class="callout"><h4>What Claude changed</h4>${list(r.changes)}</div>` : ""}
    <div><b>Cover letter</b> <button type="button" class="btn small" data-apply="copy-letter">Copy</button>
      <div class="letter-preview" id="letterText">${esc(r.cover_letter || "")}</div></div>
    <div class="row">
      <a class="btn" href="${esc(safeUrl(apply.job.url))}" target="_blank" rel="noopener noreferrer">Go to the job posting to apply</a>
      <button type="button" class="btn" data-apply="applied">Mark as applied</button>
    </div>
  </div>`;
}

// ------------------------------------------------------------------ the tailored files

function findVersion(id) {
  return Object.values(apply.versions).flat().find((v) => v.id === id);
}

function viewDoc(rec, letter) {
  apply.doc = { rec, letter };
  $("docTitle").textContent = `${letter ? "Cover letter" : "Resume"} for ${rec.job.company || rec.job.title}`;
  $("docPaper").innerHTML = ResumeTools.resumeHtml(rec.resume, letter);
  $("docDialog").showModal();
}

function wordDoc(rec, letter) {
  const bytes = letter ? ResumeTools.coverLetterDocx(rec.resume) : ResumeTools.resumeDocx(rec.resume);
  saveBlob(new Blob([bytes], { type: ResumeTools.DOCX_TYPE }), `${ResumeTools.fileName(rec, letter ? "Cover Letter" : "Resume")}.docx`);
}

/** Prints only the open resume or letter; the print window's "Save as PDF" makes the PDF. */
function printDoc() {
  const { rec, letter } = apply.doc;
  const title = document.title;
  $("printArea").innerHTML = $("docPaper").innerHTML;
  document.title = ResumeTools.fileName(rec, letter ? "Cover Letter" : "Resume");  // the PDF's suggested file name
  document.body.classList.add("printing");
  const done = () => {
    document.body.classList.remove("printing");
    document.title = title;
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

// ------------------------------------------------------------------ events

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-apply]");
  if (!el) return;
  const action = el.dataset.apply;
  const id = el.dataset.id;
  if (action === "open-resumes") openResumes();
  if (action === "tailor") openTailor();
  if (action === "run") runTailor();
  if (action === "rematch") rematch();
  if (action === "copy-claude") copyForClaudeAi(el);
  if (action === "main") resumeChanged(desk.setMain(id));
  if (action === "download") downloadResume(id);
  if (action === "delete" && confirm("Delete this resume from Job Radar? Tailored versions you made stay.")) {
    resumeChanged(desk.remove(id));
  }
  if (action === "view" || action === "word") {
    const rec = findVersion(id);
    if (rec) (action === "view" ? viewDoc : wordDoc)(rec, !!el.dataset.letter);
  }
  if (action === "settings") { $("tailorDialog").close(); openSettings(); }
  if (action === "save-key" || action === "forget-key") {
    const posting = $("tailorPosting").value;
    try {
      if (action === "save-key") desk.setKey($("tailorKey").value);
      else desk.clearKey();
      renderTailorForm(posting);
    } catch (err) {
      tailorError(err.message);
    }
  }
  if (action === "copy-letter") {
    navigator.clipboard?.writeText($("letterText").textContent).then(() => { el.textContent = "Copied"; });
  }
  if (action === "applied") {
    const job = state.data.jobs.find((j) => j.key === apply.job.key);
    if (job && job.status !== "applied") setStatus(job, "applied");
    el.textContent = "Marked as applied";
    el.disabled = true;
  }
});

$("resumeHint").innerHTML = STATIC
  ? `Your resumes are kept only <b>in this browser on this device</b>. They're never uploaded to this website.
     Keep your original file too: if you clear this browser's data, add it again here.`
  : "Your resumes are stored only on this computer.";
$("resumeBtn").addEventListener("click", openResumes);
$("resumeFile").addEventListener("change", uploadResume);
$("saveResumeTextBtn").addEventListener("click", savePastedResume);
$("docPrintBtn").addEventListener("click", printDoc);
$("docWordBtn").addEventListener("click", () => wordDoc(apply.doc.rec, apply.doc.letter));
loadResumes().catch(() => {});
