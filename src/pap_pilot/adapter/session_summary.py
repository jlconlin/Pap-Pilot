"""Extract one raw OSCAR session summary with source provenance."""

from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3
from typing import Final

from pap_pilot.adapter.oscar import OscarDatabaseError, open_oscar_database


REQUIRED_SETTING_CODES: Final[tuple[str, ...]] = (
    "PAPMode",
    "RMS9_Mode",
    "EPAP",
    "PSMin",
    "PSMax",
    "IPAPHi",
)

_PROFILE_PREFERENCES: Final[dict[str, str]] = {
    "TimeZone": "string",
    "DaySplitTime": "time",
    "LockSummarySessions": "bool",
}


class SessionSummaryError(OscarDatabaseError):
    """Base class for a session that cannot be summarized safely."""


class SessionNotFoundError(SessionSummaryError):
    """Raised when the selected OSCAR session does not exist."""


class InvalidSessionSummaryError(SessionSummaryError):
    """Raised when required provenance or settings are invalid or missing."""


@dataclass(frozen=True, slots=True)
class OscarSchemaProvenance:
    """OSCAR database schema identity for this extraction."""

    version: int
    applied_at: str | None


@dataclass(frozen=True, slots=True)
class OscarProfileProvenance:
    """Profile identity and local session-calendar context."""

    database_id: int
    name: str
    status: str
    timezone: str
    day_split_time: str
    lock_summary_sessions_raw: str


@dataclass(frozen=True, slots=True)
class OscarMachineProvenance:
    """OSCAR and loader identities for the source PAP machine."""

    database_id: int
    source_id: int
    loader_name: str
    machine_type_code: int
    brand: str | None
    model: str | None
    series: str | None
    model_number: str | None
    serial_number: str | None
    loader_data_version: int
    last_imported_at: str | None
    purge_cutoff_date: str | None


@dataclass(frozen=True, slots=True)
class OscarSessionBoundaries:
    """Raw OSCAR session identity, boundaries, and completeness flags."""

    database_id: int
    source_id: int
    machine_database_id: int
    raw_start_ms: int
    raw_end_ms: int
    raw_duration_ms: int
    enabled: bool
    summary_only: bool
    no_settings: bool
    events_loaded: bool


@dataclass(frozen=True, slots=True)
class OscarSettingSource:
    """Profile-scoped channel provenance for one extracted setting."""

    channel_code: str
    source_channel_id: int


@dataclass(frozen=True, slots=True)
class OscarSessionSettings:
    """The six fixed-EPAP ASV settings required by the first experiment."""

    therapy_mode_code: int
    loader_mode_code: int
    epap_cm_h2o: float
    ps_min_cm_h2o: float
    ps_max_cm_h2o: float
    max_ipap_cm_h2o: float
    sources: tuple[OscarSettingSource, ...]


@dataclass(frozen=True, slots=True)
class OscarSessionSummary:
    """One raw OSCAR session and the provenance needed to interpret it."""

    schema: OscarSchemaProvenance
    profile: OscarProfileProvenance
    machine: OscarMachineProvenance
    session: OscarSessionBoundaries
    settings: OscarSessionSettings


def extract_session_summary(
    database_path: str | Path,
    session_database_id: int,
    *,
    trusted_immutable_copy: bool = False,
) -> OscarSessionSummary:
    """Extract exactly one selected session from a guarded OSCAR database."""

    if type(session_database_id) is not int:
        raise InvalidSessionSummaryError(
            "The selected session database identifier must be an integer."
        )

    with open_oscar_database(
        database_path,
        trusted_immutable_copy=trusted_immutable_copy,
    ) as connection:
        connection.row_factory = sqlite3.Row
        return _extract_session_summary(connection, session_database_id)


