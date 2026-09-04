"""Extract the raw MaskPressureHi waveform for one OSCAR session."""

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


MASK_PRESSURE_CHANNEL_CODE: Final = "MaskPressureHi"
MASK_PRESSURE_CANONICAL_UNIT: Final = "cm H₂O"
MASK_PRESSURE_SOURCE_DIMENSION: Final = "cmH2O"
MASK_PRESSURE_SAMPLE_INTERVAL_MS: Final = 40.0

_MASK_PRESSURE_SPEC: Final = UniformWaveformSpec(
    signal_name=MASK_PRESSURE_CHANNEL_CODE,
    channel_code=MASK_PRESSURE_CHANNEL_CODE,
    source_dimension=MASK_PRESSURE_SOURCE_DIMENSION,
    canonical_unit=MASK_PRESSURE_CANONICAL_UNIT,
    sample_interval_ms=MASK_PRESSURE_SAMPLE_INTERVAL_MS,
)


class OscarMaskPressureAvailability(StrEnum):
    """Why a selected session does or does not have MaskPressureHi samples."""

    AVAILABLE = "available"
    CHANNEL_MISSING = "channel_missing"
    DATA_MISSING = "data_missing"


class SessionMaskPressureError(OscarDatabaseError):
    """Base class for MaskPressureHi data that cannot be extracted safely."""


class InvalidMaskPressureSignalError(SessionMaskPressureError):
    """Raised when MaskPressureHi violates the schema-17 signal contract."""


@dataclass(frozen=True, slots=True)
class OscarMaskPressureSegment:
    """One independent, uniformly sampled MaskPressureHi EventList."""

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
    values_cm_h2o: tuple[float, ...]
    gain_cm_h2o_per_raw_unit: float
    offset_cm_h2o: float
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
class OscarMaskPressureSignal:
    """The raw MaskPressureHi availability and segments for one session."""

    session_summary: OscarSessionSummary
    availability: OscarMaskPressureAvailability
    source_channel_id: int | None
    channel_code: str
    canonical_unit: str
    segments: tuple[OscarMaskPressureSegment, ...]
    source_class: OscarSignalSourceClass

    @property
    def total_sample_count(self) -> int:
        """Return the number of stored samples across independent segments."""

        return sum(segment.sample_count for segment in self.segments)


def extract_mask_pressure_signal(
    database_path: str | Path,
    session_database_id: int,
    *,
    trusted_immutable_copy: bool = False,
) -> OscarMaskPressureSignal:
    """Extract only MaskPressureHi EventLists for one validated session."""

    waveform = extract_uniform_waveform(
        database_path,
        session_database_id,
        spec=_MASK_PRESSURE_SPEC,
        error_type=InvalidMaskPressureSignalError,
        trusted_immutable_copy=trusted_immutable_copy,
    )
    return _mask_pressure_signal(waveform)


def _extract_mask_pressure_signal(
    connection: sqlite3.Connection,
    session_summary: OscarSessionSummary,
) -> OscarMaskPressureSignal:
    """Extract Mask Pressure inside an existing guarded read transaction."""

    return _mask_pressure_signal(
        _extract_uniform_waveform(
            connection,
            session_summary,
            spec=_MASK_PRESSURE_SPEC,
            error_type=InvalidMaskPressureSignalError,
        )
    )


def _mask_pressure_signal(waveform: DecodedUniformWaveform) -> OscarMaskPressureSignal:
    return OscarMaskPressureSignal(
        session_summary=waveform.session_summary,
        availability=OscarMaskPressureAvailability(waveform.availability.value),
        source_channel_id=waveform.source_channel_id,
        channel_code=waveform.channel_code,
        canonical_unit=waveform.canonical_unit,
        segments=tuple(
            _mask_pressure_segment(segment) for segment in waveform.segments
        ),
        source_class=waveform.source_class,
    )


def _mask_pressure_segment(
    segment: DecodedUniformWaveformSegment,
) -> OscarMaskPressureSegment:
    return OscarMaskPressureSegment(
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
        values_cm_h2o=segment.values,
        gain_cm_h2o_per_raw_unit=segment.gain_per_raw_unit,
        offset_cm_h2o=segment.offset,
        source_dimension=segment.source_dimension,
        canonical_unit=segment.canonical_unit,
        gap_before_ms=segment.gap_before_ms,
        storage=segment.storage,
        data_size_bytes=segment.data_size_bytes,
        compressed_size_bytes=segment.compressed_size_bytes,
        source_checksum=segment.source_checksum,
        source_class=segment.source_class,
    )
