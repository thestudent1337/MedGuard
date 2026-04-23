const state = {
  sessionId: null,
  bootstrap: null,
};

const els = {
  principalSelect: document.getElementById("principal-select"),
  detectorMode: document.getElementById("detector-mode"),
  messageInput: document.getElementById("message-input"),
  sendButton: document.getElementById("send-button"),
  resetButton: document.getElementById("reset-button"),
  samplePrompts: document.getElementById("sample-prompts"),
  statusBanner: document.getElementById("status-banner"),
  transcript: document.getElementById("transcript"),
  classifierStatus: document.getElementById("classifier-status"),
  executorStatus: document.getElementById("executor-status"),
  storageStatus: document.getElementById("storage-status"),
  plannerOutput: document.getElementById("planner-output"),
  toolResult: document.getElementById("tool-result"),
  assistantResponse: document.getElementById("assistant-response"),
  executionSummary: document.getElementById("execution-summary"),
  classifierPrompt: document.getElementById("classifier-prompt"),
  executorPrompt: document.getElementById("executor-prompt"),
  heuristicCard: document.getElementById("heuristic-card"),
  llmCard: document.getElementById("llm-card"),
  hybridCard: document.getElementById("hybrid-card"),
  heuristicRisk: document.getElementById("heuristic-risk"),
  heuristicAction: document.getElementById("heuristic-action"),
  heuristicScore: document.getElementById("heuristic-score"),
  heuristicAttack: document.getElementById("heuristic-attack"),
  llmRisk: document.getElementById("llm-risk"),
  llmAction: document.getElementById("llm-action"),
  llmScoreReadout: document.getElementById("llm-score-readout"),
  llmAttack: document.getElementById("llm-attack"),
  hybridRisk: document.getElementById("hybrid-risk"),
  hybridAction: document.getElementById("hybrid-action"),
  hybridScore: document.getElementById("hybrid-score"),
  hybridAttack: document.getElementById("hybrid-attack"),
  heuristicReasons: document.getElementById("heuristic-reasons"),
  llmReasons: document.getElementById("llm-reasons"),
  hybridReasons: document.getElementById("hybrid-reasons"),
  graphUser: document.getElementById("graph-user"),
  graphPlanner: document.getElementById("graph-planner"),
  graphDetector: document.getElementById("graph-detector"),
  graphExecutor: document.getElementById("graph-executor"),
  graphResponse: document.getElementById("graph-response"),
  graphUserState: document.getElementById("graph-user-state"),
  graphPlannerState: document.getElementById("graph-planner-state"),
  graphDetectorState: document.getElementById("graph-detector-state"),
  graphExecutorState: document.getElementById("graph-executor-state"),
  graphResponseState: document.getElementById("graph-response-state"),
  edgeUserPlanner: document.getElementById("edge-user-planner"),
  edgePlannerDetector: document.getElementById("edge-planner-detector"),
  edgeDetectorExec: document.getElementById("edge-detector-exec"),
  edgeExecResponse: document.getElementById("edge-exec-response"),
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

function renderBootstrap(data) {
  state.bootstrap = data;

  els.principalSelect.innerHTML = "";
  data.principals.forEach((principal) => {
    const option = document.createElement("option");
    option.value = principal.id;
    option.textContent = `${principal.name} (${principal.role})`;
    els.principalSelect.appendChild(option);
  });

  els.detectorMode.innerHTML = "";
  data.detector_modes.forEach((mode) => {
    const option = document.createElement("option");
    option.value = mode;
    option.textContent = mode;
    if (mode === "hybrid") option.selected = true;
    els.detectorMode.appendChild(option);
  });

  els.samplePrompts.innerHTML = "";
  [...data.sample_prompts, ...data.sample_attacks].forEach((prompt) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = prompt;
    button.addEventListener("click", () => {
      els.messageInput.value = prompt;
    });
    els.samplePrompts.appendChild(button);
  });

  els.classifierStatus.textContent = data.classifier_status.enabled
    ? `${data.classifier_status.model} available`
    : data.classifier_status.reason;
  els.executorStatus.textContent = data.executor_status.enabled
    ? `${data.executor_status.model} available`
    : data.executor_status.reason;
  els.storageStatus.textContent = data.storage.database_path.endsWith(".sqlite3")
    ? `SQLite: ${data.storage.database_path.split(/[/\\\\]/).pop()}`
    : data.storage.mode;
  els.classifierPrompt.textContent = data.system_prompts.classifier_developer_prompt;
  els.executorPrompt.textContent = data.system_prompts.executor_developer_prompt;
}

