const RESOURCE_FORMAT = "pap-pilot.analysis-resource-json";
const RESOURCE_VERSION = 1;
const DETAIL_SCHEMA = "pap-pilot.analysis-night-detail";
const DETAIL_SCHEMA_VERSION = 1;
const SIGNAL_PREVIEW_MAX_SAMPLES = 2000;
const WAVEFORM_WIDTH = 760;
const WAVEFORM_HEIGHT = 210;
const WAVEFORM_PADDING = Object.freeze({top: 18, right: 18, bottom: 34, left: 62});

const LABELS = Object.freeze({
  available: "Available",
  partial: "Partial",
  unavailable: "Unavailable",
  not_evaluable: "Not evaluable",
  uniform_waveform: "Uniform waveform",
  timed_updates: "Timed updates",
  pass: "Pass",
  flagged: "Flagged",
  insufficient_evidence: "Insufficient evidence",
  not_applicable: "Not applicable",
  none: "No exclusion",
  caution: "Caution",
  exclude_interval: "Exclude interval",
  exclude_session: "Exclude session",
  block_requested_analysis: "Blocks requested analysis",
});

export function renderNightDetail(envelope) {
  const payload = object(envelope, "night-detail envelope");
  if (payload.format !== RESOURCE_FORMAT || payload.format_version !== RESOURCE_VERSION) throw new Error("The local API returned an unsupported night-detail format.");
  const resource = object(payload.resource, "night-detail resource");
  if (resource.kind !== "night_detail") throw new Error("The local API returned an unexpected night-detail resource.");
  const night = object(payload.night, "analysis night");
  const detail = object(payload.detail, "night evidence detail");
  if (detail.schema_id !== DETAIL_SCHEMA || detail.schema_version !== DETAIL_SCHEMA_VERSION) throw new Error("The local API returned an unsupported night-evidence schema.");
  const nightId = text(detail.night_record_id, "night identifier");
  if (nightId !== text(night.night_record_id, "analysis-night identifier") || resource.target_record_id !== nightId) throw new Error("The night-detail identifiers do not agree.");

  const sessions = objectArray(detail.sessions, "night sessions");
  const settings = objectArray(detail.settings, "night settings");
  const events = objectArray(detail.events, "night events");
  const signals = objectArray(detail.signals, "night signals");
  const findings = objectArray(detail.quality_findings, "quality findings");
  const sourceIds = textArray(detail.source_record_ids, "source record identifiers");
  const provenanceIds = textArray(detail.source_provenance_ids, "source provenance identifiers");
  const provenance = objectArray(detail.provenance, "provenance records");
  const links = sourceLinkIndex(sourceIds, provenanceIds);
  const state = text(detail.availability, "night-detail availability");

  return `
    <article class="night-detail" data-night-id="${escapeHtml(nightId)}">
      <a class="back-link" href="/">← All PAP nights</a>
      <section class="hero detail-hero" aria-labelledby="night-title">
        <div>
          <p class="eyebrow">Therapy-night evidence · Local only</p>
          <h1 id="night-title"><time datetime="${escapeHtml(text(detail.local_date, "night local date"))}">${escapeHtml(detail.local_date)}</time></h1>
          <p class="hero-copy">Inspect the normalized source record without a settings experiment. Signal charts are bounded previews of exact stored samples; quality findings remain separate from the therapy evidence.</p>
        </div>
        <aside class="status-panel status-panel-${escapeHtml(stateClass(state))}" aria-label="Night evidence availability">
          <div class="status-label">Evidence status</div>
          <p class="status-value">${escapeHtml(displayLabel(state))}</p>
          <p class="status-detail">${sessions.length} ${plural(sessions.length, "session")} · ${signals.length} signal ${plural(signals.length, "record")} · ${findings.length} quality ${plural(findings.length, "finding")}</p>
          ${reasonLine(detail.reason_codes)}
        </aside>
      </section>

      <section class="summary-grid detail-summary" aria-label="Night evidence inventory">
        ${summaryCard("Sessions", sessions.length, detail.sessions_availability)}
        ${summaryCard("Settings", settings.length, detail.settings_availability)}
        ${summaryCard("Events", events.length, detail.events_availability)}
        ${summaryCard("Signals", signals.length, detail.signals_availability)}
      </section>

      <section class="section" aria-labelledby="sessions-heading">
        ${sectionHeading("sessions-heading", "Therapy sessions", "Exact normalized boundaries and device identifiers. Timestamps remain source milliseconds and are also displayed as UTC instants for orientation.")}
        ${renderSessions(sessions, links, detail)}
      </section>

      <section class="section" aria-labelledby="settings-heading">
        ${sectionHeading("settings-heading", "Observed settings", "These are recorded observations from the normalized source. PAP Pilot does not treat them as prescriptions or write them to a device.")}
        ${renderSettings(settings, detail, links)}
      </section>

      <section class="section" aria-labelledby="events-heading">
        ${sectionHeading("events-heading", "Machine-labeled events", "Event names, start times, and durations are retained as source evidence. Absence is not interpreted as proof that no respiratory event occurred.")}
        ${renderEvents(events, detail, links)}
      </section>

      <section class="section" aria-labelledby="signals-heading">
        ${sectionHeading("signals-heading", "Signal evidence", "Each chart shows only the first stored source segment and no more than 2,000 exact samples. Timed updates are points; waveform samples are joined only within that one segment.")}
        ${renderSignals(signals, detail, links)}
      </section>

      <section class="section" aria-labelledby="quality-heading">
        ${sectionHeading("quality-heading", "Data-quality findings", "Every existing deterministic rule result is shown with its status, impact, measurements, limitations, and source links. No combined quality score is invented.")}
        ${renderQuality(findings, detail, links)}
      </section>

      <section class="section" aria-labelledby="sources-heading">
        ${sectionHeading("sources-heading", "Sources and provenance", "Evidence links above resolve here. Provenance retains the producing system, transformation class, and upstream source references supplied by the normalized records.")}
        ${renderSources(sourceIds, provenanceIds, provenance, links)}
      </section>

      <section class="section" aria-labelledby="limits-heading">
        ${sectionHeading("limits-heading", "Evidence boundaries", "These limits travel with this versioned night-detail projection.")}
        <div class="content-card">${renderList(textArray(detail.limitations, "night-detail limitations"), "No limitations were supplied.")}</div>
      </section>

      <footer class="report-footer">
        <span>${escapeHtml(detail.timezone === null ? "Timezone unavailable" : text(detail.timezone, "night timezone"))} · day boundary ${escapeHtml(detail.day_boundary_local_time === null ? "unavailable" : text(detail.day_boundary_local_time, "day boundary"))}</span>
        <code>${escapeHtml(text(detail.record_id, "night-detail record identifier"))}</code>
        <span>Schema ${integer(detail.schema_version, "night-detail schema version")} · ${sourceIds.length} source records · ${provenanceIds.length} provenance records</span>
      </footer>
    </article>`;
}

