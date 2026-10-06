"use strict";
// Applying for a job (program only): your stored resumes, the free match check, and AI tailoring.
// Uses helpers from app.js ($, esc, api, state, STATIC, renderDetail, setStatus, openSettings).

const apply = { resumes: null, match: {}, versions: {}, busy: false, job: null };

async function loadResumes() {
  apply.resumes = await api("/api/resumes");
  return apply.resumes;
}

function mainResume() {
  const r = apply.resumes;
  return r && r.resumes.find((x) => x.id === r.main);
}

// ------------------------------------------------------------------ job details section

/** Called by renderDetail() in app.js after it draws a job. */
function renderApply(job) {
  const box = $("applyBox");
  if (!box || STATIC || !apply.resumes) return;
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
      <a class="btn" href="/api/resumes/${esc(main.id)}/download" title="${esc(main.filename)}">Download my resume</a>
    </div>
    ${versions.length ? `<div><b>Made for this job</b><ul class="versions">${versions.map(versionItem).join("")}</ul></div>` : ""}
  </div>`;
}

function versionItem(v) {
  const when = new Date(v.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  const id = esc(v.id);
  return `<li>${esc(when)}:
    <a href="/tailored/${id}" target="_blank" rel="noopener">resume</a> ·
    <a href="/tailored/${id}/resume.docx">Word</a> ·
    <a href="/tailored/${id}/letter" target="_blank" rel="noopener">cover letter</a> ·
    <a href="/tailored/${id}/cover-letter.docx">Word</a></li>`;
}

/** Called by selectJob() in app.js. */
async function onJobSelected(key) {
  if (STATIC || !key) return;
  try {
    if (!apply.resumes) await loadResumes();
    const tasks = [api(`/api/tailored?key=${encodeURIComponent(key)}`).then((v) => { apply.versions[key] = v; })];
    if (mainResume() && !apply.match[key]) {
      tasks.push(api("/api/match", { key }).then((m) => { apply.match[key] = m; })
        .catch((e) => { apply.match[key] = { error: e.message }; }));
    }
    await Promise.all(tasks);
  } catch (e) {
    apply.match[key] = { error: e.message };
  }
  if (state.selected === key) renderDetail();
}

// ------------------------------------------------------------------ "My resume" window

async function openResumes() {
  $("resumeError").hidden = true;
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
      <a class="btn small" href="/api/resumes/${esc(x.id)}/download">Download</a>
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
  const reader = new FileReader();
  reader.onload = () => {
    const data = String(reader.result).split(",")[1] || "";
    $("resumeList").insertAdjacentHTML("afterbegin", `<li class="none"><span class="spinner"></span>Reading ${esc(file.name)}…</li>`);
    resumeChanged(api("/api/resumes", { filename: file.name, data }));
    $("resumeFile").value = "";
  };
  reader.onerror = () => showResumeError("That file couldn't be read.");
  reader.readAsDataURL(file);
}

function savePastedResume() {
  const text = $("resumeText").value.trim();
  if (text.length < 40) {
    showResumeError("Paste the whole resume first.");
    return;
  }
  resumeChanged(api("/api/resumes", { text, name: "Pasted resume" }));
  $("resumeText").value = "";
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

function renderTailorForm(posting, error = "") {
  const job = apply.job;
  const hasKey = state.data.config.anthropic?.has_key;
  const resumes = apply.resumes?.resumes || [];
  $("tailorBody").innerHTML = `<div class="tailor-form">
    <p class="hint">Claude rewords and reorders what's <b>already on your resume</b> to fit this job at
      ${esc(job.company || "this employer")}, and writes a matching cover letter. It won't add any job, skill, license or
      degree you don't list. Anything the job asks for that your resume doesn't show is listed separately for you.</p>
    ${hasKey ? "" : `<div class="callout warn"><h4>One-time setup: an Anthropic API key</h4>
      Tailoring uses Claude, Anthropic's AI. Create a key at <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>
      (pay as you go: roughly 10–30¢ per tailored resume), then paste it in Settings.
      <div class="row" style="margin-top:8px"><button type="button" class="btn" data-apply="settings">Open Settings</button></div></div>`}
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
  </div>`;
}

async function runTailor() {
  if (apply.busy) return;
  const posting = $("tailorPosting").value;
  const resume_id = $("tailorResume")?.value;
  apply.busy = true;
  $("tailorBody").innerHTML = `<p><span class="spinner"></span>Claude is tailoring your resume. This usually takes a minute or two.</p>`;
  try {
    const record = await api("/api/tailor", { key: apply.job.key, posting, resume_id });
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
    apply.match[key] = { ...(await api("/api/match", { key, posting })), fromPaste: true };
  } catch (e) {
    apply.match[key] = { error: e.message };
  }
  $("tailorDialog").close();
  renderDetail();
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
      <a class="btn primary" href="/tailored/${id}" target="_blank" rel="noopener">Open resume (save as PDF)</a>
      <a class="btn" href="/tailored/${id}/resume.docx">Resume as Word</a>
      <a class="btn" href="/tailored/${id}/letter" target="_blank" rel="noopener">Open cover letter</a>
      <a class="btn" href="/tailored/${id}/cover-letter.docx">Cover letter as Word</a>
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

// ------------------------------------------------------------------ events

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-apply]");
  if (!el) return;
  const action = el.dataset.apply;
  if (action === "open-resumes") openResumes();
  if (action === "tailor") openTailor();
  if (action === "run") runTailor();
  if (action === "rematch") rematch();
  if (action === "main") resumeChanged(api(`/api/resumes/${el.dataset.id}/main`, {}));
  if (action === "delete" && confirm("Delete this resume from Job Radar? Tailored versions you made stay.")) {
    resumeChanged(api(`/api/resumes/${el.dataset.id}/delete`, {}));
  }
  if (action === "settings") { $("tailorDialog").close(); openSettings(); }
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

if (!STATIC) {
  $("resumeBtn").addEventListener("click", openResumes);
  $("resumeFile").addEventListener("change", uploadResume);
  $("saveResumeTextBtn").addEventListener("click", savePastedResume);
  loadResumes().catch(() => {});
}
