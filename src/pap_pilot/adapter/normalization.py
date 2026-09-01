"""Map validated OSCAR adapter records into the normalized engine model."""

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
import json
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pap_pilot.adapter._uniform_waveform import OscarSignalSourceClass
from pap_pilot.adapter.session_events import (
    EVENT_CHANNELS,
    OscarEventCompleteness,
    OscarEventSourceClass,
    OscarSessionEvent,
    OscarSessionEvents,
)
from pap_pilot.adapter.session_flow import (
    FLOW_RATE_CANONICAL_UNIT,
    FLOW_RATE_CHANNEL_CODE,
    OscarFlowAvailability,
    OscarFlowSegment,
    OscarFlowSignal,
)
from pap_pilot.adapter.session_leak import (
    LEAK_CANONICAL_UNIT,
    LEAK_CHANNEL_CODE,
    OscarLeakAvailability,
    OscarLeakSegment,
    OscarLeakSignal,
)
from pap_pilot.adapter.session_mask_pressure import (
    MASK_PRESSURE_CANONICAL_UNIT,
    MASK_PRESSURE_CHANNEL_CODE,
    OscarMaskPressureAvailability,
    OscarMaskPressureSegment,
    OscarMaskPressureSignal,
)
from pap_pilot.adapter.session_summary import (
    REQUIRED_SETTING_CODES,
    OscarSessionSummary,
)
from pap_pilot.engine.model import (
    EventRecord,
    IntervalClosure,
    NightRecord,
    ProvenanceRecord,
    ProvenanceValue,
    SessionRecord,
    SettingRecord,
    SignalRecord,
    SignalRepresentation,
    SignalSegmentRecord,
    SourceClass,
    SourceReference,
)


_SOURCE_SYSTEM: Final = "OSCAR"
_SOURCE_CLASSES: Final = (
    SourceClass.MACHINE_RECORDED,
    SourceClass.OSCAR_NORMALIZED,
)
_EVENT_SOURCE_CLASSES: Final = (
    SourceClass.MACHINE_LABELED,
    SourceClass.OSCAR_NORMALIZED,
)

_SETTING_FIELDS: Final[Mapping[str, tuple[str, str, str | None]]] = {
    "PAPMode": ("therapy_mode_code", "therapy_mode_code", None),
    "RMS9_Mode": ("loader_mode_code", "loader_mode_code", None),
    "EPAP": ("epap", "epap_cm_h2o", "cm H₂O"),
    "PSMin": ("ps_min", "ps_min_cm_h2o", "cm H₂O"),
    "PSMax": ("ps_max", "ps_max_cm_h2o", "cm H₂O"),
    "IPAPHi": ("max_ipap", "max_ipap_cm_h2o", "cm H₂O"),
}


class OscarNormalizationError(ValueError):
    """Raised when independently extracted OSCAR records cannot be mapped safely."""


