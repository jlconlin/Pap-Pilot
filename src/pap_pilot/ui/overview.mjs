const OVERVIEW_ENDPOINT = "/api/v1/analysis/overview";
const NIGHTS_ENDPOINT = "/api/v1/analysis/nights";
const TRENDS_ENDPOINT = "/api/v1/analysis/trends";
const WORKSPACE_FORMAT = "pap-pilot.analysis-workspace-json";
const RESOURCE_FORMAT = "pap-pilot.analysis-resource-json";
const FORMAT_VERSION = 1;
const RECENT_NIGHT_LIMIT = 8;
const RECENT_QUALITY_LIMIT = 8;
const TREND_WIDTH = 620;
const TREND_HEIGHT = 170;
const TREND_PADDING = Object.freeze({top: 20, right: 20, bottom: 30, left: 58});

const LABELS = Object.freeze({
  analysis_workspace_not_configured: "Analysis workspace not configured",
  available: "Available",
  partial: "Partial",
  unavailable: "Unavailable",
  not_evaluable: "Not evaluable",
  setting: "Settings",
  event: "Events",
  signal: "Signals",
  quality: "Data quality",
  metric: "Metrics",
  journal: "Morning journal",
  experiment_report: "Experiment report",
});

export function renderOverview(overviewEnvelope, nightsEnvelope, trendsEnvelope) {
  const workspace = readWorkspace(overviewEnvelope);
  const nights = readCollection(nightsEnvelope, "night_collection", "nights");
  const trends = readCollection(trendsEnvelope, "trend_collection", "trends");
  const evidence = array(workspace.evidence, "workspace evidence").map((value) => object(value, "evidence record"));
  const experiments = array(workspace.experiments, "workspace experiments").map((value) => object(value, "experiment reference"));
  const limitations = textArray(workspace.limitations, "workspace limitations");
  const qualityEvidence = evidence.filter((value) => text(value.kind, "evidence kind") === "quality");
  const availableTrendPoints = trends.flatMap((trend) => array(object(trend, "trend").points, "trend points")).filter((point) => object(point, "trend point").availability === "available").length;
  const title = text(workspace.title, "workspace title");
  const state = text(workspace.availability, "workspace availability");

  return `
    <article class="analysis-overview" data-workspace-id="${escapeHtml(text(workspace.record_id, "workspace identifier"))}">
      <section class="hero" aria-labelledby="overview-title">
        <div>
          <p class="eyebrow">General PAP analysis · Local only</p>
          <h1 id="overview-title">${escapeHtml(title)}</h1>
          <p class="hero-copy">Review recent therapy nights, follow deterministic metrics over time, and see where source quality limits the evidence. Experiments are optional; this workspace does not require a settings change.</p>
        </div>
        <aside class="status-panel status-panel-${escapeHtml(stateClass(state))}" aria-label="Workspace availability">
          <div class="status-label">Workspace status</div>
          <p class="status-value">${escapeHtml(availabilityLabel(state))}</p>
          <p class="status-detail">${nights.length} retained ${plural(nights.length, "night")} · ${trends.length} trend ${plural(trends.length, "series", "series")}</p>
          ${reasonLine(workspace.reason_codes)}
        </aside>
      </section>

      <section class="summary-grid" aria-label="Analysis inventory">
        ${summaryCard("Recent nights", nights.length, "retained across the local workspace", text(object(nightsEnvelope.resource, "night collection resource").availability, "night collection availability"))}
        ${summaryCard("Trend points", availableTrendPoints, "available values; missing values stay gaps", text(object(trendsEnvelope.resource, "trend collection resource").availability, "trend collection availability"))}
        ${summaryCard("Quality records", qualityEvidence.length, "retained findings, without a synthetic score", collectionAvailability(qualityEvidence, text(workspace.availability, "workspace availability")))}
        ${summaryCard("Experiments", experiments.length, experiments.length ? "optional linked workflows" : "none required for general analysis", collectionAvailability(experiments, "unavailable"))}
      </section>

      <section class="section" aria-labelledby="nights-heading">
        ${sectionHeading("nights-heading", "Recent nights", "The local API orders nights most recent first. Counts describe retained evidence only; they are not therapy or clinical judgments.")}
        ${renderNights(nights, object(nightsEnvelope.resource, "night collection resource"))}
      </section>

      <section class="section" aria-labelledby="trends-heading">
        ${sectionHeading("trends-heading", "Longitudinal patterns", "Each series uses an existing deterministic metric. Supplied values are connected in date order; unavailable and not-evaluable points are shown as gaps and never plotted as zero.")}
        ${renderTrends(trends, object(trendsEnvelope.resource, "trend collection resource"))}
      </section>

      <section class="section" aria-labelledby="quality-heading">
        ${sectionHeading("quality-heading", "Data quality", "This is an inventory of retained quality records, not a combined score. Exact availability states and source reason codes remain visible for every record shown.")}
        ${renderQuality(qualityEvidence, nights)}
      </section>

      <section class="section" aria-labelledby="paths-heading">
        ${sectionHeading("paths-heading", "Available analysis paths", "These links open versioned local records. PAP Pilot does not send data to a remote service or change device settings.")}
        ${renderAnalysisPaths(nights, trends, qualityEvidence, experiments)}
      </section>

      <section class="section" aria-labelledby="limits-heading">
        ${sectionHeading("limits-heading", "Evidence boundaries", "These limitations apply to the whole workspace and travel with the deterministic analysis record.")}
        <div class="content-card">${renderList(limitations, "No workspace limitations were supplied.")}</div>
      </section>

      <footer class="report-footer">
        <span>Local deterministic workspace · Engine ${escapeHtml(text(workspace.engine_version, "engine version"))} · Schema ${integer(workspace.schema_version, "schema version")}</span>
        <code>${escapeHtml(text(workspace.record_id, "workspace identifier"))}</code>
        <span>${array(workspace.source_record_ids, "workspace source records").length} linked source records</span>
      </footer>
    </article>`;
}

