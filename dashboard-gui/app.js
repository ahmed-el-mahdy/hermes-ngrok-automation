const state = {
  lastResponseText: "",
};

const els = {
  guiStatus: document.getElementById("guiStatus"),
  hermesStatus: document.getElementById("hermesStatus"),
  apiStatus: document.getElementById("apiStatus"),
  checkList: document.getElementById("checkList"),
  publicUrl: document.getElementById("publicUrl"),
  modelInput: document.getElementById("modelInput"),
  modelOptions: document.getElementById("modelOptions"),
  systemInput: document.getElementById("systemInput"),
  messageInput: document.getElementById("messageInput"),
  responseOutput: document.getElementById("responseOutput"),
  chatForm: document.getElementById("chatForm"),
  sendButton: document.getElementById("sendButton"),
  refreshButton: document.getElementById("refreshButton"),
  clearButton: document.getElementById("clearButton"),
  copyButton: document.getElementById("copyButton"),
};

function setPill(el, label, mode) {
  el.textContent = label;
  el.className = `status-pill ${mode || ""}`.trim();
}

function setChecks(checks) {
  els.checkList.innerHTML = "";
  checks.forEach((check) => {
    const item = document.createElement("li");
    item.className = check.mode || "";
    item.textContent = check.text;
    els.checkList.appendChild(item);
  });
}

async function readResponse(response) {
  const text = await response.text();
  try {
    return { text, json: JSON.parse(text) };
  } catch {
    return { text, json: null };
  }
}

function formatAssistantResponse(payload, fallbackText) {
  const message = payload?.choices?.[0]?.message?.content;
  if (message) return message.trim();
  const text = payload?.choices?.[0]?.text;
  if (text) return text.trim();
  return fallbackText || JSON.stringify(payload, null, 2);
}

async function loadModels() {
  const response = await fetch("/api/gateway/v1/models", {
    headers: { Accept: "application/json" },
  });
  const { json, text } = await readResponse(response);
  if (!response.ok) {
    throw new Error(text || `Model check failed with HTTP ${response.status}`);
  }

  const models = Array.isArray(json?.data) ? json.data : [];
  els.modelOptions.innerHTML = "";
  models
    .map((model) => model.id || model.name)
    .filter(Boolean)
    .slice(0, 80)
    .forEach((id) => {
      const option = document.createElement("option");
      option.value = id;
      els.modelOptions.appendChild(option);
    });

  return models.length;
}

async function refreshStatus() {
  els.publicUrl.textContent = window.location.href;
  const checks = [];

  try {
    const gui = await fetch("/healthz", { cache: "no-store" });
    setPill(els.guiStatus, gui.ok ? "GUI online" : "GUI warning", gui.ok ? "ok" : "warn");
    checks.push({
      text: gui.ok ? "Custom dashboard GUI is responding." : `GUI health returned HTTP ${gui.status}.`,
      mode: gui.ok ? "ok" : "warn",
    });
  } catch (error) {
    setPill(els.guiStatus, "GUI offline", "fail");
    checks.push({ text: `GUI health failed: ${error.message}`, mode: "fail" });
  }

  try {
    const hermes = await fetch("/api/health", { cache: "no-store" });
    setPill(
      els.hermesStatus,
      hermes.ok ? "Hermes healthy" : "Hermes warning",
      hermes.ok ? "ok" : "warn",
    );
    checks.push({
      text: hermes.ok
        ? "Hermes internal dashboard health is reachable through the GUI service."
        : `Hermes health returned HTTP ${hermes.status}.`,
      mode: hermes.ok ? "ok" : "warn",
    });
  } catch (error) {
    setPill(els.hermesStatus, "Hermes offline", "fail");
    checks.push({ text: `Hermes health failed: ${error.message}`, mode: "fail" });
  }

  try {
    const count = await loadModels();
    setPill(els.apiStatus, count ? `${count} models` : "API reachable", "ok");
    checks.push({
      text: count
        ? `Gateway API is reachable and returned ${count} model entries.`
        : "Gateway API is reachable; no model list was returned.",
      mode: "ok",
    });
  } catch (error) {
    setPill(els.apiStatus, "API needs check", "warn");
    checks.push({ text: `Gateway API model check: ${error.message}`, mode: "warn" });
  }

  setChecks(checks);
}

async function sendChat(event) {
  event.preventDefault();
  els.sendButton.disabled = true;
  els.responseOutput.textContent = "Sending request...";

  const body = {
    model: els.modelInput.value.trim(),
    messages: [
      { role: "system", content: els.systemInput.value.trim() },
      { role: "user", content: els.messageInput.value.trim() },
    ],
    stream: false,
  };

  try {
    const response = await fetch("/api/gateway/v1/chat/completions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const { json, text } = await readResponse(response);
    if (!response.ok) {
      throw new Error(text || `Chat request failed with HTTP ${response.status}`);
    }
    const output = formatAssistantResponse(json, text);
    state.lastResponseText = output;
    els.responseOutput.textContent = output;
  } catch (error) {
    state.lastResponseText = error.message;
    els.responseOutput.textContent = error.message;
  } finally {
    els.sendButton.disabled = false;
  }
}

els.chatForm.addEventListener("submit", sendChat);
els.refreshButton.addEventListener("click", refreshStatus);
els.clearButton.addEventListener("click", () => {
  els.responseOutput.textContent = "Waiting for a request.";
  state.lastResponseText = "";
});
els.copyButton.addEventListener("click", async () => {
  const text = state.lastResponseText || els.responseOutput.textContent;
  await navigator.clipboard.writeText(text);
  els.copyButton.textContent = "Copied";
  window.setTimeout(() => {
    els.copyButton.textContent = "Copy";
  }, 1200);
});

refreshStatus();
window.setInterval(refreshStatus, 30000);