def normalize_oscar_session(
    session_summary: OscarSessionSummary,
    session_events: OscarSessionEvents,
    flow_rate: OscarFlowSignal,
    mask_pressure: OscarMaskPressureSignal,
    leak: OscarLeakSignal,
) -> NightRecord:
    """Create one deterministic normalized night from existing adapter output."""

    _validate_inputs(
        session_summary,
        session_events,
        flow_rate,
        mask_pressure,
        leak,
    )
    local_date, day_boundary_local_time = _session_calendar(session_summary)
    ids = _normalized_ids(session_summary, local_date)
    base_references = _summary_references(session_summary)

    session_provenance = _provenance(
        ids["session"],
        source_classes=_SOURCE_CLASSES,
        source_references=base_references,
        source_values=(
            *_summary_source_values(session_summary),
            *_event_collection_source_values(session_events),
        ),
        schema_version=session_summary.schema.version,
    )
    settings = _settings(
        session_summary,
        session_record_id=ids["session"],
        parent_provenance_id=session_provenance.record_id,
        base_references=base_references,
    )
    events = tuple(
        _event(
            source_event,
            session_summary=session_summary,
            session_record_id=ids["session"],
            parent_provenance_id=session_provenance.record_id,
            base_references=base_references,
            completeness=session_events.completeness,
        )
        for source_event in session_events.events
    )
    signals = (
        _uniform_signal(
            flow_rate,
            signal_kind="flow_rate",
            session_summary=session_summary,
            session_record_id=ids["session"],
            parent_provenance_id=session_provenance.record_id,
            base_references=base_references,
        ),
        _uniform_signal(
            mask_pressure,
            signal_kind="mask_pressure",
            session_summary=session_summary,
            session_record_id=ids["session"],
            parent_provenance_id=session_provenance.record_id,
            base_references=base_references,
        ),
        _leak_signal(
            leak,
            session_summary=session_summary,
            session_record_id=ids["session"],
            parent_provenance_id=session_provenance.record_id,
            base_references=base_references,
        ),
    )
    session = SessionRecord(
        record_id=ids["session"],
        device_id=ids["device"],
        start_time_ms=session_summary.session.raw_start_ms,
        end_time_ms=session_summary.session.raw_end_ms,
        settings=settings,
        events=events,
        signals=signals,
        provenance=session_provenance,
    )
    night_provenance = _provenance(
        ids["night"],
        source_classes=(SourceClass.COMPANION_DERIVED, SourceClass.OSCAR_NORMALIZED),
        source_references=base_references,
        source_values=_values(
            {
                "night.day_boundary_local_time": day_boundary_local_time,
                "night.local_date": local_date,
                "night.local_date_derivation": "raw session start converted to the profile timezone, then assigned before the configured day boundary to the prior local date",
                "night.source_raw_start_ms": session_summary.session.raw_start_ms,
                "night.timezone": session_summary.profile.timezone,
            }
        ),
        schema_version=session_summary.schema.version,
        parent_provenance_ids=(session_provenance.record_id,),
    )
    return NightRecord(
        record_id=ids["night"],
        local_date=local_date,
        timezone=session_summary.profile.timezone,
        day_boundary_local_time=day_boundary_local_time,
        sessions=(session,),
        provenance=night_provenance,
    )


def _validate_inputs(
    summary: OscarSessionSummary,
    events: OscarSessionEvents,
    flow: OscarFlowSignal,
    mask_pressure: OscarMaskPressureSignal,
    leak: OscarLeakSignal,
) -> None:
    for label, embedded_summary in (
        ("events", events.session_summary),
        ("FlowRate", flow.session_summary),
        ("MaskPressureHi", mask_pressure.session_summary),
        ("Leak", leak.session_summary),
    ):
        if embedded_summary != summary:
            raise OscarNormalizationError(
                f"The {label} extraction does not match the selected session summary."
            )

    expected_counts = Counter(event.event_kind for event in events.events)
    observed_kinds = tuple(count.event_kind for count in events.observed_row_counts)
    expected_kinds = {event_kind for event_kind, _ in EVENT_CHANNELS.values()}
    if len(set(observed_kinds)) != len(observed_kinds) or set(observed_kinds) != expected_kinds:
        raise OscarNormalizationError("The observed event counts do not cover the allowlisted kinds exactly once.")
    for count in events.observed_row_counts:
        if count.completeness is not events.completeness or count.observed_rows != expected_counts[count.event_kind]:
            raise OscarNormalizationError("The observed event counts do not match the event rows.")
    if events.completeness is not OscarEventCompleteness.UNKNOWN:
        raise OscarNormalizationError("The mapper supports only the current unknown event-completeness contract.")

    source_codes = tuple(source.channel_code for source in summary.settings.sources)
    if len(set(source_codes)) != len(source_codes) or set(source_codes) != set(REQUIRED_SETTING_CODES):
        raise OscarNormalizationError("The session settings do not have the required source channels.")

    _validate_signal(
        flow,
        label="FlowRate",
        expected_channel=FLOW_RATE_CHANNEL_CODE,
        expected_unit=FLOW_RATE_CANONICAL_UNIT,
        available=OscarFlowAvailability.AVAILABLE,
        channel_missing=OscarFlowAvailability.CHANNEL_MISSING,
        data_missing=OscarFlowAvailability.DATA_MISSING,
    )
    _validate_signal(
        mask_pressure,
        label="MaskPressureHi",
        expected_channel=MASK_PRESSURE_CHANNEL_CODE,
        expected_unit=MASK_PRESSURE_CANONICAL_UNIT,
        available=OscarMaskPressureAvailability.AVAILABLE,
        channel_missing=OscarMaskPressureAvailability.CHANNEL_MISSING,
        data_missing=OscarMaskPressureAvailability.DATA_MISSING,
    )
    _validate_signal(
        leak,
        label="Leak",
        expected_channel=LEAK_CHANNEL_CODE,
        expected_unit=LEAK_CANONICAL_UNIT,
        available=OscarLeakAvailability.AVAILABLE,
        channel_missing=OscarLeakAvailability.CHANNEL_MISSING,
        data_missing=OscarLeakAvailability.DATA_MISSING,
    )