export function renderOverviewError(message) {
  return `
    <section class="error-panel" role="alert">
      <p class="eyebrow">Local analysis unavailable</p>
      <h1>The PAP analysis overview could not be loaded.</h1>
      <p>${escapeHtml(typeof message === "string" && message.trim() ? message : "The local API did not return a usable analysis workspace.")}</p>
      <p>No missing value has been estimated. Check the local workspace configuration, restart PAP Pilot, and reload this page.</p>
    </section>`;
}

function readWorkspace(envelope) {
  const value = object(envelope, "workspace envelope");
  if (value.format !== WORKSPACE_FORMAT || value.format_version !== FORMAT_VERSION) {
    throw new Error("The local API returned an unsupported analysis-workspace format.");
  }
  return object(value.workspace, "analysis workspace");
}

function readCollection(envelope, expectedKind, field) {
  const value = object(envelope, `${field} envelope`);
  if (value.format !== RESOURCE_FORMAT || value.format_version !== FORMAT_VERSION) {
    throw new Error(`The local API returned an unsupported ${field} format.`);
  }
  const resource = object(value.resource, `${field} resource`);
  if (resource.kind !== expectedKind) {
    throw new Error(`The local API returned an unexpected ${field} resource.`);
  }
  return array(value[field], field).map((entry) => object(entry, field.slice(0, -1)));
}

function summaryCard(labelText, count, detail, state) {
  return `<article class="summary-card"><div class="summary-top"><span class="summary-number">${integer(count, "summary count")}</span>${badge(state)}</div><h2>${escapeHtml(labelText)}</h2><p>${escapeHtml(detail)}</p></article>`;
}

function collectionAvailability(values, emptyState) {
  if (!values.length) return emptyState;
  const states = new Set(values.map((value) => text(object(value, "analysis item").availability, "availability")));
  if (states.size === 1) return [...states][0];
  return "partial";
}

function renderNights(nights, resource) {
  if (!nights.length) {
    return emptyCard("No recent nights are available", "The configured analysis source supplied no therapy-night records. PAP Pilot has not searched for, inferred, or fabricated nights.", resource.availability, resource.reason_codes);
  }
  const shown = nights.slice(0, RECENT_NIGHT_LIMIT);
  return `<div class="night-list">${shown.map(renderNight).join("")}</div>${nights.length > shown.length ? `<p class="section-note">Showing the ${shown.length} most recent of ${nights.length} retained nights.</p>` : ""}`;
}

