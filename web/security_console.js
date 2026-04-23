const state = {
  bootstrap: null,
};

const els = {
  principalSelect: document.getElementById("admin-principal-select"),
  messageInput: document.getElementById("admin-message-input"),
  simulateButton: document.getElementById("simulate-button"),
  benchmarkButton: document.getElementById("benchmark-button"),
  attackPrompts: document.getElementById("attack-prompts"),
  decisionCard: document.getElementById("admin-decision-card"),
  risk: document.getElementById("admin-risk"),
  attack: document.getElementById("admin-attack"),
  policy: document.getElementById("admin-policy"),
  plannerOutput: document.getElementById("admin-planner-output"),
  plannerNoteList: document.getElementById("planner-note-list"),
  reasonList: document.getElementById("admin-reason-list"),
  policyMessage: document.getElementById("admin-policy-message"),
  incidentLog: document.getElementById("admin-incident-log"),
  incidentStats: document.getElementById("incident-stats"),
  refreshIncidents: document.getElementById("refresh-incidents"),
  benchmarkResults: document.getElementById("benchmark-results"),
  benchmarkSummary: document.getElementById("benchmark-summary"),
  incidentCount: document.getElementById("admin-incident-count"),
  latestRisk: document.getElementById("latest-risk"),
  detectorStatus: document.getElementById("detector-status"),
  storageStatus: document.getElementById("storage-status"),
  finalScore: document.getElementById("final-score"),
  scoreSource: document.getElementById("score-source"),
  plannerConfidence: document.getElementById("planner-confidence"),
  heuristicScore: document.getElementById("heuristic-score"),
  llmScore: document.getElementById("llm-score"),
  llmUsed: document.getElementById("llm-used"),
  llmModel: document.getElementById("llm-model"),
  llmError: document.getElementById("llm-error"),
};

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed.");
  }
  return data;
}

function renderPrincipals(principals) {
  els.principalSelect.innerHTML = "";
  principals.forEach((principal) => {
    const option = document.createElement("option");
    option.value = principal.id;
    option.textContent = `${principal.name} (${principal.role})`;
    els.principalSelect.appendChild(option);
  });
}

function renderAttackPrompts(prompts) {
  els.attackPrompts.innerHTML = "";
  prompts.forEach((prompt) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = prompt;
    button.addEventListener("click", () => {
      els.messageInput.value = prompt;
    });
    els.attackPrompts.appendChild(button);
  });
}

function renderReasons(reasons) {
  els.reasonList.innerHTML = "";
  reasons.forEach((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    els.reasonList.appendChild(item);
  });
}

function renderPlannerNotes(notes) {
  els.plannerNoteList.innerHTML = "";
  (notes || []).forEach((note) => {
    const item = document.createElement("li");
    item.textContent = note;
    els.plannerNoteList.appendChild(item);
  });
  if (!(notes || []).length) {
    els.plannerNoteList.innerHTML = "<li>No planner notes yet.</li>";
  }
}

function renderSimulation(payload) {
  els.risk.textContent = `${payload.monitor_result.risk_level} (${payload.monitor_result.score})`;
  els.attack.textContent = payload.monitor_result.attack_type.replaceAll("_", " ");
  const sourceLabel = payload.monitor_result.source ? ` [${payload.monitor_result.source}]` : "";
  els.policy.textContent = `${payload.policy_decision.action.replaceAll("_", " ")}${sourceLabel}`;
  els.policyMessage.textContent = payload.policy_decision.user_message;
  els.plannerOutput.textContent = JSON.stringify(payload.tool_call, null, 2);
  els.decisionCard.className = `decision-card ${payload.monitor_result.risk_level}`;
  els.latestRisk.textContent = payload.monitor_result.risk_level.toUpperCase();
  els.finalScore.textContent = String(payload.monitor_result.score ?? "N/A");
  els.scoreSource.textContent = payload.monitor_result.source || "heuristic";
  els.plannerConfidence.textContent = String(payload.tool_call.confidence ?? "N/A");
  els.heuristicScore.textContent = payload.monitor_result.heuristic_score ?? "N/A";
  els.llmScore.textContent = payload.monitor_result.llm_score ?? "N/A";
  els.llmUsed.textContent = payload.monitor_result.llm_used ? "Yes" : "No";
  els.llmModel.textContent = payload.monitor_result.llm_model || "N/A";
  els.llmError.textContent = payload.monitor_result.llm_error || "No LLM classifier error.";
  renderPlannerNotes(payload.tool_call.planner_notes);
  renderReasons(payload.monitor_result.reasons);
}