def _validate_signal(
    signal: OscarFlowSignal | OscarMaskPressureSignal | OscarLeakSignal,
    *,
    label: str,
    expected_channel: str,
    expected_unit: str,
    available: StrEnum,
    channel_missing: StrEnum,
    data_missing: StrEnum,
) -> None:
    if signal.channel_code != expected_channel or signal.canonical_unit != expected_unit:
        raise OscarNormalizationError(f"The {label} identity or unit is inconsistent.")
    if signal.source_class is not OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED:
        raise OscarNormalizationError(f"The {label} source classification is unsupported.")
    if signal.availability is available:
        if signal.source_channel_id is None or not signal.segments:
            raise OscarNormalizationError(f"Available {label} data requires a channel and segments.")
    elif signal.availability is channel_missing:
        if signal.source_channel_id is not None or signal.segments:
            raise OscarNormalizationError(f"Channel-missing {label} data cannot contain source data.")
    elif signal.availability is data_missing:
        if signal.source_channel_id is None or signal.segments:
            raise OscarNormalizationError(f"Data-missing {label} requires only its source channel.")
    else:
        raise OscarNormalizationError(f"The {label} availability is unsupported.")

    for segment in signal.segments:
        if (
            segment.session_database_id != signal.session_summary.session.database_id
            or segment.profile_database_id != signal.session_summary.profile.database_id
            or segment.source_channel_id != signal.source_channel_id
            or segment.source_class is not signal.source_class
            or segment.canonical_unit != signal.canonical_unit
            or segment.sample_count != len(segment.raw_sample_times_ms)
        ):
            raise OscarNormalizationError(f"A {label} segment has conflicting source provenance.")


def _session_calendar(summary: OscarSessionSummary) -> tuple[str, str]:
    try:
        profile_timezone = ZoneInfo(summary.profile.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise OscarNormalizationError("The profile timezone is not a usable IANA timezone.") from error
    try:
        day_boundary = time.fromisoformat(summary.profile.day_split_time)
    except ValueError as error:
        raise OscarNormalizationError("The profile day boundary is not an ISO local time.") from error
    if day_boundary.tzinfo is not None:
        raise OscarNormalizationError("The profile day boundary cannot include a timezone offset.")

    try:
        utc_start = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
            milliseconds=summary.session.raw_start_ms
        )
    except OverflowError as error:
        raise OscarNormalizationError("The raw session start is outside the supported datetime range.") from error
    local_start = utc_start.astimezone(profile_timezone)
    local_date = local_start.date()
    if local_start.time().replace(tzinfo=None) < day_boundary:
        local_date -= timedelta(days=1)
    return local_date.isoformat(), day_boundary.isoformat()


def _normalized_ids(summary: OscarSessionSummary, local_date: str) -> dict[str, str]:
    identity = (
        f"oscar:v{summary.schema.version}:profile-db:{summary.profile.database_id}"
        f":machine-db:{summary.machine.database_id}:machine-source:{summary.machine.source_id}"
    )
    return {
        "device": f"device:{identity}",
        "night": f"night:oscar:v{summary.schema.version}:profile-db:{summary.profile.database_id}:{local_date}",
        "session": f"session:{identity}:session-db:{summary.session.database_id}:session-source:{summary.session.source_id}",
    }