export function renderNightDetailError(message) {
  return `<section class="error-panel" role="alert"><p class="eyebrow">Night evidence unavailable</p><h1>This therapy-night record could not be loaded.</h1><p>${escapeHtml(typeof message === "string" && message.trim() ? message : "The local API did not return usable night evidence.")}</p><p>No event, sample, setting, or quality state has been inferred. Return to the overview or check the local workspace configuration.</p><a class="path-link error-back" href="/">Return to PAP analysis</a></section>`;
}

function renderSessions(sessions, links, detail) {
  if (!sessions.length) return emptyCard("Session details are unavailable", "The summary identifies this night, but no normalized session detail was supplied.", detail.sessions_availability, detail.sessions_reason_codes);
  return `<div class="session-grid">${sessions.map((session) => `<article class="content-card session-card"><div class="card-row"><div><p class="card-kicker">Therapy session</p><h3>${escapeHtml(text(session.device_id, "session device identifier"))}</h3></div>${sourceLinks(session.source_record_ids, session.source_provenance_ids, links)}</div><dl class="detail-list"><div><dt>Start</dt><dd>${timestamp(session.start_time_ms, "session start")}</dd></div><div><dt>End</dt><dd>${timestamp(session.end_time_ms, "session end")}</dd></div><div><dt>Duration</dt><dd>${duration(number(session.end_time_ms, "session end") - number(session.start_time_ms, "session start"))}</dd></div><div><dt>Record</dt><dd><code>${escapeHtml(text(session.session_record_id, "session identifier"))}</code></dd></div></dl></article>`).join("")}</div>`;
}

