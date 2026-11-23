"use strict";

// Course Converter page.
// Security: everything from the server (titles, messages, course JSON) is shown
// with textContent, never parsed as HTML, because it comes from the LLM and the
// uploaded document. The access code and API key stay in memory only.
// The page has three views: set up, converting, course ready.

const POLL_MS = 2000;
const MAX_POLL_FAILURES = 5;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const FILE_TYPES = [".txt", ".docx", ".pdf"];
const MINUTES_PER_LESSON = 30;
const JSON_PREVIEW_CHARS = 200000; // keeps the page responsive for large lessons

const $ = (id) => document.getElementById(id);

const state = {
  file: null,
  fileIsSample: false,
  provider: "gemini",
  size: {
    modules: { mode: "auto", value: 2, min: 1, max: 30 },
    lessons: { mode: "auto", value: 3, min: 1, max: 8 },
    hours: { mode: "auto", value: 3, min: 1, max: 32 },
  },
  preview: null, // the last /api/size answer
  previewRequest: 0,
  startedAt: 0,
  timer: null,
  course: null,
  courseText: "",
  downloadUrl: null,
};

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

/** Make an element; `text` is always set with textContent. */
function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  for (const [name, value] of Object.entries(options.attrs || {})) node.setAttribute(name, value);
  for (const child of children) if (child) node.append(child);
  return node;
}

function svgIcon(path) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  for (const [name, value] of Object.entries({
    width: "14", height: "14", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
    "stroke-width": "3", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true",
  })) svg.setAttribute(name, value);
  const line = document.createElementNS(ns, "path");
  line.setAttribute("d", path);
  svg.append(line);
  return svg;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatHours(hours) {
  return Number.isInteger(hours) ? `${hours} h` : `${hours.toFixed(1)} h`;
}

