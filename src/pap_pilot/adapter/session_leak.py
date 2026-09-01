"""Extract the raw sparse Leak signal for one OSCAR session."""

from dataclasses import dataclass
from enum import StrEnum
import math
from pathlib import Path
import sqlite3
import struct
from typing import Final
import zlib

from pap_pilot.adapter._uniform_waveform import (
    OscarSignalSourceClass,
    OscarSignalStorage,
    _qt_iso3309_checksum,
)
from pap_pilot.adapter.oscar import OscarDatabaseError, open_oscar_database
from pap_pilot.adapter.session_summary import (
    OscarSessionSummary,
    _extract_session_summary,
)


LEAK_CHANNEL_CODE: Final = "Leak"
LEAK_CANONICAL_UNIT: Final = "L/min"
LEAK_SOURCE_DIMENSION: Final[str | None] = None

_SPARSE_EVENT_TYPE: Final = 1
_SPARSE_RATE_MS: Final = 0.0


class OscarLeakAvailability(StrEnum):
    """Why a selected session does or does not have Leak samples."""

    AVAILABLE = "available"
    CHANNEL_MISSING = "channel_missing"
    DATA_MISSING = "data_missing"


class OscarLeakSemantics(StrEnum):
    """What the stored Leak values represent clinically."""

    UNDETERMINED_TOTAL_OR_EXCESS = "undetermined_total_or_excess"


class SessionLeakError(OscarDatabaseError):
    """Base class for Leak data that cannot be extracted safely."""


class InvalidLeakSignalError(SessionLeakError):
    """Raised when Leak violates the schema-17 sparse-signal contract."""


@dataclass(frozen=True, slots=True)
class OscarLeakSegment:
    """One independent sparse Leak EventList without inferred step holds."""

    source_eventlist_id: int
    source_event_data_id: int
    session_database_id: int
    profile_database_id: int
    source_channel_id: int
    eventlist_index: int
    raw_first_time_ms: int
    raw_last_time_ms: int
    sample_count: int
    raw_time_deltas_ms: tuple[int, ...]
    raw_sample_times_ms: tuple[int, ...]
    values_l_min: tuple[float, ...]
    gain_l_min_per_raw_unit: float
    offset_l_min: float
    source_dimension: str | None
    canonical_unit: str
    gap_before_ms: int | None
    storage: OscarSignalStorage
    source_data_size_bytes: int
    source_compressed_size_bytes: int | None
    value_data_size_bytes: int
    value_stored_size_bytes: int
    time_data_size_bytes: int
    time_stored_size_bytes: int
    source_checksum: int
    source_class: OscarSignalSourceClass


@dataclass(frozen=True, slots=True)
class OscarLeakSignal:
    """The raw Leak availability and sparse segments for one session."""

    session_summary: OscarSessionSummary
    availability: OscarLeakAvailability
    source_channel_id: int | None
    channel_code: str
    canonical_unit: str
    semantics: OscarLeakSemantics
    segments: tuple[OscarLeakSegment, ...]
    source_class: OscarSignalSourceClass

    @property
    def total_sample_count(self) -> int:
        """Return the number of stored updates across independent segments."""

        return sum(segment.sample_count for segment in self.segments)