function renderSettings(settings, detail, links) {
  if (!settings.length) return emptyCard("Settings are unavailable", "No normalized settings were supplied for this night. Values have not been carried forward from another session.", detail.settings_availability, detail.settings_reason_codes);
  return `<div class="table-card"><table><thead><tr><th scope="col">Setting</th><th scope="col">Value</th><th scope="col">Session</th><th scope="col">Evidence</th></tr></thead><tbody>${settings.map((setting) => `<tr><th scope="row">${escapeHtml(text(setting.name, "setting name"))}</th><td class="value-cell">${scalar(setting.value)}${setting.unit === null ? "" : ` <span>${escapeHtml(text(setting.unit, "setting unit"))}</span>`}</td><td><code>${escapeHtml(text(setting.session_record_id, "setting session identifier"))}</code></td><td>${sourceLinks(setting.source_record_ids, setting.source_provenance_ids, links)}</td></tr>`).join("")}</tbody></table></div>`;
}

function renderEvents(events, detail, links) {
  if (!events.length) return emptyCard("No normalized event records are available", "The configured source supplied no machine-labeled event occurrences for this night. PAP Pilot does not turn that absence into a zero event rate.", detail.events_availability, detail.events_reason_codes);
  return `<div class="event-list">${events.map((event) => `<article class="content-card event-card"><div><p class="card-kicker">Machine label</p><h3>${escapeHtml(displayLabel(text(event.event_kind, "event kind")))}</h3><p>${timestamp(event.start_time_ms, "event start")} · ${duration(event.duration_ms)}</p></div><div class="event-evidence"><strong>${escapeHtml(formatNumber(number(event.duration_ms, "event duration")))} ms</strong>${sourceLinks(event.source_record_ids, event.source_provenance_ids, links)}</div></article>`).join("")}</div>`;
}

function renderSignals(signals, detail, links) {
  if (!signals.length) return emptyCard("Signal evidence is unavailable", "No normalized signal records were supplied for this night. No waveform has been estimated.", detail.signals_availability, detail.signals_reason_codes);
  return `<div class="signal-grid">${signals.map((signal) => renderSignal(signal, links)).join("")}</div>${reasonLine(detail.signals_reason_codes)}`;
}

