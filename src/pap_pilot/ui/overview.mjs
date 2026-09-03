const SUMMARY_ENDPOINT = "/api/v1/experiments/ps-min-2-to-1/summary";
const HISTORY_ENDPOINT = "/api/v1/experiments/ps-min-2-to-1/history";
const BOUNDARY_CORRECTION_ENDPOINT = "/api/v1/experiments/ps-min-2-to-1/boundary-corrections";
const REPORT_FORMAT = "pap-pilot.retrospective-evidence-report-json";
const REPORT_FORMAT_VERSION = 1;
const WAVEFORM_DISPLAY_CONTRACT_VERSION = 1;
const MAX_WAVEFORM_SIGNALS = 3;
const MAX_WAVEFORM_POINTS = 2000;
const WAVEFORM_WIDTH = 800;
const WAVEFORM_HEIGHT = 190;
const WAVEFORM_PADDING = Object.freeze({top: 18, right: 18, bottom: 30, left: 62});

const SIGNAL_SPECS = Object.freeze({
  flow_rate: Object.freeze({label: "Flow Rate", unit: "L/min", representation: "uniform_waveform", colorClass: "waveform-flow"}),
  mask_pressure: Object.freeze({label: "Mask Pressure", unit: "cm H₂O", representation: "uniform_waveform", colorClass: "waveform-pressure"}),
  leak: Object.freeze({label: "Leak", unit: "L/min", representation: "timed_updates", colorClass: "waveform-leak"}),
});

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
  const evidence = evidenceIndex(provenance.source_record_ids);

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
        ${sectionHeading("intervals-heading", "Representative intervals", "Only preselected report excerpts are displayed. Samples are plotted without smoothing or interval selection, and unavailable signal evidence stays visibly missing.")}
        <div class="interval-grid">${representativeIntervals.map((interval) => renderInterval(interval, evidence.targets)).join("")}</div>
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
          <div class="content-card evidence-inventory" id="report-evidence">
            <h3>Linked evidence</h3>
            <p>Waveform references resolve to the report’s retained source-record inventory.</p>
            ${renderEvidenceInventory(evidence.records)}
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

      <section class="section" aria-labelledby="history-heading">
        ${sectionHeading("history-heading", "Corrections and notes", "Corrections are appended to the local ledger. Earlier events remain visible; replay marks the corrected boundary as historical and uses the newer boundary as effective state.")}
        <div id="experiment-history" aria-live="polite"><p class="empty-value">Loading local history…</p></div>
      </section>

      <footer class="report-footer">
        <span>Companion-derived report · Engine ${escapeHtml(text(report.engine_version, "engine version"))} · Schema ${integer(report.schema_version, "schema version")}</span>
        <code>${escapeHtml(text(report.record_id, "report identifier"))}</code>
        <span>${array(provenance.source_record_ids, "source records").length} linked source records</span>
      </footer>
    </article>`;
}

export function renderExperimentHistory(envelope) {
  const value = object(envelope, "experiment history envelope");
  if (value.format !== "pap-pilot.experiment-history-json" || value.format_version !== 1) {
    throw new Error("The local API returned an unsupported experiment history format.");
  }
  const history = array(value.history, "experiment history");
  const boundary = value.effective_boundary === null ? null : object(value.effective_boundary, "effective boundary");
  const correctionSurface = boundary === null
    ? `<div class="history-unavailable"><h3>No confirmed boundary to correct</h3><p>The retained retrospective record does not contain a user-confirmed application timestamp. PAP Pilot will not invent one.</p></div>`
    : `<form id="boundary-correction-form" class="correction-form" data-corrected-event-id="${escapeHtml(text(boundary.record_id, "boundary event identifier"))}">
        <div><label for="applied-at">Corrected application time</label><input id="applied-at" name="applied-at" type="datetime-local" required></div>
        <div><label for="correction-note">Reason or note</label><textarea id="correction-note" name="correction-note" maxlength="4000" required></textarea></div>
        <button type="submit">Append correction and note</button><p class="form-status" role="status"></p>
      </form>`;
  return `<div class="history-layout">${correctionSurface}<div class="history-ledger"><h3>Complete event history</h3><ol>${history.map(renderHistoryEvent).join("")}</ol></div></div>`;
}

function renderHistoryEvent(value) {
  const event = object(value, "history event");
  const eventType = text(event.event_type, "history event type");
  const effective = event.effective === true;
  const details = [];
  if (Number.isInteger(event.applied_at_ms)) details.push(`Boundary: ${new Date(event.applied_at_ms).toLocaleString()}`);
  if (typeof event.note === "string" && event.note.trim()) details.push(event.note);
  if (typeof event.correction_of_event_id === "string") details.push(`Corrects ${event.correction_of_event_id}`);
  return `<li class="history-event ${effective ? "history-event-effective" : "history-event-corrected"}"><div><strong>${escapeHtml(label(eventType))}</strong><span>Event ${integer(event.sequence_number, "event sequence number")} · ${effective ? "effective" : "corrected history"}</span></div>${details.map((detail) => `<p>${escapeHtml(detail)}</p>`).join("")}<code>${escapeHtml(text(event.record_id, "history event identifier"))}</code></li>`;
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

function renderInterval(value, evidenceTargets) {
  const interval = object(value, "representative interval");
  const state = text(interval.availability, "interval availability");
  const period = text(interval.period, "interval period");
  if (!(period === "baseline" || period === "intervention")) {
    throw new Error("A representative interval has an unsupported period.");
  }
  const sourceRecordIds = textArray(interval.source_record_ids, "interval source identifiers");
  if (state === "missing") {
    if (interval.interval_record_id !== null || interval.start_ms !== null || interval.end_ms !== null) {
      throw new Error("A missing representative interval cannot contain bounds or an identifier.");
    }
    return `
      <article class="interval-card interval-card-missing" data-period="${escapeHtml(period)}">
        <small>${escapeHtml(label(period))}</small>
        <div class="card-row"><h3>Waveform interval</h3>${badge(state)}</div>
        <p class="empty-value">Not available</p>
        <p class="waveform-missing-copy">No attributable interval or signal excerpt was supplied, so no waveform is drawn.</p>
        ${reasonLine(interval.reason_codes)}
        ${renderEvidenceLinks(sourceRecordIds, evidenceTargets)}
      </article>`;
  }
  if (state !== "available") {
    throw new Error("A representative interval has an unsupported availability state.");
  }

  const intervalRecordId = text(interval.interval_record_id, "interval identifier");
  const startMs = finiteNumber(interval.start_ms, "interval start");
  const endMs = finiteNumber(interval.end_ms, "interval end");
  const durationMs = endMs - startMs;
  if (startMs >= endMs || !Number.isFinite(durationMs)) {
    throw new Error("A representative interval must have positive half-open bounds.");
  }
  if (interval.display_contract_version !== WAVEFORM_DISPLAY_CONTRACT_VERSION) {
    throw new Error("A representative interval has an unsupported waveform display contract.");
  }
  const signals = array(interval.signals, "representative interval signals");
  if (!signals.length || signals.length > MAX_WAVEFORM_SIGNALS) {
    throw new Error("A representative interval requires one to three bounded signal excerpts.");
  }
  const signalKinds = signals.map((signal) => text(object(signal, "waveform signal").signal_kind, "signal kind"));
  if (new Set(signalKinds).size !== signalKinds.length) {
    throw new Error("A representative interval cannot repeat a signal kind.");
  }
  const allEvidenceIds = [...new Set([intervalRecordId, ...sourceRecordIds, ...signals.flatMap((signal) => textArray(object(signal, "waveform signal").source_record_ids, "signal source identifiers"))])];
  return `
    <article class="interval-card interval-card-available" data-period="${escapeHtml(period)}">
      <small>${escapeHtml(label(period))}</small>
      <div class="card-row"><h3>Waveform interval</h3>${badge(state)}</div>
      <p class="interval-window"><span>${escapeHtml(formatTimestamp(startMs))}</span><span aria-hidden="true">→</span><span>${escapeHtml(formatTimestamp(endMs))}</span></p>
      <p class="interval-duration">${escapeHtml(formatDuration(endMs - startMs))} preselected window · raw-relative milliseconds</p>
      ${reasonLine(interval.reason_codes)}
      <div class="waveform-stack">${signals.map((signal, index) => renderSignalSafely(signal, period, index, startMs, endMs, evidenceTargets)).join("")}</div>
      ${renderEvidenceLinks(allEvidenceIds, evidenceTargets)}
    </article>`;
}

function renderSignalSafely(value, period, index, intervalStartMs, intervalEndMs, evidenceTargets) {
  try {
    return renderSignal(value, period, index, intervalStartMs, intervalEndMs, evidenceTargets);
  } catch (error) {
    const message = error instanceof Error ? error.message : "The signal excerpt is invalid.";
    return `<section class="waveform-failure" role="alert"><h4>Signal unavailable</h4><p>${escapeHtml(message)} No values were estimated or drawn.</p></section>`;
  }
}

function renderSignal(value, period, index, intervalStartMs, intervalEndMs, evidenceTargets) {
  const signal = object(value, "waveform signal");
  const signalKind = text(signal.signal_kind, "signal kind");
  const spec = SIGNAL_SPECS[signalKind];
  if (!spec) {
    throw new Error("The signal kind is unsupported.");
  }
  const state = text(signal.availability, "signal availability");
  const unit = text(signal.unit, "signal unit");
  if (unit !== spec.unit) {
    throw new Error(`${spec.label} must retain its ${spec.unit} unit.`);
  }
  const sourceRecordIds = textArray(signal.source_record_ids, "signal source identifiers");
  const reasonCodes = array(signal.reason_codes, "signal reason codes");
  if (state === "missing") {
    if (signal.signal_record_id !== null || signal.representation !== null || array(signal.sample_times_ms, "signal sample times").length || array(signal.values, "signal values").length) {
      throw new Error("A missing signal cannot contain an identifier, representation, or samples.");
    }
    return `
      <section class="waveform-panel waveform-panel-missing" data-signal-kind="${escapeHtml(signalKind)}">
        <div class="waveform-heading"><div><h4>${escapeHtml(spec.label)}</h4><p>${escapeHtml(unit)}</p></div>${badge(state)}</div>
        <p class="empty-value">Not available</p>
        <p class="waveform-missing-copy">This signal excerpt was not supplied and no trace was inferred.</p>
        ${reasonLine(reasonCodes)}
        ${renderEvidenceLinks(sourceRecordIds, evidenceTargets)}
      </section>`;
  }
  if (state !== "available") {
    throw new Error(`${spec.label} has an unsupported availability state.`);
  }

  const signalRecordId = text(signal.signal_record_id, "signal identifier");
  const representation = text(signal.representation, "signal representation");
  if (representation !== spec.representation) {
    throw new Error(`${spec.label} has an unsupported sample representation.`);
  }
  const times = numericArray(signal.sample_times_ms, "signal sample times");
  const values = numericArray(signal.values, "signal values");
  if (times.length < 2 || times.length > MAX_WAVEFORM_POINTS || times.length !== values.length) {
    throw new Error(`The ${spec.label} excerpt must contain two to ${MAX_WAVEFORM_POINTS} paired samples.`);
  }
  if (times.some((time, sampleIndex) => time < intervalStartMs || time >= intervalEndMs || (sampleIndex > 0 && time <= times[sampleIndex - 1]))) {
    throw new Error(`The ${spec.label} sample times must be strictly increasing inside the selected interval.`);
  }

  const plot = waveformPlot(times, values, intervalStartMs, intervalEndMs, representation);
  const titleId = `waveform-title-${period}-${signalKind}-${index}`;
  const signalEvidenceIds = [...new Set([signalRecordId, ...sourceRecordIds])];
  return `
    <section class="waveform-panel" data-signal-kind="${escapeHtml(signalKind)}" data-unit="${escapeHtml(unit)}">
      <div class="waveform-heading"><div><h4>${escapeHtml(spec.label)}</h4><p>${escapeHtml(unit)} · ${times.length} supplied samples</p></div>${badge(state)}</div>
      <svg class="waveform-chart ${escapeHtml(spec.colorClass)}" viewBox="0 0 ${WAVEFORM_WIDTH} ${WAVEFORM_HEIGHT}" role="img" aria-labelledby="${titleId}">
        <title id="${titleId}">${escapeHtml(`${label(period)} ${spec.label}, ${unit}, ${times.length} supplied samples`)}</title>
        <line class="waveform-axis" x1="${WAVEFORM_PADDING.left}" y1="${WAVEFORM_PADDING.top}" x2="${WAVEFORM_PADDING.left}" y2="${WAVEFORM_HEIGHT - WAVEFORM_PADDING.bottom}"></line>
        <line class="waveform-axis" x1="${WAVEFORM_PADDING.left}" y1="${WAVEFORM_HEIGHT - WAVEFORM_PADDING.bottom}" x2="${WAVEFORM_WIDTH - WAVEFORM_PADDING.right}" y2="${WAVEFORM_HEIGHT - WAVEFORM_PADDING.bottom}"></line>
        ${plot.zeroY === null ? "" : `<line class="waveform-zero" x1="${WAVEFORM_PADDING.left}" y1="${plot.zeroY}" x2="${WAVEFORM_WIDTH - WAVEFORM_PADDING.right}" y2="${plot.zeroY}"></line>`}
        <path class="waveform-trace" d="${plot.path}"></path>
        <text class="waveform-axis-label" x="${WAVEFORM_PADDING.left - 8}" y="${WAVEFORM_PADDING.top + 4}" text-anchor="end">${escapeHtml(formatValue(plot.maximum))}</text>
        <text class="waveform-axis-label" x="${WAVEFORM_PADDING.left - 8}" y="${WAVEFORM_HEIGHT - WAVEFORM_PADDING.bottom + 4}" text-anchor="end">${escapeHtml(formatValue(plot.minimum))}</text>
        <text class="waveform-axis-label" x="${WAVEFORM_PADDING.left}" y="${WAVEFORM_HEIGHT - 8}">0 s</text>
        <text class="waveform-axis-label" x="${WAVEFORM_WIDTH - WAVEFORM_PADDING.right}" y="${WAVEFORM_HEIGHT - 8}" text-anchor="end">${escapeHtml(formatDuration(intervalEndMs - intervalStartMs))}</text>
      </svg>
      <p class="waveform-contract">${representation === "timed_updates" ? "Stored updates shown as steps" : "Supplied samples connected without smoothing"} · display range ${escapeHtml(formatValue(plot.minimum))}–${escapeHtml(formatValue(plot.maximum))} ${escapeHtml(unit)}</p>
      ${reasonLine(reasonCodes)}
      ${renderEvidenceLinks(signalEvidenceIds, evidenceTargets)}
    </section>`;
}

function waveformPlot(times, values, intervalStartMs, intervalEndMs, representation) {
  const left = WAVEFORM_PADDING.left;
  const right = WAVEFORM_WIDTH - WAVEFORM_PADDING.right;
  const top = WAVEFORM_PADDING.top;
  const bottom = WAVEFORM_HEIGHT - WAVEFORM_PADDING.bottom;
  const rawMinimum = Math.min(...values);
  const rawMaximum = Math.max(...values);
  const rawRange = rawMaximum - rawMinimum;
  if (!Number.isFinite(rawRange)) {
    throw new Error("The signal value range cannot be plotted safely.");
  }
  const padding = rawMaximum === rawMinimum ? Math.max(Math.abs(rawMaximum) * 0.05, 1) : rawRange * 0.08;
  const minimum = rawMinimum - padding;
  const maximum = rawMaximum + padding;
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || minimum >= maximum) {
    throw new Error("The signal display range cannot be plotted safely.");
  }
  const x = (time) => left + ((time - intervalStartMs) / (intervalEndMs - intervalStartMs)) * (right - left);
  const y = (value) => top + ((maximum - value) / (maximum - minimum)) * (bottom - top);
  const coordinates = times.map((time, index) => [rounded(x(time)), rounded(y(values[index]))]);
  if (coordinates.some(([horizontal, vertical]) => !Number.isFinite(horizontal) || !Number.isFinite(vertical))) {
    throw new Error("The signal coordinates cannot be plotted safely.");
  }
  let path = `M ${coordinates[0][0]} ${coordinates[0][1]}`;
  for (let index = 1; index < coordinates.length; index += 1) {
    const [nextX, nextY] = coordinates[index];
    path += representation === "timed_updates" ? ` H ${nextX} V ${nextY}` : ` L ${nextX} ${nextY}`;
  }
  const zeroY = minimum <= 0 && maximum >= 0 ? rounded(y(0)) : null;
  return {path, zeroY, minimum: rawMinimum, maximum: rawMaximum};
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

function evidenceIndex(values) {
  const records = textArray(values, "source records");
  if (new Set(records).size !== records.length) {
    throw new Error("The report source-record inventory contains duplicates.");
  }
  return {records, targets: new Map(records.map((recordId, index) => [recordId, `evidence-source-${index + 1}`]))};
}

function renderEvidenceInventory(records) {
  return `<ol class="evidence-source-list">${records.map((recordId, index) => `<li id="evidence-source-${index + 1}"><code>${escapeHtml(recordId)}</code></li>`).join("")}</ol>`;
}

function renderEvidenceLinks(sourceRecordIds, evidenceTargets) {
  if (!sourceRecordIds.length) {
    return `<p class="evidence-links evidence-links-missing"><strong>Evidence links</strong><span>Not available</span></p>`;
  }
  return `
    <div class="evidence-links">
      <strong>Evidence links</strong>
      <ul>${sourceRecordIds.map((recordId) => {
        const target = evidenceTargets.get(recordId);
        return target
          ? `<li><a href="#${target}"><code>${escapeHtml(recordId)}</code></a></li>`
          : `<li><span class="evidence-link-unresolved" title="This identifier is absent from the report provenance inventory"><code>${escapeHtml(recordId)}</code> · unresolved</span></li>`;
      }).join("")}</ul>
    </div>`;
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

function textArray(value, labelName) {
  return array(value, labelName).map((entry) => text(entry, labelName));
}

function numericArray(value, labelName) {
  return array(value, labelName).map((entry) => finiteNumber(entry, labelName));
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

function finiteNumber(value, labelName) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`The ${labelName} is missing or invalid.`);
  }
  return value;
}

function rounded(value) {
  const result = Math.round(value * 100) / 100;
  return Object.is(result, -0) ? 0 : result;
}

function formatTimestamp(value) {
  return `${String(value)} ms`;
}

function formatDuration(milliseconds) {
  return `${formatValue(milliseconds / 1000)} s`;
}

function formatValue(value) {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
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
    await loadExperimentHistory();
  } catch (error) {
    root.innerHTML = renderOverviewError(error instanceof Error ? error.message : "The local report could not be loaded.");
  } finally {
    root.setAttribute("aria-busy", "false");
  }
}

async function loadExperimentHistory() {
  const target = document.querySelector("#experiment-history");
  if (!target) return;
  try {
    const response = await fetch(HISTORY_ENDPOINT, {cache: "no-store", headers: {Accept: "application/json"}});
    if (!response.ok) throw new Error(`History returned HTTP ${response.status}.`);
    target.innerHTML = renderExperimentHistory(await response.json());
    bindCorrectionForm(target);
  } catch (error) {
    target.innerHTML = `<div class="history-unavailable" role="alert"><h3>Local history unavailable</h3><p>${escapeHtml(error instanceof Error ? error.message : "The history could not be loaded.")}</p></div>`;
  }
}

function bindCorrectionForm(target) {
  const form = target.querySelector("#boundary-correction-form");
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = form.querySelector(".form-status");
    const appliedAt = form.querySelector("#applied-at");
    const note = form.querySelector("#correction-note");
    const appliedAtMs = new Date(appliedAt.value).getTime();
    if (!Number.isInteger(appliedAtMs)) {
      status.textContent = "Enter a valid local date and time.";
      return;
    }
    status.textContent = "Saving append-only events…";
    try {
      const response = await fetch(BOUNDARY_CORRECTION_ENDPOINT, {
        method: "POST",
        headers: {Accept: "application/json", "Content-Type": "application/json"},
        body: JSON.stringify({corrected_event_id: form.dataset.correctedEventId, applied_at_ms: appliedAtMs, note: note.value}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : `Save returned HTTP ${response.status}.`);
      target.innerHTML = renderExperimentHistory(payload);
      bindCorrectionForm(target);
      const updatedStatus = target.querySelector(".form-status");
      if (updatedStatus) updatedStatus.textContent = "Correction and note appended. Earlier history remains below.";
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "The correction could not be saved.";
    }
  });
}

if (typeof document !== "undefined") {
  loadOverview();
}

export {BOUNDARY_CORRECTION_ENDPOINT, HISTORY_ENDPOINT, SUMMARY_ENDPOINT};
