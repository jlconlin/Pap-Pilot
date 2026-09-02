"""Immutable records for deterministic PAP data-quality findings."""

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Final, TypeAlias

from pap_pilot.engine.model import SourceClass


QUALITY_RULE_SET_ID: Final = "pap-pilot.quality"
QUALITY_RULE_SET_VERSION: Final = 1
QUALITY_ENGINE_VERSION: Final = "0.1.0"
SHORT_SESSION_THRESHOLD_MS: Final = 300_000
LARGE_LEAK_THRESHOLD_L_MIN: Final = 24.0
ARTIFACT_SAMPLE_INTERVAL_MS: Final = 40.0
ARTIFACT_RAW_COUNT_ABS_TOLERANCE: Final = 1e-6
FLOW_IMPULSE_THRESHOLD_L_MIN: Final = 30.0
FLOW_NEIGHBOR_TOLERANCE_L_MIN: Final = 3.0
PRESSURE_IMPULSE_THRESHOLD_CM_H2O: Final = 3.0
PRESSURE_NEIGHBOR_TOLERANCE_CM_H2O: Final = 0.3
WAKE_WINDOW_BREATHS: Final = 5
WAKE_REQUIRED_IRREGULAR_WINDOWS: Final = 3
WAKE_MINIMUM_ELIGIBLE_BREATHS: Final = 7
WAKE_DURATION_CV_THRESHOLD: Final = 0.20
WAKE_AMPLITUDE_CV_THRESHOLD: Final = 0.30

QualityScalar: TypeAlias = bool | int | float | str | None
TimestampMs: TypeAlias = int | float


class QualityModelError(ValueError):
    """Raised when a quality input or result is structurally invalid."""


class QualityStatus(StrEnum):
    """Outcome of one quality rule for one evaluated scope."""

    PASS = "pass"
    FLAGGED = "flagged"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


class QualityImpact(StrEnum):
    """How one quality finding affects a requested analysis."""

    NONE = "none"
    CAUTION = "caution"
    EXCLUDE_INTERVAL = "exclude_interval"
    EXCLUDE_SESSION = "exclude_session"
    BLOCK_REQUESTED_ANALYSIS = "block_requested_analysis"


class QualityRule(StrEnum):
    """Version-1 quality rule identifiers."""

    MISSING_REQUIRED_SIGNAL = "missing_required_signal"
    FLOW_PRESSURE_MISALIGNMENT = "flow_pressure_misalignment"
    SHORT_SESSION = "short_session"
    SPLIT_SESSION_NIGHT = "split_session_night"
    CLOCK_CORRECTION_INTEGRITY = "clock_correction_integrity"
    LARGE_LEAK = "large_leak"
    SIGNAL_ARTIFACT = "signal_artifact"
    LIKELY_WAKE_BREATHING = "likely_wake_breathing"


class TimeBasis(StrEnum):
    """Timeline required by the requested analysis."""

    RAW_RELATIVE = "raw_relative"
    CORRECTED_WALL_CLOCK = "corrected_wall_clock"


_QUALITY_RULE_ORDER: Final = {
    QualityRule.SPLIT_SESSION_NIGHT: 0,
    QualityRule.SHORT_SESSION: 1,
    QualityRule.MISSING_REQUIRED_SIGNAL: 2,
    QualityRule.FLOW_PRESSURE_MISALIGNMENT: 3,
    QualityRule.CLOCK_CORRECTION_INTEGRITY: 4,
    QualityRule.LARGE_LEAK: 5,
    QualityRule.SIGNAL_ARTIFACT: 6,
    QualityRule.LIKELY_WAKE_BREATHING: 7,
}

_FLAGGED_REASON_CODES: Final = {
    QualityRule.MISSING_REQUIRED_SIGNAL: frozenset({"coverage_gap"}),
    QualityRule.FLOW_PRESSURE_MISALIGNMENT: frozenset({"bounds_mismatch", "sample_count_mismatch", "sample_time_mismatch"}),
    QualityRule.SHORT_SESSION: frozenset({"duration_below_300000_ms"}),
    QualityRule.SPLIT_SESSION_NIGHT: frozenset({"multiple_sessions"}),
    QualityRule.CLOCK_CORRECTION_INTEGRITY: frozenset({"supported_correction_present"}),
    QualityRule.LARGE_LEAK: frozenset({"threshold_exceeded", "machine_large_leak_span"}),
    QualityRule.SIGNAL_ARTIFACT: frozenset({"digital_clipping", "isolated_impulse"}),
    QualityRule.LIKELY_WAKE_BREATHING: frozenset({"irregular_breathing_candidate"}),
}