function formatSeconds(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${s % 60} s`;
}

function extensionOf(name) {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

function headers() {
  const result = { "X-Access-Code": $("access-code").value.trim() };
  const apiKey = $("api-key").value.trim();
  if (apiKey) result["X-API-Key"] = apiKey;
  return result;
}

async function errorMessage(response) {
  try {
    const body = await response.json();
    return body.error || `Request failed (${response.status}).`;
  } catch {
    return `Request failed (${response.status}).`;
  }
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function showView(name) {
  for (const view of ["setup", "progress", "result"]) {
    $(`view-${view}`).hidden = view !== name;
  }
  window.scrollTo(0, 0);
}

function setServerState(text, tone) {
  $("server-text").textContent = text;
  $("server-dot").className = `dot dot-${tone}`;
}

// ---------------------------------------------------------------------------
// 1. Document
// ---------------------------------------------------------------------------

function setFile(file, isSample) {
  hideFormError();
  if (file) {
    const ext = extensionOf(file.name);
    if (!FILE_TYPES.includes(ext)) {
      showFormError("Only .txt, .docx and .pdf files can be converted.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      showFormError("The file is larger than 10 MB.");
      return;
    }
  }
  state.file = file;
  state.fileIsSample = Boolean(file && isSample);
  $("file").value = "";
  renderFile();
  renderHint();
}

function renderFile() {
  const file = state.file;
  $("drop-zone").hidden = Boolean(file);
  $("file-card").hidden = !file;
  if (!file) return;
  $("file-type").textContent = extensionOf(file.name).slice(1).toUpperCase();
  $("file-name").textContent = file.name;
  $("file-meta").textContent = state.fileIsSample
    ? `Sample document · ${formatBytes(file.size)} · a short Python tutorial`
    : formatBytes(file.size);
}

async function useSample() {
  const response = await fetch("/sample/python-basics.txt");
  if (!response.ok) {
    showFormError("The sample document could not be loaded.");
    return;
  }
  const blob = await response.blob();
  setFile(new File([blob], "python-basics.txt", { type: "text/plain" }), true);
}

function setUpDropZone() {
  const zone = $("drop-zone");
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("dragging");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    zone.classList.remove("dragging");
    const file = event.dataTransfer.files[0];
    if (file) setFile(file, false);
  });
}

// ---------------------------------------------------------------------------
// 2. Course size. The rules live on the server (GET /api/size); the page
//    only shows what the server works out, so the two always agree.
// ---------------------------------------------------------------------------

function sizeField(name) {
  return document.querySelector(`.size-field[data-field="${name}"]`);
}

function durationLocked() {
  const { modules, lessons } = state.size;
  return modules.mode === "custom" && lessons.mode === "custom";
}

/** The size values to send: only the ones set to Choose. */
function chosenSize() {
  const { modules, lessons, hours } = state.size;
  const chosen = {};
  if (modules.mode === "custom") chosen.modules = modules.value;
  if (lessons.mode === "custom") chosen.lessons = lessons.value;
  if (hours.mode === "custom" && !durationLocked()) chosen.hours = hours.value;
  return chosen;
}

function renderSizeControls() {
  const locked = durationLocked();
  for (const [name, field] of Object.entries(state.size)) {
    const box = sizeField(name);
    const custom = field.mode === "custom" && !(name === "hours" && locked);
    for (const button of box.querySelectorAll(".segmented button")) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === (custom ? "custom" : "auto")));
      button.disabled = name === "hours" && locked;
    }
    box.querySelector(".stepper").hidden = !custom;
    box.querySelector(".auto-text").hidden = custom;
    box.querySelector("output").textContent = name === "hours" ? `${field.value} h` : String(field.value);
  }
  updateSizePreview();
}

async function updateSizePreview() {
  const request = ++state.previewRequest;
  const query = new URLSearchParams(
    Object.entries(chosenSize()).map(([key, value]) => [key, String(value)]),
  );
  let preview = null;
  let error = "";
  try {
    const response = await fetch(`/api/size?${query}`);
    if (response.ok) preview = await response.json();
    else error = await errorMessage(response);
  } catch {
    error = "The size could not be worked out: the server is not reachable.";
  }
  if (request !== state.previewRequest) return; // a newer click has already asked
  state.preview = preview;
  renderSizeTexts(error);
  renderHint();
}

function renderSizeTexts(error) {
  const preview = state.preview;
  const { hours } = state.size;
  const hoursChosen = hours.mode === "custom" && !durationLocked();
  const fit = hoursChosen ? `, to fit ${hours.value} h` : "";

  const modulesText = preview && preview.modules !== null
    ? `Automatic: ${preview.modules} module${preview.modules === 1 ? "" : "s"}${fit}.`
    : "Automatic: from the document's length.";
  const lessonsText = preview && preview.lessons !== null
    ? `Automatic: ${preview.lessons} per module${fit}.`
    : "Automatic: from the document's length (up to 8).";
  let hoursText = `Automatic: about ${MINUTES_PER_LESSON} min per lesson, from the document's length.`;
  if (durationLocked() && preview && preview.hours !== null) {
    hoursText = `Set by your choices: ${preview.totalLessons} lessons × ~${MINUTES_PER_LESSON} min = ${formatHours(preview.hours)}.`;
  } else if (preview && preview.hours !== null) {
    hoursText = `Automatic: about ${formatHours(preview.hours)} (${preview.totalLessons} lessons × ~${MINUTES_PER_LESSON} min).`;
  }

  sizeField("modules").querySelector(".auto-text").textContent = modulesText;
  sizeField("lessons").querySelector(".auto-text").textContent = lessonsText;
  sizeField("hours").querySelector(".auto-text").textContent = hoursText;

  const chips = [];
  if (error) {
    chips.push(error);
  } else if (preview && preview.totalLessons !== null) {
    chips.push(`${preview.modules} × ${preview.lessons} = ${preview.totalLessons} lessons`);
    chips.push(`about ${formatHours(preview.hours)} of learning`);
    chips.push(`about ${preview.apiCalls} AI calls · ${preview.minutes} min to convert`);
  } else {
    chips.push("Sized when the document is read. Choose a duration or both counts to see it now.");
  }
  $("size-chips").replaceChildren(...chips.map((text) => el("span", { className: "chip", text })));
}

function setUpSizeControls() {
  for (const [name, field] of Object.entries(state.size)) {
    const box = sizeField(name);
    for (const button of box.querySelectorAll(".segmented button")) {
      button.addEventListener("click", () => {
        field.mode = button.dataset.mode;
        renderSizeControls();
      });
    }
    for (const button of box.querySelectorAll(".stepper button")) {
      button.addEventListener("click", () => {
        const next = field.value + Number(button.dataset.step);
        field.value = Math.min(field.max, Math.max(field.min, next));
        renderSizeControls();
      });
    }
  }
}

// ---------------------------------------------------------------------------
// 3. Access, and starting a conversion
// ---------------------------------------------------------------------------