function renderNight(value) {
  const night = object(value, "analysis night");
  const nightId = text(night.night_record_id, "night identifier");
  const sessions = array(night.session_record_ids, "night sessions").length;
  const metrics = array(night.metric_result_ids, "night metrics").length;
  const quality = array(night.quality_report_ids, "night quality reports").length;
  const journals = array(night.journal_entry_ids, "night journal entries").length;
  const state = text(night.availability, "night availability");
  return `
    <article class="night-card">
      <div class="night-primary">
        <p class="card-kicker">Therapy night</p>
        <h3><time datetime="${escapeHtml(text(night.local_date, "night local date"))}">${escapeHtml(night.local_date)}</time></h3>
        <p>${sessions} ${plural(sessions, "session")} · ${array(night.evidence_record_ids, "night evidence records").length} evidence ${plural(array(night.evidence_record_ids, "night evidence records").length, "record")}</p>
      </div>
      <div class="night-coverage" aria-label="Retained night evidence counts">
        ${coverageItem("Metrics", metrics)}
        ${coverageItem("Quality", quality)}
        ${coverageItem("Journal", journals)}
      </div>
      <div class="night-action">${badge(state)}<a class="text-link" href="${nightUrl(nightId)}">Open local record <span aria-hidden="true">→</span></a></div>
      ${reasonLine(night.reason_codes)}
    </article>`;
}

function coverageItem(labelText, count) {
  return `<span><strong>${integer(count, "evidence count")}</strong>${escapeHtml(labelText)}</span>`;
}

function renderTrends(trends, resource) {
  if (!trends.length) {
    return emptyCard("No trend series are available", "No deterministic metric series was supplied. The overview does not infer a longitudinal pattern from absent results.", resource.availability, resource.reason_codes);
  }
  return `<div class="trend-grid">${trends.map(renderTrend).join("")}</div>`;
}

function renderTrend(value) {
  const trend = object(value, "analysis trend");
  const points = array(trend.points, "trend points").map((point) => object(point, "trend point"));
  const state = text(trend.availability, "trend availability");
  const unit = trend.unit === null ? null : text(trend.unit, "trend unit");
  const available = points.filter((point) => point.availability === "available");
  const latest = [...available].reverse().find((point) => point.value !== null);
  const unavailableCount = points.length - available.length;
  return `
    <article class="trend-card">
      <div class="trend-heading"><div><p class="card-kicker">Deterministic metric</p><h3>${escapeHtml(text(trend.label, "trend label"))}</h3><p>${escapeHtml(text(trend.metric_id, "trend metric identifier"))}</p></div>${badge(state)}</div>
      <div class="trend-current"><span>Latest available</span><strong>${latest ? formatScalar(latest.value, unit) : "Not available"}</strong>${latest ? `<time datetime="${escapeHtml(text(latest.local_date, "trend-point date"))}">${escapeHtml(latest.local_date)}</time>` : ""}</div>
      ${renderTrendPlot(points, unit, text(trend.label, "trend label"))}
      <div class="trend-foot"><span>${available.length} available · ${unavailableCount} unavailable or not evaluable</span><a class="text-link" href="${trendUrl(text(trend.record_id, "trend identifier"))}">Open series <span aria-hidden="true">→</span></a></div>
      ${renderPointStates(points, unit)}
      ${reasonLine(trend.reason_codes)}
    </article>`;
}

