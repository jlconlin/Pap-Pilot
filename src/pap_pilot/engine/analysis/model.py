"""Source-independent records for the generic PAP analysis workspace."""

from dataclasses import asdict, dataclass
from enum import StrEnum
import json
import math
from typing import Final, TypeAlias


ANALYSIS_WORKSPACE_FORMAT: Final = "pap-pilot.analysis-workspace-json"
ANALYSIS_WORKSPACE_FORMAT_VERSION: Final = 1
ANALYSIS_WORKSPACE_SCHEMA_ID: Final = "pap-pilot.analysis-workspace"
ANALYSIS_WORKSPACE_SCHEMA_VERSION: Final = 1
ANALYSIS_WORKSPACE_RECORD_VERSION: Final = 1
ANALYSIS_WORKSPACE_ENGINE_VERSION: Final = "0.1.0"

AnalysisScalar: TypeAlias = bool | int | float | str | None


class AnalysisModelError(ValueError):
    """Raised when a generic analysis-workspace record is invalid."""


class AnalysisAvailability(StrEnum):
    """Whether an analysis resource has attributable evidence."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_EVALUABLE = "not_evaluable"


class AnalysisResourceKind(StrEnum):
    """Stable logical resources exposed by the generic workspace."""

    OVERVIEW = "overview"
    NIGHT_COLLECTION = "night_collection"
    NIGHT_DETAIL = "night_detail"
    TREND_COLLECTION = "trend_collection"
    TREND_DETAIL = "trend_detail"
    EVIDENCE = "evidence"
    EXPERIMENT = "experiment"


def analysis_resource_id(kind: AnalysisResourceKind, target_record_id: str) -> str:
    """Return the stable logical identity for one generic analysis resource."""

    _enum(kind, AnalysisResourceKind, "analysis resource kind")
    target = _text(target_record_id, "analysis resource target identifier")
    if kind is AnalysisResourceKind.OVERVIEW:
        return "analysis:overview"
    if kind is AnalysisResourceKind.NIGHT_COLLECTION:
        return "analysis:nights"
    if kind is AnalysisResourceKind.TREND_COLLECTION:
        return "analysis:trends"
    prefix = {
        AnalysisResourceKind.NIGHT_DETAIL: "analysis:night",
        AnalysisResourceKind.TREND_DETAIL: "analysis:trend",
        AnalysisResourceKind.EVIDENCE: "analysis:evidence",
        AnalysisResourceKind.EXPERIMENT: "analysis:experiment",
    }[kind]
    return f"{prefix}:{target}"


class AnalysisEvidenceKind(StrEnum):
    """Evidence classes that a generic analysis may link without reinterpreting."""

    SETTING = "setting"
    EVENT = "event"
    SIGNAL = "signal"
    QUALITY = "quality"
    METRIC = "metric"
    JOURNAL = "journal"
    EXPERIMENT_REPORT = "experiment_report"


@dataclass(frozen=True, slots=True)
class AnalysisEvidence:
    """One attributable evidence item available to analysis resources."""

    record_id: str
    kind: AnalysisEvidenceKind
    label: str
    availability: AnalysisAvailability
    night_record_ids: tuple[str, ...]
    session_record_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    record_version: int = ANALYSIS_WORKSPACE_RECORD_VERSION

    def __post_init__(self) -> None:
        _record_header(self.record_id, self.record_version, "analysis evidence")
        _enum(self.kind, AnalysisEvidenceKind, "analysis evidence kind")
        _text(self.label, "analysis evidence label")
        _enum(self.availability, AnalysisAvailability, "analysis evidence availability")
        _set_text_tuples(
            self,
            ("night_record_ids", "session_record_ids", "source_record_ids", "source_provenance_ids", "reason_codes", "limitations"),
        )
        if self.availability is AnalysisAvailability.AVAILABLE and (not self.source_record_ids or not self.source_provenance_ids):
            raise AnalysisModelError("Available analysis evidence requires source records and provenance.")
        if self.availability is not AnalysisAvailability.AVAILABLE and not self.reason_codes:
            raise AnalysisModelError("Non-available analysis evidence requires a reason code.")


@dataclass(frozen=True, slots=True)
class AnalysisNight:
    """One therapy night summarized independently of any experiment."""

    record_id: str
    night_record_id: str
    local_date: str
    availability: AnalysisAvailability
    session_record_ids: tuple[str, ...]
    setting_record_ids: tuple[str, ...]
    event_record_ids: tuple[str, ...]
    signal_record_ids: tuple[str, ...]
    quality_report_ids: tuple[str, ...]
    metric_result_ids: tuple[str, ...]
    journal_entry_ids: tuple[str, ...]
    evidence_record_ids: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    record_version: int = ANALYSIS_WORKSPACE_RECORD_VERSION

    def __post_init__(self) -> None:
        _record_header(self.record_id, self.record_version, "analysis night")
        _text(self.night_record_id, "normalized night identifier")
        _local_date(self.local_date)
        _enum(self.availability, AnalysisAvailability, "analysis night availability")
        _set_text_tuples(
            self,
            (
                "session_record_ids",
                "setting_record_ids",
                "event_record_ids",
                "signal_record_ids",
                "quality_report_ids",
                "metric_result_ids",
                "journal_entry_ids",
                "evidence_record_ids",
                "source_record_ids",
                "source_provenance_ids",
                "reason_codes",
                "limitations",
            ),
        )
        if self.availability in (AnalysisAvailability.AVAILABLE, AnalysisAvailability.PARTIAL) and (not self.session_record_ids or not self.source_record_ids or not self.source_provenance_ids):
            raise AnalysisModelError("An available or partial analysis night requires a session, source records, and provenance.")
        if self.availability in (AnalysisAvailability.UNAVAILABLE, AnalysisAvailability.NOT_EVALUABLE) and not self.reason_codes:
            raise AnalysisModelError("An unavailable or not-evaluable analysis night requires a reason code.")
        linked_records = {
            self.night_record_id,
            *self.session_record_ids,
            *self.setting_record_ids,
            *self.event_record_ids,
            *self.signal_record_ids,
            *self.quality_report_ids,
            *self.metric_result_ids,
            *self.journal_entry_ids,
        }
        if not linked_records.issubset(self.source_record_ids):
            raise AnalysisModelError("Analysis-night sources must include every linked therapy record.")


@dataclass(frozen=True, slots=True)
class AnalysisTrendPoint:
    """One night-aligned point in a generic longitudinal series."""

    night_record_id: str
    local_date: str
    value: AnalysisScalar
    availability: AnalysisAvailability
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.night_record_id, "trend-point night identifier")
        _local_date(self.local_date)
        _scalar(self.value, "trend-point value")
        _enum(self.availability, AnalysisAvailability, "trend-point availability")
        _set_text_tuples(self, ("source_record_ids", "source_provenance_ids", "reason_codes"))
        if self.availability is AnalysisAvailability.PARTIAL:
            raise AnalysisModelError("One trend point cannot be partially available.")
        if self.availability is AnalysisAvailability.AVAILABLE:
            if self.value is None or not self.source_record_ids or not self.source_provenance_ids:
                raise AnalysisModelError("An available trend point requires a value, source records, and provenance.")
        elif self.value is not None or not self.reason_codes:
            raise AnalysisModelError("A non-available trend point requires no value and at least one reason code.")


@dataclass(frozen=True, slots=True)
class AnalysisTrend:
    """One versioned longitudinal series whose metric meaning is externally defined."""

    record_id: str
    metric_id: str
    label: str
    unit: str | None
    availability: AnalysisAvailability
    points: tuple[AnalysisTrendPoint, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    record_version: int = ANALYSIS_WORKSPACE_RECORD_VERSION

    def __post_init__(self) -> None:
        _record_header(self.record_id, self.record_version, "analysis trend")
        _text(self.metric_id, "analysis trend metric identifier")
        _text(self.label, "analysis trend label")
        _optional_text(self.unit, "analysis trend unit")
        _enum(self.availability, AnalysisAvailability, "analysis trend availability")
        points = _typed_tuple(self.points, AnalysisTrendPoint, "analysis trend points")
        _unique(tuple(point.night_record_id for point in points), "analysis trend night identifiers")
        points = tuple(sorted(points, key=lambda point: (point.local_date, point.night_record_id)))
        _set_text_tuples(self, ("source_record_ids", "source_provenance_ids", "reason_codes", "limitations"))
        point_sources = {identifier for point in points for identifier in point.source_record_ids}
        point_provenance = {identifier for point in points for identifier in point.source_provenance_ids}
        if not point_sources.issubset(self.source_record_ids) or not point_provenance.issubset(self.source_provenance_ids):
            raise AnalysisModelError("Analysis-trend provenance must include every point source and provenance identifier.")
        point_states = {point.availability for point in points}
        if not points or point_states == {AnalysisAvailability.UNAVAILABLE}:
            expected = AnalysisAvailability.UNAVAILABLE
        elif point_states == {AnalysisAvailability.NOT_EVALUABLE}:
            expected = AnalysisAvailability.NOT_EVALUABLE
        elif point_states == {AnalysisAvailability.AVAILABLE}:
            expected = AnalysisAvailability.AVAILABLE
        else:
            expected = AnalysisAvailability.PARTIAL
        if self.availability is not expected:
            raise AnalysisModelError("Analysis trend availability must reflect its points.")
        if self.availability is not AnalysisAvailability.AVAILABLE and not self.reason_codes:
            raise AnalysisModelError("A partial or unavailable trend requires a reason code.")
        object.__setattr__(self, "points", points)


@dataclass(frozen=True, slots=True)
class AnalysisResource:
    """Stable logical identity for one generic analysis resource."""

    resource_id: str
    kind: AnalysisResourceKind
    target_record_id: str
    availability: AnalysisAvailability
    reason_codes: tuple[str, ...] = ()
    record_version: int = ANALYSIS_WORKSPACE_RECORD_VERSION

    def __post_init__(self) -> None:
        _record_header(self.resource_id, self.record_version, "analysis resource")
        _enum(self.kind, AnalysisResourceKind, "analysis resource kind")
        _text(self.target_record_id, "analysis resource target identifier")
        _enum(self.availability, AnalysisAvailability, "analysis resource availability")
        _set_text_tuples(self, ("reason_codes",))
        if self.resource_id != analysis_resource_id(self.kind, self.target_record_id):
            raise AnalysisModelError("The analysis resource identifier does not match its kind and target.")
        if self.availability is not AnalysisAvailability.AVAILABLE and not self.reason_codes:
            raise AnalysisModelError("A non-available analysis resource requires a reason code.")


@dataclass(frozen=True, slots=True)
class AnalysisExperimentReference:
    """Optional link to an experiment without making it the analysis root."""

    experiment_record_id: str
    label: str
    resource_id: str
    summary_record_id: str | None
    availability: AnalysisAvailability
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    compatibility_fixture_id: str | None = None
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    record_version: int = ANALYSIS_WORKSPACE_RECORD_VERSION

    def __post_init__(self) -> None:
        _record_header(self.experiment_record_id, self.record_version, "analysis experiment reference")
        _text(self.label, "analysis experiment label")
        _text(self.resource_id, "analysis experiment resource identifier")
        _optional_text(self.summary_record_id, "analysis experiment summary identifier")
        _optional_text(self.compatibility_fixture_id, "analysis compatibility fixture identifier")
        _enum(self.availability, AnalysisAvailability, "analysis experiment availability")
        _set_text_tuples(self, ("source_record_ids", "source_provenance_ids", "reason_codes", "limitations"))
        if self.availability is AnalysisAvailability.AVAILABLE and (self.summary_record_id is None or not self.source_record_ids or not self.source_provenance_ids):
            raise AnalysisModelError("An available experiment reference requires a summary record, sources, and provenance.")
        if self.summary_record_id is not None and ({self.experiment_record_id, self.summary_record_id} - set(self.source_record_ids)):
            raise AnalysisModelError("Experiment-reference sources must include the experiment and summary records.")
        if self.availability is not AnalysisAvailability.AVAILABLE and not self.reason_codes:
            raise AnalysisModelError("A non-available experiment reference requires a reason code.")


@dataclass(frozen=True, slots=True)
class AnalysisWorkspace:
    """The generic product-level contract for PAP analysis over time."""

    record_id: str
    title: str
    availability: AnalysisAvailability
    nights: tuple[AnalysisNight, ...]
    trends: tuple[AnalysisTrend, ...]
    evidence: tuple[AnalysisEvidence, ...]
    resources: tuple[AnalysisResource, ...]
    experiments: tuple[AnalysisExperimentReference, ...]
    source_record_ids: tuple[str, ...]
    source_provenance_ids: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    schema_id: str = ANALYSIS_WORKSPACE_SCHEMA_ID
    schema_version: int = ANALYSIS_WORKSPACE_SCHEMA_VERSION
    record_version: int = ANALYSIS_WORKSPACE_RECORD_VERSION
    engine_version: str = ANALYSIS_WORKSPACE_ENGINE_VERSION

    def __post_init__(self) -> None:
        _record_header(self.record_id, self.record_version, "analysis workspace")
        _text(self.title, "analysis workspace title")
        if self.schema_id != ANALYSIS_WORKSPACE_SCHEMA_ID or self.schema_version != ANALYSIS_WORKSPACE_SCHEMA_VERSION:
            raise AnalysisModelError("The analysis workspace schema identity or version is unsupported.")
        if self.engine_version != ANALYSIS_WORKSPACE_ENGINE_VERSION:
            raise AnalysisModelError("The analysis workspace engine version is unsupported.")
        _enum(self.availability, AnalysisAvailability, "analysis workspace availability")
        nights = _typed_tuple(self.nights, AnalysisNight, "analysis nights")
        trends = _typed_tuple(self.trends, AnalysisTrend, "analysis trends")
        evidence = _typed_tuple(self.evidence, AnalysisEvidence, "analysis evidence")
        resources = _typed_tuple(self.resources, AnalysisResource, "analysis resources")
        experiments = _typed_tuple(self.experiments, AnalysisExperimentReference, "analysis experiment references")
        for label, values in (
            ("analysis night record identifiers", tuple(value.record_id for value in nights)),
            ("normalized night identifiers", tuple(value.night_record_id for value in nights)),
            ("analysis trend identifiers", tuple(value.record_id for value in trends)),
            ("analysis evidence identifiers", tuple(value.record_id for value in evidence)),
            ("analysis resource identifiers", tuple(value.resource_id for value in resources)),
            ("analysis experiment identifiers", tuple(value.experiment_record_id for value in experiments)),
        ):
            _unique(values, label)
        _set_text_tuples(self, ("source_record_ids", "source_provenance_ids", "reason_codes", "limitations"))
        night_targets = {value.night_record_id for value in nights}
        trend_targets = {value.record_id for value in trends}
        evidence_targets = {value.record_id for value in evidence}
        experiment_targets = {value.experiment_record_id for value in experiments}
        expected_targets = {
            AnalysisResourceKind.OVERVIEW: {self.record_id},
            AnalysisResourceKind.NIGHT_COLLECTION: {self.record_id},
            AnalysisResourceKind.NIGHT_DETAIL: night_targets,
            AnalysisResourceKind.TREND_COLLECTION: {self.record_id},
            AnalysisResourceKind.TREND_DETAIL: trend_targets,
            AnalysisResourceKind.EVIDENCE: evidence_targets,
            AnalysisResourceKind.EXPERIMENT: experiment_targets,
        }
        if any(resource.target_record_id not in expected_targets[resource.kind] for resource in resources):
            raise AnalysisModelError("Every analysis resource must target a record of its declared kind.")
        resource_ids = {resource.resource_id for resource in resources}
        if any(value.resource_id not in resource_ids for value in experiments):
            raise AnalysisModelError("Every experiment reference must resolve to an experiment resource.")
        if any(identifier not in evidence_targets for night in nights for identifier in night.evidence_record_ids):
            raise AnalysisModelError("Every night evidence identifier must resolve in the workspace evidence inventory.")
        nested_sources = {
            identifier
            for value in (*nights, *trends, *evidence, *experiments)
            for identifier in value.source_record_ids
        }
        nested_provenance = {
            identifier
            for value in (*nights, *trends, *evidence, *experiments)
            for identifier in value.source_provenance_ids
        }
        if not nested_sources.issubset(self.source_record_ids) or not nested_provenance.issubset(self.source_provenance_ids):
            raise AnalysisModelError("Workspace provenance must include every nested source and provenance identifier.")
        if self.availability in (AnalysisAvailability.AVAILABLE, AnalysisAvailability.PARTIAL) and (not nights or not self.source_record_ids or not self.source_provenance_ids):
            raise AnalysisModelError("An available or partial workspace requires therapy nights, sources, and provenance.")
        if self.availability in (AnalysisAvailability.UNAVAILABLE, AnalysisAvailability.NOT_EVALUABLE) and not self.reason_codes:
            raise AnalysisModelError("An unavailable or not-evaluable workspace requires a reason code.")
        object.__setattr__(self, "nights", tuple(sorted(nights, key=lambda value: (value.local_date, value.night_record_id))))
        object.__setattr__(self, "trends", tuple(sorted(trends, key=lambda value: value.record_id)))
        object.__setattr__(self, "evidence", tuple(sorted(evidence, key=lambda value: value.record_id)))
        object.__setattr__(self, "resources", tuple(sorted(resources, key=lambda value: value.resource_id)))
        object.__setattr__(self, "experiments", tuple(sorted(experiments, key=lambda value: value.experiment_record_id)))


def serialize_analysis_workspace(workspace: AnalysisWorkspace, *, indent: int | None = None) -> str:
    """Serialize a workspace to stable JSON without interpreting its evidence."""

    if not isinstance(workspace, AnalysisWorkspace):
        raise AnalysisModelError("Only an AnalysisWorkspace can be serialized.")
    envelope = {
        "format": ANALYSIS_WORKSPACE_FORMAT,
        "format_version": ANALYSIS_WORKSPACE_FORMAT_VERSION,
        "workspace": _json_value(asdict(workspace)),
    }
    if indent is None:
        return json.dumps(envelope, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    if type(indent) is not int or indent <= 0:
        raise AnalysisModelError("Indented workspace serialization requires a positive integer.")
    return json.dumps(envelope, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=indent) + "\n"


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _record_header(record_id: str, record_version: int, label: str) -> None:
    _text(record_id, f"{label} identifier")
    if record_version != ANALYSIS_WORKSPACE_RECORD_VERSION:
        raise AnalysisModelError(f"The {label} record version is unsupported.")


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise AnalysisModelError(f"The {label} must be nonempty text.")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is not None:
        return _text(value, label)
    return None


def _local_date(value: object) -> str:
    text = _text(value, "analysis local date")
    try:
        year, month, day = (int(part) for part in text.split("-"))
    except (TypeError, ValueError):
        raise AnalysisModelError("The analysis local date must use YYYY-MM-DD.") from None
    from datetime import date

    try:
        parsed = date(year, month, day)
    except ValueError as error:
        raise AnalysisModelError("The analysis local date must be valid.") from error
    if parsed.isoformat() != text:
        raise AnalysisModelError("The analysis local date must use canonical YYYY-MM-DD.")
    return text


def _scalar(value: object, label: str) -> AnalysisScalar:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise AnalysisModelError(f"The {label} must be a finite JSON scalar.")


def _enum(value: object, expected: type[StrEnum], label: str) -> None:
    if not isinstance(value, expected):
        raise AnalysisModelError(f"The {label} is unsupported.")


def _typed_tuple(value: object, expected: type, label: str) -> tuple:
    if type(value) is not tuple or any(not isinstance(item, expected) for item in value):
        raise AnalysisModelError(f"The {label} must be a tuple of {expected.__name__} records.")
    return value


def _set_text_tuples(record: object, field_names: tuple[str, ...]) -> None:
    for field_name in field_names:
        values = getattr(record, field_name)
        if type(values) is not tuple or any(type(value) is not str or not value.strip() for value in values):
            raise AnalysisModelError(f"The {field_name.replace('_', ' ')} must be a tuple of nonempty text values.")
        _unique(values, field_name.replace("_", " "))
        object.__setattr__(record, field_name, tuple(sorted(values)))


def _unique(values: tuple[object, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise AnalysisModelError(f"The {label} must be unique.")
