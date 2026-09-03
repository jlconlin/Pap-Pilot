const SUMMARY_ENDPOINT = "/api/v1/experiments/ps-min-2-to-1/summary";
const REPORT_FORMAT = "pap-pilot.retrospective-evidence-report-json";
const REPORT_FORMAT_VERSION = 1;

const LABELS = Object.freeze({
  ps_min: "PS Min",
  baseline: "Baseline",
  intervention: "Intervention",
  mean_mask_pressure_above_epap: "Mean Mask Pressure above EPAP",
  minute_ventilation_upper_tail_ratio: "Minute ventilation upper-tail ratio",
  awakenings_count: "Remembered awakenings",
  sleep_quality: "Sleep quality",
  morning_energy: "Morning energy",
  daytime_tiredness: "Daytime tiredness",
  quality_evidence: "Quality reports",
  confounder_evidence: "Confounder reports",
  adverse_effect_evidence: "Adverse-effect reports",
  not_evaluable_without_fabrication: "Not evaluable without fabrication",
});

export function renderOverview(envelope) {
  const report = readReport(envelope);
  const title = text(report.title, "report title");
  const status = text(report.evaluation_status, "evaluation status");
  const knownChange = object(report.known_change, "known change");
  const periods = array(report.periods, "periods");
  const objectiveMetrics = array(report.objective_metrics, "objective metrics");
  const subjectiveOutcomes = array(report.subjective_outcomes, "subjective outcomes");
  const representativeIntervals = array(report.representative_intervals, "representative intervals");
  const missingInputs = array(report.missing_inputs, "missing inputs");
  const uncertainty = array(report.uncertainty, "uncertainty statements");
  const limitations = array(report.limitations, "limitations");
  const classification = object(report.classification, "classification");
  const provenance = object(report.provenance, "provenance");

  return `
    <article class="overview-report" data-report-id="${escapeHtml(text(report.record_id, "report identifier"))}">
      <section class="hero" aria-labelledby="overview-title">
        <div>
          <p class="eyebrow">Experiment evidence · Retrospective review</p>
          <h1 id="overview-title">${escapeHtml(title)}</h1>
          <p class="hero-copy">This view presents the deterministic report exactly as supplied by the local API. Missing evidence stays visible and no unavailable value is estimated.</p>
        </div>
        <aside class="status-panel" aria-label="Evaluation status">
          <div class="status-label">Current status</div>
          <p class="status-value">${escapeHtml(label(status))}</p>
          <p class="status-detail"><code>${escapeHtml(status)}</code><br>Classification: ${escapeHtml(availability(classification.availability))}</p>
        </aside>
      </section>

      <section class="section" aria-labelledby="setting-heading">
        ${sectionHeading("setting-heading", "Known setting change", "The retained record identifies the intended comparison, but it does not establish when the setting was applied or which nights belong to either period.")}
        <div class="change-grid">
          ${settingCard("Baseline", knownChange.baseline_value, knownChange.unit)}
          <div class="change-arrow" aria-label="changed to"><strong>${escapeHtml(label(knownChange.setting_name))}</strong></div>
          ${settingCard("Intervention", knownChange.intervention_value, knownChange.unit)}
        </div>
      </section>

      <section class="section" aria-labelledby="periods-heading">
        ${sectionHeading("periods-heading", "Comparison periods", "Period counts come from the report inventory. Zero retained nights means the cohort is unavailable, not that therapy did not occur.")}
        <div class="period-grid">${periods.map(renderPeriod).join("")}</div>
      </section>

      <section class="section" aria-labelledby="objective-heading">
        ${sectionHeading("objective-heading", "Objective metrics", "These are PAP Pilot’s prespecified independent outcomes. Thresholds describe the accepted analysis contract; they are not observed results or clinical cutoffs.")}
        ${outcomeTable(objectiveMetrics, "objective")}
      </section>

      <section class="section" aria-labelledby="subjective-heading">
        ${sectionHeading("subjective-heading", "Subjective outcomes", "Structured journal outcomes remain separate from free text. No response is inferred from the earlier informal impression.")}
        ${outcomeTable(subjectiveOutcomes, "subjective")}
      </section>

      <section class="section" aria-labelledby="evidence-heading">
        ${sectionHeading("evidence-heading", "Evidence reports", "Quality, confounder, and adverse-effect evidence are separate inputs. An empty inventory means unknown, not clear or absent.")}
        <div class="evidence-grid">
          ${renderEvidenceCard("quality_evidence", report.quality_evidence)}
          ${renderEvidenceCard("confounder_evidence", report.confounder_evidence)}
          ${renderEvidenceCard("adverse_effect_evidence", report.adverse_effect_evidence)}
        </div>
      </section>

      <section class="section" aria-labelledby="intervals-heading">
        ${sectionHeading("intervals-heading", "Representative intervals", "The report reserves one evidence slot for each period. Waveforms are not rendered when no attributable interval is available.")}
        <div class="interval-grid">${representativeIntervals.map(renderInterval).join("")}</div>
      </section>

      <section class="section" aria-labelledby="evaluation-heading">
        ${sectionHeading("evaluation-heading", "Evaluation", "A classification and next action are shown only when the deterministic evidence requirements have been met.")}
        ${renderClassification(classification)}
      </section>

      <section class="section" aria-labelledby="boundaries-heading">
        ${sectionHeading("boundaries-heading", "Evidence boundaries", "The report records both what is known and what prevents evaluation. These statements are evidence inventory, not generated interpretation.")}
        <div class="two-column">
          <div class="content-card">
            <h3>Known facts</h3>
            ${renderList(array(report.known_facts, "known facts").map((fact) => object(fact, "known fact").statement))}
          </div>
          <div class="content-card">
            <h3>Uncertainty</h3>
            ${renderList(uncertainty)}
          </div>
        </div>
      </section>

      <section class="section" aria-labelledby="missing-heading">
        ${sectionHeading("missing-heading", "Missing inputs", "Each item names source evidence that must exist before the retrospective result can be evaluated without fabrication.")}
        <div class="missing-list">${missingInputs.map(renderMissingInput).join("")}</div>
      </section>

      <section class="section limitations" aria-labelledby="limitations-heading">
        ${sectionHeading("limitations-heading", "Limitations", "These constraints travel with the report and apply to every interpretation of this experiment.")}
        <div class="content-card">${renderList(limitations)}</div>
      </section>

      <footer class="report-footer">
        <span>Companion-derived report · Engine ${escapeHtml(text(report.engine_version, "engine version"))} · Schema ${integer(report.schema_version, "schema version")}</span>
        <code>${escapeHtml(text(report.record_id, "report identifier"))}</code>
        <span>${array(provenance.source_record_ids, "source records").length} linked source records</span>
      </footer>
    </article>`;
}