def _settings(
    summary: OscarSessionSummary,
    *,
    session_record_id: str,
    parent_provenance_id: str,
    base_references: tuple[SourceReference, ...],
) -> tuple[SettingRecord, ...]:
    source_by_code = {source.channel_code: source for source in summary.settings.sources}
    records = []
    for channel_code in REQUIRED_SETTING_CODES:
        normalized_name, attribute_name, unit = _SETTING_FIELDS[channel_code]
        value = getattr(summary.settings, attribute_name)
        source = source_by_code[channel_code]
        record_id = f"setting:{session_record_id}:{channel_code}"
        provenance = _provenance(
            record_id,
            source_classes=_SOURCE_CLASSES,
            source_references=(
                *base_references,
                SourceReference("channels.channel_id", str(source.source_channel_id)),
            ),
            source_values=_values(
                {
                    "setting.canonical_unit": unit,
                    "setting.channel_code": channel_code,
                    "setting.normalized_name": normalized_name,
                    "setting.source_value": value,
                }
            ),
            schema_version=summary.schema.version,
            parent_provenance_ids=(parent_provenance_id,),
        )
        records.append(
            SettingRecord(
                record_id=record_id,
                name=normalized_name,
                value=value,
                unit=unit,
                provenance=provenance,
            )
        )
    return tuple(records)


def _event(
    event: OscarSessionEvent,
    *,
    session_summary: OscarSessionSummary,
    session_record_id: str,
    parent_provenance_id: str,
    base_references: tuple[SourceReference, ...],
    completeness: OscarEventCompleteness,
) -> EventRecord:
    if event.source_class is not OscarEventSourceClass.MACHINE_LABELED_OSCAR_NORMALIZED:
        raise OscarNormalizationError("An event has an unsupported source classification.")
    expected_event = EVENT_CHANNELS.get(event.channel_code)
    contained_within_session = (
        event.raw_start_ms >= session_summary.session.raw_start_ms
        and event.raw_end_ms <= session_summary.session.raw_end_ms
    )
    if (
        expected_event != (event.event_kind, event.oscar_label)
        or event.session_database_id != session_summary.session.database_id
        or event.profile_database_id != session_summary.profile.database_id
        or event.duration_s < 0
        or event.raw_end_ms - event.raw_start_ms != event.duration_s * 1000
        or event.contained_within_session is not contained_within_session
    ):
        raise OscarNormalizationError("An event has conflicting source identity, timing, or provenance.")
    record_id = f"event:{session_record_id}:source-event:{event.source_event_id}"
    provenance = _provenance(
        record_id,
        source_classes=_EVENT_SOURCE_CLASSES,
        source_references=(
            *base_references,
            SourceReference("channels.channel_id", str(event.source_channel_id)),
            SourceReference("respiratory_events.id", str(event.source_event_id)),
        ),
        source_values=_values(
            {
                "event.channel_code": event.channel_code,
                "event.completeness": completeness,
                "event.contained_within_session": event.contained_within_session,
                "event.duration_s": event.duration_s,
                "event.event_kind": event.event_kind,
                "event.oscar_label": event.oscar_label,
                "event.profile_database_id": event.profile_database_id,
                "event.raw_end_ms": event.raw_end_ms,
                "event.raw_start_ms": event.raw_start_ms,
                "event.session_database_id": event.session_database_id,
                "event.source_class": event.source_class,
                "event.source_event_type": event.source_event_type,
            }
        ),
        schema_version=session_summary.schema.version,
        parent_provenance_ids=(parent_provenance_id,),
    )
    return EventRecord(
        record_id=record_id,
        event_kind=event.event_kind.value,
        start_time_ms=event.raw_start_ms,
        duration_ms=event.duration_s * 1000,
        provenance=provenance,
    )


