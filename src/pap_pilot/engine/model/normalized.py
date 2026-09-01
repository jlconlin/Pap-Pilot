"""Immutable normalized PAP records with canonical JSON serialization."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, time
from enum import StrEnum
import json
import math
from typing import Any, ClassVar, Final, TypeAlias


NORMALIZED_FORMAT: Final = "pap-pilot.normalized"
NORMALIZED_FORMAT_VERSION: Final = 1
NORMALIZED_RECORD_VERSION: Final = 1


class NormalizedModelError(ValueError):
    """Raised when a normalized record or serialized payload is invalid."""


class SourceClass(StrEnum):
    """A stage in the provenance chain for normalized information."""

    MACHINE_RECORDED = "machine_recorded"
    MACHINE_LABELED = "machine_labeled"
    OSCAR_NORMALIZED = "oscar_normalized"
    OSCAR_DERIVED = "oscar_derived"
    COMPANION_DERIVED = "companion_derived"
    AI_GENERATED = "ai_generated"
    USER_REPORTED = "user_reported"
    EXTERNAL_SENSOR = "external_sensor"


class SignalRepresentation(StrEnum):
    """How timestamps and values in a normalized signal are interpreted."""

    UNIFORM_WAVEFORM = "uniform_waveform"
    TIMED_UPDATES = "timed_updates"


class IntervalClosure(StrEnum):
    """Whether a segment's final boundary is inclusive or exclusive."""

    START_INCLUSIVE_END_EXCLUSIVE = "start_inclusive_end_exclusive"
    START_AND_END_INCLUSIVE = "start_and_end_inclusive"


@dataclass(frozen=True, slots=True)
class SourceReference:
    """One stable identifier in an upstream source system."""

    RECORD_TYPE: ClassVar[str] = "source_reference"

    source_record_type: str
    source_record_id: str
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.source_record_type, "source record type")
        _validate_text(self.source_record_id, "source record identifier")