def _extract_session_summary(
    connection: sqlite3.Connection,
    session_database_id: int,
) -> OscarSessionSummary:
    schema = _extract_schema_provenance(connection)
    source_row = _extract_source_row(connection, session_database_id)
    profile = _extract_profile_provenance(
        connection,
        source_row,
    )
    machine = _extract_machine_provenance(source_row)
    session = _extract_session_boundaries(source_row)
    settings = _extract_session_settings(
        connection,
        session_database_id=session.database_id,
        profile_database_id=profile.database_id,
    )
    return OscarSessionSummary(
        schema=schema,
        profile=profile,
        machine=machine,
        session=session,
        settings=settings,
    )


def _extract_schema_provenance(
    connection: sqlite3.Connection,
) -> OscarSchemaProvenance:
    row = connection.execute(
        """
        SELECT version, applied_at
        FROM schema_version
        ORDER BY version DESC, applied_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise InvalidSessionSummaryError(
            "The supported OSCAR schema provenance row is missing."
        )
    return OscarSchemaProvenance(
        version=_required_integer(row["version"], "schema version"),
        applied_at=_optional_text(row["applied_at"], "schema applied_at"),
    )


def _extract_source_row(
    connection: sqlite3.Connection,
    session_database_id: int,
) -> sqlite3.Row:
    rows = connection.execute(
        """
        SELECT
            p.id AS profile_database_id,
            p.username AS profile_name,
            p.status AS profile_status,
            ui.timezone AS profile_timezone,
            m.id AS machine_database_id,
            m.profile_id AS machine_profile_database_id,
            m.machine_id AS machine_source_id,
            m.loader_name,
            m.machine_type AS machine_type_code,
            m.brand,
            m.model,
            m.series,
            m.model_number,
            m.serial_number,
            m.data_version AS loader_data_version,
            m.last_imported AS last_imported_at,
            m.purge_date AS purge_cutoff_date,
            s.id AS session_database_id,
            s.session_id AS session_source_id,
            s.machine_id AS session_machine_database_id,
            s.start_time AS raw_start_ms,
            s.end_time AS raw_end_ms,
            s.duration AS raw_duration_ms,
            s.enabled,
            s.summary_only,
            s.no_settings,
            s.events_loaded
        FROM sessions AS s
        JOIN machines AS m ON m.id = s.machine_id
        JOIN profiles AS p ON p.id = m.profile_id
        LEFT JOIN user_info AS ui ON ui.profile_id = p.id
        WHERE s.id = ?
        """,
        (session_database_id,),
    ).fetchall()

    if not rows:
        raise SessionNotFoundError("The selected OSCAR session was not found.")
    if len(rows) != 1:
        raise InvalidSessionSummaryError(
            "The selected OSCAR session has ambiguous profile provenance."
        )
    return rows[0]


def _extract_profile_provenance(
    connection: sqlite3.Connection,
    source_row: sqlite3.Row,
) -> OscarProfileProvenance:
    profile_database_id = _required_integer(
        source_row["profile_database_id"],
        "profile database identifier",
    )
    if source_row["profile_status"] != "active":
        raise InvalidSessionSummaryError(
            "The selected session does not belong to an active profile."
        )

    preference_rows = connection.execute(
        """
        SELECT key, value, data_type
        FROM profile_preferences
        WHERE profile_id = ?
          AND category = 'profile'
          AND key IN ('TimeZone', 'DaySplitTime', 'LockSummarySessions')
        """,
        (profile_database_id,),
    ).fetchall()
    preferences: dict[str, str] = {}
    for row in preference_rows:
        key = _required_text(row["key"], "profile preference key")
        if key in preferences:
            raise InvalidSessionSummaryError(
                "A required profile preference has duplicate rows."
            )
        if row["data_type"] != _PROFILE_PREFERENCES[key]:
            raise InvalidSessionSummaryError(
                "A required profile preference has an unexpected data type."
            )
        preferences[key] = _required_text(
            row["value"],
            "profile preference value",
        )

    if set(preferences) != set(_PROFILE_PREFERENCES):
        raise InvalidSessionSummaryError(
            "The selected profile is missing required session-calendar context."
        )

    profile_timezone = _required_text(
        source_row["profile_timezone"],
        "profile timezone",
    )
    if profile_timezone != preferences["TimeZone"]:
        raise InvalidSessionSummaryError(
            "The selected profile has conflicting timezone values."
        )

    return OscarProfileProvenance(
        database_id=profile_database_id,
        name=_required_text(source_row["profile_name"], "profile name"),
        status="active",
        timezone=profile_timezone,
        day_split_time=preferences["DaySplitTime"],
        lock_summary_sessions_raw=preferences["LockSummarySessions"],
    )


def _extract_machine_provenance(
    source_row: sqlite3.Row,
) -> OscarMachineProvenance:
    profile_database_id = _required_integer(
        source_row["profile_database_id"],
        "profile database identifier",
    )
    machine_profile_database_id = _required_integer(
        source_row["machine_profile_database_id"],
        "machine profile identifier",
    )
    if machine_profile_database_id != profile_database_id:
        raise InvalidSessionSummaryError(
            "The machine and profile provenance do not agree."
        )

    return OscarMachineProvenance(
        database_id=_required_integer(
            source_row["machine_database_id"],
            "machine database identifier",
        ),
        source_id=_required_integer(
            source_row["machine_source_id"],
            "machine source identifier",
        ),
        loader_name=_required_text(source_row["loader_name"], "loader name"),
        machine_type_code=_required_integer(
            source_row["machine_type_code"],
            "machine type code",
        ),
        brand=_optional_text(source_row["brand"], "machine brand"),
        model=_optional_text(source_row["model"], "machine model"),
        series=_optional_text(source_row["series"], "machine series"),
        model_number=_optional_text(
            source_row["model_number"],
            "machine model number",
        ),
        serial_number=_optional_text(
            source_row["serial_number"],
            "machine serial number",
        ),
        loader_data_version=_required_integer(
            source_row["loader_data_version"],
            "loader data version",
        ),
        last_imported_at=_optional_text(
            source_row["last_imported_at"],
            "machine last-imported timestamp",
        ),
        purge_cutoff_date=_optional_text(
            source_row["purge_cutoff_date"],
            "machine purge cutoff date",
        ),
    )


def _extract_session_boundaries(
    source_row: sqlite3.Row,
) -> OscarSessionBoundaries:
    machine_database_id = _required_integer(
        source_row["machine_database_id"],
        "machine database identifier",
    )
    session_machine_database_id = _required_integer(
        source_row["session_machine_database_id"],
        "session machine identifier",
    )
    if session_machine_database_id != machine_database_id:
        raise InvalidSessionSummaryError(
            "The session and machine provenance do not agree."
        )

    raw_start_ms = _required_integer(source_row["raw_start_ms"], "start time")
    raw_end_ms = _required_integer(source_row["raw_end_ms"], "end time")
    raw_duration_ms = _required_integer(
        source_row["raw_duration_ms"],
        "duration",
    )
    enabled = _required_boolean(source_row["enabled"], "enabled")
    summary_only = _required_boolean(
        source_row["summary_only"],
        "summary_only",
    )
    no_settings = _required_boolean(
        source_row["no_settings"],
        "no_settings",
    )
    events_loaded = _required_boolean(
        source_row["events_loaded"],
        "events_loaded",
    )

    if (
        not enabled
        or summary_only
        or no_settings
        or raw_end_ms <= raw_start_ms
        or raw_duration_ms <= 0
        or raw_duration_ms != raw_end_ms - raw_start_ms
    ):
        raise InvalidSessionSummaryError(
            "The selected OSCAR session is not a usable settings session."
        )

    return OscarSessionBoundaries(
        database_id=_required_integer(
            source_row["session_database_id"],
            "session database identifier",
        ),
        source_id=_required_integer(
            source_row["session_source_id"],
            "session source identifier",
        ),
        machine_database_id=machine_database_id,
        raw_start_ms=raw_start_ms,
        raw_end_ms=raw_end_ms,
        raw_duration_ms=raw_duration_ms,
        enabled=enabled,
        summary_only=summary_only,
        no_settings=no_settings,
        events_loaded=events_loaded,
    )


def _extract_session_settings(
    connection: sqlite3.Connection,
    *,
    session_database_id: int,
    profile_database_id: int,
) -> OscarSessionSettings:
    placeholders = ", ".join("?" for _ in REQUIRED_SETTING_CODES)
    rows = connection.execute(
        f"""
        SELECT
            ss.profile_id,
            ss.channel_id,
            c.channel_code,
            ss.value,
            ss.data_type,
            ss.json_value
        FROM session_settings AS ss
        JOIN channels AS c
          ON c.profile_id = ss.profile_id
         AND c.channel_id = ss.channel_id
        WHERE ss.session_id = ?
          AND c.channel_code IN ({placeholders})
        """,
        (session_database_id, *REQUIRED_SETTING_CODES),
    ).fetchall()

    values: dict[str, float] = {}
    source_channel_ids: dict[str, int] = {}
    for row in rows:
        channel_code = _required_text(row["channel_code"], "channel code")
        if channel_code in values:
            raise InvalidSessionSummaryError(
                "A required session setting has duplicate rows."
            )
        if (
            _required_integer(row["profile_id"], "setting profile identifier")
            != profile_database_id
        ):
            raise InvalidSessionSummaryError(
                "A session setting has conflicting profile provenance."
            )
        if row["data_type"] != "numeric" or row["json_value"] is not None:
            raise InvalidSessionSummaryError(
                "A required session setting has an unsupported encoding."
            )
        values[channel_code] = _required_number(
            row["value"],
            "setting value",
        )
        source_channel_ids[channel_code] = _required_integer(
            row["channel_id"],
            "setting channel identifier",
        )

    if set(values) != set(REQUIRED_SETTING_CODES):
        raise InvalidSessionSummaryError(
            "The selected session is missing one or more required ASV settings."
        )

    therapy_mode_code = _required_integral_setting(
        values["PAPMode"],
        expected=6,
    )
    loader_mode_code = _required_integral_setting(
        values["RMS9_Mode"],
        expected=7,
    )
    epap = values["EPAP"]
    ps_min = values["PSMin"]
    ps_max = values["PSMax"]
    max_ipap = values["IPAPHi"]
    if ps_min > ps_max or not math.isclose(
        epap + ps_max,
        max_ipap,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise InvalidSessionSummaryError(
            "The selected session has inconsistent ASV pressure settings."
        )

    sources = tuple(
        OscarSettingSource(
            channel_code=channel_code,
            source_channel_id=source_channel_ids[channel_code],
        )
        for channel_code in REQUIRED_SETTING_CODES
    )
    return OscarSessionSettings(
        therapy_mode_code=therapy_mode_code,
        loader_mode_code=loader_mode_code,
        epap_cm_h2o=epap,
        ps_min_cm_h2o=ps_min,
        ps_max_cm_h2o=ps_max,
        max_ipap_cm_h2o=max_ipap,
        sources=sources,
    )


def _required_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise InvalidSessionSummaryError(
            f"The OSCAR {field_name} is not an integer."
        )
    return value


def _required_boolean(value: object, field_name: str) -> bool:
    integer = _required_integer(value, field_name)
    if integer not in (0, 1):
        raise InvalidSessionSummaryError(
            f"The OSCAR {field_name} flag is not encoded as 0 or 1."
        )
    return bool(integer)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidSessionSummaryError(
            f"The OSCAR {field_name} is missing or is not text."
        )
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidSessionSummaryError(
            f"The OSCAR {field_name} is not text."
        )
    return value


def _required_number(value: object, field_name: str) -> float:
    if type(value) not in (int, float):
        raise InvalidSessionSummaryError(
            f"The OSCAR {field_name} is not numeric."
        )
    number = float(value)
    if not math.isfinite(number):
        raise InvalidSessionSummaryError(
            f"The OSCAR {field_name} is not finite."
        )
    return number


def _required_integral_setting(value: float, *, expected: int) -> int:
    if not value.is_integer() or int(value) != expected:
        raise InvalidSessionSummaryError(
            "The selected session is not supported fixed-EPAP ASV therapy."
        )
    return int(value)
