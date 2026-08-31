"""Extract the raw FlowRate waveform for one OSCAR session."""

from dataclasses import dataclass
from enum import StrEnum
import math
from pathlib import Path
import sqlite3
import struct
from typing import Final
import zlib

from pap_pilot.adapter.oscar import OscarDatabaseError, open_oscar_database
from pap_pilot.adapter.session_summary import (
    OscarSessionSummary,
    _extract_session_summary,
)


FLOW_RATE_CHANNEL_CODE: Final = "FlowRate"
FLOW_RATE_CANONICAL_UNIT: Final = "L/min"
FLOW_RATE_SOURCE_DIMENSION: Final = "L/M"
FLOW_RATE_SAMPLE_INTERVAL_MS: Final = 40.0
_FLOW_RATE_EVENT_TYPE: Final = 0


class OscarFlowAvailability(StrEnum):
    """Why a selected session does or does not have FlowRate samples."""

    AVAILABLE = "available"
    CHANNEL_MISSING = "channel_missing"
    DATA_MISSING = "data_missing"


class OscarSignalStorage(StrEnum):
    """Storage branch used by one OSCAR EventList primary array."""

    UNCOMPRESSED = "uncompressed"
    QT_ZLIB = "qt_zlib"


class OscarSignalSourceClass(StrEnum):
    """Provenance class distinguishing source samples from analysis."""

    MACHINE_RECORDED_OSCAR_NORMALIZED = (
        "machine_recorded_oscar_normalized"
    )


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

    if type(session_database_id) is not int:
        raise InvalidFlowSignalError(
            "The selected session database identifier must be an integer."
        )

    with open_oscar_database(
        database_path,
        trusted_immutable_copy=trusted_immutable_copy,
    ) as connection:
        connection.row_factory = sqlite3.Row
        session_summary = _extract_session_summary(
            connection,
            session_database_id,
        )
        channel_id = _extract_flow_channel_id(connection, session_summary)
        if channel_id is None:
            return _missing_flow_signal(
                session_summary,
                OscarFlowAvailability.CHANNEL_MISSING,
                source_channel_id=None,
            )

        rows = _extract_flow_rows(
            connection,
            session_summary,
            channel_id,
        )
        if not rows:
            return _missing_flow_signal(
                session_summary,
                OscarFlowAvailability.DATA_MISSING,
                source_channel_id=channel_id,
            )

        segments = _segments_from_rows(
            rows,
            session_summary,
            channel_id,
        )

    return OscarFlowSignal(
        session_summary=session_summary,
        availability=OscarFlowAvailability.AVAILABLE,
        source_channel_id=channel_id,
        channel_code=FLOW_RATE_CHANNEL_CODE,
        canonical_unit=FLOW_RATE_CANONICAL_UNIT,
        segments=segments,
        source_class=(
            OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED
        ),
    )


def _missing_flow_signal(
    session_summary: OscarSessionSummary,
    availability: OscarFlowAvailability,
    *,
    source_channel_id: int | None,
) -> OscarFlowSignal:
    return OscarFlowSignal(
        session_summary=session_summary,
        availability=availability,
        source_channel_id=source_channel_id,
        channel_code=FLOW_RATE_CHANNEL_CODE,
        canonical_unit=FLOW_RATE_CANONICAL_UNIT,
        segments=(),
        source_class=(
            OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED
        ),
    )


