const CATEGORY_COLORS = {
  benign_single_record: "#4fa3ff",
  benign_self_service: "#5bd0c8",
  benign_cohort_query: "#7db8ff",
  unauthorized_access: "#ff8a65",
  unauthorized_modification: "#ff6f98",
  prompt_injection: "#ff4d6d",
  system_prompt_extraction: "#ffb454",
  bulk_phi_exfiltration: "#ff7a45",
  sensitive_inference: "#c792ea",
  role_impersonation: "#ffd36b",
  multilingual_spanish: "#8bd17c",
};

const state = {
  dataset: null,
  selectedCategories: new Set(),
  lastEvaluationRuns: [],
  liveRunActive: false,
};

const els = {
  datasetTotal: document.getElementById("dataset-total"),
  benchmarkTotal: document.getElementById("benchmark-total"),
  datasetLanguages: document.getElementById("dataset-languages"),
  categorySummary: document.getElementById("category-summary"),
  categoryPrompts: document.getElementById("category-prompts"),
  evalDetectorMode: document.getElementById("eval-detector-mode"),
  runEvalButton: document.getElementById("run-eval-button"),
  evalStatus: document.getElementById("eval-status"),
  evaluationGraph: document.getElementById("evaluation-graph"),
  evaluationLiveLog: document.getElementById("evaluation-live-log"),
  evaluationResults: document.getElementById("evaluation-results"),
  selectAllCategories: document.getElementById("select-all-categories"),
  clearAllCategories: document.getElementById("clear-all-categories"),
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

function getSelectedCategories() {
  return [...state.selectedCategories];
}

function getCategoryColor(category) {
  return CATEGORY_COLORS[category] || "#57a6ff";
}

function buildCategoryCounts() {
  const counts = Object.fromEntries((state.dataset.summary.categories || []).map((category) => [category, 0]));
  (state.dataset.cases || []).forEach((item) => {
    counts[item.label] = (counts[item.label] || 0) + 1;
  });
  return counts;
}

function renderCategorySummary() {
  const counts = buildCategoryCounts();
  els.categorySummary.innerHTML = "";

  (state.dataset.summary.categories || []).forEach((category) => {
    const button = document.createElement("button");
    const count = counts[category] || 0;
    const active = state.selectedCategories.has(category);

    button.type = "button";
    button.className = `summary-item summary-toggle ${active ? "active" : "inactive"}`;
    button.style.setProperty("--category-color", getCategoryColor(category));
    button.innerHTML = `<strong>${category}</strong><span>${count}</span>`;
    button.disabled = count === 0;
    button.addEventListener("click", () => {
      if (active) {
        state.selectedCategories.delete(category);
      } else {
        state.selectedCategories.add(category);
      }
      renderCategorySummary();
      renderCategoryPrompts();
      renderEvaluationFromState();
    });

    els.categorySummary.appendChild(button);
  });
}

function renderCategoryPrompts() {
  const selected = getSelectedCategories();
  els.categoryPrompts.innerHTML = "";

  if (!selected.length) {
    els.categoryPrompts.innerHTML = `<p class="muted-line">Select one or more categories to inspect their prompts.</p>`;
    return;
  }

  const prompts = (state.dataset.cases || []).filter((item) => state.selectedCategories.has(item.label));
  prompts.forEach((item) => {
    const article = document.createElement("article");
    article.className = "case-item compact-case-item";
    article.style.setProperty("--category-color", getCategoryColor(item.label));
    article.innerHTML = `
      <div class="case-meta">
        <strong class="category-chip" style="--category-color: ${getCategoryColor(item.label)}">${item.label}</strong>
        <span>${item.language} | ${item.principal_id} | ${item.include_in_benchmark ? "benchmark" : "dataset-only"}${item.semantic_challenge ? " | semantic challenge" : ""}</span>
      </div>
      <p class="case-message">${item.message}</p>
    `;
    els.categoryPrompts.appendChild(article);
  });
}

function getSelectedEvaluationCases() {
  const allCases = state.dataset.cases || [];
  const benchmarkCases = allCases.filter((item) => item.include_in_benchmark);
  if (!state.selectedCategories.size) {
    return benchmarkCases;
  }
  return allCases.filter((item) => state.selectedCategories.has(item.label));
}

function filterRunBySelectedCategories(run) {
  if (!state.selectedCategories.size) {
    return run;
  }

  const results = run.results.filter((item) => state.selectedCategories.has(item.label));
  const actionCounts = {};
  let passed = 0;
  results.forEach((item) => {
    actionCounts[item.actual_action] = (actionCounts[item.actual_action] || 0) + 1;
    if (item.passed) {
      passed += 1;
    }
  });

  return {
    ...run,
    summary: {
      ...run.summary,
      passed,
      total: results.length,
      action_counts: actionCounts,
      category_filter: getSelectedCategories(),
    },
    results,
  };
}

function renderEvaluationRun(run) {
  const wrapper = document.createElement("section");
  wrapper.className = "eval-run";

  wrapper.innerHTML = `
    <div class="eval-run-header">
      <h4>${run.summary.detector_mode}</h4>
      <span>${run.summary.passed}/${run.summary.total} passed</span>
    </div>
    <div class="summary-list"></div>
    <div class="category-benchmark-summary"></div>
    <div class="eval-result-table"></div>
  `;

  const summaryContainer = wrapper.querySelector(".summary-list");
  Object.entries(run.summary.action_counts || {}).forEach(([action, count]) => {
    const item = document.createElement("div");
    item.className = "summary-item";
    item.innerHTML = `<strong>${action}</strong><span>${count}</span>`;
    summaryContainer.appendChild(item);
  });
  if (run.summary.write_cases) {
    const writeItem = document.createElement("div");
    writeItem.className = "summary-item";
    writeItem.innerHTML = `<strong>write_checks</strong><span>${run.summary.write_passed}/${run.summary.write_cases}</span>`;
    summaryContainer.appendChild(writeItem);
  }
  if (!Object.keys(run.summary.action_counts || {}).length) {
    summaryContainer.innerHTML = `<p class="muted-line">No benchmark cases match the current category selection.</p>`;
  }

  const categorySummary = wrapper.querySelector(".category-benchmark-summary");
  const byCategory = {};
  run.results.forEach((item) => {
    if (!byCategory[item.label]) {
      byCategory[item.label] = { total: 0, passed: 0 };
    }
    byCategory[item.label].total += 1;
    byCategory[item.label].passed += item.passed ? 1 : 0;
  });
  const categoryEntries = Object.entries(byCategory);
  if (categoryEntries.length) {
    categoryEntries.forEach(([label, summary]) => {
      const item = document.createElement("div");
      item.className = "category-benchmark-item";
      item.style.setProperty("--category-color", getCategoryColor(label));
      item.innerHTML = `<strong>${label}</strong><span>${summary.passed}/${summary.total} passed</span>`;
      categorySummary.appendChild(item);
    });
  } else {
    categorySummary.innerHTML = `<p class="muted-line">No category summary available for the current selection.</p>`;
  }

  const table = wrapper.querySelector(".eval-result-table");
  run.results.forEach((item) => {
    const row = document.createElement("div");
    row.className = `eval-result-row ${item.passed ? "pass" : "fail"}`;
    row.style.setProperty("--category-color", getCategoryColor(item.label));
    const writeBadge = item.expected_write
      ? `<span class="eval-write-badge ${item.write_evaluation.passed ? "pass" : "fail"}">write ${item.write_evaluation.passed ? "pass" : "fail"}</span>`
      : `<span class="eval-write-badge neutral">no write</span>`;
    row.innerHTML = `
      <strong>${item.index}. ${item.label}</strong>
      <span>${item.principal_id}</span>
      <span>${item.actual_action}</span>
      <span>${item.monitor_risk}</span>
      <span>${item.message}</span>
      ${writeBadge}
    `;
    table.appendChild(row);
  });
  if (!run.results.length) {
    table.innerHTML = `<p class="muted-line">No benchmark cases match the current category selection.</p>`;
  }

  return wrapper;
}

function renderEvaluationGraph(runs) {
  els.evaluationGraph.innerHTML = "";

  const populatedRuns = runs.filter((run) => run.summary.total > 0);
  if (!populatedRuns.length) {
    els.evaluationGraph.innerHTML = `<p class="muted-line">No benchmark cases match the current category selection.</p>`;
    return;
  }

  const width = 960;
  const height = 340;
  const chartTop = 32;
  const chartBottom = 270;
  const chartLeft = 72;
  const chartRight = 28;
  const chartHeight = chartBottom - chartTop;
  const chartWidth = width - chartLeft - chartRight;
  const maxTotal = Math.max(...populatedRuns.map((run) => run.summary.total), 1);
  const groupWidth = chartWidth / populatedRuns.length;
  const barWidth = Math.min(56, Math.max(24, (groupWidth - 46) / 2));

  let svg = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Benchmark results chart">
      <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
  `;

  for (let tick = 0; tick <= maxTotal; tick += Math.max(1, Math.ceil(maxTotal / 5))) {
    const y = chartBottom - (tick / maxTotal) * chartHeight;
    svg += `
      <line x1="${chartLeft}" y1="${y}" x2="${width - chartRight}" y2="${y}" class="chart-grid-line"></line>
      <text x="${chartLeft - 12}" y="${y + 4}" text-anchor="end" class="chart-axis-label">${tick}</text>
    `;
  }

  populatedRuns.forEach((run, index) => {
    const passed = run.summary.passed;
    const failed = run.summary.total - run.summary.passed;
    const baseX = chartLeft + index * groupWidth + groupWidth / 2;
    const passedHeight = (passed / maxTotal) * chartHeight;
    const failedHeight = (failed / maxTotal) * chartHeight;
    const passedX = baseX - barWidth - 8;
    const failedX = baseX + 8;
    const passedY = chartBottom - passedHeight;
    const failedY = chartBottom - failedHeight;

    svg += `
      <rect x="${passedX}" y="${passedY}" width="${barWidth}" height="${passedHeight}" rx="10" class="chart-bar-passed"></rect>
      <rect x="${failedX}" y="${failedY}" width="${barWidth}" height="${failedHeight}" rx="10" class="chart-bar-failed"></rect>
      <text x="${passedX + barWidth / 2}" y="${Math.max(passedY - 8, chartTop - 4)}" text-anchor="middle" class="chart-value-label">${passed}</text>
      <text x="${failedX + barWidth / 2}" y="${Math.max(failedY - 8, chartTop - 4)}" text-anchor="middle" class="chart-value-label">${failed}</text>
      <text x="${baseX}" y="${chartBottom + 28}" text-anchor="middle" class="chart-axis-label">${run.summary.detector_mode}</text>
    `;
  });

  svg += `
      <line x1="${chartLeft}" y1="${chartBottom}" x2="${width - chartRight}" y2="${chartBottom}" class="chart-axis-line"></line>
      <g transform="translate(${chartLeft}, 300)">
        <rect x="0" y="-12" width="18" height="18" rx="5" class="chart-bar-passed"></rect>
        <text x="28" y="2" class="chart-legend-label">Passed</text>
        <rect x="120" y="-12" width="18" height="18" rx="5" class="chart-bar-failed"></rect>
        <text x="148" y="2" class="chart-legend-label">Failed</text>
      </g>
    </svg>
  `;

  els.evaluationGraph.innerHTML = svg;
}

function renderEvaluationFromState() {
  if (!state.lastEvaluationRuns.length) {
    return;
  }

  const runs = state.lastEvaluationRuns.map(filterRunBySelectedCategories);
  const totalPassed = runs.reduce((sum, run) => sum + run.summary.passed, 0);
  const totalCases = runs.reduce((sum, run) => sum + run.summary.total, 0);
  const categoryText = state.selectedCategories.size
    ? ` Filtered to ${state.selectedCategories.size} selected categor${state.selectedCategories.size === 1 ? "y" : "ies"} from the full dataset.`
    : " No category filter applied; running all benchmark categories.";

  els.evalStatus.textContent = `Completed ${runs.length} run(s): ${totalPassed}/${totalCases} passed.${categoryText}`;
  els.evalStatus.className = "status-banner low";

  renderEvaluationGraph(runs);
  els.evaluationResults.innerHTML = "";
  runs.forEach((run) => {
    els.evaluationResults.appendChild(renderEvaluationRun(run));
  });
}

async function runEvaluation() {
  if (!state.dataset || state.liveRunActive) {
    return;
  }
  els.runEvalButton.disabled = true;
  state.liveRunActive = true;
  const evaluationCases = getSelectedEvaluationCases();
  const detectorModes = els.evalDetectorMode.value === "all"
    ? ["heuristic", "llm", "hybrid"]
    : [els.evalDetectorMode.value];

  if (!evaluationCases.length) {
    els.evalStatus.textContent = "No evaluation cases match the current category selection.";
    els.evalStatus.className = "status-banner high";
    els.runEvalButton.disabled = false;
    state.liveRunActive = false;
    return;
  }

  const selectionMode = state.selectedCategories.size ? "selected dataset case(s)" : "benchmark case(s)";
  els.evalStatus.textContent = `Running ${evaluationCases.length} ${selectionMode} across ${detectorModes.length} detector mode(s)...`;
  els.evalStatus.className = "status-banner neutral";
  els.evaluationLiveLog.innerHTML = "";
  els.evaluationResults.innerHTML = `<p class="muted-line">Evaluation in progress...</p>`;
  els.evaluationGraph.innerHTML = `<p class="muted-line">Evaluation in progress...</p>`;
  try {
    const runs = [];
    let completed = 0;
    const total = evaluationCases.length * detectorModes.length;

    for (const detectorMode of detectorModes) {
      const run = {
        summary: {
          passed: 0,
          total: 0,
          action_counts: {},
          detector_mode: detectorMode,
          write_passed: 0,
          write_cases: 0,
        },
        results: [],
      };

      for (const caseItem of evaluationCases) {
        const result = await fetchJson("/api/evaluate/case", {
          method: "POST",
          body: JSON.stringify({
            case_id: caseItem.id,
            detector_mode: detectorMode,
          }),
        });
        const evaluated = {
          index: run.results.length + 1,
          ...result,
        };
        run.results.push(evaluated);
        run.summary.total += 1;
        run.summary.passed += evaluated.passed ? 1 : 0;
        run.summary.action_counts[evaluated.actual_action] = (run.summary.action_counts[evaluated.actual_action] || 0) + 1;
        if (evaluated.expected_write) {
          run.summary.write_cases += 1;
          run.summary.write_passed += evaluated.write_evaluation.passed ? 1 : 0;
        }
        completed += 1;
        appendLiveLogEntry(evaluated, detectorMode, completed, total);
        els.evalStatus.textContent = `Running ${completed}/${total}: ${detectorMode} -> ${caseItem.id}`;
      }

      runs.push(run);
    }

    state.lastEvaluationRuns = runs;
    renderEvaluationFromState();
  } catch (error) {
    els.evalStatus.textContent = error.message;
    els.evalStatus.className = "status-banner high";
  } finally {
    els.runEvalButton.disabled = false;
    state.liveRunActive = false;
  }
}

function appendLiveLogEntry(item, detectorMode, completed, total) {
  const entry = document.createElement("article");
  entry.className = `live-log-entry ${item.passed ? "pass" : "fail"}`;
  entry.style.setProperty("--category-color", getCategoryColor(item.label));
  const writeLine = item.expected_write
    ? `Write: ${item.write_evaluation.passed ? "PASS" : "FAIL"} (${item.write_evaluation.status})`
    : "Write: N/A";
  entry.innerHTML = `
    <div class="live-log-header">
      <strong>${completed}/${total} ${detectorMode} -> ${item.id}</strong>
      <span>${item.passed ? "PASS" : "FAIL"}</span>
    </div>
    <div class="live-log-meta">
      <span>${item.label}</span>
      <span>${item.principal_id}</span>
      <span>${item.actual_action}</span>
      <span>${item.monitor_risk}</span>
    </div>
    <p class="case-message">${item.message}</p>
    <pre class="live-log-output">Tool: ${item.interaction.tool_call.tool}
Decision: ${item.interaction.policy_decision.action}
Assistant: ${item.interaction.assistant_response || "No assistant response."}
${writeLine}</pre>
  `;
  els.evaluationLiveLog.prepend(entry);
}

function renderDataset(dataset) {
  state.dataset = dataset;
  state.selectedCategories = new Set();
  els.datasetTotal.textContent = String(dataset.summary.total_cases);
  els.benchmarkTotal.textContent = String(dataset.summary.benchmark_cases);
  els.datasetLanguages.textContent = Object.keys(dataset.summary.counts_by_language).join(", ");
  renderCategorySummary();
  renderCategoryPrompts();
}

async function init() {
  const dataset = await fetchJson("/api/research-dataset");
  renderDataset(dataset);

  els.runEvalButton.addEventListener("click", runEvaluation);
  els.selectAllCategories.addEventListener("click", () => {
    state.selectedCategories = new Set(state.dataset.summary.categories || []);
    renderCategorySummary();
    renderCategoryPrompts();
    renderEvaluationFromState();
  });
  els.clearAllCategories.addEventListener("click", () => {
    state.selectedCategories = new Set();
    renderCategorySummary();
    renderCategoryPrompts();
    renderEvaluationFromState();
  });
}

init().catch((error) => {
  els.evalStatus.textContent = error.message;
  els.evalStatus.className = "status-banner high";
});