@dataclass(frozen=True, slots=True)
class ProvenanceValue:
    """One lossless source-specific provenance value."""

    RECORD_TYPE: ClassVar[str] = "provenance_value"

    name: str
    value: str
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.name, "provenance value name")
        _validate_text(self.value, "provenance value")


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Source identity and transformation history for one normalized record."""

    RECORD_TYPE: ClassVar[str] = "provenance"

    record_id: str
    source_classes: tuple[SourceClass, ...]
    source_system: str
    source_references: tuple[SourceReference, ...]
    source_system_version: str | None = None
    source_schema_version: str | None = None
    producer: str = "pap_pilot"
    producer_version: str = "0.1.0"
    parent_provenance_ids: tuple[str, ...] = ()
    source_values: tuple[ProvenanceValue, ...] = ()
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.record_id, "provenance record identifier")
        _validate_text(self.source_system, "source system")
        _validate_optional_text(self.source_system_version, "source system version")
        _validate_optional_text(self.source_schema_version, "source schema version")
        _validate_text(self.producer, "producer")
        _validate_text(self.producer_version, "producer version")
        source_classes = _typed_tuple(
            self.source_classes,
            SourceClass,
            "source classes",
        )
        if not source_classes:
            raise NormalizedModelError("Provenance requires at least one source class.")
        if len(set(source_classes)) != len(source_classes):
            raise NormalizedModelError("Provenance source classes must be unique.")
        source_references = _typed_tuple(
            self.source_references,
            SourceReference,
            "source references",
        )
        if not source_references:
            raise NormalizedModelError("Provenance requires at least one source reference.")
        source_values = _typed_tuple(
            self.source_values,
            ProvenanceValue,
            "source values",
        )
        parent_ids = _text_tuple(
            self.parent_provenance_ids,
            "parent provenance identifiers",
        )
        _require_unique(source_references, "source references")
        _require_unique(source_values, "source values")
        _require_unique(
            tuple(value.name for value in source_values),
            "source value names",
        )
        _require_unique(parent_ids, "parent provenance identifiers")
        object.__setattr__(
            self,
            "source_classes",
            tuple(sorted(source_classes, key=lambda value: value.value)),
        )
        object.__setattr__(
            self,
            "source_references",
            tuple(
                sorted(
                    source_references,
                    key=lambda value: (
                        value.source_record_type,
                        value.source_record_id,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "source_values",
            tuple(
                sorted(
                    source_values,
                    key=lambda value: (value.name, value.value),
                )
            ),
        )
        object.__setattr__(self, "parent_provenance_ids", tuple(sorted(parent_ids)))


@dataclass(frozen=True, slots=True)
class SettingRecord:
    """One normalized therapy setting with an explicit unit and provenance."""

    RECORD_TYPE: ClassVar[str] = "setting"

    record_id: str
    name: str
    value: bool | int | float | str
    unit: str | None
    provenance: ProvenanceRecord
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.record_id, "setting record identifier")
        _validate_text(self.name, "setting name")
        _validate_scalar(self.value, "setting value")
        _validate_optional_text(self.unit, "setting unit")
        _validate_instance(self.provenance, ProvenanceRecord, "setting provenance")


@dataclass(frozen=True, slots=True)
class EventRecord:
    """One normalized event occurrence without a derived interpretation."""

    RECORD_TYPE: ClassVar[str] = "event"

    record_id: str
    event_kind: str
    start_time_ms: int
    duration_ms: int
    provenance: ProvenanceRecord
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.record_id, "event record identifier")
        _validate_text(self.event_kind, "event kind")
        _validate_integer(self.start_time_ms, "event start time")
        _validate_integer(self.duration_ms, "event duration")
        if self.duration_ms < 0:
            raise NormalizedModelError("Event duration cannot be negative.")
        _validate_instance(self.provenance, ProvenanceRecord, "event provenance")


@dataclass(frozen=True, slots=True)
class SignalSegmentRecord:
    """One independent normalized signal segment with exact stored samples."""

    RECORD_TYPE: ClassVar[str] = "signal_segment"

    record_id: str
    start_time_ms: int
    end_time_ms: int
    interval_closure: IntervalClosure
    sample_times_ms: tuple[float, ...]
    values: tuple[float, ...]
    sample_interval_ms: float | None
    provenance: ProvenanceRecord
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.record_id, "signal segment record identifier")
        _validate_integer(self.start_time_ms, "signal segment start time")
        _validate_integer(self.end_time_ms, "signal segment end time")
        _validate_instance(
            self.interval_closure,
            IntervalClosure,
            "signal interval closure",
        )
        sample_times = _number_tuple(self.sample_times_ms, "signal sample times")
        values = _number_tuple(self.values, "signal values")
        if not sample_times or len(sample_times) != len(values):
            raise NormalizedModelError(
                "Signal sample times and values must have the same positive length."
            )
        if any(
            current > following
            for current, following in zip(sample_times, sample_times[1:])
        ):
            raise NormalizedModelError("Signal sample times must be nondecreasing.")
        if self.interval_closure is IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE:
            if (
                self.start_time_ms >= self.end_time_ms
                or sample_times[0] < self.start_time_ms
                or sample_times[-1] >= self.end_time_ms
            ):
                raise NormalizedModelError(
                    "Signal samples must lie inside the half-open segment interval."
                )
        elif (
            self.start_time_ms > self.end_time_ms
            or sample_times[0] < self.start_time_ms
            or sample_times[-1] > self.end_time_ms
        ):
            raise NormalizedModelError(
                "Signal samples must lie inside the closed segment interval."
            )
        if self.sample_interval_ms is not None:
            _validate_number(self.sample_interval_ms, "signal sample interval")
            if self.sample_interval_ms <= 0:
                raise NormalizedModelError(
                    "Signal sample interval must be positive when present."
                )
            try:
                normalized_interval = float(self.sample_interval_ms)
            except OverflowError as error:
                raise NormalizedModelError(
                    "Signal sample interval must fit a finite floating-point value."
                ) from error
            if not math.isfinite(normalized_interval):
                raise NormalizedModelError(
                    "Signal sample interval must fit a finite floating-point value."
                )
            expected_times = tuple(
                self.start_time_ms + index * normalized_interval
                for index in range(len(sample_times))
            )
            if any(
                not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6)
                for actual, expected in zip(sample_times, expected_times)
            ):
                raise NormalizedModelError(
                    "Uniform signal sample times must match the declared interval."
                )
            expected_end = self.start_time_ms + len(sample_times) * normalized_interval
            if not math.isclose(
                self.end_time_ms,
                expected_end,
                rel_tol=0.0,
                abs_tol=1e-6,
            ):
                raise NormalizedModelError(
                    "A uniform signal segment must end one interval after its final sample."
                )
            object.__setattr__(self, "sample_interval_ms", normalized_interval)
        _validate_instance(
            self.provenance,
            ProvenanceRecord,
            "signal segment provenance",
        )
        object.__setattr__(self, "sample_times_ms", sample_times)
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class SignalRecord:
    """One normalized signal channel composed of independent segments."""

    RECORD_TYPE: ClassVar[str] = "signal"

    record_id: str
    signal_kind: str
    unit: str
    representation: SignalRepresentation
    segments: tuple[SignalSegmentRecord, ...]
    provenance: ProvenanceRecord
    value_semantics: str | None = None
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.record_id, "signal record identifier")
        _validate_text(self.signal_kind, "signal kind")
        _validate_text(self.unit, "signal unit")
        _validate_instance(
            self.representation,
            SignalRepresentation,
            "signal representation",
        )
        _validate_optional_text(self.value_semantics, "signal value semantics")
        segments = _typed_tuple(self.segments, SignalSegmentRecord, "signal segments")
        _require_unique_ids(segments, "signal segment identifiers")
        if (
            self.representation is SignalRepresentation.UNIFORM_WAVEFORM
            and any(segment.sample_interval_ms is None for segment in segments)
        ):
            raise NormalizedModelError(
                "Uniform waveform segments require a sample interval."
            )
        if (
            self.representation is SignalRepresentation.TIMED_UPDATES
            and any(segment.sample_interval_ms is not None for segment in segments)
        ):
            raise NormalizedModelError(
                "Timed-update segments cannot declare a uniform sample interval."
            )
        _validate_instance(self.provenance, ProvenanceRecord, "signal provenance")
        object.__setattr__(
            self,
            "segments",
            tuple(
                sorted(
                    segments,
                    key=lambda value: (value.start_time_ms, value.record_id),
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One normalized therapy session and its source records."""

    RECORD_TYPE: ClassVar[str] = "session"

    record_id: str
    device_id: str
    start_time_ms: int
    end_time_ms: int
    settings: tuple[SettingRecord, ...]
    events: tuple[EventRecord, ...]
    signals: tuple[SignalRecord, ...]
    provenance: ProvenanceRecord
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.record_id, "session record identifier")
        _validate_text(self.device_id, "device identifier")
        _validate_integer(self.start_time_ms, "session start time")
        _validate_integer(self.end_time_ms, "session end time")
        if self.start_time_ms >= self.end_time_ms:
            raise NormalizedModelError("Session end time must be after its start time.")
        settings = _typed_tuple(self.settings, SettingRecord, "session settings")
        events = _typed_tuple(self.events, EventRecord, "session events")
        signals = _typed_tuple(self.signals, SignalRecord, "session signals")
        _require_unique_ids(settings, "setting record identifiers")
        _require_unique_ids(events, "event record identifiers")
        _require_unique_ids(signals, "signal record identifiers")
        _require_unique(
            tuple(setting.name for setting in settings),
            "setting names",
        )
        _require_unique(
            tuple(signal.signal_kind for signal in signals),
            "signal kinds",
        )
        _validate_instance(self.provenance, ProvenanceRecord, "session provenance")
        object.__setattr__(
            self,
            "settings",
            tuple(sorted(settings, key=lambda value: value.record_id)),
        )
        object.__setattr__(
            self,
            "events",
            tuple(
                sorted(
                    events,
                    key=lambda value: (value.start_time_ms, value.record_id),
                )
            ),
        )
        object.__setattr__(
            self,
            "signals",
            tuple(sorted(signals, key=lambda value: value.record_id)),
        )