def _extract_flow_channel_id(
    connection: sqlite3.Connection,
    session_summary: OscarSessionSummary,
) -> int | None:
    rows = connection.execute(
        """
        SELECT channel_id
        FROM channels
        WHERE profile_id = ?
          AND channel_code = ?
        """,
        (
            session_summary.profile.database_id,
            FLOW_RATE_CHANNEL_CODE,
        ),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise InvalidFlowSignalError(
            "The profile has ambiguous FlowRate channel provenance."
        )
    return _required_integer(rows[0]["channel_id"], "FlowRate channel identifier")


def _extract_flow_rows(
    connection: sqlite3.Connection,
    session_summary: OscarSessionSummary,
    channel_id: int,
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            el.id AS source_eventlist_id,
            el.session_id AS session_database_id,
            el.profile_id AS profile_database_id,
            el.channel_id AS source_channel_id,
            el.eventlist_index,
            el.event_type,
            el.first_time AS raw_first_time_ms,
            el.last_time AS raw_end_time_ms_exclusive,
            el.count AS sample_count,
            el.rate AS sample_interval_ms,
            el.gain,
            el.offset,
            el.dimension AS source_dimension,
            el.has_second_field,
            el.data_size AS data_size_bytes,
            el.compressed_size AS compressed_size_bytes,
            ed.id AS source_event_data_id,
            ed.data_blob,
            ed.data_compressed,
            ed.data2_blob,
            ed.data2_compressed,
            ed.time_blob,
            ed.time_compressed,
            ed.compression_method,
            ed.checksum AS source_checksum
        FROM event_lists AS el
        LEFT JOIN event_data AS ed ON ed.eventlist_id = el.id
        WHERE el.session_id = ?
          AND el.channel_id = ?
        ORDER BY el.eventlist_index, el.id
        """,
        (session_summary.session.database_id, channel_id),
    ).fetchall()


def _segments_from_rows(
    rows: list[sqlite3.Row],
    session_summary: OscarSessionSummary,
    channel_id: int,
) -> tuple[OscarFlowSegment, ...]:
    segments: list[OscarFlowSegment] = []
    previous_end_ms: int | None = None
    for expected_index, row in enumerate(rows):
        eventlist_index = _required_integer(
            row["eventlist_index"],
            "FlowRate EventList index",
        )
        if eventlist_index != expected_index:
            raise InvalidFlowSignalError(
                "FlowRate EventList indexes are not zero-based and contiguous."
            )
        segment = _segment_from_row(
            row,
            session_summary,
            channel_id,
            previous_end_ms=previous_end_ms,
        )
        segments.append(segment)
        previous_end_ms = segment.raw_end_time_ms_exclusive
    return tuple(segments)


def _segment_from_row(
    row: sqlite3.Row,
    session_summary: OscarSessionSummary,
    channel_id: int,
    *,
    previous_end_ms: int | None,
) -> OscarFlowSegment:
    _validate_segment_provenance(row, session_summary, channel_id)
    if (
        _required_integer(row["event_type"], "FlowRate event type")
        != _FLOW_RATE_EVENT_TYPE
    ):
        raise InvalidFlowSignalError(
            "FlowRate is not stored as a uniform waveform EventList."
        )
    if (
        _required_text(row["source_dimension"], "FlowRate dimension")
        != FLOW_RATE_SOURCE_DIMENSION
    ):
        raise InvalidFlowSignalError(
            "FlowRate does not have the expected OSCAR source dimension."
        )
    if _required_boolean(
        row["has_second_field"],
        "FlowRate has_second_field",
    ):
        raise InvalidFlowSignalError(
            "FlowRate unexpectedly contains a second value field."
        )
    if any(
        row[field] is not None
        for field in (
            "data2_blob",
            "data2_compressed",
            "time_blob",
            "time_compressed",
        )
    ):
        raise InvalidFlowSignalError(
            "FlowRate contains unsupported secondary or explicit-time data."
        )

    sample_count = _required_integer(row["sample_count"], "FlowRate sample count")
    if sample_count <= 0:
        raise InvalidFlowSignalError("FlowRate has a non-positive sample count.")
    sample_interval_ms = _required_number(
        row["sample_interval_ms"],
        "FlowRate sample interval",
    )
    if not math.isclose(
        sample_interval_ms,
        FLOW_RATE_SAMPLE_INTERVAL_MS,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise InvalidFlowSignalError(
            "FlowRate does not have the required 25 Hz sample interval."
        )

    raw_first_time_ms = _required_integer(
        row["raw_first_time_ms"],
        "FlowRate first timestamp",
    )
    raw_end_time_ms = _required_integer(
        row["raw_end_time_ms_exclusive"],
        "FlowRate end timestamp",
    )
    expected_end_ms = raw_first_time_ms + sample_count * sample_interval_ms
    if not math.isclose(
        float(raw_end_time_ms),
        expected_end_ms,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise InvalidFlowSignalError(
            "FlowRate bounds do not match its count and sample interval."
        )
    session = session_summary.session
    if (
        raw_first_time_ms < session.raw_start_ms
        or raw_end_time_ms > session.raw_end_ms
    ):
        raise InvalidFlowSignalError(
            "FlowRate boundaries fall outside the selected session."
        )

    gap_before_ms: int | None = None
    if previous_end_ms is not None:
        gap_before_ms = raw_first_time_ms - previous_end_ms
        if gap_before_ms < 0:
            raise InvalidFlowSignalError(
                "FlowRate EventLists overlap or are not chronological."
            )

    gain = _required_number(row["gain"], "FlowRate gain")
    offset = _required_number(row["offset"], "FlowRate offset")
    if gain <= 0:
        raise InvalidFlowSignalError("FlowRate has a non-positive gain.")
    data_size_bytes = _required_integer(
        row["data_size_bytes"],
        "FlowRate uncompressed data size",
    )
    expected_data_size = sample_count * 2
    if data_size_bytes != expected_data_size:
        raise InvalidFlowSignalError(
            "FlowRate data_size does not match its sample count."
        )

    primary_data, storage, compressed_size = _decode_primary_data(
        row,
        expected_size=expected_data_size,
    )
    source_checksum = _required_integer(
        row["source_checksum"],
        "FlowRate checksum",
    )
    if not 0 <= source_checksum <= 0xFFFF:
        raise InvalidFlowSignalError("FlowRate checksum is outside uint16 range.")
    if _qt_iso3309_checksum(primary_data) != source_checksum:
        raise InvalidFlowSignalError("FlowRate checksum validation failed.")

    raw_values = tuple(value[0] for value in struct.iter_unpack("<h", primary_data))
    values = tuple(raw_value * gain + offset for raw_value in raw_values)
    if any(not math.isfinite(value) for value in values):
        raise InvalidFlowSignalError("FlowRate produced a non-finite value.")
    sample_times = tuple(
        raw_first_time_ms + index * sample_interval_ms
        for index in range(sample_count)
    )

    return OscarFlowSegment(
        source_eventlist_id=_required_integer(
            row["source_eventlist_id"],
            "FlowRate EventList identifier",
        ),
        source_event_data_id=_required_integer(
            row["source_event_data_id"],
            "FlowRate data-row identifier",
        ),
        session_database_id=session.database_id,
        profile_database_id=session_summary.profile.database_id,
        source_channel_id=channel_id,
        eventlist_index=_required_integer(
            row["eventlist_index"],
            "FlowRate EventList index",
        ),
        raw_first_time_ms=raw_first_time_ms,
        raw_end_time_ms_exclusive=raw_end_time_ms,
        sample_interval_ms=sample_interval_ms,
        sample_count=sample_count,
        raw_sample_times_ms=sample_times,
        values_l_min=values,
        gain_l_min_per_raw_unit=gain,
        offset_l_min=offset,
        source_dimension=FLOW_RATE_SOURCE_DIMENSION,
        canonical_unit=FLOW_RATE_CANONICAL_UNIT,
        gap_before_ms=gap_before_ms,
        storage=storage,
        data_size_bytes=data_size_bytes,
        compressed_size_bytes=compressed_size,
        source_checksum=source_checksum,
        source_class=(
            OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED
        ),
    )


def _validate_segment_provenance(
    row: sqlite3.Row,
    session_summary: OscarSessionSummary,
    channel_id: int,
) -> None:
    expected_values = (
        (
            "session_database_id",
            session_summary.session.database_id,
            "session",
        ),
        (
            "profile_database_id",
            session_summary.profile.database_id,
            "profile",
        ),
        ("source_channel_id", channel_id, "channel"),
    )
    for field, expected, label in expected_values:
        if _required_integer(row[field], f"FlowRate {label} identifier") != expected:
            raise InvalidFlowSignalError(
                f"A FlowRate EventList has conflicting {label} provenance."
            )


def _decode_primary_data(
    row: sqlite3.Row,
    *,
    expected_size: int,
) -> tuple[bytes, OscarSignalStorage, int | None]:
    compression_method = _required_integer(
        row["compression_method"],
        "FlowRate compression method",
    )
    raw_blob = row["data_blob"]
    compressed_blob = row["data_compressed"]
    if compression_method == 0:
        if not isinstance(raw_blob, bytes) or compressed_blob is not None:
            raise InvalidFlowSignalError(
                "FlowRate has invalid uncompressed primary storage."
            )
        primary_data = raw_blob
        stored_size = len(raw_blob)
        storage = OscarSignalStorage.UNCOMPRESSED
    elif compression_method == 1:
        if raw_blob is not None or not isinstance(compressed_blob, bytes):
            raise InvalidFlowSignalError(
                "FlowRate has invalid compressed primary storage."
            )
        primary_data = _qt_uncompress(
            compressed_blob,
            expected_size=expected_size,
        )
        stored_size = len(compressed_blob)
        storage = OscarSignalStorage.QT_ZLIB
    else:
        raise InvalidFlowSignalError(
            "FlowRate uses an unsupported compression method."
        )

    if len(primary_data) != expected_size:
        raise InvalidFlowSignalError(
            "FlowRate primary data length does not match its sample count."
        )
    compressed_size = _optional_integer(
        row["compressed_size_bytes"],
        "FlowRate stored data size",
    )
    if compressed_size is not None and compressed_size != stored_size:
        raise InvalidFlowSignalError(
            "FlowRate compressed_size does not match the selected storage BLOB."
        )
    return primary_data, storage, compressed_size


def _qt_uncompress(data: bytes, *, expected_size: int) -> bytes:
    if len(data) < 5:
        raise InvalidFlowSignalError("FlowRate qCompress data is truncated.")
    header_size = int.from_bytes(data[:4], byteorder="big", signed=False)
    if header_size != expected_size:
        raise InvalidFlowSignalError(
            "FlowRate qCompress length header does not match data_size."
        )
    decompressor = zlib.decompressobj()
    try:
        result = decompressor.decompress(data[4:]) + decompressor.flush()
    except zlib.error as error:
        raise InvalidFlowSignalError(
            "FlowRate qCompress data could not be decompressed."
        ) from error
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        raise InvalidFlowSignalError(
            "FlowRate qCompress data has an incomplete or trailing stream."
        )
    return result


def _qt_iso3309_checksum(data: bytes) -> int:
    """Match Qt qChecksum(data, Qt::ChecksumIso3309)."""

    checksum = 0xFFFF
    for byte in data:
        checksum ^= byte
        for _ in range(8):
            if checksum & 1:
                checksum = (checksum >> 1) ^ 0x8408
            else:
                checksum >>= 1
    return (~checksum) & 0xFFFF


def _required_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise InvalidFlowSignalError(
            f"The OSCAR {field_name} is not an integer."
        )
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _required_integer(value, field_name)


def _required_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidFlowSignalError(
            f"The OSCAR {field_name} is not numeric."
        )
    number = float(value)
    if not math.isfinite(number):
        raise InvalidFlowSignalError(
            f"The OSCAR {field_name} is not finite."
        )
    return number


def _required_boolean(value: object, field_name: str) -> bool:
    if type(value) is not int or value not in (0, 1):
        raise InvalidFlowSignalError(
            f"The OSCAR {field_name} is not encoded as 0 or 1."
        )
    return bool(value)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidFlowSignalError(
            f"The OSCAR {field_name} is missing or is not text."
        )
    return value
