"""Consent-gated structured AI boundary; no provider SDK or network client."""

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Any, Callable, Final, Mapping


AI_PAYLOAD_CONTRACT_ID: Final = "pap-pilot.ai-advisory-payload"
AI_PAYLOAD_CONTRACT_VERSION: Final = 1
AI_RESPONSE_CONTRACT_ID: Final = "pap-pilot.ai-advisory-response"
AI_RESPONSE_CONTRACT_VERSION: Final = 1


class AiAdapterError(ValueError):
    """Raised when an AI payload or response violates its contract."""


class AiTransmissionNotAuthorized(AiAdapterError):
    """Raised before any transport is invoked without explicit consent."""


class AiProviderUnavailable(AiAdapterError):
    """Raised when an authorized provider transport is unavailable."""


class AiTransmissionState(StrEnum):
    NOT_AUTHORIZED = "hosted_transmission_not_authorized"
    AUTHORIZED = "authorized"


@dataclass(frozen=True, slots=True)
class AiMetricSummary:
    metric_id: str
    value: float | int | None
    unit: str
    status: str

    def __post_init__(self) -> None:
        _text(self.metric_id, "metric identifier")
        _text(self.unit, "metric unit")
        _text(self.status, "metric status")
        if self.value is not None and (type(self.value) not in (int, float) or not math.isfinite(float(self.value))):
            raise AiAdapterError("Metric values must be finite numbers or null.")