@dataclass(frozen=True, slots=True)
class NightRecord:
    """One normalized local therapy day containing one or more sessions."""

    RECORD_TYPE: ClassVar[str] = "night"

    record_id: str
    local_date: str
    timezone: str
    day_boundary_local_time: str
    sessions: tuple[SessionRecord, ...]
    provenance: ProvenanceRecord
    record_version: int = NORMALIZED_RECORD_VERSION

    def __post_init__(self) -> None:
        _validate_record_version(self.record_version)
        _validate_text(self.record_id, "night record identifier")
        _validate_iso_date(self.local_date)
        _validate_text(self.timezone, "night timezone")
        _validate_iso_time(self.day_boundary_local_time)
        sessions = _typed_tuple(self.sessions, SessionRecord, "night sessions")
        if not sessions:
            raise NormalizedModelError("A normalized night requires at least one session.")
        _require_unique_ids(sessions, "session record identifiers")
        _validate_instance(self.provenance, ProvenanceRecord, "night provenance")
        object.__setattr__(
            self,
            "sessions",
            tuple(
                sorted(
                    sessions,
                    key=lambda value: (value.start_time_ms, value.record_id),
                )
            ),
        )


NormalizedRecord: TypeAlias = (
    SourceReference
    | ProvenanceValue
    | ProvenanceRecord
    | SettingRecord
    | EventRecord
    | SignalSegmentRecord
    | SignalRecord
    | SessionRecord
    | NightRecord
)

