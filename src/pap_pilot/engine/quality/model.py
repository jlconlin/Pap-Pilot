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
    """Version-1 structural rule identifiers implemented in S19."""

    MISSING_REQUIRED_SIGNAL = "missing_required_signal"
    FLOW_PRESSURE_MISALIGNMENT = "flow_pressure_misalignment"
    SHORT_SESSION = "short_session"
    SPLIT_SESSION_NIGHT = "split_session_night"
    CLOCK_CORRECTION_INTEGRITY = "clock_correction_integrity"


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
