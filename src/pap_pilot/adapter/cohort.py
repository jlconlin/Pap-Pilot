"""Explicit, read-only extraction of a selected OSCAR session cohort."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Final

from pap_pilot.adapter.oscar import OscarDatabaseError, open_oscar_database
from pap_pilot.adapter.session_events import _extract_session_events
from pap_pilot.adapter.session_flow import _extract_flow_rate_signal
from pap_pilot.adapter.session_leak import _extract_leak_signal
from pap_pilot.adapter.session_mask_pressure import _extract_mask_pressure_signal
from pap_pilot.adapter.session_summary import OscarSessionSummary, _extract_session_summary
from pap_pilot.adapter.normalization import normalize_oscar_session
from pap_pilot.engine.model import (
    NightRecord,
    ProvenanceRecord,
    ProvenanceValue,
    SourceReference,
    serialize_normalized_record,
)


OSCAR_COHORT_RECORD_VERSION: Final = 1
SUPPORTED_CORRECTION_SCHEMA_VERSION: Final = 17
_OPEN_ENDED_DATE_SENTINEL: Final = "2099-12-31"


class OscarCohortError(OscarDatabaseError):
    """Raised when an explicit cohort cannot be extracted safely."""


class OscarCorrectionType(StrEnum):
    """Correction labels permitted by the schema-17 table contract."""

    TIMEZONE = "timezone"
    TRAVEL = "travel"
    DST = "dst"
    RESET = "reset"
    OFFSET = "offset"
    DRIFT = "drift"


class OscarCorrectionEvidenceState(StrEnum):
    """Whether corrected session bounds can be derived without guessing."""

    CONFIRMED_NONE = "confirmed_none"
    SUPPORTED_CONSTANT = "supported_constant"
    UNSUPPORTED_DRIFT = "unsupported_drift"


@dataclass(frozen=True, slots=True)
class OscarCohortSelection:
    """The complete caller-supplied OSCAR session selection."""

    session_database_ids: tuple[int, ...]
    record_version: int = OSCAR_COHORT_RECORD_VERSION

    def __post_init__(self) -> None:
        if self.record_version != OSCAR_COHORT_RECORD_VERSION:
            raise OscarCohortError("The OSCAR cohort selection record version is unsupported.")
        if type(self.session_database_ids) is not tuple or not self.session_database_ids:
            raise OscarCohortError("An OSCAR cohort selection requires at least one explicit session identifier.")
        if any(type(value) is not int or value <= 0 for value in self.session_database_ids):
            raise OscarCohortError("Every selected OSCAR session identifier must be a positive integer.")
        if len(set(self.session_database_ids)) != len(self.session_database_ids):
            raise OscarCohortError("Selected OSCAR session identifiers must be unique.")
        object.__setattr__(self, "session_database_ids", tuple(sorted(self.session_database_ids)))


@dataclass(frozen=True, slots=True)
class OscarTimeCorrection:
    """One date-matching schema-17 correction row retained as source evidence."""

    source_correction_id: int
    machine_database_id: int
    date_from: str
    date_to: str | None
    correction_type: OscarCorrectionType
    offset_ms: int | None
    drift_intercept_ms: int | None
    drift_slope_encoding: float | None
    reason: str | None
    applied_at: str
    undone_at: str | None
    record_version: int = OSCAR_COHORT_RECORD_VERSION

    def __post_init__(self) -> None:
        if self.record_version != OSCAR_COHORT_RECORD_VERSION:
            raise OscarCohortError("The OSCAR time-correction record version is unsupported.")
        _positive_integer(self.source_correction_id, "correction row identifier")
        _positive_integer(self.machine_database_id, "correction machine identifier")
        start = _iso_date(self.date_from, "correction start date")
        end = _optional_iso_date(self.date_to, "correction end date")
        if end is not None and end < start:
            raise OscarCohortError("An OSCAR correction date range cannot be reversed.")
        if not isinstance(self.correction_type, OscarCorrectionType):
            raise OscarCohortError("An OSCAR correction row has an unsupported type.")
        _optional_text(self.reason, "correction reason")
        _text(self.applied_at, "correction applied timestamp")
        _optional_text(self.undone_at, "correction undone timestamp")
        if self.correction_type is OscarCorrectionType.DRIFT:
            if (
                self.offset_ms is not None
                or type(self.drift_intercept_ms) is not int
                or not _finite_number(self.drift_slope_encoding)
            ):
                raise OscarCohortError(
                    "A drift correction requires c0/c1 evidence and cannot contain a constant offset."
                )
        elif (
            type(self.offset_ms) is not int
            or self.drift_intercept_ms is not None
            or self.drift_slope_encoding is not None
        ):
            raise OscarCohortError("A constant correction requires only an integer offset.")

    @property
    def is_active(self) -> bool:
        """Return whether OSCAR has not marked this row undone."""

        return self.undone_at is None

    @property
    def source_record_id(self) -> str:
        """Return the stable source-row reference used by later provenance."""

        return f"device_time_corrections.id:{self.source_correction_id}"

    def applies_to(self, local_date: str) -> bool:
        selected = _iso_date(local_date, "session OSCAR local date")
        start = date.fromisoformat(self.date_from)
        end = (
            date.max
            if self.date_to is None or self.date_to == _OPEN_ENDED_DATE_SENTINEL
            else date.fromisoformat(self.date_to)
        )
        return start <= selected <= end


@dataclass(frozen=True, slots=True)
class OscarSessionTimeEvidence:
    """Raw and separately derived corrected bounds for one selected session."""

    record_id: str
    session_database_id: int
    profile_database_id: int
    machine_database_id: int
    local_date: str
    raw_start_ms: int
    raw_end_ms: int
    state: OscarCorrectionEvidenceState
    observed_corrections: tuple[OscarTimeCorrection, ...]
    total_offset_ms: int | None
    corrected_start_ms: int | None
    corrected_end_ms: int | None
    source_record_ids: tuple[str, ...]
    schema_version: int = SUPPORTED_CORRECTION_SCHEMA_VERSION
    record_version: int = OSCAR_COHORT_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "session time-evidence identifier")
        _positive_integer(self.session_database_id, "time-evidence session identifier")
        _positive_integer(self.profile_database_id, "time-evidence profile identifier")
        _positive_integer(self.machine_database_id, "time-evidence machine identifier")
        _iso_date(self.local_date, "time-evidence local date")
        if (
            type(self.raw_start_ms) is not int
            or type(self.raw_end_ms) is not int
            or self.raw_start_ms >= self.raw_end_ms
        ):
            raise OscarCohortError("Raw time-evidence bounds must be increasing integer milliseconds.")
        if not isinstance(self.state, OscarCorrectionEvidenceState):
            raise OscarCohortError("Session time evidence has an unsupported state.")
        if type(self.observed_corrections) is not tuple or any(
            not isinstance(value, OscarTimeCorrection)
            for value in self.observed_corrections
        ):
            raise OscarCohortError("Observed corrections must be immutable OSCAR correction records.")
        if len({value.source_correction_id for value in self.observed_corrections}) != len(self.observed_corrections):
            raise OscarCohortError("Observed correction identifiers must be unique.")
        if any(
            value.machine_database_id != self.machine_database_id
            or not value.applies_to(self.local_date)
            for value in self.observed_corrections
        ):
            raise OscarCohortError("Observed corrections must match the session machine and OSCAR local date.")
        active = tuple(value for value in self.observed_corrections if value.is_active)
        has_drift = any(value.correction_type is OscarCorrectionType.DRIFT for value in active)
        if self.state is OscarCorrectionEvidenceState.CONFIRMED_NONE:
            valid_values = (
                not active
                and self.total_offset_ms == 0
                and self.corrected_start_ms == self.raw_start_ms
                and self.corrected_end_ms == self.raw_end_ms
            )
        elif self.state is OscarCorrectionEvidenceState.SUPPORTED_CONSTANT:
            expected_offset = sum(value.offset_ms for value in active if value.offset_ms is not None)
            valid_values = (
                bool(active)
                and not has_drift
                and self.total_offset_ms == expected_offset
                and self.corrected_start_ms == self.raw_start_ms + expected_offset
                and self.corrected_end_ms == self.raw_end_ms + expected_offset
            )
        else:
            valid_values = (
                has_drift
                and self.total_offset_ms is None
                and self.corrected_start_ms is None
                and self.corrected_end_ms is None
            )
        if not valid_values:
            raise OscarCohortError("Session correction state and corrected bounds are inconsistent.")
        sources = _text_tuple(self.source_record_ids, "session time-evidence sources")
        required_sources = {
            f"schema_version.version:{self.schema_version}",
            f"profiles.id:{self.profile_database_id}",
            f"machines.id:{self.machine_database_id}",
            f"sessions.id:{self.session_database_id}",
            f"device_time_corrections.machine_id:{self.machine_database_id}:queried",
            *(value.source_record_id for value in self.observed_corrections),
        }
        if not required_sources.issubset(sources):
            raise OscarCohortError("Session time evidence does not retain its complete source inventory.")
        if (
            self.schema_version != SUPPORTED_CORRECTION_SCHEMA_VERSION
            or self.record_version != OSCAR_COHORT_RECORD_VERSION
        ):
            raise OscarCohortError("Session time evidence has unsupported version metadata.")
        object.__setattr__(
            self,
            "observed_corrections",
            tuple(
                sorted(
                    self.observed_corrections,
                    key=lambda value: value.source_correction_id,
                )
            ),
        )
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))


@dataclass(frozen=True, slots=True)
class OscarNormalizedCohort:
    """Deterministic normalized nights and correction evidence for one selection."""

    record_id: str
    selection: OscarCohortSelection
    nights: tuple[NightRecord, ...]
    session_time_evidence: tuple[OscarSessionTimeEvidence, ...]
    profile_database_id: int
    machine_database_id: int
    schema_version: int
    source_record_ids: tuple[str, ...]
    record_version: int = OSCAR_COHORT_RECORD_VERSION

    def __post_init__(self) -> None:
        _text(self.record_id, "normalized cohort identifier")
        if not isinstance(self.selection, OscarCohortSelection):
            raise OscarCohortError("A normalized cohort requires an explicit selection.")
        if type(self.nights) is not tuple or not self.nights or any(
            not isinstance(value, NightRecord) for value in self.nights
        ):
            raise OscarCohortError("A normalized cohort requires immutable normalized nights.")
        if type(self.session_time_evidence) is not tuple or any(
            not isinstance(value, OscarSessionTimeEvidence)
            for value in self.session_time_evidence
        ):
            raise OscarCohortError("A normalized cohort requires immutable session time evidence.")
        _positive_integer(self.profile_database_id, "cohort profile identifier")
        _positive_integer(self.machine_database_id, "cohort machine identifier")
        if (
            self.schema_version != SUPPORTED_CORRECTION_SCHEMA_VERSION
            or self.record_version != OSCAR_COHORT_RECORD_VERSION
        ):
            raise OscarCohortError("The normalized cohort has unsupported version metadata.")
        sessions = tuple(session for night in self.nights for session in night.sessions)
        evidence_by_session = {value.session_database_id: value for value in self.session_time_evidence}
        if (
            len(evidence_by_session) != len(self.session_time_evidence)
            or tuple(sorted(evidence_by_session))
            != self.selection.session_database_ids
        ):
            raise OscarCohortError("Session time evidence must cover the explicit selection exactly once.")
        normalized_session_ids = {_source_session_database_id(session.provenance) for session in sessions}
        if normalized_session_ids != set(self.selection.session_database_ids) or len(
            sessions
        ) != len(normalized_session_ids):
            raise OscarCohortError("Normalized sessions must cover the explicit selection exactly once.")
        for night in self.nights:
            for session in night.sessions:
                evidence = evidence_by_session[_source_session_database_id(session.provenance)]
                if (
                    evidence.local_date != night.local_date
                    or evidence.raw_start_ms != session.start_time_ms
                    or evidence.raw_end_ms != session.end_time_ms
                ):
                    raise OscarCohortError("Normalized sessions and their raw time evidence disagree.")
        sources = _text_tuple(self.source_record_ids, "normalized cohort sources")
        required_sources = {
            source
            for value in self.session_time_evidence
            for source in value.source_record_ids
        }
        required_sources.update(
            source for night in self.nights for source in _night_source_record_ids(night)
        )
        if not required_sources.issubset(sources):
            raise OscarCohortError("The normalized cohort does not retain every session source.")
        object.__setattr__(
            self,
            "nights",
            tuple(
                sorted(
                    self.nights,
                    key=lambda value: (value.local_date, value.record_id),
                )
            ),
        )
        object.__setattr__(
            self,
            "session_time_evidence",
            tuple(
                sorted(
                    self.session_time_evidence,
                    key=lambda value: value.session_database_id,
                )
            ),
        )
        object.__setattr__(self, "source_record_ids", tuple(sorted(sources)))


def extract_normalized_oscar_cohort(
    database_path: str | Path,
    selection: OscarCohortSelection,
    *,
    trusted_immutable_copy: bool = False,
) -> OscarNormalizedCohort:
    """Read exactly the selected sessions in one guarded transaction."""

    if not isinstance(selection, OscarCohortSelection):
        raise OscarCohortError("Cohort extraction requires an OscarCohortSelection.")
    with open_oscar_database(
        database_path,
        trusted_immutable_copy=trusted_immutable_copy,
    ) as connection:
        connection.row_factory = sqlite3.Row
        summaries = tuple(
            _extract_session_summary(connection, value)
            for value in selection.session_database_ids
        )
        _validate_common_source(summaries)
        single_session_nights = tuple(
            normalize_oscar_session(
                summary,
                _extract_session_events(connection, summary),
                _extract_flow_rate_signal(connection, summary),
                _extract_mask_pressure_signal(connection, summary),
                _extract_leak_signal(connection, summary),
            )
            for summary in summaries
        )
        correction_rows = _extract_time_corrections(connection, summaries[0].machine.database_id)
        time_evidence = tuple(
            _time_evidence(summary, night.local_date, correction_rows)
            for summary, night in zip(summaries, single_session_nights, strict=True)
        )

    nights = _group_nights(single_session_nights)
    sources = tuple(
        sorted(
            {
                *(source for value in time_evidence for source in value.source_record_ids),
                *(source for night in nights for source in _night_source_record_ids(night)),
            }
        )
    )
    identity = _canonical_json({
        "nights": [serialize_normalized_record(value) for value in nights],
        "selection": selection.session_database_ids,
        "time_evidence": [_time_evidence_identity(value) for value in time_evidence],
    })
    return OscarNormalizedCohort(
        record_id=f"oscar-cohort:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        selection=selection,
        nights=nights,
        session_time_evidence=time_evidence,
        profile_database_id=summaries[0].profile.database_id,
        machine_database_id=summaries[0].machine.database_id,
        schema_version=summaries[0].schema.version,
        source_record_ids=sources,
    )


def _validate_common_source(summaries: tuple[OscarSessionSummary, ...]) -> None:
    first = summaries[0]
    for value in summaries[1:]:
        if (
            value.schema.version != first.schema.version
            or value.profile.database_id != first.profile.database_id
            or value.machine.database_id != first.machine.database_id
        ):
            raise OscarCohortError(
                "All selected sessions must belong to one supported OSCAR schema, profile, and machine."
            )
        if (
            value.profile.timezone != first.profile.timezone
            or value.profile.day_split_time != first.profile.day_split_time
        ):
            raise OscarCohortError("All selected sessions must share one OSCAR local-day context.")


def _extract_time_corrections(
    connection: sqlite3.Connection,
    machine_database_id: int,
) -> tuple[OscarTimeCorrection, ...]:
    try:
        rows = connection.execute(
            """
            SELECT id, machine_id, date_from, date_to, type, offset_ms, c0_ms, c1, reason, applied_at, undone_at
            FROM device_time_corrections
            WHERE machine_id = ?
            ORDER BY date_from, COALESCE(date_to, '9999-12-31'), id
            """,
            (machine_database_id,),
        ).fetchall()
    except sqlite3.DatabaseError as error:
        raise OscarCohortError("The schema-17 device-time-correction evidence is unavailable.") from error
    return tuple(_time_correction_from_row(row) for row in rows)


def _time_correction_from_row(row: sqlite3.Row) -> OscarTimeCorrection:
    try:
        correction_type = OscarCorrectionType(row["type"])
    except ValueError as error:
        raise OscarCohortError("An OSCAR correction row has an unsupported type.") from error
    return OscarTimeCorrection(
        source_correction_id=_required_integer(row["id"], "correction row identifier"),
        machine_database_id=_required_integer(row["machine_id"], "correction machine identifier"),
        date_from=_required_text(row["date_from"], "correction start date"),
        date_to=_optional_string(row["date_to"], "correction end date"),
        correction_type=correction_type,
        offset_ms=_optional_integer(row["offset_ms"], "correction offset"),
        drift_intercept_ms=_optional_integer(row["c0_ms"], "correction drift intercept"),
        drift_slope_encoding=_optional_number(row["c1"], "correction drift slope"),
        reason=_optional_string(row["reason"], "correction reason"),
        applied_at=_required_text(row["applied_at"], "correction applied timestamp"),
        undone_at=_optional_string(row["undone_at"], "correction undone timestamp"),
    )


def _time_evidence(
    summary: OscarSessionSummary,
    local_date: str,
    corrections: tuple[OscarTimeCorrection, ...],
) -> OscarSessionTimeEvidence:
    observed = tuple(value for value in corrections if value.applies_to(local_date))
    active = tuple(value for value in observed if value.is_active)
    if any(value.correction_type is OscarCorrectionType.DRIFT for value in active):
        state = OscarCorrectionEvidenceState.UNSUPPORTED_DRIFT
        total_offset = corrected_start = corrected_end = None
    else:
        total_offset = sum(value.offset_ms for value in active if value.offset_ms is not None)
        state = (
            OscarCorrectionEvidenceState.SUPPORTED_CONSTANT
            if active
            else OscarCorrectionEvidenceState.CONFIRMED_NONE
        )
        corrected_start = summary.session.raw_start_ms + total_offset
        corrected_end = summary.session.raw_end_ms + total_offset
    sources = (
        f"schema_version.version:{summary.schema.version}",
        f"profiles.id:{summary.profile.database_id}",
        f"machines.id:{summary.machine.database_id}",
        f"sessions.id:{summary.session.database_id}",
        f"device_time_corrections.machine_id:{summary.machine.database_id}:queried",
        *(value.source_record_id for value in observed),
    )
    identity = _canonical_json({
        "corrected_end_ms": corrected_end,
        "corrected_start_ms": corrected_start,
        "local_date": local_date,
        "observed_correction_ids": [value.source_correction_id for value in observed],
        "raw_end_ms": summary.session.raw_end_ms,
        "raw_start_ms": summary.session.raw_start_ms,
        "session_database_id": summary.session.database_id,
        "state": state.value,
        "total_offset_ms": total_offset,
    })
    return OscarSessionTimeEvidence(
        record_id=f"oscar-session-time:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
        session_database_id=summary.session.database_id,
        profile_database_id=summary.profile.database_id,
        machine_database_id=summary.machine.database_id,
        local_date=local_date,
        raw_start_ms=summary.session.raw_start_ms,
        raw_end_ms=summary.session.raw_end_ms,
        state=state,
        observed_corrections=observed,
        total_offset_ms=total_offset,
        corrected_start_ms=corrected_start,
        corrected_end_ms=corrected_end,
        source_record_ids=sources,
        schema_version=summary.schema.version,
    )


def _group_nights(single_session_nights: tuple[NightRecord, ...]) -> tuple[NightRecord, ...]:
    grouped: dict[str, list[NightRecord]] = defaultdict(list)
    for night in single_session_nights:
        grouped[night.record_id].append(night)
    result = []
    for record_id, members in grouped.items():
        first = members[0]
        if any(
            (value.local_date, value.timezone, value.day_boundary_local_time)
            != (first.local_date, first.timezone, first.day_boundary_local_time)
            for value in members
        ):
            raise OscarCohortError("Sessions with one normalized night identifier have conflicting local-day context.")
        sessions = tuple(
            sorted(
                (session for value in members for session in value.sessions),
                key=lambda value: (value.start_time_ms, value.record_id),
            )
        )
        provenances = tuple(value.provenance for value in members)
        source_references = tuple(
            {reference for value in provenances for reference in value.source_references}
        )
        parent_ids = tuple(
            {
                identifier
                for value in provenances
                for identifier in value.parent_provenance_ids
            }
        )
        source_classes = tuple(
            {
                source_class
                for value in provenances
                for source_class in value.source_classes
            }
        )
        raw_starts = [session.start_time_ms for session in sessions]
        provenance = ProvenanceRecord(
            record_id=f"provenance:{record_id}",
            source_classes=source_classes,
            source_system=first.provenance.source_system,
            source_references=source_references,
            source_system_version=first.provenance.source_system_version,
            source_schema_version=first.provenance.source_schema_version,
            producer=first.provenance.producer,
            producer_version=first.provenance.producer_version,
            parent_provenance_ids=parent_ids,
            source_values=(
                _provenance_value("night.day_boundary_local_time", first.day_boundary_local_time),
                _provenance_value("night.local_date", first.local_date),
                _provenance_value(
                    "night.local_date_derivation",
                    "each selected raw session start converted to the profile timezone and assigned before the configured day boundary to the prior local date",
                ),
                _provenance_value("night.selected_session_count", len(sessions)),
                _provenance_value("night.selected_session_record_ids", [value.record_id for value in sessions]),
                _provenance_value("night.source_raw_start_ms", raw_starts),
                _provenance_value("night.timezone", first.timezone),
            ),
        )
        result.append(
            NightRecord(
                record_id=record_id,
                local_date=first.local_date,
                timezone=first.timezone,
                day_boundary_local_time=first.day_boundary_local_time,
                sessions=sessions,
                provenance=provenance,
            )
        )
    return tuple(sorted(result, key=lambda value: (value.local_date, value.record_id)))


def _source_session_database_id(provenance: ProvenanceRecord) -> int:
    values = [
        value.source_record_id
        for value in provenance.source_references
        if value.source_record_type == "sessions.id"
    ]
    if len(values) != 1:
        raise OscarCohortError("A normalized session must retain exactly one OSCAR sessions.id reference.")
    try:
        identifier = int(values[0])
    except ValueError as error:
        raise OscarCohortError("A normalized session has a malformed OSCAR sessions.id reference.") from error
    _positive_integer(identifier, "normalized source session identifier")
    return identifier


def _night_source_record_ids(night: NightRecord) -> tuple[str, ...]:
    provenances = [night.provenance]
    for session in night.sessions:
        provenances.append(session.provenance)
        provenances.extend(setting.provenance for setting in session.settings)
        provenances.extend(event.provenance for event in session.events)
        for signal in session.signals:
            provenances.append(signal.provenance)
            provenances.extend(segment.provenance for segment in signal.segments)
    return tuple(
        sorted(
            {
                f"{reference.source_record_type}:{reference.source_record_id}"
                for provenance in provenances
                for reference in provenance.source_references
            }
        )
    )


def _time_evidence_identity(value: OscarSessionTimeEvidence) -> dict[str, object]:
    return {
        "corrected_end_ms": value.corrected_end_ms,
        "corrected_start_ms": value.corrected_start_ms,
        "local_date": value.local_date,
        "observed_corrections": [
            {
                "applied_at": row.applied_at,
                "c0_ms": row.drift_intercept_ms,
                "c1": row.drift_slope_encoding,
                "date_from": row.date_from,
                "date_to": row.date_to,
                "id": row.source_correction_id,
                "machine_id": row.machine_database_id,
                "offset_ms": row.offset_ms,
                "reason": row.reason,
                "type": row.correction_type.value,
                "undone_at": row.undone_at,
            }
            for row in value.observed_corrections
        ],
        "raw_end_ms": value.raw_end_ms,
        "raw_start_ms": value.raw_start_ms,
        "record_id": value.record_id,
        "session_database_id": value.session_database_id,
        "source_record_ids": value.source_record_ids,
        "state": value.state.value,
        "total_offset_ms": value.total_offset_ms,
    }


def _provenance_value(name: str, value: object) -> ProvenanceValue:
    return ProvenanceValue(name, _canonical_json(value))


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise OscarCohortError(f"{label.capitalize()} must be nonempty text.")
    return value


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _text(value, label)


def _required_text(value: object, label: str) -> str:
    return _text(value, label)


def _optional_string(value: object, label: str) -> str | None:
    return _optional_text(value, label)


def _positive_integer(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise OscarCohortError(f"{label.capitalize()} must be a positive integer.")
    return value


def _required_integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise OscarCohortError(f"{label.capitalize()} must be an integer.")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    if value is None:
        return None
    return _required_integer(value, label)


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _optional_number(value: object, label: str) -> float | None:
    if value is None:
        return None
    if not _finite_number(value):
        raise OscarCohortError(f"{label.capitalize()} must be finite numeric evidence.")
    return float(value)


def _iso_date(value: object, label: str) -> date:
    text = _text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise OscarCohortError(f"{label.capitalize()} must be an ISO date.") from error
    if parsed.isoformat() != text:
        raise OscarCohortError(f"{label.capitalize()} must use canonical YYYY-MM-DD form.")
    return parsed


def _optional_iso_date(value: object, label: str) -> date | None:
    if value is None:
        return None
    return _iso_date(value, label)


def _text_tuple(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or not values or any(type(value) is not str or not value.strip() for value in values):
        raise OscarCohortError(f"{label.capitalize()} must be a nonempty tuple of text values.")
    if len(set(values)) != len(values):
        raise OscarCohortError(f"{label.capitalize()} must be unique.")
    return values
