"""Immutable records for deterministic PAP Pilot metric results."""

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Final, TypeAlias

from pap_pilot.engine.model import SourceClass
from pap_pilot.engine.quality import QUALITY_RULE_SET_ID, QUALITY_RULE_SET_VERSION


METRIC_SET_ID: Final = "pap-pilot.ps-min-objective-metrics"
METRIC_SET_VERSION: Final = 1
METRIC_ENGINE_VERSION: Final = "0.1.0"
MEAN_MASK_PRESSURE_ABOVE_EPAP_ALGORITHM_VERSION: Final = 1
MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION: Final = 1
MINIMUM_ELIGIBLE_DURATION_MS: Final = 300_000
VENTILATION_WINDOW_DURATION_MS: Final = 60_000
VENTILATION_WINDOW_STEP_MS: Final = 1_000
MINIMUM_VENTILATION_OBSERVATIONS: Final = 20

MetricScalar: TypeAlias = bool | int | float | str | None
TimestampMs: TypeAlias = int | float


class MetricModelError(ValueError):
    """Raised when a metric input or result is structurally invalid."""


class MetricId(StrEnum):
    """Metric identifiers in metric-set version 1."""

    MEAN_MASK_PRESSURE_ABOVE_EPAP = "mean_mask_pressure_above_epap"
    MINUTE_VENTILATION_UPPER_TAIL_RATIO = "minute_ventilation_upper_tail_ratio"