function renderSignal(signal, links) {
  const state = text(signal.availability, "signal availability");
  const times = numberArray(signal.sample_times_ms, "signal sample times");
  const values = numberArray(signal.values, "signal values");
  if (times.length !== values.length || integer(signal.displayed_sample_count, "displayed sample count") !== values.length || values.length > SIGNAL_PREVIEW_MAX_SAMPLES) throw new Error("A signal preview violates the bounded sample contract.");
  const labelText = displayLabel(text(signal.signal_kind, "signal kind"));
  const chart = state === "available" && values.length ? waveform(signal, times, values, labelText) : `<div class="plot-unavailable"><strong>No stored sample preview</strong><span>${escapeHtml(textArray(signal.reason_codes, "signal reason codes").join(" · ") || "Signal samples unavailable")}</span></div>`;
  const omitted = integer(signal.omitted_sample_count, "omitted sample count");
  return `<article class="signal-card">
    <div class="signal-heading"><div><p class="card-kicker">${escapeHtml(displayLabel(text(signal.representation, "signal representation")))}</p><h3>${escapeHtml(labelText)}</h3><p>${escapeHtml(text(signal.unit, "signal unit"))}${signal.value_semantics === null ? "" : ` · ${escapeHtml(text(signal.value_semantics, "signal semantics"))}`}</p></div>${badge(state)}</div>
    ${chart}
    ${renderSignalMetadata(signal, state)}
    <div class="signal-facts"><span><strong>${values.length}</strong> displayed samples</span><span><strong>${integer(signal.source_sample_count, "source sample count")}</strong> source samples</span><span><strong>${omitted}</strong> omitted samples</span><span><strong>${integer(signal.source_segment_count, "source segment count")}</strong> source ${plural(integer(signal.source_segment_count, "source segment count"), "segment")}</span></div>
    <p class="preview-policy">${signal.preview_selection === null ? "No preview selection was possible." : `${escapeHtml(text(signal.preview_selection, "preview selection"))}. ${omitted ? "The response is intentionally truncated." : "All samples in the selected segment are displayed."}`}</p>
    ${renderList(textArray(signal.limitations, "signal limitations"), "No signal limitations were supplied.")}
    ${sourceLinks(signal.source_record_ids, signal.source_provenance_ids, links)}
    ${reasonLine(signal.reason_codes)}
  </article>`;
}

function renderSignalMetadata(signal, state) {
  if (state !== "available") return "";
  const segmentId = text(signal.selected_segment_record_id, "selected segment identifier");
  const interval = signal.sample_interval_ms === null ? "Stored timestamps" : `${escapeHtml(formatNumber(number(signal.sample_interval_ms, "sample interval")))} ms`;
  return `<dl class="detail-list signal-meta"><div><dt>Segment</dt><dd><code>${escapeHtml(segmentId)}</code></dd></div><div><dt>Source bounds</dt><dd>${timestamp(signal.selected_segment_start_time_ms, "selected segment start")} through ${timestamp(signal.selected_segment_end_time_ms, "selected segment end")}</dd></div><div><dt>Closure</dt><dd>${escapeHtml(displayLabel(text(signal.selected_segment_interval_closure, "selected segment interval closure")))}</dd></div><div><dt>Sampling</dt><dd>${interval}</dd></div></dl>`;
}

function waveform(signal, times, values, labelText) {
  const left = WAVEFORM_PADDING.left;
  const right = WAVEFORM_WIDTH - WAVEFORM_PADDING.right;
  const top = WAVEFORM_PADDING.top;
  const bottom = WAVEFORM_HEIGHT - WAVEFORM_PADDING.bottom;
  const minimumTime = Math.min(...times);
  const maximumTime = Math.max(...times);
  const minimumValue = Math.min(...values);
  const maximumValue = Math.max(...values);
  const valuePadding = minimumValue === maximumValue ? Math.max(Math.abs(minimumValue) * 0.05, 1) : (maximumValue - minimumValue) * 0.08;
  const low = minimumValue - valuePadding;
  const high = maximumValue + valuePadding;
  const x = (value) => minimumTime === maximumTime ? (left + right) / 2 : left + ((value - minimumTime) / (maximumTime - minimumTime)) * (right - left);
  const y = (value) => top + ((high - value) / (high - low)) * (bottom - top);
  const points = times.map((value, index) => `${rounded(x(value))},${rounded(y(values[index]))}`).join(" ");
  const representation = text(signal.representation, "signal representation");
  const marks = representation === "uniform_waveform" ? `<polyline class="waveform-line" points="${points}"></polyline>` : times.map((value, index) => `<circle class="timed-update-point" cx="${rounded(x(value))}" cy="${rounded(y(values[index]))}" r="4"></circle>`).join("");
  return `<svg class="waveform-chart" viewBox="0 0 ${WAVEFORM_WIDTH} ${WAVEFORM_HEIGHT}" role="img" aria-label="${escapeHtml(`${labelText}: ${values.length} exact source samples from one stored segment`)}"><line class="trend-gridline" x1="${left}" y1="${top}" x2="${right}" y2="${top}"></line><line class="trend-gridline" x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}"></line>${marks}<text class="trend-axis-label" x="${left - 8}" y="${top + 4}" text-anchor="end">${escapeHtml(formatNumber(maximumValue))}</text><text class="trend-axis-label" x="${left - 8}" y="${bottom + 4}" text-anchor="end">${escapeHtml(formatNumber(minimumValue))}</text><text class="trend-axis-label" x="${left}" y="${WAVEFORM_HEIGHT - 9}">${escapeHtml(formatOffset(minimumTime, minimumTime))}</text><text class="trend-axis-label" x="${right}" y="${WAVEFORM_HEIGHT - 9}" text-anchor="end">${escapeHtml(formatOffset(maximumTime, minimumTime))}</text></svg>`;
}

