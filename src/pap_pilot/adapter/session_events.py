"""Extract allowlisted machine-labeled events for one OSCAR session."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import sqlite3
from types import MappingProxyType
from typing import Final

from pap_pilot.adapter.oscar import OscarDatabaseError, open_oscar_database
from pap_pilot.adapter.session_summary import (
    OscarSessionSummary,
    _extract_session_summary,
)


class OscarEventKind(StrEnum):
    """Allowlisted machine/OSCAR event identities for the first experiment."""

    OBSTRUCTIVE_APNEA = "obstructive_apnea"
    CLEAR_AIRWAY_APNEA = "clear_airway_apnea"
    UNCLASSIFIED_APNEA = "unclassified_apnea"
    HYPOPNEA = "hypopnea"
    RERA = "rera"
    LARGE_LEAK = "large_leak"


class OscarEventCompleteness(StrEnum):
    """Whether observed event rows establish a complete event count."""

    UNKNOWN = "unknown"


class OscarEventSourceClass(StrEnum):
    """Provenance class distinguishing source labels from companion results."""

    MACHINE_LABELED_OSCAR_NORMALIZED = "machine_labeled_oscar_normalized"


EVENT_CHANNELS: Final[Mapping[str, tuple[OscarEventKind, str]]] = MappingProxyType({
    "Obstructive": (OscarEventKind.OBSTRUCTIVE_APNEA, "OA"),
    "ClearAirway": (OscarEventKind.CLEAR_AIRWAY_APNEA, "CA"),
    "Apnea": (OscarEventKind.UNCLASSIFIED_APNEA, "UA"),
    "Hypopnea": (OscarEventKind.HYPOPNEA, "H"),
    "RERA": (OscarEventKind.RERA, "RE"),
    "LeakSpan": (OscarEventKind.LARGE_LEAK, "LL"),
})


class SessionEventsError(OscarDatabaseError):
    """Base class for event rows that cannot be extracted safely."""


class InvalidSessionEventError(SessionEventsError):
    """Raised when an allowlisted event row violates the schema-17 contract."""


@dataclass(frozen=True, slots=True)
class OscarSessionEvent:
    """One raw machine-labeled event with OSCAR source provenance."""

    source_event_id: int
    session_database_id: int
    profile_database_id: int
    source_channel_id: int
    channel_code: str
    event_kind: OscarEventKind
    oscar_label: str
    source_event_type: int
    raw_start_ms: int
    raw_end_ms: int
    duration_s: int
    contained_within_session: bool
    source_class: OscarEventSourceClass


@dataclass(frozen=True, slots=True)
class OscarObservedEventCount:
    """Count of observed source rows, never an assertion of completeness."""

    event_kind: OscarEventKind
    oscar_label: str
    observed_rows: int
    completeness: OscarEventCompleteness


@dataclass(frozen=True, slots=True)
class OscarSessionEvents:
    """One validated session plus its allowlisted raw event rows."""

    session_summary: OscarSessionSummary
    events: tuple[OscarSessionEvent, ...]
    observed_row_counts: tuple[OscarObservedEventCount, ...]
    completeness: OscarEventCompleteness


def extract_session_events(
    database_path: str | Path,
    session_database_id: int,
    *,
    trusted_immutable_copy: bool = False,
) -> OscarSessionEvents:
    """Extract the six allowlisted event kinds for exactly one session."""

    if type(session_database_id) is not int:
        raise InvalidSessionEventError(
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
        return _extract_session_events(connection, session_summary)


def _extract_session_events(
    connection: sqlite3.Connection,
    session_summary: OscarSessionSummary,
) -> OscarSessionEvents:
    """Extract allowlisted events inside an existing guarded read transaction."""

    events = _extract_events(connection, session_summary)

    observed_counts = Counter(event.event_kind for event in events)
    counts = tuple(
        OscarObservedEventCount(
            event_kind=event_kind,
            oscar_label=oscar_label,
            observed_rows=observed_counts[event_kind],
            completeness=OscarEventCompleteness.UNKNOWN,
        )
        for event_kind, oscar_label in EVENT_CHANNELS.values()
    )
    return OscarSessionEvents(
        session_summary=session_summary,
        events=events,
        observed_row_counts=counts,
        completeness=OscarEventCompleteness.UNKNOWN,
    )


def _extract_events(
    connection: sqlite3.Connection,
    session_summary: OscarSessionSummary,
) -> tuple[OscarSessionEvent, ...]:
    channel_codes = tuple(EVENT_CHANNELS)
    placeholders = ", ".join("?" for _ in channel_codes)
    rows = connection.execute(
        f"""
        SELECT
            re.id AS source_event_id,
            re.session_id AS session_database_id,
            re.profile_id AS profile_database_id,
            re.channel_id AS source_channel_id,
            c.channel_code,
            re.event_type AS source_event_type,
            re.start_time AS raw_start_ms,
            re.end_time AS raw_end_ms,
            re.duration AS duration_s
        FROM respiratory_events AS re
        JOIN channels AS c
          ON c.profile_id = ?
         AND c.channel_id = re.channel_id
        WHERE re.session_id = ?
          AND c.channel_code IN ({placeholders})
        ORDER BY re.start_time, re.end_time, re.id
        """,
        (
            session_summary.profile.database_id,
            session_summary.session.database_id,
            *channel_codes,
        ),
    ).fetchall()

    return tuple(_event_from_row(row, session_summary) for row in rows)


def _event_from_row(
    row: sqlite3.Row,
    session_summary: OscarSessionSummary,
) -> OscarSessionEvent:
    session_database_id = _required_integer(
        row["session_database_id"],
        "event session identifier",
    )
    if session_database_id != session_summary.session.database_id:
        raise InvalidSessionEventError(
            "An event row has conflicting session provenance."
        )

    profile_database_id = _required_integer(
        row["profile_database_id"],
        "event profile identifier",
    )
    if profile_database_id != session_summary.profile.database_id:
        raise InvalidSessionEventError(
            "An event row has conflicting profile provenance."
        )

    channel_code = _required_text(row["channel_code"], "event channel code")
    event_kind, oscar_label = EVENT_CHANNELS[channel_code]
    raw_start_ms = _required_integer(row["raw_start_ms"], "event start time")
    raw_end_ms = _required_integer(row["raw_end_ms"], "event end time")
    duration_s = _required_integer(row["duration_s"], "event duration")
    if (
        duration_s < 0
        or raw_end_ms < raw_start_ms
        or raw_end_ms - raw_start_ms != duration_s * 1000
    ):
        raise InvalidSessionEventError(
            "An event row has inconsistent raw boundaries or duration."
        )

    session = session_summary.session
    contained_within_session = (
        raw_start_ms >= session.raw_start_ms
        and raw_end_ms <= session.raw_end_ms
    )
    return OscarSessionEvent(
        source_event_id=_required_integer(
            row["source_event_id"],
            "source event identifier",
        ),
        session_database_id=session_database_id,
        profile_database_id=profile_database_id,
        source_channel_id=_required_integer(
            row["source_channel_id"],
            "event channel identifier",
        ),
        channel_code=channel_code,
        event_kind=event_kind,
        oscar_label=oscar_label,
        source_event_type=_required_integer(
            row["source_event_type"],
            "opaque source event type",
        ),
        raw_start_ms=raw_start_ms,
        raw_end_ms=raw_end_ms,
        duration_s=duration_s,
        contained_within_session=contained_within_session,
        source_class=OscarEventSourceClass.MACHINE_LABELED_OSCAR_NORMALIZED,
    )


def _required_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise InvalidSessionEventError(
            f"The OSCAR {field_name} is not an integer."
        )
    return value


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidSessionEventError(
            f"The OSCAR {field_name} is missing or is not text."
        )
    return value