function renderTrendPlot(points, unit, trendLabel) {
  const numeric = points.map((point, index) => point.availability === "available" && typeof point.value === "number" && Number.isFinite(point.value) ? {index, value: point.value} : null);
  const supplied = numeric.filter(Boolean);
  if (!supplied.length) {
    return `<div class="plot-unavailable"><strong>No numeric plot available</strong><span>Exact point states remain listed below.</span></div>`;
  }
  const values = supplied.map((point) => point.value);
  const rawMinimum = Math.min(...values);
  const rawMaximum = Math.max(...values);
  const padding = rawMinimum === rawMaximum ? Math.max(Math.abs(rawMinimum) * 0.05, 1) : (rawMaximum - rawMinimum) * 0.08;
  const minimum = rawMinimum - padding;
  const maximum = rawMaximum + padding;
  const left = TREND_PADDING.left;
  const right = TREND_WIDTH - TREND_PADDING.right;
  const top = TREND_PADDING.top;
  const bottom = TREND_HEIGHT - TREND_PADDING.bottom;
  const x = (index) => points.length === 1 ? (left + right) / 2 : left + (index / (points.length - 1)) * (right - left);
  const y = (numberValue) => top + ((maximum - numberValue) / (maximum - minimum)) * (bottom - top);
  const segments = [];
  let segment = [];
  for (const point of numeric) {
    if (point) {
      segment.push(point);
    } else if (segment.length) {
      segments.push(segment);
      segment = [];
    }
  }
  if (segment.length) segments.push(segment);
  const paths = segments.filter((valuesInSegment) => valuesInSegment.length > 1).map((valuesInSegment) => `M ${rounded(x(valuesInSegment[0].index))} ${rounded(y(valuesInSegment[0].value))}${valuesInSegment.slice(1).map((point) => ` L ${rounded(x(point.index))} ${rounded(y(point.value))}`).join("")}`).join(" ");
  const circles = supplied.map((point) => `<circle cx="${rounded(x(point.index))}" cy="${rounded(y(point.value))}" r="3.5"></circle>`).join("");
  const firstDate = text(points[0].local_date, "first trend-point date");
  const lastDate = text(points[points.length - 1].local_date, "last trend-point date");
  return `
    <svg class="trend-chart" viewBox="0 0 ${TREND_WIDTH} ${TREND_HEIGHT}" role="img" aria-label="${escapeHtml(`${trendLabel}: ${supplied.length} supplied numeric points; missing values shown as gaps`)}">
      <line class="trend-gridline" x1="${left}" y1="${top}" x2="${right}" y2="${top}"></line>
      <line class="trend-gridline" x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}"></line>
      ${paths ? `<path class="trend-line" d="${paths}"></path>` : ""}
      <g class="trend-points">${circles}</g>
      <text class="trend-axis-label" x="${left - 8}" y="${top + 4}" text-anchor="end">${escapeHtml(formatNumber(rawMaximum))}</text>
      <text class="trend-axis-label" x="${left - 8}" y="${bottom + 4}" text-anchor="end">${escapeHtml(formatNumber(rawMinimum))}</text>
      <text class="trend-axis-label" x="${left}" y="${TREND_HEIGHT - 8}">${escapeHtml(firstDate)}</text>
      <text class="trend-axis-label" x="${right}" y="${TREND_HEIGHT - 8}" text-anchor="end">${escapeHtml(lastDate)}</text>
    </svg>
    <p class="plot-note">Supplied numeric values${unit ? ` · ${escapeHtml(unit)}` : ""}; gaps are not joined.</p>`;
}

function renderPointStates(points, unit) {
  return `<details class="point-details"><summary>Point-by-point evidence</summary><ol>${points.map((point) => {
    const state = text(point.availability, "trend-point availability");
    const value = state === "available" ? formatScalar(point.value, unit) : availabilityLabel(state);
    return `<li><time datetime="${escapeHtml(text(point.local_date, "trend-point date"))}">${escapeHtml(point.local_date)}</time><span class="point-value ${state === "available" ? "" : "empty-value"}">${value}</span>${badge(state)}${reasonLine(point.reason_codes)}</li>`;
  }).join("")}</ol></details>`;
}