function setUpAccess() {
  for (const button of $("provider").querySelectorAll("button")) {
    button.addEventListener("click", () => {
      state.provider = button.dataset.provider;
      for (const other of $("provider").querySelectorAll("button")) {
        other.setAttribute("aria-pressed", String(other === button));
      }
    });
  }
  $("toggle-key").addEventListener("click", () => {
    const open = $("toggle-key").getAttribute("aria-expanded") !== "true";
    $("toggle-key").setAttribute("aria-expanded", String(open));
    $("key-field").hidden = !open;
    if (open) $("api-key").focus();
  });
}

function renderHint() {
  const preview = state.preview;
  $("convert").disabled = !state.file;
  if (!state.file) {
    $("convert-hint").textContent = "Choose a file first.";
    return;
  }
  const time = preview && preview.minutes !== null ? `Takes about ${preview.minutes} min to convert. ` : "";
  $("convert-hint").textContent = `${time}Keep this page open while it runs.`;
}

function showFormError(message) {
  $("form-error").textContent = message;
  $("form-error").hidden = false;
}

function hideFormError() {
  $("form-error").hidden = true;
}

function buildForm() {
  const form = new FormData();
  form.append("file", state.file, state.file.name);
  form.append("provider", state.provider);
  for (const [key, value] of Object.entries(chosenSize())) form.append(key, String(value));
  return form;
}

async function startConversion(event) {
  if (event) event.preventDefault();
  hideFormError();
  if (!state.file) {
    showFormError("Choose a file, or use the sample document.");
    return;
  }
  if (!$("access-code").value.trim()) {
    showFormError("Enter the access code: the DEMO_ACCESS_CODE value from the server's .env file.");
    $("access-code").focus();
    return;
  }

  $("convert").disabled = true;
  $("retry-job").disabled = true;
  $("convert-hint").textContent = "Uploading…";
  let jobId;
  try {
    const response = await fetch("/api/convert", { method: "POST", headers: headers(), body: buildForm() });
    if (!response.ok) throw new Error(await errorMessage(response));
    jobId = (await response.json()).jobId;
  } catch (error) {
    // Still on the set-up view, or back to it after a failed retry: inputs are kept.
    showView("setup");
    showFormError(error.message || "The conversion could not start.");
    $("convert").disabled = false;
    $("retry-job").disabled = false;
    renderHint();
    return;
  }

  beginProgressView();
  try {
    await followJob(jobId);
  } catch (error) {
    showFailure(error.message || "The conversion failed.");
  } finally {
    stopTimer();
    $("convert").disabled = false;
    $("retry-job").disabled = false;
    renderHint();
  }
}

// ---------------------------------------------------------------------------
// Converting
// ---------------------------------------------------------------------------

function beginProgressView() {
  showView("progress");
  setServerState("Converting", "run");
  $("failure").hidden = true;
  $("retry-notice").hidden = true;
  $("progress-title").textContent = "Reading the document and planning the course";
  $("progress-count").textContent = "0";
  $("progress-total").textContent = "–";
  $("bar-fill").style.width = "0%";
  $("progress-hint").textContent = "Keep this page open while it runs.";
  $("steps").replaceChildren(stepRow("active", "1", "Course outline", "working"));
  renderSummary();
  state.startedAt = Date.now();
  stopTimer();
  state.timer = setInterval(() => {
    $("elapsed").textContent = formatSeconds((Date.now() - state.startedAt) / 1000);
  }, 1000);
}

function stopTimer() {
  if (state.timer) clearInterval(state.timer);
  state.timer = null;
}

function renderSummary() {
  const chosen = chosenSize();
  const preview = state.preview;
  const describe = (key, label) => (key in chosen ? `${chosen[key]} (chosen)` : `automatic${label}`);
  const known = preview && preview.totalLessons !== null;
  const rows = [
    ["File", state.file.name],
    ["Modules", describe("modules", known ? ` → ${preview.modules}` : "")],
    ["Lessons per module", describe("lessons", known ? ` → ${preview.lessons}` : "")],
    ["Duration", "hours" in chosen ? `${chosen.hours} h (chosen)` : (known ? `about ${formatHours(preview.hours)}` : "automatic")],
    ["AI service", state.provider === "openai" ? "OpenAI" : "Gemini"],
  ];
  $("job-summary").replaceChildren(
    ...rows.flatMap(([term, value]) => [el("dt", { text: term }), el("dd", { text: value })]),
  );
  $("progress-meta").textContent = state.file.name;
}