function renderQuality(findings, detail, links) {
  if (!findings.length) return emptyCard("Quality findings are unavailable", "No deterministic quality finding was supplied. Their absence is not interpreted as clean data.", detail.quality_availability, detail.quality_reason_codes);
  const counts = new Map();
  for (const finding of findings) counts.set(finding.status, (counts.get(finding.status) || 0) + 1);
  return `<div class="quality-summary">${[...counts].map(([state, count]) => `<span>${qualityBadge(state)}<strong>${count}</strong></span>`).join("")}</div><div class="finding-list">${findings.map((finding) => renderFinding(finding, links)).join("")}</div>${reasonLine(detail.quality_reason_codes)}`;
}

function renderFinding(finding, links) {
  const parameters = valueTriples(finding.parameters, "quality parameters");
  const measurements = valueTriples(finding.measurements, "quality measurements");
  return `<article class="finding-card finding-${escapeHtml(stateClass(text(finding.status, "quality status")))}"><div class="finding-heading"><div><p class="card-kicker">${escapeHtml(text(finding.report_kind, "quality report kind"))} quality · ${escapeHtml(text(finding.quality_report_id, "quality report identifier"))}</p><h3>${escapeHtml(displayLabel(text(finding.rule_id, "quality rule")))}</h3></div><div class="finding-badges">${qualityBadge(finding.status)}<span class="impact-chip">${escapeHtml(displayLabel(text(finding.impact, "quality impact")))}</span></div></div><p class="reason-line">${escapeHtml(text(finding.reason_code, "quality reason code"))}</p>${finding.start_time_ms === null ? "" : `<p class="finding-interval">Affected interval: ${timestamp(finding.start_time_ms, "finding start")} through ${timestamp(finding.end_time_ms, "finding end")}</p>`}<div class="finding-values">${valueGroup("Parameters", parameters)}${valueGroup("Measurements", measurements)}</div><p class="finding-scope">Evaluated <code>${escapeHtml(text(finding.evaluated_record_id, "evaluated record identifier"))}</code>${finding.session_record_id === null ? "" : ` · session <code>${escapeHtml(text(finding.session_record_id, "quality session identifier"))}</code>`}</p>${renderList(textArray(finding.affected_capabilities, "affected capabilities"), "No capabilities were listed.")}${renderList(textArray(finding.limitations, "quality limitations"), "No finding limitations were supplied.")}${sourceLinks(finding.source_record_ids, finding.source_provenance_ids, links)}</article>`;
}

function valueGroup(title, values) {
  return `<div><h4>${escapeHtml(title)}</h4>${values.length ? `<dl>${values.map((value) => `<div><dt>${escapeHtml(value[0])}</dt><dd>${scalar(value[1])}${value[2] === null ? "" : ` ${escapeHtml(value[2])}`}</dd></div>`).join("")}</dl>` : '<p class="empty-value">None supplied</p>'}</div>`;
}