class MetricStatus(StrEnum):
    """Whether a deterministic metric could be calculated."""

    CALCULATED = "calculated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class MetricReason(StrEnum):
    """Stable result reasons for metric-set version 1."""

    CALCULATED = "calculated"
    SETTINGS_UNAVAILABLE = "settings_unavailable"
    SETTINGS_INCONSISTENT = "settings_inconsistent"
    REQUIRED_SIGNAL_UNAVAILABLE = "required_signal_unavailable"
    UNSUPPORTED_SIGNAL_CONTRACT = "unsupported_signal_contract"
    QUALITY_PREREQUISITE_UNRESOLVED = "quality_prerequisite_unresolved"
    ELIGIBLE_DURATION_BELOW_300000_MS = "eligible_duration_below_300000_ms"
    TOO_FEW_VENTILATION_WINDOWS = "too_few_ventilation_windows"
    NONPOSITIVE_VENTILATION_MEDIAN = "nonpositive_ventilation_median"


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One versioned metric parameter with an optional unit."""

    name: str
    value: MetricScalar
    unit: str | None = None

    def __post_init__(self) -> None:
        _text(self.name, "metric value name")
        _scalar(self.value, "metric value")
        _optional_text(self.unit, "metric value unit")


@dataclass(frozen=True, slots=True)
class MetricSettingValue:
    """One exact normalized setting used for one evaluated session."""

    session_record_id: str
    setting_record_id: str
    name: str
    value: int | float
    unit: str | None

    def __post_init__(self) -> None:
        _text(self.session_record_id, "metric setting session identifier")
        _text(self.setting_record_id, "metric setting record identifier")
        _text(self.name, "metric setting name")
        _number(self.value, "metric setting value")
        _optional_text(self.unit, "metric setting unit")


@dataclass(frozen=True, slots=True)
class MetricInterval:
    """One requested, eligible, or excluded half-open raw-time interval."""

    session_record_id: str
    start_time_ms: TimestampMs
    end_time_ms: TimestampMs
    source_segment_ids: tuple[str, ...] = ()
    quality_finding_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.session_record_id, "metric interval session identifier")
        start = _timestamp(self.start_time_ms, "metric interval start")
        end = _timestamp(self.end_time_ms, "metric interval end")
        if start >= end:
            raise MetricModelError("A metric interval must be positive and half-open.")
        source_segment_ids = _text_tuple(self.source_segment_ids, "metric interval source segment identifiers")
        quality_finding_ids = _text_tuple(self.quality_finding_ids, "metric interval quality finding identifiers")
        reason_codes = _text_tuple(self.reason_codes, "metric interval reason codes")
        _unique(source_segment_ids, "metric interval source segment identifiers")
        _unique(quality_finding_ids, "metric interval quality finding identifiers")
        _unique(reason_codes, "metric interval reason codes")
        object.__setattr__(self, "start_time_ms", start)
        object.__setattr__(self, "end_time_ms", end)
        object.__setattr__(self, "source_segment_ids", tuple(sorted(source_segment_ids)))
        object.__setattr__(self, "quality_finding_ids", tuple(sorted(quality_finding_ids)))
        object.__setattr__(self, "reason_codes", tuple(sorted(reason_codes)))


@dataclass(frozen=True, slots=True)
class MetricResult:
    """One deterministic, evidence-linked result for one normalized night."""

    record_id: str
    metric_id: MetricId
    algorithm_version: int
    status: MetricStatus
    reason_code: MetricReason
    value: float | None
    unit: str | None
    parameters: tuple[MetricValue, ...]
    settings: tuple[MetricSettingValue, ...]
    night_record_id: str
    session_record_ids: tuple[str, ...]
    setting_record_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    quality_report_ids: tuple[str, ...]
    quality_finding_ids: tuple[str, ...]
    requested_intervals: tuple[MetricInterval, ...]
    eligible_intervals: tuple[MetricInterval, ...]
    excluded_intervals: tuple[MetricInterval, ...]
    requested_duration_ms: TimestampMs
    eligible_duration_ms: TimestampMs
    excluded_duration_ms: TimestampMs
    sample_cell_count: int
    limitations: tuple[str, ...]
    measurements: tuple[MetricValue, ...] = ()
    observation_count: int = 0
    source_class: SourceClass = SourceClass.COMPANION_DERIVED
    metric_set_id: str = METRIC_SET_ID
    metric_set_version: int = METRIC_SET_VERSION
    quality_rule_set_id: str = QUALITY_RULE_SET_ID
    quality_rule_set_version: int = QUALITY_RULE_SET_VERSION
    engine_version: str = METRIC_ENGINE_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "metric result identifier")
        _enum(self.metric_id, MetricId, "metric identifier")
        _positive_integer(self.algorithm_version, "metric algorithm version")
        _enum(self.status, MetricStatus, "metric status")
        _enum(self.reason_code, MetricReason, "metric reason")
        expected_algorithm_version = {
            MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP: MEAN_MASK_PRESSURE_ABOVE_EPAP_ALGORITHM_VERSION,
            MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO: MINUTE_VENTILATION_UPPER_TAIL_RATIO_ALGORITHM_VERSION,
        }[self.metric_id]
        if self.algorithm_version != expected_algorithm_version:
            raise MetricModelError("The metric identity or algorithm version is unsupported.")
        if self.metric_set_id != METRIC_SET_ID or self.metric_set_version != METRIC_SET_VERSION:
            raise MetricModelError("The metric-set identity or version is unsupported.")
        if self.quality_rule_set_id != QUALITY_RULE_SET_ID or self.quality_rule_set_version != QUALITY_RULE_SET_VERSION:
            raise MetricModelError("The quality rule-set identity or version is unsupported.")
        if self.engine_version != METRIC_ENGINE_VERSION:
            raise MetricModelError("The metric engine version is unsupported.")
        _enum(self.source_class, SourceClass, "metric source class")
        if self.source_class is not SourceClass.COMPANION_DERIVED:
            raise MetricModelError("Metric results must be companion-derived.")

        parameters = _typed_tuple(self.parameters, MetricValue, "metric parameters")
        measurements = _typed_tuple(self.measurements, MetricValue, "metric measurements")
        settings = _typed_tuple(self.settings, MetricSettingValue, "metric settings")
        requested = _typed_tuple(self.requested_intervals, MetricInterval, "requested metric intervals")
        eligible = _typed_tuple(self.eligible_intervals, MetricInterval, "eligible metric intervals")
        excluded = _typed_tuple(self.excluded_intervals, MetricInterval, "excluded metric intervals")
        _unique(tuple(value.name for value in parameters), "metric parameter names")
        _unique(tuple(value.name for value in measurements), "metric measurement names")
        _unique(tuple((value.session_record_id, value.name) for value in settings), "per-session metric setting names")
        for name, values in (
            ("metric session identifiers", self.session_record_ids),
            ("metric setting identifiers", self.setting_record_ids),
            ("metric source identifiers", self.source_record_ids),
            ("metric source provenance identifiers", self.source_provenance_ids),
            ("metric quality report identifiers", self.quality_report_ids),
            ("metric quality finding identifiers", self.quality_finding_ids),
            ("metric limitations", self.limitations),
        ):
            normalized = _text_tuple(values, name)
            _unique(normalized, name)
            object.__setattr__(self, _field_name(name), tuple(sorted(normalized)))
        _text(self.night_record_id, "metric night identifier")
        if not self.session_record_ids or not requested or not self.quality_report_ids or not self.quality_finding_ids or not self.limitations:
            raise MetricModelError("A metric result requires sessions, requested intervals, consulted quality evidence, and limitations.")
        if tuple(sorted(value.setting_record_id for value in settings)) != self.setting_record_ids:
            raise MetricModelError("Metric setting identifiers must exactly match the setting snapshot.")
        _duration(self.requested_duration_ms, "requested metric duration")
        _duration(self.eligible_duration_ms, "eligible metric duration")
        _duration(self.excluded_duration_ms, "excluded metric duration")
        if not math.isclose(sum(value.end_time_ms - value.start_time_ms for value in requested), self.requested_duration_ms, rel_tol=0.0, abs_tol=1e-6):
            raise MetricModelError("Requested metric intervals must match the requested duration.")
        if not math.isclose(sum(value.end_time_ms - value.start_time_ms for value in eligible), self.eligible_duration_ms, rel_tol=0.0, abs_tol=1e-6):
            raise MetricModelError("Eligible metric intervals must match the eligible duration.")
        if not math.isclose(sum(value.end_time_ms - value.start_time_ms for value in excluded), self.excluded_duration_ms, rel_tol=0.0, abs_tol=1e-6):
            raise MetricModelError("Excluded metric intervals must match the excluded duration.")
        if not math.isclose(self.eligible_duration_ms + self.excluded_duration_ms, self.requested_duration_ms, rel_tol=0.0, abs_tol=1e-6):
            raise MetricModelError("Eligible and excluded durations must partition the requested duration.")
        if type(self.sample_cell_count) is not int or self.sample_cell_count < 0:
            raise MetricModelError("The metric sample-cell count must be a nonnegative integer.")
        if type(self.observation_count) is not int or self.observation_count < 0:
            raise MetricModelError("The metric observation count must be a nonnegative integer.")
        if any(value.session_record_id not in self.session_record_ids for value in (*requested, *eligible, *excluded)):
            raise MetricModelError("Every metric interval must identify an evaluated session.")
        if self.metric_id is MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP and (measurements or self.observation_count):
            raise MetricModelError("The pressure metric cannot carry ventilation observations or measurements.")
        if self.status is MetricStatus.CALCULATED:
            expected_unit = "cm H₂O" if self.metric_id is MetricId.MEAN_MASK_PRESSURE_ABOVE_EPAP else "1"
            if self.reason_code is not MetricReason.CALCULATED or self.value is None or self.unit != expected_unit:
                raise MetricModelError("A calculated metric requires its calculated reason, finite value, and canonical unit.")
            _number(self.value, "calculated metric value")
            if self.eligible_duration_ms < MINIMUM_ELIGIBLE_DURATION_MS or self.sample_cell_count == 0:
                raise MetricModelError("A calculated metric requires the minimum eligible duration and contributing sample cells.")
            if len(settings) != len(self.session_record_ids) * 6:
                raise MetricModelError("A calculated metric requires all six settings for every session.")
            if self.metric_id is MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO:
                values = {measurement.name: measurement for measurement in measurements}
                if self.observation_count < MINIMUM_VENTILATION_OBSERVATIONS or set(values) != {"ventilation_q50_l_min", "ventilation_q95_l_min"}:
                    raise MetricModelError("A calculated ventilation metric requires its observation minimum and exact supporting quantiles.")
                if any(measurement.unit != "L/min" or type(measurement.value) is not float for measurement in values.values()):
                    raise MetricModelError("Ventilation quantiles require finite floating-point L/min values.")
                q50 = values["ventilation_q50_l_min"].value
                q95 = values["ventilation_q95_l_min"].value
                assert type(q50) is float and type(q95) is float
                if q50 <= 0 or q95 < q50 or not math.isclose(self.value, q95 / q50, rel_tol=1e-12, abs_tol=1e-12):
                    raise MetricModelError("A calculated ventilation metric requires a positive median.")
        elif self.reason_code is MetricReason.CALCULATED or self.value is not None or self.unit is not None:
            raise MetricModelError("An insufficient metric cannot carry a calculated reason, value, or unit.")
        elif self.reason_code is MetricReason.ELIGIBLE_DURATION_BELOW_300000_MS and self.eligible_duration_ms >= MINIMUM_ELIGIBLE_DURATION_MS:
            raise MetricModelError("The eligible-duration reason requires duration below the exact minimum.")
        elif self.reason_code is MetricReason.TOO_FEW_VENTILATION_WINDOWS and (self.metric_id is not MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO or self.eligible_duration_ms < MINIMUM_ELIGIBLE_DURATION_MS or self.observation_count >= MINIMUM_VENTILATION_OBSERVATIONS):
            raise MetricModelError("The too-few-windows reason requires sufficient duration and fewer than twenty ventilation observations.")
        elif self.reason_code is MetricReason.NONPOSITIVE_VENTILATION_MEDIAN:
            values = {measurement.name: measurement for measurement in measurements}
            q50 = values.get("ventilation_q50_l_min")
            if self.metric_id is not MetricId.MINUTE_VENTILATION_UPPER_TAIL_RATIO or self.eligible_duration_ms < MINIMUM_ELIGIBLE_DURATION_MS or self.observation_count < MINIMUM_VENTILATION_OBSERVATIONS or set(values) != {"ventilation_q50_l_min", "ventilation_q95_l_min"} or any(measurement.unit != "L/min" or type(measurement.value) is not float for measurement in values.values()) or q50 is None or q50.value > 0:
                raise MetricModelError("The nonpositive-median reason requires sufficient ventilation observations and a nonpositive Q50.")
        object.__setattr__(self, "parameters", tuple(sorted(parameters, key=lambda value: value.name)))
        object.__setattr__(self, "measurements", tuple(sorted(measurements, key=lambda value: value.name)))
        object.__setattr__(self, "settings", tuple(sorted(settings, key=lambda value: (value.session_record_id, value.name))))
        object.__setattr__(self, "requested_intervals", tuple(sorted(requested, key=_interval_key)))
        object.__setattr__(self, "eligible_intervals", tuple(sorted(eligible, key=_interval_key)))
        object.__setattr__(self, "excluded_intervals", tuple(sorted(excluded, key=_interval_key)))


def _field_name(label: str) -> str:
    return {
        "metric session identifiers": "session_record_ids",
        "metric setting identifiers": "setting_record_ids",
        "metric source identifiers": "source_record_ids",
        "metric source provenance identifiers": "source_provenance_ids",
        "metric quality report identifiers": "quality_report_ids",
        "metric quality finding identifiers": "quality_finding_ids",
        "metric limitations": "limitations",
    }[label]


def _interval_key(value: MetricInterval) -> tuple[str, float, float, tuple[str, ...]]:
    return value.session_record_id, float(value.start_time_ms), float(value.end_time_ms), value.source_segment_ids


def _text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise MetricModelError(f"The {label} must be nonempty text.")


def _optional_text(value: object, label: str) -> None:
    if value is not None:
        _text(value, label)


def _scalar(value: object, label: str) -> None:
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float and math.isfinite(value):
        return
    raise MetricModelError(f"The {label} must be a finite JSON scalar or null.")


def _number(value: object, label: str) -> None:
    try:
        finite = type(value) in (int, float) and math.isfinite(float(value))
    except OverflowError:
        finite = False
    if not finite:
        raise MetricModelError(f"The {label} must be a finite number.")


def _timestamp(value: object, label: str) -> TimestampMs:
    _number(value, label)
    return value  # type: ignore[return-value]


def _duration(value: object, label: str) -> None:
    _number(value, label)
    if value < 0:  # type: ignore[operator]
        raise MetricModelError(f"The {label} cannot be negative.")


def _positive_integer(value: object, label: str) -> None:
    if type(value) is not int or value <= 0:
        raise MetricModelError(f"The {label} must be a positive integer.")


def _enum(value: object, expected: type[StrEnum], label: str) -> None:
    if not isinstance(value, expected):
        raise MetricModelError(f"The {label} is unsupported.")


def _text_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str or not item.strip() for item in value):
        raise MetricModelError(f"The {label} must be a tuple of nonempty text values.")
    return value


def _typed_tuple(value: object, expected: type, label: str) -> tuple:
    if type(value) is not tuple or any(not isinstance(item, expected) for item in value):
        raise MetricModelError(f"The {label} must be a tuple of {expected.__name__} records.")
    return value


def _unique(values: tuple, label: str) -> None:
    if len(set(values)) != len(values):
        raise MetricModelError(f"The {label} must be unique.")