_INSUFFICIENT_REASON_CODES: Final = {
    QualityRule.MISSING_REQUIRED_SIGNAL: frozenset({"channel_missing", "data_missing", "unsupported_signal_contract", "no_common_eligible_interval"}),
    QualityRule.FLOW_PRESSURE_MISALIGNMENT: frozenset({"paired_signal_unavailable"}),
    QualityRule.SHORT_SESSION: frozenset({"session_bounds_unavailable"}),
    QualityRule.SPLIT_SESSION_NIGHT: frozenset({"night_sessions_unavailable"}),
    QualityRule.CLOCK_CORRECTION_INTEGRITY: frozenset({"correction_input_missing", "correction_range_ambiguous", "unsupported_drift", "stacked_correction_unreproducible", "corrected_timeline_invalid"}),
    QualityRule.LARGE_LEAK: frozenset({"leak_evidence_missing", "unsupported_leak_contract"}),
    QualityRule.SIGNAL_ARTIFACT: frozenset({"artifact_input_missing"}),
    QualityRule.LIKELY_WAKE_BREATHING: frozenset({"wake_prerequisite_missing", "too_few_eligible_breaths"}),
}


class ClockCorrectionEvidenceState(StrEnum):
    """Version-gated state supplied by a correction-aware adapter boundary."""

    NOT_QUERIED = "not_queried"
    CONFIRMED_NONE = "confirmed_none"
    SUPPORTED_CONSTANT = "supported_constant"
    RANGE_AMBIGUOUS = "range_ambiguous"
    UNSUPPORTED_DRIFT = "unsupported_drift"
    STACKED_UNREPRODUCIBLE = "stacked_unreproducible"


@dataclass(frozen=True, slots=True)
class ValidatedBreath:
    """One externally validated breath boundary and amplitude measurement."""

    record_id: str
    start_time_ms: TimestampMs
    end_time_ms: TimestampMs
    peak_to_trough_l_min: float

    def __post_init__(self) -> None:
        _text(self.record_id, "validated breath identifier")
        start_time_ms = _timestamp(self.start_time_ms, "validated breath start")
        end_time_ms = _timestamp(self.end_time_ms, "validated breath end")
        if start_time_ms >= end_time_ms:
            raise QualityModelError("A validated breath must have positive duration.")
        amplitude = _positive_number(self.peak_to_trough_l_min, "validated breath peak-to-trough amplitude")
        object.__setattr__(self, "start_time_ms", start_time_ms)
        object.__setattr__(self, "end_time_ms", end_time_ms)
        object.__setattr__(self, "peak_to_trough_l_min", amplitude)