function renderSources(sourceIds, provenanceIds, provenance, links) {
  const provenanceById = new Map(provenance.map((value) => [text(value.provenance_record_id, "provenance identifier"), value]));
  return `<div class="source-columns"><article class="content-card"><p class="card-kicker">Linked records</p><h3>Source inventory</h3><ol class="source-inventory">${sourceIds.map((identifier) => `<li id="${links.source.get(identifier)}"><code>${escapeHtml(identifier)}</code></li>`).join("")}</ol></article><article class="content-card"><p class="card-kicker">Transformation chain</p><h3>Provenance inventory</h3><ol class="provenance-inventory">${provenanceIds.map((identifier) => renderProvenance(identifier, provenanceById.get(identifier), links)).join("")}</ol></article></div>`;
}

function renderProvenance(identifier, value, links) {
  const anchor = links.provenance.get(identifier);
  if (!value) return `<li id="${anchor}"><code>${escapeHtml(identifier)}</code><p>Referenced parent provenance; its full record is outside this bounded night projection.</p></li>`;
  const references = array(value.source_references, "upstream source references").map((entry) => array(entry, "upstream source reference"));
  return `<li id="${anchor}"><code>${escapeHtml(identifier)}</code><p>${escapeHtml(text(value.source_system, "provenance source system"))} · ${textArray(value.source_classes, "provenance source classes").map(displayLabel).map(escapeHtml).join(", ")} · producer ${escapeHtml(text(value.producer, "provenance producer"))} ${escapeHtml(text(value.producer_version, "provenance producer version"))}</p>${references.length ? `<ul>${references.map((entry) => `<li><strong>${escapeHtml(text(entry[0], "source reference type"))}</strong> <code>${escapeHtml(text(entry[1], "source reference identifier"))}</code></li>`).join("")}</ul>` : ""}</li>`;
}

function sourceLinkIndex(sourceIds, provenanceIds) {
  return {
    source: new Map(sourceIds.map((identifier, index) => [identifier, `source-record-${index + 1}`])),
    provenance: new Map(provenanceIds.map((identifier, index) => [identifier, `source-provenance-${index + 1}`])),
  };
}

function sourceLinks(sourceValues, provenanceValues, links) {
  const sources = textArray(sourceValues, "linked source identifiers");
  const provenance = textArray(provenanceValues, "linked provenance identifiers");
  return `<details class="source-links"><summary>${sources.length} source · ${provenance.length} provenance</summary><div><span>Records</span>${sources.map((identifier) => linkedCode(identifier, links.source)).join(" ")}<span>Provenance</span>${provenance.map((identifier) => linkedCode(identifier, links.provenance)).join(" ")}</div></details>`;
}

function linkedCode(identifier, index) {
  const anchor = index.get(identifier);
  return anchor ? `<a href="#${anchor}"><code>${escapeHtml(identifier)}</code></a>` : `<code>${escapeHtml(identifier)}</code>`;
}

function summaryCard(labelText, count, state) {
  return `<article class="summary-card"><div class="summary-top"><span class="summary-number">${integer(count, "summary count")}</span>${badge(text(state, "summary availability"))}</div><h2>${escapeHtml(labelText)}</h2><p>retained in this night-detail response</p></article>`;
}

function sectionHeading(identifier, title, description) {
  return `<div class="section-heading"><h2 id="${escapeHtml(identifier)}">${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>`;
}

function emptyCard(title, description, state, reasons) {
  return `<article class="empty-card"><div>${badge(text(state, "empty-state availability"))}<h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div>${reasonLine(reasons)}</article>`;
}