function stepRow(kind, num, label, meta) {
  const icon = el("span", { className: "state-icon", attrs: { role: "img", "aria-label": { done: "Done", active: "In progress", waiting: "Waiting" }[kind] } });
  if (kind === "done") icon.append(svgIcon("M5 12l4 4 10-10"));
  return el("li", { className: kind }, [
    icon,
    el("span", { className: "num", text: num }),
    el("span", { className: "label", text: label }),
    meta ? el("span", { className: "meta", text: meta }) : null,
  ]);
}

function renderProgress(job) {
  const total = job.total || 0;
  const done = job.done || 0;
  const steps = job.steps || [];

  $("progress-count").textContent = String(done);
  $("progress-total").textContent = total ? String(total) : "–";
  $("progress-bar").setAttribute("aria-valuemax", String(total || 1));
  $("progress-bar").setAttribute("aria-valuenow", String(done));
  $("bar-fill").style.width = total ? `${Math.round((done / total) * 100)}%` : "0%";

  if (steps.length) {
    const last = steps[steps.length - 1].label;
    $("progress-title").textContent = done < total ? `Writing part ${done + 1} of ${total}` : "Finishing and checking the course";
    const elapsed = (Date.now() - state.startedAt) / 1000;
    const left = done ? (elapsed / done) * (total - done) : 0;
    $("progress-hint").textContent = done < total
      ? `Last finished: ${last}. About ${formatSeconds(left)} left. Keep this page open while it runs.`
      : `Last finished: ${last}.`;
  }

  const rows = steps.map((step, index) =>
    stepRow("done", `${index + 1}/${total}`, step.label, step.reused ? "already saved" : ""));
  if (total && done < total) {
    rows.push(stepRow("active", `${done + 1}/${total}`, steps.length ? "Writing the next part" : "Course outline", "working"));
    const remaining = total - done - 1;
    if (remaining > 0) rows.push(stepRow("waiting", "", `${remaining} more part${remaining === 1 ? "" : "s"}`, ""));
  } else if (!total) {
    rows.push(stepRow("active", "1", "Course outline", "working"));
  }
  $("steps").replaceChildren(...rows);

  $("retry-notice").hidden = !job.notice;
  $("retry-text").textContent = job.notice || "";
}

async function followJob(jobId) {
  let failures = 0;
  for (;;) {
    await wait(POLL_MS);
    let job;
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { headers: headers() });
      if (!response.ok) throw new Error(await errorMessage(response));
      job = await response.json();
      failures = 0;
    } catch (error) {
      failures += 1;
      if (failures >= MAX_POLL_FAILURES) throw error;
      continue;
    }

    renderProgress(job);
    if (job.state === "done") {
      await showResult(jobId);
      return;
    }
    if (job.state === "failed") throw new Error(job.error || "The conversion failed.");
  }
}

function showFailure(message) {
  setServerState("Stopped", "bad");
  $("retry-notice").hidden = true;
  $("failure-text").textContent = message;
  $("failure").hidden = false;
  $("progress-title").textContent = "The conversion stopped";
  $("progress-hint").textContent = "Press Try again to start it again with the same file and settings.";
  for (const row of $("steps").querySelectorAll(".active, .waiting")) row.remove();
  $("retry-job").focus();
}

// ---------------------------------------------------------------------------
// Course ready
// ---------------------------------------------------------------------------