function clearSessionView(message = "No request analyzed yet.") {
  els.transcript.innerHTML = "";
  els.statusBanner.textContent = message;
  els.statusBanner.className = "status-banner neutral";
  els.plannerOutput.textContent = "No tool call yet.";
  els.toolResult.textContent = "No tool result yet.";
  els.assistantResponse.textContent = "No GPT response yet.";
  els.executionSummary.textContent = "No request executed yet.";
  renderDetectorCard(els.heuristicCard, els.heuristicRisk, els.heuristicAction, els.heuristicScore, els.heuristicAttack, {});
  renderDetectorCard(els.llmCard, els.llmRisk, els.llmAction, els.llmScoreReadout, els.llmAttack, {});
  renderDetectorCard(els.hybridCard, els.hybridRisk, els.hybridAction, els.hybridScore, els.hybridAttack, {});
  renderReasons(els.heuristicReasons, []);
  renderReasons(els.llmReasons, []);
  renderReasons(els.hybridReasons, []);
  setNodeState(els.graphUser, els.graphUserState, "idle", "idle");
  setNodeState(els.graphPlanner, els.graphPlannerState, "idle", "idle");
  setNodeState(els.graphDetector, els.graphDetectorState, "idle", "idle");
  setNodeState(els.graphExecutor, els.graphExecutorState, "idle", "idle");
  setNodeState(els.graphResponse, els.graphResponseState, "idle", "idle");
  setEdgeState(els.edgeUserPlanner, "WAIT", "idle");
  setEdgeState(els.edgePlannerDetector, "WAIT", "idle");
  setEdgeState(els.edgeDetectorExec, "WAIT", "idle");
  setEdgeState(els.edgeExecResponse, "WAIT", "idle");
}

function renderReasons(listEl, reasons) {
  listEl.innerHTML = "";
  (reasons || []).forEach((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    listEl.appendChild(item);
  });
  if (!(reasons || []).length) {
    listEl.innerHTML = "<li>No result yet.</li>";
  }
}

function renderDetectorCard(card, riskEl, actionEl, scoreEl, attackEl, result) {
  riskEl.textContent = result.risk_level || "No result";
  actionEl.textContent = result.recommended_action || "No action";
  scoreEl.textContent = `Score: ${result.score ?? "N/A"} | Source: ${result.source || "N/A"}`;
  attackEl.textContent = `Attack: ${result.attack_type || "N/A"}`;
  card.className = `detector-card ${result.risk_level || "idle"}`;
}

function renderTranscript(history) {
  els.transcript.innerHTML = "";
  history.forEach((event) => {
    const userBubble = document.createElement("div");
    userBubble.className = "bubble user";
    userBubble.innerHTML = `<small>${event.actor}</small>${event.message}`;
    els.transcript.appendChild(userBubble);

    const assistantBubble = document.createElement("div");
    assistantBubble.className = "bubble assistant";
    assistantBubble.innerHTML = `<small>${event.decision}</small>${(event.outcome || "").replace(/\n/g, "<br />")}`;
    els.transcript.appendChild(assistantBubble);
  });
}

function setNodeState(node, stateEl, label, stateClass) {
  stateEl.textContent = label;
  node.className = `graph-node ${stateClass}`;
}

function setEdgeState(edge, label, stateClass) {
  edge.textContent = label;
  edge.className = `graph-edge ${stateClass}`;
}