@dataclass(frozen=True, slots=True)
class AiWaveformExcerpt:
    signal_kind: str
    unit: str
    relative_times_ms: tuple[int, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        _text(self.signal_kind, "waveform signal kind")
        _text(self.unit, "waveform unit")
        if type(self.relative_times_ms) is not tuple or type(self.values) is not tuple or len(self.relative_times_ms) != len(self.values) or not self.values or len(self.values) > 2000:
            raise AiAdapterError("Waveform excerpts must contain 1 through 2,000 paired samples.")
        if any(type(value) is not int or value < 0 or value > 60_000 for value in self.relative_times_ms) or any(type(value) is not float or not math.isfinite(value) for value in self.values):
            raise AiAdapterError("Waveform excerpts must use finite relative samples within 60 seconds.")
        if any(left >= right for left, right in zip(self.relative_times_ms, self.relative_times_ms[1:])):
            raise AiAdapterError("Waveform excerpt times must be strictly increasing.")


@dataclass(frozen=True, slots=True)
class StructuredAiContext:
    """Minimal redaction-ready context; no source identifiers or free text are accepted."""

    experiment_label: str
    hypothesis: str
    metrics: tuple[AiMetricSummary, ...]
    journal_ratings: Mapping[str, int | None]
    confounder_states: tuple[str, ...]
    waveforms: tuple[AiWaveformExcerpt, ...]
    engine_version: str
    rule_set_versions: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, label in ((self.experiment_label, "experiment label"), (self.hypothesis, "hypothesis"), (self.engine_version, "engine version")):
            _text(value, label)
        if "\n" in self.hypothesis or len(self.hypothesis) > 1000:
            raise AiAdapterError("The hypothesis must be bounded single-line text.")
        if type(self.metrics) is not tuple or any(not isinstance(value, AiMetricSummary) for value in self.metrics) or len({value.metric_id for value in self.metrics}) != len(self.metrics):
            raise AiAdapterError("Metrics must be a unique immutable tuple.")
        if type(self.journal_ratings) is not dict:
            raise AiAdapterError("Journal ratings must be a structured mapping.")
        for key, value in self.journal_ratings.items():
            _text(key, "journal field")
            if value is not None and (type(value) is not int or not 1 <= value <= 5):
                raise AiAdapterError("Journal ratings must be integers from 1 through 5 or null.")
        if type(self.confounder_states) is not tuple or any(type(value) is not str or not value for value in self.confounder_states):
            raise AiAdapterError("Confounder states must be an immutable text tuple.")
        if type(self.waveforms) is not tuple or any(not isinstance(value, AiWaveformExcerpt) for value in self.waveforms) or len(self.waveforms) > 3:
            raise AiAdapterError("At most three waveform excerpts may be supplied.")
        if type(self.rule_set_versions) is not tuple or any(type(value) is not str or not value for value in self.rule_set_versions):
            raise AiAdapterError("Rule-set versions must be an immutable text tuple.")


@dataclass(frozen=True, slots=True)
class AiTransmissionConsent:
    provider: str
    endpoint: str
    model: str
    payload_contract: str = AI_PAYLOAD_CONTRACT_ID
    payload_version: int = AI_PAYLOAD_CONTRACT_VERSION
    retention_acknowledged: bool = False

    def __post_init__(self) -> None:
        for value, label in ((self.provider, "provider"), (self.endpoint, "endpoint"), (self.model, "model")):
            _text(value, label)
        if self.provider != "openai" or self.payload_contract != AI_PAYLOAD_CONTRACT_ID or self.payload_version != AI_PAYLOAD_CONTRACT_VERSION or self.retention_acknowledged is not True:
            raise AiAdapterError("Consent must explicitly identify OpenAI, the endpoint/model, payload version, and retention acknowledgement.")


@dataclass(frozen=True, slots=True)
class StructuredAiResponse:
    hypothesis: str
    experiment_title: str
    expected_objective_effects: tuple[str, ...]
    expected_subjective_effects: tuple[str, ...]
    limitations: tuple[str, ...]


def build_ai_payload(context: StructuredAiContext) -> dict[str, Any]:
    """Build a redacted JSON-ready payload with opaque labels and no free text notes."""

    if not isinstance(context, StructuredAiContext):
        raise AiAdapterError("The AI context has an unsupported type.")
    return {
        "format": AI_PAYLOAD_CONTRACT_ID,
        "format_version": AI_PAYLOAD_CONTRACT_VERSION,
        "experiment_label": "experiment-1",
        "hypothesis": context.hypothesis,
        "metrics": [{"metric_id": value.metric_id, "value": value.value, "unit": value.unit, "status": value.status} for value in context.metrics],
        "journal_ratings": dict(sorted(context.journal_ratings.items())),
        "confounder_states": list(context.confounder_states),
        "waveform_excerpts": [{"signal_kind": value.signal_kind, "unit": value.unit, "relative_times_ms": list(value.relative_times_ms), "values": list(value.values)} for value in context.waveforms],
        "versions": {"engine": context.engine_version, "rule_sets": list(context.rule_set_versions)},
    }


def parse_ai_response(value: Mapping[str, Any]) -> StructuredAiResponse:
    """Validate a structured advisory response; reject prose, missing fields, and extras."""

    if not isinstance(value, Mapping) or set(value) != {"format", "format_version", "hypothesis", "experiment"} or value.get("format") != AI_RESPONSE_CONTRACT_ID or value.get("format_version") != AI_RESPONSE_CONTRACT_VERSION:
        raise AiAdapterError("The AI response envelope is malformed or unsupported.")
    experiment = value["experiment"]
    if not isinstance(experiment, Mapping) or set(experiment) != {"title", "expected_objective_effects", "expected_subjective_effects", "limitations"}:
        raise AiAdapterError("The AI experiment response is malformed or contains unauthorized fields.")
    strings = [value["hypothesis"], experiment["title"], *experiment["expected_objective_effects"], *experiment["expected_subjective_effects"], *experiment["limitations"]]
    if any(type(item) is not str or not item.strip() or len(item) > 1000 for item in strings) or any("\n" in item for item in strings):
        raise AiAdapterError("The AI response contains invalid or unbounded text.")
    return StructuredAiResponse(value["hypothesis"], experiment["title"], tuple(experiment["expected_objective_effects"]), tuple(experiment["expected_subjective_effects"]), tuple(experiment["limitations"]))


def request_structured_advisory(context: StructuredAiContext, *, consent: AiTransmissionConsent | None = None, transport: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None) -> StructuredAiResponse:
    """Invoke only an injected transport after consent; default behavior is fail-closed."""

    if consent is None:
        raise AiTransmissionNotAuthorized("hosted_transmission_not_authorized")
    if transport is None:
        raise AiProviderUnavailable("The authorized provider transport is unavailable.")
    payload = build_ai_payload(context)
    try:
        response = transport(payload)
    except Exception as error:
        raise AiProviderUnavailable("The authorized provider transport failed.") from error
    return parse_ai_response(response)


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise AiAdapterError(f"The {label} must be nonempty text.")