def _uniform_signal(
    signal: OscarFlowSignal | OscarMaskPressureSignal,
    *,
    signal_kind: str,
    session_summary: OscarSessionSummary,
    session_record_id: str,
    parent_provenance_id: str,
    base_references: tuple[SourceReference, ...],
) -> SignalRecord:
    record_id = f"signal:{session_record_id}:{signal.channel_code}"
    signal_references = _channel_references(base_references, signal.source_channel_id)
    provenance = _provenance(
        record_id,
        source_classes=_SOURCE_CLASSES,
        source_references=signal_references,
        source_values=_values(
            {
                "signal.availability": signal.availability,
                "signal.canonical_unit": signal.canonical_unit,
                "signal.channel_code": signal.channel_code,
                "signal.source_channel_id": signal.source_channel_id,
                "signal.source_class": signal.source_class,
            }
        ),
        schema_version=session_summary.schema.version,
        parent_provenance_ids=(parent_provenance_id,),
    )
    segments = tuple(
        _uniform_segment(
            segment,
            signal_record_id=record_id,
            signal_provenance_id=provenance.record_id,
            schema_version=session_summary.schema.version,
            base_references=base_references,
        )
        for segment in signal.segments
    )
    return SignalRecord(
        record_id=record_id,
        signal_kind=signal_kind,
        unit=signal.canonical_unit,
        representation=SignalRepresentation.UNIFORM_WAVEFORM,
        segments=segments,
        provenance=provenance,
    )


def _uniform_segment(
    segment: OscarFlowSegment | OscarMaskPressureSegment,
    *,
    signal_record_id: str,
    signal_provenance_id: str,
    schema_version: int,
    base_references: tuple[SourceReference, ...],
) -> SignalSegmentRecord:
    record_id = f"segment:{signal_record_id}:eventlist-index:{segment.eventlist_index}:source-eventlist:{segment.source_eventlist_id}"
    values = segment.values_l_min if isinstance(segment, OscarFlowSegment) else segment.values_cm_h2o
    gain = segment.gain_l_min_per_raw_unit if isinstance(segment, OscarFlowSegment) else segment.gain_cm_h2o_per_raw_unit
    offset = segment.offset_l_min if isinstance(segment, OscarFlowSegment) else segment.offset_cm_h2o
    provenance = _provenance(
        record_id,
        source_classes=_SOURCE_CLASSES,
        source_references=(
            *base_references,
            SourceReference("channels.channel_id", str(segment.source_channel_id)),
            SourceReference("event_lists.id", str(segment.source_eventlist_id)),
            SourceReference("event_data.id", str(segment.source_event_data_id)),
        ),
        source_values=_values(
            {
                "segment.canonical_unit": segment.canonical_unit,
                "segment.compressed_size_bytes": segment.compressed_size_bytes,
                "segment.data_size_bytes": segment.data_size_bytes,
                "segment.eventlist_index": segment.eventlist_index,
                "segment.gain_per_raw_unit": gain,
                "segment.gap_before_ms": segment.gap_before_ms,
                "segment.offset": offset,
                "segment.profile_database_id": segment.profile_database_id,
                "segment.raw_end_time_ms_exclusive": segment.raw_end_time_ms_exclusive,
                "segment.raw_first_time_ms": segment.raw_first_time_ms,
                "segment.sample_count": segment.sample_count,
                "segment.sample_interval_ms": segment.sample_interval_ms,
                "segment.session_database_id": segment.session_database_id,
                "segment.source_checksum": segment.source_checksum,
                "segment.source_class": segment.source_class,
                "segment.source_dimension": segment.source_dimension,
                "segment.storage": segment.storage,
            }
        ),
        schema_version=schema_version,
        parent_provenance_ids=(signal_provenance_id,),
    )
    return SignalSegmentRecord(
        record_id=record_id,
        start_time_ms=segment.raw_first_time_ms,
        end_time_ms=segment.raw_end_time_ms_exclusive,
        interval_closure=IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
        sample_times_ms=segment.raw_sample_times_ms,
        values=values,
        sample_interval_ms=segment.sample_interval_ms,
        provenance=provenance,
    )