async function showResult(jobId) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/download`, { headers: headers() });
  if (!response.ok) throw new Error(await errorMessage(response));
  const data = await response.json();

  state.courseText = JSON.stringify(data, null, 2);
  state.course = data && typeof data.course === "object" ? data.course : data;
  if (state.downloadUrl) URL.revokeObjectURL(state.downloadUrl);
  state.downloadUrl = URL.createObjectURL(new Blob([state.courseText], { type: "application/json" }));

  const course = state.course || {};
  const modules = Array.isArray(course.modules) ? course.modules : [];
  const lessonCount = modules.reduce((sum, m) => sum + (Array.isArray(m.lessons) ? m.lessons.length : 0), 0);
  const elapsed = formatSeconds((Date.now() - state.startedAt) / 1000);
  $("course-title").textContent = course.courseTitle || "Your course";
  $("course-stats").textContent = [
    `${modules.length} module${modules.length === 1 ? "" : "s"}`,
    `${lessonCount} lesson${lessonCount === 1 ? "" : "s"}`,
    course.totalDuration,
    "matches the course schema",
    `converted in ${elapsed}`,
  ].filter(Boolean).join(" · ");
  $("copy-status").textContent = "";

  renderOutline(modules);
  showView("result");
  setServerState("Done", "ok");
  if (lessonCount) {
    const firstModule = modules.findIndex((m) => Array.isArray(m.lessons) && m.lessons.length);
    showLesson(firstModule, 0);
  }
  $("download").focus();
}

function renderOutline(modules) {
  const parts = [];
  modules.forEach((module, m) => {
    parts.push(el("h3", {}, [
      el("span", { className: "module-meta", text: `Module ${m + 1}${module.duration ? ` · ${module.duration}` : ""}` }),
      document.createTextNode(String(module.title || `Module ${m + 1}`)),
    ]));
    const items = (Array.isArray(module.lessons) ? module.lessons : []).map((lesson, l) => {
      const button = el("button", { attrs: { type: "button", "data-module": String(m), "data-lesson": String(l), "aria-current": "false" } }, [
        el("span", { className: "lesson-num", text: `${m + 1}.${l + 1}` }),
        el("span", { text: lesson.title || `Lesson ${l + 1}` }),
      ]);
      button.addEventListener("click", () => showLesson(m, l));
      return el("li", {}, [button]);
    });
    parts.push(el("ul", {}, items));
  });
  $("outline").replaceChildren(...parts);
}

function showLesson(m, l) {
  const module = state.course.modules[m];
  const lesson = module.lessons[l] || {};
  for (const button of $("outline").querySelectorAll("button")) {
    const current = button.dataset.module === String(m) && button.dataset.lesson === String(l);
    button.setAttribute("aria-current", String(current));
  }
  $("lesson-meta").textContent = [`Lesson ${m + 1}.${l + 1}`, lesson.duration].filter(Boolean).join(" · ");
  $("lesson-title").textContent = lesson.title || `Lesson ${m + 1}.${l + 1}`;

  const quiz = Array.isArray(lesson.quiz) ? lesson.quiz : [];
  $("tab-quiz").textContent = quiz.length ? `Quiz (${quiz.length})` : "Quiz";
  $("panel-overview").replaceChildren(...overviewParts(lesson));
  $("panel-quiz").replaceChildren(...quizParts(quiz));
  $("panel-exercises").replaceChildren(...exerciseParts(lesson));
  const json = JSON.stringify(lesson, null, 2);
  $("lesson-json").textContent = json.length > JSON_PREVIEW_CHARS ? `${json.slice(0, JSON_PREVIEW_CHARS)}\n…` : json;
}

function block(title, children) {
  const kept = children.filter(Boolean);
  return kept.length ? el("div", {}, [el("h3", { text: title }), ...kept]) : null;
}

function paragraphs(text) {
  if (typeof text !== "string" || !text.trim()) return [];
  return text.split(/\n{2,}|\n/).filter((part) => part.trim()).map((part) => el("p", { text: part }));
}

function codeBlock(code) {
  return typeof code === "string" && code.trim() ? el("pre", { className: "code", text: code }) : null;
}

function overviewParts(lesson) {
  const concepts = Array.isArray(lesson.concepts) ? lesson.concepts : [];
  const takeaways = Array.isArray(lesson.keyTakeaways) ? lesson.keyTakeaways : [];
  const examples = Array.isArray(lesson.example) ? lesson.example : [];
  const parts = [
    block("Objective", paragraphs(lesson.objective)),
    block("Explanation", paragraphs(lesson.lessonExplanation)),
    concepts.length ? block("Concepts", [el("ul", { className: "tags" }, concepts.map((c) => el("li", { text: c })))]) : null,
    takeaways.length ? block("Key takeaways", [el("ul", {}, takeaways.map((t) => el("li", { text: t })))]) : null,
    examples.length ? block("Code examples", examples.map((example) => el("div", { className: "item" }, [
      el("h4", { text: example.title || "Example" }),
      codeBlock(example.code),
      ...paragraphs(example.explanation),
    ]))) : null,
  ].filter(Boolean);
  return parts.length ? parts : [el("p", { className: "empty", text: "This lesson has no overview fields." })];
}

function quizParts(quiz) {
  if (!quiz.length) return [el("p", { className: "empty", text: "This lesson has no quiz." })];
  return [el("ol", {}, quiz.map((question) => {
    const options = Array.isArray(question.options) ? question.options : [];
    const correct = Number.parseInt(question.correctAnswer, 10);
    return el("li", { className: "item" }, [
      el("p", { text: question.question }),
      el("ul", {}, options.map((option, index) => {
        const right = index === correct;
        return el("li", { className: right ? "correct" : "" }, [
          document.createTextNode(String(option)),
          right ? el("span", { text: " — correct answer" }) : null,
        ]);
      })),
      ...paragraphs(question.explanation),
    ]);
  }))];
}

// Labels for the exercise fields the schema uses; any other text field is shown too.
const EXERCISES = [
  ["interactiveExercise", "Interactive exercise"],
  ["miniChallenge", "Mini challenge"],
  ["bugHunt", "Bug hunt"],
  ["codereordering", "Code reordering"],
];
const FIELD_LABELS = {
  instruction: "Instruction", scenario: "Scenario", prompt: "Task", starterCode: "Starter code",
  expectebehavior: "Expected behaviour", buggyCode: "Code with the bug", bug: "The bug",
  fixedCode: "Fixed code", hint: "Hint", hints: "Hints", codelines: "Lines", answer: "Answer",
};

function exerciseParts(lesson) {
  const parts = EXERCISES.map(([key, title]) => {
    const value = lesson[key];
    if (!value || typeof value !== "object") return null;
    const fields = Object.entries(value).filter(([name]) => name !== "title").map(([name, field]) => {
      const label = FIELD_LABELS[name] || name;
      if (Array.isArray(field)) {
        return el("div", {}, [el("p", { className: "small muted", text: label }),
          el("ul", {}, field.map((item) => el("li", { text: typeof item === "string" ? item : JSON.stringify(item) })))]);
      }
      if (typeof field !== "string") return null;
      const isCode = /code/i.test(name);
      return el("div", {}, [el("p", { className: "small muted", text: label }), isCode ? codeBlock(field) : el("p", { text: field })]);
    });
    return block(title, [el("div", { className: "item stack-sm" }, [el("h4", { text: value.title || title }), ...fields])]);
  }).filter(Boolean);
  return parts.length ? parts : [el("p", { className: "empty", text: "This lesson has no exercises." })];
}

function setUpTabs() {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const select = (tab) => {
    for (const other of tabs) {
      const on = other === tab;
      other.setAttribute("aria-selected", String(on));
      other.tabIndex = on ? 0 : -1;
      $(other.getAttribute("aria-controls")).hidden = !on;
    }
    tab.focus();
  };
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => select(tab));
    tab.addEventListener("keydown", (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (step) {
        event.preventDefault();
        select(tabs[(index + step + tabs.length) % tabs.length]);
      }
    });
  });
}

function download() {
  const stem = state.file ? state.file.name.replace(/\.[^.]+$/, "") : "course";
  const link = el("a", { attrs: { href: state.downloadUrl, download: `${stem}-course.json` } });
  link.click();
}

async function copyCourse() {
  try {
    await navigator.clipboard.writeText(state.courseText);
    $("copy-status").textContent = "Copied the course JSON.";
  } catch {
    $("copy-status").textContent = "Copying is blocked in this browser. Use Download JSON instead.";
  }
}

function convertAnother() {
  setFile(null, false);
  showView("setup");
  setServerState("Server ready", "ok");
  $("file").focus();
}

// ---------------------------------------------------------------------------

async function checkServer() {
  try {
    const response = await fetch("/healthz");
    setServerState(response.ok ? "Server ready" : "Server problem", response.ok ? "ok" : "bad");
  } catch {
    setServerState("Server not reachable", "bad");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  $("convert-form").addEventListener("submit", startConversion);
  $("use-sample").addEventListener("click", useSample);
  $("file").addEventListener("change", () => setFile($("file").files[0] || null, false));
  $("remove-file").addEventListener("click", () => setFile(null, false));
  $("retry-job").addEventListener("click", () => startConversion());
  $("back-to-setup").addEventListener("click", () => {
    showView("setup");
    setServerState("Server ready", "ok");
  });
  $("download").addEventListener("click", download);
  $("copy").addEventListener("click", copyCourse);
  $("convert-another").addEventListener("click", convertAnother);
  setUpDropZone();
  setUpSizeControls();
  setUpAccess();
  setUpTabs();
  renderFile();
  renderSizeControls();
  renderHint();
  checkServer();
});