function renderIncidents(payload) {
  const { incidents, stats } = payload;
  els.incidentCount.textContent = String(stats.total);
  els.incidentStats.textContent = JSON.stringify(stats, null, 2);
  els.incidentLog.innerHTML = "";

  if (!incidents.length) {
    const empty = document.createElement("div");
    empty.className = "incident-item";
    empty.innerHTML = "<strong>No incidents logged</strong><span>Use the user app to generate monitored traffic.</span>";
    els.incidentLog.appendChild(empty);
    return;
  }

  incidents.forEach((incident) => {
    const item = document.createElement("div");
    item.className = "incident-item";
    item.innerHTML = `
      <strong>${incident.monitor_result.risk_level.toUpperCase()} - ${incident.monitor_result.attack_type.replaceAll("_", " ")}</strong>
      <span>${incident.timestamp}</span>
      <span>${incident.principal.name}: ${incident.message}</span>
      <span>Action: ${incident.policy_decision.action.replaceAll("_", " ")}</span>
      <span>Source: ${(incident.monitor_result.source || "heuristic").replaceAll("_", " ")}</span>
      <span>Scores: heuristic ${incident.monitor_result.heuristic_score ?? "N/A"}, llm ${incident.monitor_result.llm_score ?? "N/A"}</span>
    `;
    els.incidentLog.appendChild(item);
  });
}

function renderBenchmark(payload) {
  els.benchmarkSummary.textContent = `${payload.summary.passed}/${payload.summary.total} passed`;
  els.benchmarkResults.innerHTML = "";
  payload.results.forEach((result) => {
    const item = document.createElement("div");
    item.className = "incident-item";
    item.innerHTML = `
      <strong>${result.passed ? "PASS" : "FAIL"} - ${result.label}</strong>
      <span>${result.principal_id}: ${result.message}</span>
      <span>Expected: ${result.expected_actions.join(", ")}</span>
      <span>Actual: ${result.actual_action}</span>
      <span>Risk: ${result.monitor_risk} | Attack: ${result.attack_type}</span>
      <span>Scores: final ${result.final_score ?? "N/A"}, heuristic ${result.heuristic_score ?? "N/A"}, llm ${result.llm_score ?? "N/A"}</span>
      <span>Detector source: ${result.source || "heuristic"}</span>
    `;
    els.benchmarkResults.appendChild(item);
  });
}

async function loadIncidents() {
  const payload = await fetchJson("/api/admin/incidents");
  renderIncidents(payload);
}

async function simulateDetection() {
  const message = els.messageInput.value.trim();
  if (!message) return;
  els.simulateButton.disabled = true;
  try {
    const payload = await fetchJson("/api/admin/simulate", {
      method: "POST",
      body: JSON.stringify({
        principal_id: els.principalSelect.value,
        message,
      }),
    });
    renderSimulation(payload);
  } catch (error) {
    alert(error.message);
  } finally {
    els.simulateButton.disabled = false;
  }
}

async function runBenchmark() {
  els.benchmarkButton.disabled = true;
  try {
    const payload = await fetchJson("/api/admin/evaluate", {
      method: "POST",
      body: "{}",
    });
    renderBenchmark(payload);
  } catch (error) {
    alert(error.message);
  } finally {
    els.benchmarkButton.disabled = false;
  }
}

async function init() {
  const bootstrap = await fetchJson("/api/admin/bootstrap");
  state.bootstrap = bootstrap;
  renderPrincipals(bootstrap.principals);
  renderAttackPrompts(bootstrap.sample_attacks);
  els.detectorStatus.textContent = bootstrap.classifier_status.enabled
    ? `${bootstrap.classifier_status.model} enabled`
    : bootstrap.classifier_status.reason;
  els.storageStatus.textContent = bootstrap.storage.database_path.endsWith(".sqlite3")
    ? `SQLite: ${bootstrap.storage.database_path.split(/[/\\\\]/).pop()}`
    : bootstrap.storage.mode;
  renderIncidents({
    incidents: bootstrap.incidents || [],
    stats: bootstrap.incident_stats || {
      total: (bootstrap.incidents || []).length,
      counts_by_risk: {},
      counts_by_action: {},
    },
  });

  els.simulateButton.addEventListener("click", simulateDetection);
  els.benchmarkButton.addEventListener("click", runBenchmark);
  els.refreshIncidents.addEventListener("click", loadIncidents);
  els.messageInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      simulateDetection();
    }
  });

  await loadIncidents();
}

init().catch((error) => {
  alert(error.message);
});