def extract_leak_signal(
    database_path: str | Path,
    session_database_id: int,
    *,
    trusted_immutable_copy: bool = False,
) -> OscarLeakSignal:
    """Extract only stored Leak updates for one validated session."""

    if type(session_database_id) is not int:
        raise InvalidLeakSignalError(
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
        channel_id = _extract_channel_id(connection, session_summary)
        if channel_id is None:
            return _missing_signal(
                session_summary,
                OscarLeakAvailability.CHANNEL_MISSING,
                source_channel_id=None,
            )

        rows = _extract_rows(connection, session_summary, channel_id)
        if not rows:
            return _missing_signal(
                session_summary,
                OscarLeakAvailability.DATA_MISSING,
                source_channel_id=channel_id,
            )
        segments = _segments_from_rows(rows, session_summary, channel_id)

    return OscarLeakSignal(
        session_summary=session_summary,
        availability=OscarLeakAvailability.AVAILABLE,
        source_channel_id=channel_id,
        channel_code=LEAK_CHANNEL_CODE,
        canonical_unit=LEAK_CANONICAL_UNIT,
        semantics=OscarLeakSemantics.UNDETERMINED_TOTAL_OR_EXCESS,
        segments=segments,
        source_class=(
            OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED
        ),
    )


def _missing_signal(
    session_summary: OscarSessionSummary,
    availability: OscarLeakAvailability,
    *,
    source_channel_id: int | None,
) -> OscarLeakSignal:
    return OscarLeakSignal(
        session_summary=session_summary,
        availability=availability,
        source_channel_id=source_channel_id,
        channel_code=LEAK_CHANNEL_CODE,
        canonical_unit=LEAK_CANONICAL_UNIT,
        semantics=OscarLeakSemantics.UNDETERMINED_TOTAL_OR_EXCESS,
        segments=(),
        source_class=(
            OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED
        ),
    )


def _extract_channel_id(
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
        (session_summary.profile.database_id, LEAK_CHANNEL_CODE),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise InvalidLeakSignalError(
            "The profile has ambiguous Leak channel provenance."
        )
    return _required_integer(rows[0]["channel_id"], "Leak channel identifier")


def _extract_rows(
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
            el.last_time AS raw_last_time_ms,
            el.count AS sample_count,
            el.rate,
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
) -> tuple[OscarLeakSegment, ...]:
    segments: list[OscarLeakSegment] = []
    previous_last_time_ms: int | None = None
    for expected_index, row in enumerate(rows):
        eventlist_index = _required_integer(
            row["eventlist_index"],
            "Leak EventList index",
        )
        if eventlist_index != expected_index:
            raise InvalidLeakSignalError(
                "Leak EventList indexes are not zero-based and contiguous."
            )
        segment = _segment_from_row(
            row,
            session_summary,
            channel_id,
            previous_last_time_ms=previous_last_time_ms,
        )
        segments.append(segment)
        previous_last_time_ms = segment.raw_last_time_ms
    return tuple(segments)


def _segment_from_row(
    row: sqlite3.Row,
    session_summary: OscarSessionSummary,
    channel_id: int,
    *,
    previous_last_time_ms: int | None,
) -> OscarLeakSegment:
    _validate_provenance(row, session_summary, channel_id)
    if _required_integer(row["event_type"], "Leak event type") != _SPARSE_EVENT_TYPE:
        raise InvalidLeakSignalError(
            "Leak is not stored as a sparse EventList."
        )
    source_dimension = row["source_dimension"]
    if source_dimension not in (None, ""):
        raise InvalidLeakSignalError(
            "Leak does not have an absent OSCAR source dimension."
        )
    if _required_boolean(row["has_second_field"], "Leak has_second_field"):
        raise InvalidLeakSignalError(
            "Leak unexpectedly contains a second value field."
        )
    if row["data2_blob"] is not None or row["data2_compressed"] is not None:
        raise InvalidLeakSignalError(
            "Leak contains unsupported secondary-value data."
        )

    sample_count = _required_integer(row["sample_count"], "Leak sample count")
    if sample_count <= 0:
        raise InvalidLeakSignalError("Leak has a non-positive sample count.")
    rate = _required_number(row["rate"], "Leak sample rate")
    if not math.isclose(rate, _SPARSE_RATE_MS, rel_tol=0.0, abs_tol=1e-9):
        raise InvalidLeakSignalError(
            "Leak has a nonzero rate instead of explicit sparse timestamps."
        )

    raw_first_time_ms = _required_integer(
        row["raw_first_time_ms"],
        "Leak first timestamp",
    )
    raw_last_time_ms = _required_integer(
        row["raw_last_time_ms"],
        "Leak last timestamp",
    )
    if raw_last_time_ms < raw_first_time_ms:
        raise InvalidLeakSignalError("Leak has reversed EventList boundaries.")
    session = session_summary.session
    if (
        raw_first_time_ms < session.raw_start_ms
        or raw_last_time_ms > session.raw_end_ms
    ):
        raise InvalidLeakSignalError(
            "Leak boundaries fall outside the selected session."
        )

    gap_before_ms: int | None = None
    if previous_last_time_ms is not None:
        gap_before_ms = raw_first_time_ms - previous_last_time_ms
        if gap_before_ms < 0:
            raise InvalidLeakSignalError(
                "Leak EventLists overlap or are not chronological."
            )

    gain = _required_number(row["gain"], "Leak gain")
    offset = _required_number(row["offset"], "Leak offset")
    if gain <= 0:
        raise InvalidLeakSignalError("Leak has a non-positive gain.")
    expected_value_size = sample_count * 2
    expected_time_size = sample_count * 4
    expected_source_data_size = expected_value_size + expected_time_size
    source_data_size_bytes = _required_integer(
        row["data_size_bytes"],
        "Leak combined uncompressed data size",
    )
    if source_data_size_bytes != expected_source_data_size:
        raise InvalidLeakSignalError(
            "Leak data_size does not match its value and time arrays."
        )

    compression_method = _required_integer(
        row["compression_method"],
        "Leak compression method",
    )
    primary_data, storage, primary_stored_size = _decode_array(
        uncompressed_blob=row["data_blob"],
        compressed_blob=row["data_compressed"],
        compression_method=compression_method,
        expected_size=expected_value_size,
        array_name="primary",
    )
    time_data, time_storage, time_stored_size = _decode_array(
        uncompressed_blob=row["time_blob"],
        compressed_blob=row["time_compressed"],
        compression_method=compression_method,
        expected_size=expected_time_size,
        array_name="time",
    )
    if time_storage is not storage:
        raise InvalidLeakSignalError(
            "Leak primary and time arrays use conflicting storage branches."
        )

    source_compressed_size = _optional_integer(
        row["compressed_size_bytes"],
        "Leak combined stored-data size",
    )
    if (
        source_compressed_size is not None
        and source_compressed_size != primary_stored_size + time_stored_size
    ):
        raise InvalidLeakSignalError(
            "Leak compressed_size does not match its stored value and time BLOBs."
        )

    source_checksum = _required_integer(row["source_checksum"], "Leak checksum")
    if not 0 <= source_checksum <= 0xFFFF:
        raise InvalidLeakSignalError("Leak checksum is outside uint16 range.")
    if _qt_iso3309_checksum(primary_data) != source_checksum:
        raise InvalidLeakSignalError("Leak checksum validation failed.")

    raw_values = tuple(value[0] for value in struct.iter_unpack("<h", primary_data))
    values_l_min = tuple(raw_value * gain + offset for raw_value in raw_values)
    if any(not math.isfinite(value) for value in values_l_min):
        raise InvalidLeakSignalError("Leak produced a non-finite value.")
    time_deltas = tuple(value[0] for value in struct.iter_unpack("<I", time_data))
    _validate_time_deltas(
        time_deltas,
        eventlist_duration_ms=raw_last_time_ms - raw_first_time_ms,
    )
    sample_times = tuple(
        raw_first_time_ms + delta_ms for delta_ms in time_deltas
    )

    return OscarLeakSegment(
        source_eventlist_id=_required_integer(
            row["source_eventlist_id"],
            "Leak EventList identifier",
        ),
        source_event_data_id=_required_integer(
            row["source_event_data_id"],
            "Leak data-row identifier",
        ),
        session_database_id=session.database_id,
        profile_database_id=session_summary.profile.database_id,
        source_channel_id=channel_id,
        eventlist_index=_required_integer(
            row["eventlist_index"],
            "Leak EventList index",
        ),
        raw_first_time_ms=raw_first_time_ms,
        raw_last_time_ms=raw_last_time_ms,
        sample_count=sample_count,
        raw_time_deltas_ms=time_deltas,
        raw_sample_times_ms=sample_times,
        values_l_min=values_l_min,
        gain_l_min_per_raw_unit=gain,
        offset_l_min=offset,
        source_dimension=source_dimension,
        canonical_unit=LEAK_CANONICAL_UNIT,
        gap_before_ms=gap_before_ms,
        storage=storage,
        source_data_size_bytes=source_data_size_bytes,
        source_compressed_size_bytes=source_compressed_size,
        value_data_size_bytes=expected_value_size,
        value_stored_size_bytes=primary_stored_size,
        time_data_size_bytes=expected_time_size,
        time_stored_size_bytes=time_stored_size,
        source_checksum=source_checksum,
        source_class=(
            OscarSignalSourceClass.MACHINE_RECORDED_OSCAR_NORMALIZED
        ),
    )


def _validate_provenance(
    row: sqlite3.Row,
    session_summary: OscarSessionSummary,
    channel_id: int,
) -> None:
    expected_values = (
        ("session_database_id", session_summary.session.database_id, "session"),
        ("profile_database_id", session_summary.profile.database_id, "profile"),
        ("source_channel_id", channel_id, "channel"),
    )
    for field, expected, label in expected_values:
        if _required_integer(row[field], f"Leak {label} identifier") != expected:
            raise InvalidLeakSignalError(
                f"A Leak EventList has conflicting {label} provenance."
            )


def _decode_array(
    *,
    uncompressed_blob: object,
    compressed_blob: object,
    compression_method: int,
    expected_size: int,
    array_name: str,
) -> tuple[bytes, OscarSignalStorage, int]:
    if compression_method == 0:
        if not isinstance(uncompressed_blob, bytes) or compressed_blob is not None:
            raise InvalidLeakSignalError(
                f"Leak has invalid uncompressed {array_name} storage."
            )
        data = uncompressed_blob
        stored_size = len(uncompressed_blob)
        storage = OscarSignalStorage.UNCOMPRESSED
    elif compression_method == 1:
        if uncompressed_blob is not None or not isinstance(compressed_blob, bytes):
            raise InvalidLeakSignalError(
                f"Leak has invalid compressed {array_name} storage."
            )
        data = _qt_uncompress(
            compressed_blob,
            expected_size=expected_size,
            array_name=array_name,
        )
        stored_size = len(compressed_blob)
        storage = OscarSignalStorage.QT_ZLIB
    else:
        raise InvalidLeakSignalError(
            "Leak uses an unsupported compression method."
        )
    if len(data) != expected_size:
        raise InvalidLeakSignalError(
            f"Leak {array_name} data length does not match its sample count."
        )
    return data, storage, stored_size


def _qt_uncompress(
    data: bytes,
    *,
    expected_size: int,
    array_name: str,
) -> bytes:
    if len(data) < 5:
        raise InvalidLeakSignalError(
            f"Leak {array_name} qCompress data is truncated."
        )
    header_size = int.from_bytes(data[:4], byteorder="big", signed=False)
    if header_size != expected_size:
        raise InvalidLeakSignalError(
            f"Leak {array_name} qCompress length header is invalid."
        )
    decompressor = zlib.decompressobj()
    try:
        result = decompressor.decompress(data[4:]) + decompressor.flush()
    except zlib.error as error:
        raise InvalidLeakSignalError(
            f"Leak {array_name} qCompress data could not be decompressed."
        ) from error
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        raise InvalidLeakSignalError(
            f"Leak {array_name} qCompress data has an incomplete or trailing stream."
        )
    return result


def _validate_time_deltas(
    time_deltas: tuple[int, ...],
    *,
    eventlist_duration_ms: int,
) -> None:
    if not time_deltas or time_deltas[0] != 0:
        raise InvalidLeakSignalError(
            "Leak sparse timestamps do not begin at the EventList boundary."
        )
    if any(later < earlier for earlier, later in zip(time_deltas, time_deltas[1:])):
        raise InvalidLeakSignalError(
            "Leak sparse timestamps are not nondecreasing."
        )
    if time_deltas[-1] != eventlist_duration_ms:
        raise InvalidLeakSignalError(
            "Leak sparse timestamps do not end at the EventList boundary."
        )


def _required_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise InvalidLeakSignalError(f"The OSCAR {field_name} is not an integer.")
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _required_integer(value, field_name)


def _required_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidLeakSignalError(f"The OSCAR {field_name} is not numeric.")
    number = float(value)
    if not math.isfinite(number):
        raise InvalidLeakSignalError(f"The OSCAR {field_name} is not finite.")
    return number


def _required_boolean(value: object, field_name: str) -> bool:
    if type(value) is not int or value not in (0, 1):
        raise InvalidLeakSignalError(
            f"The OSCAR {field_name} is not encoded as 0 or 1."
        )
    return bool(value)