function renderWorkflowGraph(payload) {
  const gatePassed = payload.policy_decision.action === "allow" || payload.policy_decision.action === "allow_with_logging";
  const executionPassed = Boolean(payload.execution_result.executed);
  setNodeState(els.graphUser, els.graphUserState, "received", "pass");
  setNodeState(els.graphPlanner, els.graphPlannerState, payload.tool_call.tool || "unknown", payload.tool_call.tool === "unknown" ? "warn" : "pass");
  setNodeState(els.graphDetector, els.graphDetectorState, `${payload.detector_mode}:${payload.monitor_result.risk_level}`, gatePassed ? "pass" : "fail");
  setNodeState(
    els.graphExecutor,
    els.graphExecutorState,
    executionPassed ? payload.execution_result.source : (gatePassed ? "error" : "skipped"),
    executionPassed ? "pass" : (gatePassed ? "warn" : "fail")
  );
  setNodeState(
    els.graphResponse,
    els.graphResponseState,
    gatePassed ? (executionPassed ? "returned" : "tool-only") : "blocked",
    gatePassed ? "pass" : "fail"
  );

  setEdgeState(els.edgeUserPlanner, "PARSE", "pass");
  setEdgeState(els.edgePlannerDetector, "CLASSIFY", "pass");
  setEdgeState(els.edgeDetectorExec, gatePassed ? "PASS" : "FAIL", gatePassed ? "pass" : "fail");
  setEdgeState(els.edgeExecResponse, executionPassed ? "PASS" : (gatePassed ? "PARTIAL" : "STOP"), executionPassed ? "pass" : (gatePassed ? "warn" : "fail"));
}

function renderResults(payload) {
  const { detector_results, detector_mode, policy_decision, execution_result } = payload;
  renderDetectorCard(els.heuristicCard, els.heuristicRisk, els.heuristicAction, els.heuristicScore, els.heuristicAttack, detector_results.heuristic);
  renderDetectorCard(els.llmCard, els.llmRisk, els.llmAction, els.llmScoreReadout, els.llmAttack, detector_results.llm);
  renderDetectorCard(els.hybridCard, els.hybridRisk, els.hybridAction, els.hybridScore, els.hybridAttack, detector_results.hybrid);

  renderReasons(els.heuristicReasons, detector_results.heuristic.reasons);
  renderReasons(els.llmReasons, detector_results.llm.reasons);
  renderReasons(els.hybridReasons, detector_results.hybrid.reasons);

  const restartNote = payload.session_restarted ? " New session started because the principal changed." : "";
  els.statusBanner.textContent = `${detector_mode} gatekeeper -> ${policy_decision.action}: ${policy_decision.user_message}${restartNote}`;
  els.statusBanner.className = `status-banner ${payload.monitor_result.risk_level}`;

  els.plannerOutput.textContent = JSON.stringify(payload.tool_call, null, 2);
  els.toolResult.textContent = payload.tool_result || "No tool result because execution was blocked before task execution.";
  els.assistantResponse.textContent = payload.assistant_response || "No assistant response.";
  els.executionSummary.textContent = JSON.stringify(
    {
      gatekeeper_detector: detector_mode,
      selected_result: payload.monitor_result,
      execution_result,
    },
    null,
    2
  );
  renderWorkflowGraph(payload);
  renderTranscript(payload.history);
}

async function sendMessage() {
  const message = els.messageInput.value.trim();
  if (!message) return;

  els.sendButton.disabled = true;
  try {
    const payload = await fetchJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        session_id: state.sessionId,
        principal_id: els.principalSelect.value,
        detector_mode: els.detectorMode.value,
        message,
      }),
    });
    state.sessionId = payload.session_id;
    renderResults(payload);
  } catch (error) {
    alert(error.message);
  } finally {
    els.sendButton.disabled = false;
  }
}

async function resetSystem() {
  await fetchJson("/api/reset", { method: "POST", body: "{}" });
  state.sessionId = null;
  clearSessionView();
}

async function init() {
  const bootstrap = await fetchJson("/api/bootstrap");
  renderBootstrap(bootstrap);
  els.sendButton.addEventListener("click", sendMessage);
  els.resetButton.addEventListener("click", resetSystem);
  els.principalSelect.addEventListener("change", () => {
    state.sessionId = null;
    clearSessionView("Session reset because the principal changed.");
  });
  els.messageInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      sendMessage();
    }
  });
}

init().catch((error) => {
  alert(error.message);
});