function renderQuality(qualityEvidence, nights) {
  if (!qualityEvidence.length) {
    return emptyCard("Quality evidence is unavailable", "No quality records were supplied. Their absence is not interpreted as clean data.", "unavailable", ["quality_not_evaluated"]);
  }
  const dateByNight = new Map(nights.map((night) => [night.night_record_id, night.local_date]));
  const ordered = [...qualityEvidence].sort((left, right) => qualitySortKey(right, dateByNight).localeCompare(qualitySortKey(left, dateByNight)) || text(left.record_id, "quality identifier").localeCompare(text(right.record_id, "quality identifier")));
  const shown = ordered.slice(0, RECENT_QUALITY_LIMIT);
  const states = new Map();
  for (const item of qualityEvidence) {
    const state = text(item.availability, "quality availability");
    states.set(state, (states.get(state) || 0) + 1);
  }
  return `
    <div class="quality-summary" aria-label="Quality availability counts">${[...states].map(([state, count]) => `<span>${badge(state)}<strong>${count}</strong></span>`).join("")}</div>
    <div class="quality-list">${shown.map((item) => renderQualityItem(item, dateByNight)).join("")}</div>
    ${qualityEvidence.length > shown.length ? `<p class="section-note">Showing ${shown.length} of ${qualityEvidence.length} retained quality records. Open a night record to inspect its complete evidence links.</p>` : ""}`;
}

function qualitySortKey(item, dateByNight) {
  return array(item.night_record_ids, "quality night identifiers").map((identifier) => dateByNight.get(identifier) || "").sort().at(-1) || "";
}

function renderQualityItem(value, dateByNight) {
  const item = object(value, "quality evidence");
  const nights = textArray(item.night_record_ids, "quality night identifiers");
  const dates = nights.map((identifier) => dateByNight.get(identifier)).filter(Boolean);
  return `
    <article class="quality-item">
      <div><p class="card-kicker">${dates.length ? escapeHtml(dates.join(", ")) : "Workspace evidence"}</p><h3>${escapeHtml(text(item.label, "quality label"))}</h3><p>${array(item.source_record_ids, "quality source records").length} linked source ${plural(array(item.source_record_ids, "quality source records").length, "record")}</p></div>
      <div class="quality-state">${badge(text(item.availability, "quality availability"))}<a class="text-link" href="${evidenceUrl(text(item.record_id, "quality identifier"))}">Open evidence <span aria-hidden="true">→</span></a></div>
      ${reasonLine(item.reason_codes)}
    </article>`;
}

function renderAnalysisPaths(nights, trends, qualityEvidence, experiments) {
  const cards = [
    pathCard("Night records", "Inspect the versioned summary and evidence links for the most recent retained night.", nights.length ? nightUrl(text(nights[0].night_record_id, "night identifier")) : null, nights.length ? text(nights[0].availability, "night availability") : "unavailable", nights.length ? [] : ["no_therapy_nights"]),
    pathCard("Trend records", "Open a deterministic series with every supplied and unavailable point preserved.", trends.length ? trendUrl(text(trends[0].record_id, "trend identifier")) : null, trends.length ? text(trends[0].availability, "trend availability") : "unavailable", trends.length ? trends[0].reason_codes : ["no_trend_series"]),
    pathCard("Quality evidence", "Trace one retained quality result back to its exact source and provenance identifiers.", qualityEvidence.length ? evidenceUrl(text(qualityEvidence[0].record_id, "quality identifier")) : null, qualityEvidence.length ? text(qualityEvidence[0].availability, "quality availability") : "unavailable", qualityEvidence.length ? qualityEvidence[0].reason_codes : ["quality_not_evaluated"]),
  ];
  const experimentCards = experiments.length ? experiments.map(renderExperimentPath) : [pathCard("Optional experiments", "No experiment is linked, and none is required to review general PAP analysis.", null, "unavailable", ["no_optional_experiment"] )];
  return `<div class="path-grid">${[...cards, ...experimentCards].join("")}</div>`;
}

function pathCard(title, description, href, state, reasons, secondaryLink = "") {
  return `<article class="path-card"><div>${badge(state)}<h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div><div>${href ? `<a class="path-link" href="${href}">Open local data <span aria-hidden="true">→</span></a>` : `<span class="path-link path-link-disabled">Not available</span>`}${secondaryLink}</div>${reasonLine(reasons)}</article>`;
}

function renderExperimentPath(value) {
  const experiment = object(value, "experiment reference");
  const compatibilityLink = experiment.compatibility_fixture_id === "pap-pilot.ps-min-retrospective" ? '<a class="text-link secondary-link" href="/api/v1/experiments/ps-min-2-to-1/summary">Open compatibility report</a>' : "";
  return pathCard(text(experiment.label, "experiment label"), "Optional experiment evidence linked from this general workspace.", experimentUrl(text(experiment.experiment_record_id, "experiment identifier")), text(experiment.availability, "experiment availability"), experiment.reason_codes, compatibilityLink);
}