def _leak_signal(
    signal: OscarLeakSignal,
    *,
    session_summary: OscarSessionSummary,
    session_record_id: str,
    parent_provenance_id: str,
    base_references: tuple[SourceReference, ...],
) -> SignalRecord:
    record_id = f"signal:{session_record_id}:{signal.channel_code}"
    signal_references = _channel_references(base_references, signal.source_channel_id)
    provenance = _provenance(
        record_id,
        source_classes=_SOURCE_CLASSES,
        source_references=signal_references,
        source_values=_values(
            {
                "signal.availability": signal.availability,
                "signal.canonical_unit": signal.canonical_unit,
                "signal.channel_code": signal.channel_code,
                "signal.semantics": signal.semantics,
                "signal.source_channel_id": signal.source_channel_id,
                "signal.source_class": signal.source_class,
            }
        ),
        schema_version=session_summary.schema.version,
        parent_provenance_ids=(parent_provenance_id,),
    )
    segments = tuple(
        _leak_segment(
            segment,
            signal_record_id=record_id,
            signal_provenance_id=provenance.record_id,
            schema_version=session_summary.schema.version,
            base_references=base_references,
        )
        for segment in signal.segments
    )
    return SignalRecord(
        record_id=record_id,
        signal_kind="leak_rate",
        unit=signal.canonical_unit,
        representation=SignalRepresentation.TIMED_UPDATES,
        segments=segments,
        provenance=provenance,
        value_semantics=signal.semantics.value,
    )


def _leak_segment(
    segment: OscarLeakSegment,
    *,
    signal_record_id: str,
    signal_provenance_id: str,
    schema_version: int,
    base_references: tuple[SourceReference, ...],
) -> SignalSegmentRecord:
    record_id = f"segment:{signal_record_id}:eventlist-index:{segment.eventlist_index}:source-eventlist:{segment.source_eventlist_id}"
    provenance = _provenance(
        record_id,
        source_classes=_SOURCE_CLASSES,
        source_references=(
            *base_references,
            SourceReference("channels.channel_id", str(segment.source_channel_id)),
            SourceReference("event_lists.id", str(segment.source_eventlist_id)),
            SourceReference("event_data.id", str(segment.source_event_data_id)),
        ),
        source_values=_values(
            {
                "segment.canonical_unit": segment.canonical_unit,
                "segment.eventlist_index": segment.eventlist_index,
                "segment.gain_per_raw_unit": segment.gain_l_min_per_raw_unit,
                "segment.gap_before_ms": segment.gap_before_ms,
                "segment.offset": segment.offset_l_min,
                "segment.profile_database_id": segment.profile_database_id,
                "segment.raw_first_time_ms": segment.raw_first_time_ms,
                "segment.raw_last_time_ms": segment.raw_last_time_ms,
                "segment.raw_time_deltas_ms": segment.raw_time_deltas_ms,
                "segment.sample_count": segment.sample_count,
                "segment.session_database_id": segment.session_database_id,
                "segment.source_checksum": segment.source_checksum,
                "segment.source_class": segment.source_class,
                "segment.source_compressed_size_bytes": segment.source_compressed_size_bytes,
                "segment.source_data_size_bytes": segment.source_data_size_bytes,
                "segment.source_dimension": segment.source_dimension,
                "segment.storage": segment.storage,
                "segment.time_data_size_bytes": segment.time_data_size_bytes,
                "segment.time_stored_size_bytes": segment.time_stored_size_bytes,
                "segment.value_data_size_bytes": segment.value_data_size_bytes,
                "segment.value_stored_size_bytes": segment.value_stored_size_bytes,
            }
        ),
        schema_version=schema_version,
        parent_provenance_ids=(signal_provenance_id,),
    )
    return SignalSegmentRecord(
        record_id=record_id,
        start_time_ms=segment.raw_first_time_ms,
        end_time_ms=segment.raw_last_time_ms,
        interval_closure=IntervalClosure.START_AND_END_INCLUSIVE,
        sample_times_ms=segment.raw_sample_times_ms,
        values=segment.values_l_min,
        sample_interval_ms=None,
        provenance=provenance,
    )