_SERIALIZABLE_TYPES: Final = (
    SourceReference,
    ProvenanceValue,
    ProvenanceRecord,
    SettingRecord,
    EventRecord,
    SignalSegmentRecord,
    SignalRecord,
    SessionRecord,
    NightRecord,
)


def serialize_normalized_record(record: NormalizedRecord) -> str:
    """Serialize one normalized record to canonical, versioned JSON."""

    if not isinstance(record, _SERIALIZABLE_TYPES):
        raise NormalizedModelError("Only normalized model records can be serialized.")
    payload = {
        "format": NORMALIZED_FORMAT,
        "format_version": NORMALIZED_FORMAT_VERSION,
        "record": _encode_record(record),
    }
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise NormalizedModelError("The normalized record cannot be serialized safely.") from error


def deserialize_normalized_record(serialized: str) -> NormalizedRecord:
    """Deserialize and validate one versioned normalized JSON record."""

    if type(serialized) is not str:
        raise NormalizedModelError("A normalized payload must be JSON text.")
    try:
        payload = json.loads(
            serialized,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, NormalizedModelError) as error:
        raise NormalizedModelError("The normalized payload is not valid strict JSON.") from error
    root = _exact_object(
        payload,
        {"format", "format_version", "record"},
        "normalized envelope",
    )
    if (
        root["format"] != NORMALIZED_FORMAT
        or type(root["format_version"]) is not int
        or root["format_version"] != NORMALIZED_FORMAT_VERSION
    ):
        raise NormalizedModelError(
            "The normalized format or format version is unsupported."
        )
    return _decode_record(root["record"])


def _encode_record(record: NormalizedRecord) -> dict[str, Any]:
    if not is_dataclass(record) or not isinstance(record, _SERIALIZABLE_TYPES):
        raise NormalizedModelError("A nested value is not a normalized record.")
    encoded: dict[str, Any] = {"record_type": record.RECORD_TYPE}
    for field in fields(record):
        encoded[field.name] = _encode_value(getattr(record, field.name))
    return encoded