function emptyCard(title, description, state, reasons) {
  return `<article class="empty-card"><div>${badge(text(state, "empty-state availability"))}<h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div>${reasonLine(reasons)}</article>`;
}

function sectionHeading(identifier, title, description) {
  return `<div class="section-heading"><h2 id="${escapeHtml(identifier)}">${escapeHtml(title)}</h2><p>${escapeHtml(description)}</p></div>`;
}

function renderList(values, emptyText) {
  return values.length ? `<ul class="evidence-list">${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul>` : `<p class="empty-value">${escapeHtml(emptyText)}</p>`;
}

function reasonLine(values) {
  const reasons = textArray(values === undefined ? [] : values, "reason codes");
  return reasons.length ? `<p class="reason-line">${reasons.map(escapeHtml).join(" · ")}</p>` : "";
}

function badge(value) {
  const state = text(value, "availability");
  return `<span class="badge badge-${escapeHtml(stateClass(state))}">${escapeHtml(availabilityLabel(state))}</span>`;
}

function availabilityLabel(value) {
  return LABELS[value] || label(value);
}

function stateClass(value) {
  return text(value, "availability").replaceAll("_", "-");
}

function label(value) {
  return text(value, "label value").replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatScalar(value, unit) {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("A trend value is not finite.");
    return `${escapeHtml(formatNumber(value))}${unit ? ` <span>${escapeHtml(unit)}</span>` : ""}`;
  }
  if (typeof value === "string" || typeof value === "boolean") return escapeHtml(String(value));
  throw new Error("An available trend point has no displayable value.");
}

function formatNumber(value) {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 1000) / 1000);
}

function plural(count, singular, pluralForm = `${singular}s`) {
  return count === 1 ? singular : pluralForm;
}

function nightUrl(identifier) {
  return `/nights/${encodeURIComponent(identifier)}`;
}

function trendUrl(identifier) {
  return `/api/v1/analysis/trends/${encodeURIComponent(identifier)}`;
}

function evidenceUrl(identifier) {
  return `/api/v1/analysis/evidence/${encodeURIComponent(identifier)}`;
}

function experimentUrl(identifier) {
  return `/api/v1/analysis/experiments/${encodeURIComponent(identifier)}`;
}

function object(value, labelName) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(`The ${labelName} is missing or invalid.`);
  return value;
}

function array(value, labelName) {
  if (!Array.isArray(value)) throw new Error(`The ${labelName} are missing or invalid.`);
  return value;
}

function textArray(value, labelName) {
  return array(value, labelName).map((entry) => text(entry, labelName));
}

function text(value, labelName) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`The ${labelName} is missing or invalid.`);
  return value;
}

function integer(value, labelName) {
  if (!Number.isInteger(value) || value < 0) throw new Error(`The ${labelName} is missing or invalid.`);
  return value;
}

function rounded(value) {
  const result = Math.round(value * 100) / 100;
  return Object.is(result, -0) ? 0 : result;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"})[character]);
}

async function fetchJson(endpoint) {
  const response = await fetch(endpoint, {cache: "no-store", headers: {Accept: "application/json"}});
  if (!response.ok) throw new Error(`${endpoint} returned HTTP ${response.status}.`);
  return response.json();
}

async function loadOverview() {
  const root = document.querySelector("#overview");
  if (!root) return;
  try {
    const [overview, nights, trends] = await Promise.all([fetchJson(OVERVIEW_ENDPOINT), fetchJson(NIGHTS_ENDPOINT), fetchJson(TRENDS_ENDPOINT)]);
    root.innerHTML = renderOverview(overview, nights, trends);
  } catch (error) {
    root.innerHTML = renderOverviewError(error instanceof Error ? error.message : "The local analysis workspace could not be loaded.");
  } finally {
    root.setAttribute("aria-busy", "false");
  }
}

if (typeof document !== "undefined") loadOverview();

export {NIGHTS_ENDPOINT, OVERVIEW_ENDPOINT, TRENDS_ENDPOINT};
