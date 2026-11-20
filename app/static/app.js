"use strict";

// Course Converter page.
// Security: everything from the server (titles, messages, course JSON) is shown
// with textContent, never as HTML, because it comes from the LLM and the
// uploaded document. The access code and API key stay in memory only.

const POLL_MS = 2000;
const MAX_POLL_FAILURES = 5;
const PREVIEW_CHARS = 200000; // keeps the page responsive for large courses

const $ = (id) => document.getElementById(id);

let sampleFile = null;
let downloadUrl = null;

function headers() {
  const result = { "X-Access-Code": $("access-code").value.trim() };
  const apiKey = $("api-key").value.trim();
  if (apiKey) {
    result["X-API-Key"] = apiKey;
  }
  return result;
}

function showStatus(text, isError) {
  $("status").hidden = false;
  $("status-text").textContent = text;
  $("status-text").classList.toggle("error", Boolean(isError));
}

async function errorMessage(response) {
  try {
    const body = await response.json();
    return body.error || `Request failed (${response.status}).`;
  } catch {
    return `Request failed (${response.status}).`;
  }
}

function chosenFile() {
  const picked = $("file").files[0];
  return picked || sampleFile;
}

function buildForm(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("provider", $("provider").value);
  if (document.querySelector('input[name="size"]:checked').value === "custom") {
    form.append("modules", $("modules").value);
    form.append("lessons", $("lessons").value);
  }
  return form;
}

async function useSample() {
  const response = await fetch("/sample/python-basics.txt");
  if (!response.ok) {
    $("file-note").textContent = "The sample document could not be loaded.";
    return;
  }
  sampleFile = new File([await response.blob()], "python-basics.txt", { type: "text/plain" });
  $("file").value = "";
  $("file-note").textContent = "Using the sample document: python-basics.txt (a short Python tutorial).";
}

async function startConversion(event) {
  event.preventDefault();
  const file = chosenFile();
  if (!file) {
    showStatus("Choose a file, or use the sample document.", true);
    return;
  }
  if (!$("access-code").value.trim()) {
    showStatus("Enter the access code.", true);
    return;
  }

  $("convert").disabled = true;
  $("result").hidden = true;
  $("progress").value = 0;
  showStatus("Uploading...");

  try {
    const response = await fetch("/api/convert", {
      method: "POST",
      headers: headers(),
      body: buildForm(file),
    });
    if (!response.ok) {
      throw new Error(await errorMessage(response));
    }
    const { jobId } = await response.json();
    showStatus("Reading the document and planning the course...");
    await followJob(jobId);
  } catch (error) {
    showStatus(error.message || "The conversion could not start.", true);
  } finally {
    $("convert").disabled = false;
  }
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function followJob(jobId) {
  let failures = 0;
  for (;;) {
    await wait(POLL_MS);
    let job;
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { headers: headers() });
      if (!response.ok) {
        throw new Error(await errorMessage(response));
      }
      job = await response.json();
      failures = 0;
    } catch (error) {
      failures += 1;
      if (failures >= MAX_POLL_FAILURES) {
        throw error;
      }
      continue;
    }

    showProgress(job);
    if (job.state === "done") {
      await showResult(jobId);
      return;
    }
    if (job.state === "failed") {
      throw new Error(job.error || "The conversion failed.");
    }
  }
}

function showProgress(job) {
  if (job.total) {
    $("progress").max = job.total;
    $("progress").value = job.done;
    showStatus(`${job.done} of ${job.total} parts done. Last: ${job.label}`);
  }
}

async function showResult(jobId) {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/download`, {
    headers: headers(),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  const text = JSON.stringify(await response.json(), null, 2);
  const shown = text.length > PREVIEW_CHARS ? `${text.slice(0, PREVIEW_CHARS)}\n...` : text;

  if (downloadUrl) {
    URL.revokeObjectURL(downloadUrl);
  }
  downloadUrl = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  $("preview").textContent = shown;
  $("result").hidden = false;
  showStatus("Done. The course matches the schema.");
}

function download() {
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = "course.json";
  link.click();
}

function toggleCustomSize() {
  const custom = document.querySelector('input[name="size"]:checked').value === "custom";
  $("custom-size").hidden = !custom;
}

document.addEventListener("DOMContentLoaded", () => {
  $("convert-form").addEventListener("submit", startConversion);
  $("use-sample").addEventListener("click", useSample);
  $("download").addEventListener("click", download);
  $("file").addEventListener("change", () => {
    sampleFile = null;
    $("file-note").textContent = "";
  });
  document.querySelectorAll('input[name="size"]').forEach((radio) => {
    radio.addEventListener("change", toggleCustomSize);
  });
});