def _encode_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, _SERIALIZABLE_TYPES):
        return _encode_record(value)
    if isinstance(value, tuple):
        return [_encode_value(item) for item in value]
    if value is None or type(value) in (bool, int, float, str):
        return value
    raise NormalizedModelError("A normalized record contains an unsupported value type.")


def _decode_record(payload: Any) -> NormalizedRecord:
    if type(payload) is not dict or type(payload.get("record_type")) is not str:
        raise NormalizedModelError("A normalized record must have a record type.")
    record_type = payload["record_type"]
    if record_type == SourceReference.RECORD_TYPE:
        data = _record_object(
            payload,
            {"source_record_type", "source_record_id", "record_version"},
        )
        return SourceReference(
            source_record_type=data["source_record_type"],
            source_record_id=data["source_record_id"],
            record_version=data["record_version"],
        )
    if record_type == ProvenanceValue.RECORD_TYPE:
        data = _record_object(payload, {"name", "value", "record_version"})
        return ProvenanceValue(
            name=data["name"],
            value=data["value"],
            record_version=data["record_version"],
        )
    if record_type == ProvenanceRecord.RECORD_TYPE:
        data = _record_object(
            payload,
            {
                "record_id",
                "source_classes",
                "source_system",
                "source_references",
                "source_system_version",
                "source_schema_version",
                "producer",
                "producer_version",
                "parent_provenance_ids",
                "source_values",
                "record_version",
            },
        )
        return ProvenanceRecord(
            record_id=data["record_id"],
            source_classes=tuple(
                _enum(SourceClass, item, "source class")
                for item in _list(data["source_classes"], "source classes")
            ),
            source_system=data["source_system"],
            source_references=tuple(
                _nested(item, SourceReference, "source reference")
                for item in _list(
                    data["source_references"],
                    "source references",
                )
            ),
            source_system_version=data["source_system_version"],
            source_schema_version=data["source_schema_version"],
            producer=data["producer"],
            producer_version=data["producer_version"],
            parent_provenance_ids=tuple(
                _list(
                    data["parent_provenance_ids"],
                    "parent provenance identifiers",
                )
            ),
            source_values=tuple(
                _nested(item, ProvenanceValue, "source value")
                for item in _list(data["source_values"], "source values")
            ),
            record_version=data["record_version"],
        )
    if record_type == SettingRecord.RECORD_TYPE:
        data = _record_object(
            payload,
            {
                "record_id",
                "name",
                "value",
                "unit",
                "provenance",
                "record_version",
            },
        )
        return SettingRecord(
            record_id=data["record_id"],
            name=data["name"],
            value=data["value"],
            unit=data["unit"],
            provenance=_nested(
                data["provenance"],
                ProvenanceRecord,
                "setting provenance",
            ),
            record_version=data["record_version"],
        )
    if record_type == EventRecord.RECORD_TYPE:
        data = _record_object(
            payload,
            {
                "record_id",
                "event_kind",
                "start_time_ms",
                "duration_ms",
                "provenance",
                "record_version",
            },
        )
        return EventRecord(
            record_id=data["record_id"],
            event_kind=data["event_kind"],
            start_time_ms=data["start_time_ms"],
            duration_ms=data["duration_ms"],
            provenance=_nested(
                data["provenance"],
                ProvenanceRecord,
                "event provenance",
            ),
            record_version=data["record_version"],
        )
    if record_type == SignalSegmentRecord.RECORD_TYPE:
        data = _record_object(
            payload,
            {
                "record_id",
                "start_time_ms",
                "end_time_ms",
                "interval_closure",
                "sample_times_ms",
                "values",
                "sample_interval_ms",
                "provenance",
                "record_version",
            },
        )
        return SignalSegmentRecord(
            record_id=data["record_id"],
            start_time_ms=data["start_time_ms"],
            end_time_ms=data["end_time_ms"],
            interval_closure=_enum(
                IntervalClosure,
                data["interval_closure"],
                "signal interval closure",
            ),
            sample_times_ms=tuple(
                _list(data["sample_times_ms"], "signal sample times")
            ),
            values=tuple(_list(data["values"], "signal values")),
            sample_interval_ms=data["sample_interval_ms"],
            provenance=_nested(
                data["provenance"],
                ProvenanceRecord,
                "signal segment provenance",
            ),
            record_version=data["record_version"],
        )
    if record_type == SignalRecord.RECORD_TYPE:
        data = _record_object(
            payload,
            {
                "record_id",
                "signal_kind",
                "unit",
                "representation",
                "segments",
                "provenance",
                "value_semantics",
                "record_version",
            },
        )
        return SignalRecord(
            record_id=data["record_id"],
            signal_kind=data["signal_kind"],
            unit=data["unit"],
            representation=_enum(
                SignalRepresentation,
                data["representation"],
                "signal representation",
            ),
            segments=tuple(
                _nested(item, SignalSegmentRecord, "signal segment")
                for item in _list(data["segments"], "signal segments")
            ),
            provenance=_nested(
                data["provenance"],
                ProvenanceRecord,
                "signal provenance",
            ),
            value_semantics=data["value_semantics"],
            record_version=data["record_version"],
        )
    if record_type == SessionRecord.RECORD_TYPE:
        data = _record_object(
            payload,
            {
                "record_id",
                "device_id",
                "start_time_ms",
                "end_time_ms",
                "settings",
                "events",
                "signals",
                "provenance",
                "record_version",
            },
        )
        return SessionRecord(
            record_id=data["record_id"],
            device_id=data["device_id"],
            start_time_ms=data["start_time_ms"],
            end_time_ms=data["end_time_ms"],
            settings=tuple(
                _nested(item, SettingRecord, "setting")
                for item in _list(data["settings"], "session settings")
            ),
            events=tuple(
                _nested(item, EventRecord, "event")
                for item in _list(data["events"], "session events")
            ),
            signals=tuple(
                _nested(item, SignalRecord, "signal")
                for item in _list(data["signals"], "session signals")
            ),
            provenance=_nested(
                data["provenance"],
                ProvenanceRecord,
                "session provenance",
            ),
            record_version=data["record_version"],
        )
    if record_type == NightRecord.RECORD_TYPE:
        data = _record_object(
            payload,
            {
                "record_id",
                "local_date",
                "timezone",
                "day_boundary_local_time",
                "sessions",
                "provenance",
                "record_version",
            },
        )
        return NightRecord(
            record_id=data["record_id"],
            local_date=data["local_date"],
            timezone=data["timezone"],
            day_boundary_local_time=data["day_boundary_local_time"],
            sessions=tuple(
                _nested(item, SessionRecord, "session")
                for item in _list(data["sessions"], "night sessions")
            ),
            provenance=_nested(
                data["provenance"],
                ProvenanceRecord,
                "night provenance",
            ),
            record_version=data["record_version"],
        )
    raise NormalizedModelError(f"Unsupported normalized record type {record_type!r}.")