function renderList(values, emptyText) {
  return values.length ? `<ul class="evidence-list">${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : `<p class="empty-value">${escapeHtml(emptyText)}</p>`;
}

function valueTriples(value, labelName) {
  return array(value, labelName).map((entry) => {
    const triple = array(entry, labelName);
    if (triple.length !== 3) throw new Error(`The ${labelName} are invalid.`);
    return [text(triple[0], `${labelName} name`), scalarValue(triple[1], labelName), triple[2] === null ? null : text(triple[2], `${labelName} unit`)];
  });
}

function timestamp(value, labelName) {
  const milliseconds = number(value, labelName);
  const date = new Date(milliseconds);
  if (!Number.isFinite(date.getTime())) throw new Error(`The ${labelName} is invalid.`);
  return `<time datetime="${escapeHtml(date.toISOString())}">${escapeHtml(date.toISOString())}</time> <code>${escapeHtml(formatNumber(milliseconds))} ms</code>`;
}

function duration(value) {
  const milliseconds = number(value, "duration");
  if (milliseconds < 0) throw new Error("A duration cannot be negative.");
  const seconds = milliseconds / 1000;
  return `${escapeHtml(formatNumber(seconds))} s <code>${escapeHtml(formatNumber(milliseconds))} ms</code>`;
}

function formatOffset(value, origin) {
  return `+${formatNumber((value - origin) / 1000)} s`;
}

function scalar(value) {
  return escapeHtml(String(scalarValue(value, "scalar value")));
}

function scalarValue(value, labelName) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  throw new Error(`The ${labelName} is invalid.`);
}

function badge(value) {
  const state = text(value, "availability");
  return `<span class="badge badge-${escapeHtml(stateClass(state))}">${escapeHtml(displayLabel(state))}</span>`;
}

function qualityBadge(value) {
  const state = text(value, "quality status");
  return `<span class="quality-chip quality-${escapeHtml(stateClass(state))}">${escapeHtml(displayLabel(state))}</span>`;
}

function reasonLine(values) {
  const reasons = textArray(values === undefined ? [] : values, "reason codes");
  return reasons.length ? `<p class="reason-line">${reasons.map(escapeHtml).join(" · ")}</p>` : "";
}

function displayLabel(value) {
  return LABELS[value] || text(value, "label value").replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function stateClass(value) {
  return text(value, "state").replaceAll("_", "-");
}

function plural(count, singular, pluralForm = `${singular}s`) {
  return count === 1 ? singular : pluralForm;
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
}

function rounded(value) {
  const result = Math.round(value * 100) / 100;
  return Object.is(result, -0) ? 0 : result;
}

function objectArray(value, labelName) {
  return array(value, labelName).map((entry) => object(entry, labelName));
}

function numberArray(value, labelName) {
  return array(value, labelName).map((entry) => number(entry, labelName));
}

function textArray(value, labelName) {
  return array(value, labelName).map((entry) => text(entry, labelName));
}

function object(value, labelName) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(`The ${labelName} is missing or invalid.`);
  return value;
}

function array(value, labelName) {
  if (!Array.isArray(value)) throw new Error(`The ${labelName} are missing or invalid.`);
  return value;
}

function text(value, labelName) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`The ${labelName} is missing or invalid.`);
  return value;
}

function number(value, labelName) {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`The ${labelName} is missing or invalid.`);
  return value;
}

function integer(value, labelName) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`The ${labelName} is missing or invalid.`);
  return value;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"})[character]);
}

function nightIdentifierFromPath(pathname) {
  const match = /^\/nights\/([^/]+)$/.exec(pathname);
  if (!match) throw new Error("The browser URL does not identify one therapy night.");
  try {
    const identifier = decodeURIComponent(match[1]);
    return text(identifier, "night identifier");
  } catch (error) {
    throw new Error("The browser URL contains an invalid night identifier.", {cause: error});
  }
}

async function fetchJson(endpoint) {
  const response = await fetch(endpoint, {cache: "no-store", headers: {Accept: "application/json"}});
  if (!response.ok) throw new Error(`${endpoint} returned HTTP ${response.status}.`);
  return response.json();
}

async function loadNightDetail() {
  const root = document.querySelector("#night-detail");
  if (!root) return;
  try {
    const identifier = nightIdentifierFromPath(window.location.pathname);
    root.innerHTML = renderNightDetail(await fetchJson(`/api/v1/analysis/nights/${encodeURIComponent(identifier)}`));
  } catch (error) {
    root.innerHTML = renderNightDetailError(error instanceof Error ? error.message : "The local night evidence could not be loaded.");
  } finally {
    root.setAttribute("aria-busy", "false");
  }
}

if (typeof document !== "undefined") loadNightDetail();

export {nightIdentifierFromPath};
