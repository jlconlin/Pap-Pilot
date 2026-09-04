"""Extract the raw FlowRate waveform for one OSCAR session."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import sqlite3
from typing import Final

from pap_pilot.adapter._uniform_waveform import (
    DecodedUniformWaveform,
    DecodedUniformWaveformSegment,
    OscarSignalSourceClass,
    OscarSignalStorage,
    UniformWaveformSpec,
    _extract_uniform_waveform,
    extract_uniform_waveform,
)
from pap_pilot.adapter.oscar import OscarDatabaseError
from pap_pilot.adapter.session_summary import OscarSessionSummary


FLOW_RATE_CHANNEL_CODE: Final = "FlowRate"
FLOW_RATE_CANONICAL_UNIT: Final = "L/min"
FLOW_RATE_SOURCE_DIMENSION: Final = "L/M"
FLOW_RATE_SAMPLE_INTERVAL_MS: Final = 40.0

_FLOW_RATE_SPEC: Final = UniformWaveformSpec(
    signal_name=FLOW_RATE_CHANNEL_CODE,
    channel_code=FLOW_RATE_CHANNEL_CODE,
    source_dimension=FLOW_RATE_SOURCE_DIMENSION,
    canonical_unit=FLOW_RATE_CANONICAL_UNIT,
    sample_interval_ms=FLOW_RATE_SAMPLE_INTERVAL_MS,
)


class OscarFlowAvailability(StrEnum):
    """Why a selected session does or does not have FlowRate samples."""

    AVAILABLE = "available"
    CHANNEL_MISSING = "channel_missing"
    DATA_MISSING = "data_missing"


class SessionFlowError(OscarDatabaseError):
    """Base class for FlowRate data that cannot be extracted safely."""


class InvalidFlowSignalError(SessionFlowError):
    """Raised when FlowRate rows violate the schema-17 signal contract."""


@dataclass(frozen=True, slots=True)
class OscarFlowSegment:
    """One independent, uniformly sampled OSCAR FlowRate EventList."""

    source_eventlist_id: int
    source_event_data_id: int
    session_database_id: int
    profile_database_id: int
    source_channel_id: int
    eventlist_index: int
    raw_first_time_ms: int
    raw_end_time_ms_exclusive: int
    sample_interval_ms: float
    sample_count: int
    raw_sample_times_ms: tuple[float, ...]
    values_l_min: tuple[float, ...]
    gain_l_min_per_raw_unit: float
    offset_l_min: float
    source_dimension: str
    canonical_unit: str
    gap_before_ms: int | None
    storage: OscarSignalStorage
    data_size_bytes: int
    compressed_size_bytes: int | None
    source_checksum: int
    source_class: OscarSignalSourceClass

    @property
    def raw_last_sample_time_ms(self) -> float:
        """Return the timestamp of the final stored sample."""

        return self.raw_sample_times_ms[-1]


@dataclass(frozen=True, slots=True)
class OscarFlowSignal:
    """The raw FlowRate availability and segments for one session."""

    session_summary: OscarSessionSummary
    availability: OscarFlowAvailability
    source_channel_id: int | None
    channel_code: str
    canonical_unit: str
    segments: tuple[OscarFlowSegment, ...]
    source_class: OscarSignalSourceClass

    @property
    def total_sample_count(self) -> int:
        """Return the number of stored samples across independent segments."""

        return sum(segment.sample_count for segment in self.segments)


def extract_flow_rate_signal(
    database_path: str | Path,
    session_database_id: int,
    *,
    trusted_immutable_copy: bool = False,
) -> OscarFlowSignal:
    """Extract only FlowRate EventLists for exactly one validated session."""

    waveform = extract_uniform_waveform(
        database_path,
        session_database_id,
        spec=_FLOW_RATE_SPEC,
        error_type=InvalidFlowSignalError,
        trusted_immutable_copy=trusted_immutable_copy,
    )
    return _flow_signal(waveform)


def _extract_flow_rate_signal(
    connection: sqlite3.Connection,
    session_summary: OscarSessionSummary,
) -> OscarFlowSignal:
    """Extract Flow Rate inside an existing guarded read transaction."""

    return _flow_signal(
        _extract_uniform_waveform(
            connection,
            session_summary,
            spec=_FLOW_RATE_SPEC,
            error_type=InvalidFlowSignalError,
        )
    )


def _flow_signal(waveform: DecodedUniformWaveform) -> OscarFlowSignal:
    return OscarFlowSignal(
        session_summary=waveform.session_summary,
        availability=OscarFlowAvailability(waveform.availability.value),
        source_channel_id=waveform.source_channel_id,
        channel_code=waveform.channel_code,
        canonical_unit=waveform.canonical_unit,
        segments=tuple(_flow_segment(segment) for segment in waveform.segments),
        source_class=waveform.source_class,
    )


def _flow_segment(
    segment: DecodedUniformWaveformSegment,
) -> OscarFlowSegment:
    return OscarFlowSegment(
        source_eventlist_id=segment.source_eventlist_id,
        source_event_data_id=segment.source_event_data_id,
        session_database_id=segment.session_database_id,
        profile_database_id=segment.profile_database_id,
        source_channel_id=segment.source_channel_id,
        eventlist_index=segment.eventlist_index,
        raw_first_time_ms=segment.raw_first_time_ms,
        raw_end_time_ms_exclusive=segment.raw_end_time_ms_exclusive,
        sample_interval_ms=segment.sample_interval_ms,
        sample_count=segment.sample_count,
        raw_sample_times_ms=segment.raw_sample_times_ms,
        values_l_min=segment.values,
        gain_l_min_per_raw_unit=segment.gain_per_raw_unit,
        offset_l_min=segment.offset,
        source_dimension=segment.source_dimension,
        canonical_unit=segment.canonical_unit,
        gap_before_ms=segment.gap_before_ms,
        storage=segment.storage,
        data_size_bytes=segment.data_size_bytes,
        compressed_size_bytes=segment.compressed_size_bytes,
        source_checksum=segment.source_checksum,
        source_class=segment.source_class,
    )