export function renderOverviewError(message) {
  return `
    <section class="error-panel" role="alert">
      <p class="eyebrow">Local report unavailable</p>
      <h1>The experiment overview could not be loaded.</h1>
      <p>${escapeHtml(typeof message === "string" && message.trim() ? message : "The local API did not return a usable evidence report.")}</p>
      <p>No missing value has been estimated. Restart PAP Pilot and reload this page.</p>
    </section>`;
}

function readReport(envelope) {
  const value = object(envelope, "report envelope");
  if (value.format !== REPORT_FORMAT || value.format_version !== REPORT_FORMAT_VERSION) {
    throw new Error("The local API returned an unsupported report format.");
  }
  return object(value.report, "report");
}

function sectionHeading(identifier, title, description) {
  return `<div class="section-heading"><h2 id="${escapeHtml(identifier)}">${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>`;
}

function settingCard(period, value, unit) {
  return `<div class="setting-card"><small>${escapeHtml(period)}</small><div class="setting-number">${escapeHtml(number(value))}<span>${escapeHtml(text(unit, "setting unit"))}</span></div></div>`;
}

function renderPeriod(value) {
  const period = object(value, "period");
  const count = integer(period.night_count, "period night count");
  const state = text(period.availability, "period availability");
  return `
    <article class="period-card">
      <small>${escapeHtml(label(period.period))} period</small>
      <div class="card-row">
        <div><div class="count">${count}</div><p class="count-label">retained ${count === 1 ? "night" : "nights"}</p></div>
        ${badge(state)}
      </div>
      ${reasonLine(period.reason_codes)}
    </article>`;
}

function outcomeTable(outcomes, kind) {
  return `
    <div class="data-table-wrap">
      <table class="data-table">
        <thead><tr><th scope="col">${kind === "objective" ? "Metric" : "Outcome"}</th><th scope="col">Baseline</th><th scope="col">Intervention</th><th scope="col">Change</th><th scope="col">Prespecified threshold</th></tr></thead>
        <tbody>${outcomes.map(renderOutcomeRow).join("")}</tbody>
      </table>
    </div>`;
}

function renderOutcomeRow(value) {
  const outcome = object(value, "outcome");
  const unit = text(outcome.unit, "outcome unit");
  return `
    <tr>
      <td><span class="metric-name">${escapeHtml(label(outcome.outcome_id))}</span><span class="metric-unit">${escapeHtml(unit)}</span></td>
      ${armCell(outcome.baseline, unit)}
      ${armCell(outcome.intervention, unit)}
      <td>${emptyOrValue(outcome.intervention_minus_baseline, unit)}</td>
      <td><span class="metric-name">${escapeHtml(number(outcome.prespecified_threshold))} ${escapeHtml(unit)}</span><span class="metric-unit">${escapeHtml(label(outcome.favorable_direction))} is favorable</span></td>
    </tr>`;
}