@dataclass(frozen=True, slots=True)
class ValidatedBreathSeries:
    """Versioned breath-detector output supplied explicitly to quality analysis."""

    record_id: str
    session_record_id: str
    flow_signal_record_id: str
    detector_id: str
    detector_version: str
    breaths: tuple[ValidatedBreath, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED

    def __post_init__(self) -> None:
        _text(self.record_id, "validated breath-series identifier")
        _text(self.session_record_id, "validated breath-series session identifier")
        _text(self.flow_signal_record_id, "validated breath-series Flow Rate identifier")
        _text(self.detector_id, "breath detector identifier")
        _text(self.detector_version, "breath detector version")
        if type(self.breaths) is not tuple or any(not isinstance(value, ValidatedBreath) for value in self.breaths):
            raise QualityModelError("Validated breaths must be a tuple of ValidatedBreath records.")
        _unique(tuple(value.record_id for value in self.breaths), "validated breath identifiers")
        ordered = tuple(sorted(self.breaths, key=lambda value: (value.start_time_ms, value.record_id)))
        if any(current.end_time_ms > following.start_time_ms for current, following in zip(ordered, ordered[1:])):
            raise QualityModelError("Validated breaths cannot overlap.")
        source_record_ids = _required_text_tuple(self.source_record_ids, "validated breath source record identifiers")
        source_provenance_ids = _required_text_tuple(self.source_provenance_ids, "validated breath source provenance identifiers")
        _unique(source_record_ids, "validated breath source record identifiers")
        _unique(source_provenance_ids, "validated breath source provenance identifiers")
        if self.flow_signal_record_id not in source_record_ids:
            raise QualityModelError("Validated breath sources must include the Flow Rate signal identifier.")
        _enum(self.source_class, SourceClass, "validated breath source class")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise QualityModelError("Validated breath series must be companion-derived.")
        object.__setattr__(self, "breaths", ordered)
        object.__setattr__(self, "source_record_ids", tuple(sorted(source_record_ids)))
        object.__setattr__(self, "source_provenance_ids", tuple(sorted(source_provenance_ids)))


@dataclass(frozen=True, slots=True)
class QualityValue:
    """One deterministic parameter or measurement with an optional unit."""

    name: str
    value: QualityScalar
    unit: str | None = None

    def __post_init__(self) -> None:
        _text(self.name, "quality value name")
        _scalar(self.value, "quality value")
        _optional_text(self.unit, "quality value unit")


@dataclass(frozen=True, slots=True)
class ClockCorrectionEvidence:
    """Explicit correction evidence without changing normalized raw timestamps."""

    state: ClockCorrectionEvidenceState
    source_record_ids: tuple[str, ...] = ()
    correction_types: tuple[str, ...] = ()
    total_offset_ms: int | None = None
    corrected_start_time_ms: int | None = None
    corrected_end_time_ms: int | None = None

    def __post_init__(self) -> None:
        _enum(self.state, ClockCorrectionEvidenceState, "clock evidence state")
        source_record_ids = _text_tuple(self.source_record_ids, "clock source record identifiers")
        correction_types = _text_tuple(self.correction_types, "clock correction types")
        if len(set(source_record_ids)) != len(source_record_ids):
            raise QualityModelError("Clock source record identifiers must be unique.")
        if len(set(correction_types)) != len(correction_types):
            raise QualityModelError("Clock correction types must be unique.")
        for value, label in (
            (self.total_offset_ms, "clock total offset"),
            (self.corrected_start_time_ms, "corrected session start"),
            (self.corrected_end_time_ms, "corrected session end"),
        ):
            _optional_integer(value, label)

        if self.state is ClockCorrectionEvidenceState.SUPPORTED_CONSTANT:
            if not source_record_ids or not correction_types:
                raise QualityModelError("Supported correction evidence requires source records and correction types.")
            if self.total_offset_ms is None or self.corrected_start_time_ms is None or self.corrected_end_time_ms is None:
                raise QualityModelError("Supported correction evidence requires an offset and corrected boundaries.")
        elif self.state is not ClockCorrectionEvidenceState.NOT_QUERIED and not source_record_ids:
            raise QualityModelError("Queried clock evidence requires at least one source record identifier.")
        elif any(
            value is not None
            for value in (
                self.total_offset_ms,
                self.corrected_start_time_ms,
                self.corrected_end_time_ms,
            )
        ):
            raise QualityModelError("Only supported constant corrections can carry corrected values.")

        object.__setattr__(self, "source_record_ids", tuple(sorted(source_record_ids)))
        object.__setattr__(self, "correction_types", tuple(sorted(correction_types)))


@dataclass(frozen=True, slots=True)
class QualityFinding:
    """One versioned, evidence-linked result from a deterministic quality rule."""

    record_id: str
    rule_id: QualityRule
    status: QualityStatus
    impact: QualityImpact
    reason_code: str
    evaluated_record_id: str
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    parameters: tuple[QualityValue, ...]
    measurements: tuple[QualityValue, ...]
    limitations: tuple[str, ...]
    affected_capabilities: tuple[str, ...]
    start_time_ms: TimestampMs | None = None
    end_time_ms: TimestampMs | None = None
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    rule_set_id: str = QUALITY_RULE_SET_ID
    rule_set_version: int = QUALITY_RULE_SET_VERSION
    engine_version: str = QUALITY_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "quality finding identifier")
        _enum(self.rule_id, QualityRule, "quality rule")
        _enum(self.status, QualityStatus, "quality status")
        _enum(self.impact, QualityImpact, "quality impact")
        _text(self.reason_code, "quality reason code")
        if self.status is QualityStatus.PASS and self.reason_code != "condition_not_observed":
            raise QualityModelError("A passing quality finding must use condition_not_observed.")
        if self.status is QualityStatus.NOT_APPLICABLE and self.reason_code != "rule_not_applicable":
            raise QualityModelError("A not-applicable quality finding must use rule_not_applicable.")
        if self.status is QualityStatus.FLAGGED and self.reason_code not in _FLAGGED_REASON_CODES[self.rule_id]:
            raise QualityModelError("The flagged reason code is unsupported for this quality rule.")
        if self.status is QualityStatus.INSUFFICIENT_EVIDENCE and self.reason_code not in _INSUFFICIENT_REASON_CODES[self.rule_id]:
            raise QualityModelError("The insufficient-evidence reason code is unsupported for this quality rule.")
        _text(self.evaluated_record_id, "evaluated record identifier")
        _enum(self.source_class, SourceClass, "quality source class")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise QualityModelError("Quality findings must be companion-derived.")
        if self.rule_set_id != QUALITY_RULE_SET_ID or self.rule_set_version != QUALITY_RULE_SET_VERSION:
            raise QualityModelError("The quality rule-set identity or version is unsupported.")
        if self.engine_version != QUALITY_ENGINE_VERSION:
            raise QualityModelError("The quality engine version is unsupported.")
        if self.status in (QualityStatus.PASS, QualityStatus.NOT_APPLICABLE) and self.impact is not QualityImpact.NONE:
            raise QualityModelError("Pass and not-applicable findings cannot have an adverse impact.")

        source_record_ids = _required_text_tuple(self.source_record_ids, "quality source record identifiers")
        source_provenance_ids = _required_text_tuple(self.source_provenance_ids, "quality source provenance identifiers")
        limitations = _required_text_tuple(self.limitations, "quality limitations")
        affected_capabilities = _required_text_tuple(self.affected_capabilities, "affected capabilities")
        parameters = _quality_values(self.parameters, "quality parameters")
        measurements = _quality_values(self.measurements, "quality measurements")
        _unique(source_record_ids, "quality source record identifiers")
        _unique(source_provenance_ids, "quality source provenance identifiers")
        _unique(limitations, "quality limitations")
        _unique(affected_capabilities, "affected capabilities")
        _unique(tuple(value.name for value in parameters), "quality parameter names")
        _unique(tuple(value.name for value in measurements), "quality measurement names")

        if (self.start_time_ms is None) != (self.end_time_ms is None):
            raise QualityModelError("A quality interval requires both start and end timestamps.")
        if self.start_time_ms is not None and self.end_time_ms is not None:
            start_time_ms = _timestamp(self.start_time_ms, "quality interval start")
            end_time_ms = _timestamp(self.end_time_ms, "quality interval end")
            if start_time_ms >= end_time_ms:
                raise QualityModelError("A quality interval must be positive and half-open.")
            object.__setattr__(self, "start_time_ms", start_time_ms)
            object.__setattr__(self, "end_time_ms", end_time_ms)

        object.__setattr__(self, "source_record_ids", tuple(sorted(source_record_ids)))
        object.__setattr__(self, "source_provenance_ids", tuple(sorted(source_provenance_ids)))
        object.__setattr__(self, "parameters", tuple(sorted(parameters, key=lambda value: value.name)))
        object.__setattr__(self, "measurements", tuple(sorted(measurements, key=lambda value: value.name)))
        object.__setattr__(self, "limitations", tuple(sorted(limitations)))
        object.__setattr__(self, "affected_capabilities", tuple(sorted(affected_capabilities)))