def _record_object(payload: dict[str, Any], fields_required: set[str]) -> dict[str, Any]:
    return _exact_object(
        payload,
        fields_required | {"record_type"},
        f"{payload.get('record_type', 'unknown')} record",
    )


def _exact_object(value: Any, expected_keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != expected_keys:
        raise NormalizedModelError(f"The {label} has missing or unknown fields.")
    return value


def _nested(value: Any, expected_type: type[Any], label: str) -> Any:
    record = _decode_record(value)
    if not isinstance(record, expected_type):
        raise NormalizedModelError(f"The {label} has the wrong record type.")
    return record


def _list(value: Any, label: str) -> list[Any]:
    if type(value) is not list:
        raise NormalizedModelError(f"The {label} must be a JSON array.")
    return value


def _enum(enum_type: type[StrEnum], value: Any, label: str) -> Any:
    if type(value) is not str:
        raise NormalizedModelError(f"The {label} must be text.")
    try:
        return enum_type(value)
    except ValueError as error:
        raise NormalizedModelError(f"The {label} is unsupported.") from error


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise NormalizedModelError(f"Duplicate JSON field {key!r}.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise NormalizedModelError(f"Non-finite JSON number {value!r} is unsupported.")


def _validate_record_version(value: object) -> None:
    if type(value) is not int or value != NORMALIZED_RECORD_VERSION:
        raise NormalizedModelError("The normalized record version is unsupported.")


def _validate_text(value: object, label: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise NormalizedModelError(f"The {label} must be nonempty canonical text.")


def _validate_optional_text(value: object, label: str) -> None:
    if value is not None:
        _validate_text(value, label)


def _validate_integer(value: object, label: str) -> None:
    if type(value) is not int:
        raise NormalizedModelError(f"The {label} must be an integer.")


def _validate_number(value: object, label: str) -> None:
    if type(value) is int:
        return
    if type(value) is float and math.isfinite(value):
        return
    raise NormalizedModelError(f"The {label} must be a finite number.")


def _validate_scalar(value: object, label: str) -> None:
    if type(value) is str:
        _validate_text(value, label)
    elif type(value) in (int, float):
        _validate_number(value, label)
    elif type(value) is not bool:
        raise NormalizedModelError(f"The {label} has an unsupported scalar type.")


def _validate_instance(value: object, expected_type: type[Any], label: str) -> None:
    if not isinstance(value, expected_type):
        raise NormalizedModelError(f"The {label} has the wrong record type.")


def _typed_tuple(value: object, expected_type: type[Any], label: str) -> tuple[Any, ...]:
    if type(value) is not tuple or any(not isinstance(item, expected_type) for item in value):
        raise NormalizedModelError(f"The {label} must be an immutable tuple of {expected_type.__name__} records.")
    return value


def _text_tuple(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise NormalizedModelError(f"The {label} must be an immutable tuple.")
    for item in value:
        _validate_text(item, label)
    return value


def _integer_tuple(value: object, label: str) -> tuple[int, ...]:
    if type(value) is not tuple:
        raise NormalizedModelError(f"The {label} must be an immutable tuple.")
    for item in value:
        _validate_integer(item, label)
    return value


def _number_tuple(value: object, label: str) -> tuple[float, ...]:
    if type(value) is not tuple:
        raise NormalizedModelError(f"The {label} must be an immutable tuple.")
    normalized: list[float] = []
    for item in value:
        _validate_number(item, label)
        try:
            normalized_item = float(item)
        except OverflowError as error:
            raise NormalizedModelError(f"The {label} must fit finite floating-point values.") from error
        if not math.isfinite(normalized_item):
            raise NormalizedModelError(f"The {label} must fit finite floating-point values.")
        normalized.append(normalized_item)
    return tuple(normalized)


def _require_unique(values: tuple[Any, ...], label: str) -> None:
    if len(set(values)) != len(values):
        raise NormalizedModelError(f"The {label} must be unique.")


def _require_unique_ids(records: tuple[Any, ...], label: str) -> None:
    identifiers = tuple(record.record_id for record in records)
    _require_unique(identifiers, label)


def _validate_iso_date(value: object) -> None:
    _validate_text(value, "night local date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise NormalizedModelError("The night local date must be ISO 8601.") from error
    if parsed.isoformat() != value:
        raise NormalizedModelError("The night local date must use canonical ISO 8601 form.")


def _validate_iso_time(value: object) -> None:
    _validate_text(value, "night day-boundary time")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise NormalizedModelError("The night day-boundary time must be ISO 8601.") from error
    if parsed.tzinfo is not None or parsed.isoformat() != value:
        raise NormalizedModelError("The night day-boundary time must be a canonical local ISO 8601 time.")
