"use strict";
// The website's resume desk. Your resumes and tailored versions are kept in this browser
// (IndexedDB) and never uploaded to the website. When you tailor, your resume and the job ad go
// straight from this browser to Anthropic, with the API key you saved in this browser.
// apply.js uses this on the website; the program uses its own server instead (ServerDesk in apply.js).
// Uses `store` from app.js and ResumeTools from resume-tools.js.

const LocalDesk = (() => {
  const MAX_BYTES = 5 * 1024 * 1024;
  const KEY_RE = /^sk-ant-[A-Za-z0-9_-]{10,300}$/;
  const TYPES = {
    ".pdf": "application/pdf",
    ".docx": ResumeTools.DOCX_TYPE,
    ".txt": "text/plain",
    ".md": "text/plain",
  };
  const vendor = (file) => new URL(`vendor/${file}`, document.baseURI).href;

  // ---------------------------------------------------------------- storage

  let opening;
  function db() {
    opening ||= new Promise((resolve, reject) => {
      const req = indexedDB.open("job-radar", 1);
      req.onupgradeneeded = () => {
        req.result.createObjectStore("resumes", { keyPath: "id" });
        req.result.createObjectStore("tailored", { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => {
        opening = null;
        reject(new Error("This browser won't let the website save your resume. Private or incognito windows often block it."));
      };
    });
    return opening;
  }

  async function run(name, mode, fn) {
    const d = await db();
    return new Promise((resolve, reject) => {
      const t = d.transaction(name, mode);
      const req = fn(t.objectStore(name));
      t.oncomplete = () => resolve(req.result);
      t.onerror = t.onabort = () => reject(new Error(t.error?.name === "QuotaExceededError"
        ? "This browser is out of storage space for the website." : "Couldn't save that in this browser."));
    });
  }
  const getAll = (name) => run(name, "readonly", (s) => s.getAll());
  const get = (name, id) => run(name, "readonly", (s) => s.get(id));
  const put = (name, value) => run(name, "readwrite", (s) => s.put(value));
  const drop = (name, id) => run(name, "readwrite", (s) => s.delete(id));

  const newId = (bytes) => Array.from(crypto.getRandomValues(new Uint8Array(bytes)), (b) => b.toString(16).padStart(2, "0")).join("");

  // ---------------------------------------------------------------- reading files

  async function pdfText(bytes) {
    let lib;
    try {
      lib = await import(vendor("pdf.min.mjs"));
    } catch {
      throw new Error("PDF reading isn't available right now. Upload the Word version or paste the text instead.");
    }
    lib.GlobalWorkerOptions.workerSrc = vendor("pdf.worker.min.mjs");
    const task = lib.getDocument({ data: bytes.slice(), isEvalSupported: false });
    try {
      const pdf = await task.promise;
      const pages = [];
      for (let n = 1; n <= pdf.numPages; n++) {
        const content = await (await pdf.getPage(n)).getTextContent();
        pages.push(content.items.map((item) => (item.str ?? "") + (item.hasEOL ? "\n" : "")).join(""));
      }
      return pages.join("\n");
    } catch (e) {
      throw new Error(e?.name === "PasswordException" ? "That PDF is password-protected. Save a copy without a password and try again."
        : "That PDF couldn't be read.");
    } finally {
      task.destroy().catch(() => {});
    }
  }

  async function extractText(filename, bytes) {
    const ext = (filename.match(/\.[^.]+$/)?.[0] || "").toLowerCase();
    let text;
    if (ext === ".pdf") text = await pdfText(bytes);
    else if (ext === ".docx") text = await ResumeTools.docxText(bytes);
    else if (ext === ".txt" || ext === ".md") text = new TextDecoder().decode(bytes);
    else if (ext === ".doc") throw new Error("Old .doc files can't be read. In Word, use File → Save As → Word Document (.docx).");
    else throw new Error("Upload a PDF, Word (.docx) or text file.");
    text = text.replace(/\r\n/g, "\n").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
    if (text.length < 40) {
      throw new Error("No text could be read from that file. If it's a scanned picture, upload the Word version or paste the text instead.");
    }
    return text;
  }

  // ---------------------------------------------------------------- resumes

  async function list() {
    const rows = await getAll("resumes");
    rows.sort((a, b) => (a.uploaded_at < b.uploaded_at ? 1 : -1));
    let main = store.get("resume-main", null);
    if (!rows.some((r) => r.id === main)) main = rows[0]?.id || null;
    return { main, resumes: rows.map(({ data, text, ...entry }) => entry) };
  }

  async function save(filename, bytes) {
    filename = (filename.split(/[\\/]/).pop() || "resume.txt").slice(0, 120);
    if (bytes.length > MAX_BYTES) throw new Error("That file is over 5 MB. Resumes are usually much smaller; try saving it again.");
    const text = await extractText(filename, bytes);
    const ext = (filename.match(/\.[^.]+$/)?.[0] || "").toLowerCase();
    const entry = { id: newId(6), filename, ext, uploaded_at: new Date().toISOString(), chars: text.length, preview: text.slice(0, 300) };
    await put("resumes", { ...entry, text, data: bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) });
    if (!(await list()).resumes.some((r) => r.id === store.get("resume-main", null))) store.set("resume-main", entry.id);
    navigator.storage?.persist?.().catch(() => {});  // ask the browser not to clear it when space runs low
    return list();
  }

  async function resume(id) {
    const row = id && (await get("resumes", id));
    if (!row) throw new Error(id ? "Unknown resume." : "Add your resume first (My resume, top right).");
    return row;
  }

  // ---------------------------------------------------------------- tailoring with Claude

  function friendly(e, Anthropic) {
    if (e instanceof Anthropic.AuthenticationError) return "Anthropic didn't accept the API key. Check it and save it again.";
    if (e instanceof Anthropic.PermissionDeniedError) return "This Anthropic API key isn't allowed to use Claude. Check your Anthropic account.";
    if (e instanceof Anthropic.RateLimitError) return "Too many requests to Claude right now. Wait a minute and try again.";
    if (e instanceof Anthropic.BadRequestError) return `Claude couldn't take this request: ${e.error?.error?.message || e.message}`;
    if (e instanceof Anthropic.APIConnectionError) return "Couldn't reach Anthropic. Check your internet connection.";
    if (e instanceof Anthropic.APIError && e.status >= 500) return "Claude is busy or having trouble. Try again in a minute.";
    if (e instanceof Anthropic.APIError) return `Claude returned an error (${e.status}): ${e.message}`;
    return e.message || String(e);
  }

  async function tailor({ job, posting, resume_id }) {
    const apiKey = store.get("anthropic-key", "");
    if (!apiKey) throw new Error("Save your Anthropic API key first.");
    posting = String(posting || "").trim();
    if (posting.length < 80) throw new Error("Paste the full job description first. The more of the ad Claude sees, the better the result.");
    const cfg = await ResumeTools.tailorSettings();
    const row = await resume(resume_id || (await list()).main);
    let Anthropic;
    try {
      ({ default: Anthropic } = await import(vendor("anthropic-sdk.mjs")));
    } catch {
      throw new Error("Resume tailoring isn't available on this website right now.");
    }
    // The key is the person's own and stays in their browser, so calling Anthropic from the page is intended here.
    const client = new Anthropic({ apiKey, dangerouslyAllowBrowser: true, timeout: 300_000, maxRetries: 2 });
    let response;
    try {
      response = await client.beta.messages.create({
        ...cfg.request,
        system: cfg.system,
        messages: [{ role: "user", content: ResumeTools.tailorPrompt(cfg, row.text, job, posting) }],
      });
    } catch (e) {
      throw new Error(friendly(e, Anthropic));
    }
    if (response.stop_reason === "refusal") throw new Error("Claude declined to tailor this one. Try again, or edit the job description you pasted.");
    if (response.stop_reason === "max_tokens") throw new Error("Claude's answer was cut off. Try a shorter job description.");
    let data;
    try {
      data = JSON.parse(response.content.find((b) => b.type === "text")?.text || "");
    } catch {
      throw new Error("Claude's answer couldn't be read. Try again.");
    }
    const { input_tokens, output_tokens } = response.usage;
    const record = {
      id: newId(8),
      created_at: new Date().toISOString(),
      job: Object.fromEntries(["key", "title", "company", "location", "url"].map((k) => [k, job[k] || ""])),
      resume_id: row.id,
      resume_filename: row.filename,
      posting,
      resume: data,
      model: response.model,
      cost_usd: Math.round((input_tokens * cfg.prices.input + output_tokens * cfg.prices.output) / 1e3) / 1e3,
      usage: { input_tokens, output_tokens },
    };
    await put("tailored", record);
    return record;
  }

  return {
    list,
    add: async (file) => save(file.name, new Uint8Array(await file.arrayBuffer())),
    addText: (text) => save("Pasted resume.txt", new TextEncoder().encode(text)),
    setMain: async (id) => { await resume(id); store.set("resume-main", id); return list(); },
    remove: async (id) => { await drop("resumes", id); return list(); },
    text: async (id) => (await resume(id)).text,
    file: async (id) => {
      const row = await resume(id);
      return { blob: new Blob([row.data], { type: TYPES[row.ext] || "application/octet-stream" }), filename: row.filename };
    },
    versions: async (jobKey) => (await getAll("tailored")).filter((r) => r.job.key === jobKey)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    tailor,
    hasKey: () => !!store.get("anthropic-key", ""),
    setKey(key) {
      key = String(key || "").trim();
      if (!KEY_RE.test(key)) throw new Error("That doesn't look like an Anthropic API key. It starts with sk-ant-.");
      store.set("anthropic-key", key);
    },
    clearKey: () => store.set("anthropic-key", ""),
  };
})();