@dataclass(frozen=True, slots=True)
class StructuralQualityReport:
    """Deterministic collection of S19 findings for one normalized night."""

    record_id: str
    night_record_id: str
    required_signal_kinds: tuple[str, ...]
    require_flow_pressure_alignment: bool
    time_basis: TimeBasis
    findings: tuple[QualityFinding, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    rule_set_id: str = QUALITY_RULE_SET_ID
    rule_set_version: int = QUALITY_RULE_SET_VERSION
    engine_version: str = QUALITY_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "structural quality report identifier")
        _text(self.night_record_id, "quality report night identifier")
        required_signal_kinds = _text_tuple(self.required_signal_kinds, "required signal kinds")
        _unique(required_signal_kinds, "required signal kinds")
        if type(self.require_flow_pressure_alignment) is not bool:
            raise QualityModelError("The flow-pressure alignment request must be Boolean.")
        _enum(self.time_basis, TimeBasis, "quality report time basis")
        _enum(self.source_class, SourceClass, "quality report source class")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise QualityModelError("Structural quality reports must be companion-derived.")
        if self.rule_set_id != QUALITY_RULE_SET_ID or self.rule_set_version != QUALITY_RULE_SET_VERSION:
            raise QualityModelError("The quality report rule-set identity or version is unsupported.")
        if self.engine_version != QUALITY_ENGINE_VERSION:
            raise QualityModelError("The quality report engine version is unsupported.")
        if type(self.findings) is not tuple or any(not isinstance(value, QualityFinding) for value in self.findings):
            raise QualityModelError("Structural quality findings must be a tuple of QualityFinding records.")
        _unique(tuple(value.record_id for value in self.findings), "quality finding identifiers")
        object.__setattr__(self, "required_signal_kinds", tuple(sorted(required_signal_kinds)))
        object.__setattr__(
            self,
            "findings",
            tuple(
                sorted(
                    self.findings,
                    key=lambda value: (
                        _QUALITY_RULE_ORDER[value.rule_id],
                        value.evaluated_record_id,
                        float("-inf") if value.start_time_ms is None else value.start_time_ms,
                        value.reason_code,
                        value.record_id,
                    ),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class SignalQualityReport:
    """Deterministic collection of S20 findings for one normalized session."""

    record_id: str
    session_record_id: str
    breath_series_record_id: str | None
    findings: tuple[QualityFinding, ...]
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    rule_set_id: str = QUALITY_RULE_SET_ID
    rule_set_version: int = QUALITY_RULE_SET_VERSION
    engine_version: str = QUALITY_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "signal quality report identifier")
        _text(self.session_record_id, "signal quality report session identifier")
        _optional_text(self.breath_series_record_id, "signal quality report breath-series identifier")
        _enum(self.source_class, SourceClass, "signal quality report source class")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise QualityModelError("Signal quality reports must be companion-derived.")
        if self.rule_set_id != QUALITY_RULE_SET_ID or self.rule_set_version != QUALITY_RULE_SET_VERSION:
            raise QualityModelError("The signal quality report rule-set identity or version is unsupported.")
        if self.engine_version != QUALITY_ENGINE_VERSION:
            raise QualityModelError("The signal quality report engine version is unsupported.")
        if type(self.findings) is not tuple or not self.findings or any(not isinstance(value, QualityFinding) for value in self.findings):
            raise QualityModelError("Signal quality findings must be a nonempty tuple of QualityFinding records.")
        allowed_rules = {QualityRule.LARGE_LEAK, QualityRule.SIGNAL_ARTIFACT, QualityRule.LIKELY_WAKE_BREATHING}
        if any(value.rule_id not in allowed_rules for value in self.findings):
            raise QualityModelError("Signal quality reports can contain only S20 rule findings.")
        _unique(tuple(value.record_id for value in self.findings), "signal quality finding identifiers")
        object.__setattr__(
            self,
            "findings",
            tuple(
                sorted(
                    self.findings,
                    key=lambda value: (
                        _QUALITY_RULE_ORDER[value.rule_id],
                        value.evaluated_record_id,
                        float("-inf") if value.start_time_ms is None else value.start_time_ms,
                        value.reason_code,
                        value.record_id,
                    ),
                )
            ),
        )


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise QualityModelError(f"The {label} must be nonempty text.")


def _optional_text(value: object, label: str) -> None:
    if value is not None:
        _text(value, label)


def _scalar(value: object, label: str) -> None:
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float and math.isfinite(value):
        return
    raise QualityModelError(f"The {label} must be a finite JSON scalar or null.")


def _optional_integer(value: object, label: str) -> None:
    if value is not None and type(value) is not int:
        raise QualityModelError(f"The {label} must be an integer or null.")


def _positive_number(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise QualityModelError(f"The {label} must be a finite positive number.")
    try:
        normalized = float(value)
    except OverflowError as error:
        raise QualityModelError(f"The {label} must be a finite positive number.") from error
    if not math.isfinite(normalized) or normalized <= 0:
        raise QualityModelError(f"The {label} must be a finite positive number.")
    return normalized


def _timestamp(value: object, label: str) -> TimestampMs:
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise QualityModelError(f"The {label} must be a finite millisecond number.")


def _enum(value: object, expected: type[StrEnum], label: str) -> None:
    if not isinstance(value, expected):
        raise QualityModelError(f"The {label} has an unsupported value.")


def _text_tuple(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values):
        raise QualityModelError(f"The {label} must be a tuple of nonempty text values.")
    return values


def _required_text_tuple(values: object, label: str) -> tuple[str, ...]:
    normalized = _text_tuple(values, label)
    if not normalized:
        raise QualityModelError(f"The {label} cannot be empty.")
    return normalized


def _quality_values(values: object, label: str) -> tuple[QualityValue, ...]:
    if type(values) is not tuple or any(not isinstance(value, QualityValue) for value in values):
        raise QualityModelError(f"The {label} must be a tuple of QualityValue records.")
    return values


def _unique(values: tuple[object, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise QualityModelError(f"The {label} must be unique.")