def _summary_references(summary: OscarSessionSummary) -> tuple[SourceReference, ...]:
    return (
        SourceReference("schema_version.version", str(summary.schema.version)),
        SourceReference("profiles.id", str(summary.profile.database_id)),
        SourceReference("machines.id", str(summary.machine.database_id)),
        SourceReference("machines.machine_id", str(summary.machine.source_id)),
        SourceReference("sessions.id", str(summary.session.database_id)),
        SourceReference("sessions.session_id", str(summary.session.source_id)),
    )


def _summary_source_values(summary: OscarSessionSummary) -> tuple[ProvenanceValue, ...]:
    return _values(
        {
            "machine.brand": summary.machine.brand,
            "machine.database_id": summary.machine.database_id,
            "machine.last_imported_at": summary.machine.last_imported_at,
            "machine.loader_data_version": summary.machine.loader_data_version,
            "machine.loader_name": summary.machine.loader_name,
            "machine.machine_type_code": summary.machine.machine_type_code,
            "machine.model": summary.machine.model,
            "machine.model_number": summary.machine.model_number,
            "machine.purge_cutoff_date": summary.machine.purge_cutoff_date,
            "machine.serial_number": summary.machine.serial_number,
            "machine.series": summary.machine.series,
            "machine.source_id": summary.machine.source_id,
            "profile.database_id": summary.profile.database_id,
            "profile.day_split_time": summary.profile.day_split_time,
            "profile.lock_summary_sessions_raw": summary.profile.lock_summary_sessions_raw,
            "profile.name": summary.profile.name,
            "profile.status": summary.profile.status,
            "profile.timezone": summary.profile.timezone,
            "schema.applied_at": summary.schema.applied_at,
            "schema.version": summary.schema.version,
            "session.database_id": summary.session.database_id,
            "session.enabled": summary.session.enabled,
            "session.events_loaded": summary.session.events_loaded,
            "session.machine_database_id": summary.session.machine_database_id,
            "session.no_settings": summary.session.no_settings,
            "session.raw_duration_ms": summary.session.raw_duration_ms,
            "session.raw_end_ms": summary.session.raw_end_ms,
            "session.raw_start_ms": summary.session.raw_start_ms,
            "session.source_id": summary.session.source_id,
            "session.summary_only": summary.session.summary_only,
        }
    )


def _event_collection_source_values(events: OscarSessionEvents) -> tuple[ProvenanceValue, ...]:
    counts = tuple(
        {
            "completeness": count.completeness.value,
            "event_kind": count.event_kind.value,
            "observed_rows": count.observed_rows,
            "oscar_label": count.oscar_label,
        }
        for count in events.observed_row_counts
    )
    return _values(
        {
            "events.completeness": events.completeness,
            "events.observed_row_counts": counts,
        }
    )


def _channel_references(
    base_references: tuple[SourceReference, ...],
    source_channel_id: int | None,
) -> tuple[SourceReference, ...]:
    if source_channel_id is None:
        return base_references
    return (
        *base_references,
        SourceReference("channels.channel_id", str(source_channel_id)),
    )


def _provenance(
    record_id: str,
    *,
    source_classes: tuple[SourceClass, ...],
    source_references: tuple[SourceReference, ...],
    source_values: tuple[ProvenanceValue, ...],
    schema_version: int,
    parent_provenance_ids: tuple[str, ...] = (),
) -> ProvenanceRecord:
    return ProvenanceRecord(
        record_id=f"provenance:{record_id}",
        source_classes=source_classes,
        source_system=_SOURCE_SYSTEM,
        source_references=source_references,
        source_schema_version=str(schema_version),
        parent_provenance_ids=parent_provenance_ids,
        source_values=source_values,
    )


def _values(values: Mapping[str, object]) -> tuple[ProvenanceValue, ...]:
    return tuple(
        ProvenanceValue(name, _canonical_source_value(value))
        for name, value in values.items()
    )


def _canonical_source_value(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    return value