function armCell(value, unit) {
  const arm = object(value, "outcome arm");
  const count = integer(arm.count, "outcome arm count");
  return `<td>${emptyOrValue(arm.median, unit)}<span class="cell-detail">${count} retained ${count === 1 ? "observation" : "observations"}</span></td>`;
}

function emptyOrValue(value, unit) {
  if (value === null || value === undefined) {
    return `<span class="empty-value">Not available</span>`;
  }
  return `<span class="metric-name">${escapeHtml(number(value))} ${escapeHtml(unit)}</span>`;
}

function renderEvidenceCard(key, value) {
  const evidence = object(value, key);
  const count = integer(evidence.record_count, `${key} count`);
  const state = text(evidence.availability, `${key} availability`);
  return `
    <article class="evidence-card">
      <small>Evidence inventory</small>
      <h3>${escapeHtml(label(key))}</h3>
      <span class="count">${count}</span>
      <p class="count-label">retained ${count === 1 ? "record" : "records"}</p>
      ${badge(state)}
      ${reasonLine(evidence.reason_codes)}
    </article>`;
}

function renderInterval(value) {
  const interval = object(value, "representative interval");
  const state = text(interval.availability, "interval availability");
  return `
    <article class="interval-card">
      <small>${escapeHtml(label(interval.period))}</small>
      <div class="card-row"><h3>Waveform interval</h3>${badge(state)}</div>
      <p class="empty-value">${interval.start_ms === null && interval.end_ms === null ? "Not available" : `${escapeHtml(number(interval.start_ms))}–${escapeHtml(number(interval.end_ms))} ms`}</p>
      ${reasonLine(interval.reason_codes)}
    </article>`;
}

function renderClassification(value) {
  const classification = object(value, "classification");
  const state = text(classification.availability, "classification availability");
  return `
    <article class="classification-card">
      <div>
        <p class="eyebrow">Deterministic result</p>
        <p class="status-value">${escapeHtml(availability(state))}</p>
        ${badge(state)}
      </div>
      <div>
        <div class="classification-values">
          <div class="classification-value"><small>Classification</small><strong>${escapeHtml(classification.classification === null ? "Not issued" : label(classification.classification))}</strong></div>
          <div class="classification-value"><small>Next action</small><strong>${escapeHtml(classification.action === null ? "Not issued" : label(classification.action))}</strong></div>
        </div>
        ${reasonLine(classification.reason_codes)}
      </div>
    </article>`;
}

function renderMissingInput(value) {
  const item = object(value, "missing input");
  return `<article class="missing-card"><h3>${escapeHtml(label(item.input_id))}</h3><p>${escapeHtml(text(item.description, "missing-input description"))}</p></article>`;
}

function renderList(values) {
  const entries = array(values, "list entries");
  return `<ul class="evidence-list">${entries.map((value) => `<li>${escapeHtml(text(value, "list entry"))}</li>`).join("")}</ul>`;
}

function reasonLine(values) {
  const reasons = array(values, "reason codes").map((value) => text(value, "reason code"));
  return reasons.length ? `<p class="reason-line">${reasons.map(escapeHtml).join(" · ")}</p>` : "";
}

function badge(value) {
  const state = text(value, "availability");
  return `<span class="badge badge-${escapeHtml(state.replaceAll("_", "-"))}">${escapeHtml(availability(state))}</span>`;
}

function availability(value) {
  if (value === "not_issued") return "Not issued";
  if (value === "missing") return "Missing";
  return label(value);
}

function label(value) {
  const raw = text(value, "label value");
  if (LABELS[raw]) return LABELS[raw];
  return raw.replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function object(value, labelName) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`The ${labelName} is missing or invalid.`);
  }
  return value;
}

function array(value, labelName) {
  if (!Array.isArray(value)) {
    throw new Error(`The ${labelName} are missing or invalid.`);
  }
  return value;
}

function text(value, labelName) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`The ${labelName} is missing or invalid.`);
  }
  return value;
}

function integer(value, labelName) {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`The ${labelName} is missing or invalid.`);
  }
  return value;
}

function number(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error("A numeric report value is missing or invalid.");
  }
  return String(value);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"})[character]);
}

async function loadOverview() {
  const root = document.querySelector("#overview");
  if (!root) return;
  try {
    const response = await fetch(SUMMARY_ENDPOINT, {cache: "no-store", headers: {Accept: "application/json"}});
    if (!response.ok) throw new Error(`The local API returned HTTP ${response.status}.`);
    root.innerHTML = renderOverview(await response.json());
  } catch (error) {
    root.innerHTML = renderOverviewError(error instanceof Error ? error.message : "The local report could not be loaded.");
  } finally {
    root.setAttribute("aria-busy", "false");
  }
}

if (typeof document !== "undefined") {
  loadOverview();
}

export {SUMMARY_ENDPOINT};
