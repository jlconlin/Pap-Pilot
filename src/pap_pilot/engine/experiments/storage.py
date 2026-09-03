"""Local append-only SQLite persistence for version-1 experiment records."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from enum import StrEnum
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Final

from pap_pilot.engine.experiments.journal import ConfounderKind, ConfounderReportStatus, SleepJournalConfounder, SleepJournalEntry, SleepJournalModelError
from pap_pilot.engine.experiments.model import (
    EvaluationIssuedPayload,
    EvaluationSupersededPayload,
    ExperimentActionPayload,
    ExperimentDecisionPayload,
    ExperimentEvent,
    ExperimentEventType,
    ExperimentEvidenceInterval,
    ExperimentModelError,
    ExperimentProposal,
    ExperimentProposedPayload,
    ExperimentRecord,
    ExperimentRevisedPayload,
    ExperimentSetting,
    ExperimentSettingChange,
    HypothesisDraftedPayload,
    ObservationRecordedPayload,
    ProblemRecordedPayload,
    SettingChangeConfirmedPayload,
    SleepJournalEntryRecordedPayload,
    append_experiment_event,
    validate_experiment_history,
)
from pap_pilot.engine.model import SourceClass


LOCAL_EXPERIMENT_DATABASE_FILENAME: Final = "pap_pilot.sqlite3"
EXPERIMENT_STORE_SCHEMA_ID: Final = "pap-pilot.experiment-store"
EXPERIMENT_STORE_SCHEMA_VERSION: Final = 2
EXPERIMENT_STORE_RECORD_FORMAT: Final = "pap-pilot.experiment-store-record"
EXPERIMENT_STORE_RECORD_FORMAT_VERSION: Final = 1

_TABLES_V1: Final = frozenset({"pap_pilot_metadata", "experiments", "experiment_events"})
_TABLES: Final = frozenset({*_TABLES_V1, "sleep_journal_entries"})
_TRIGGERS_V1: Final = frozenset({"experiments_no_update", "experiments_no_delete", "experiments_no_replace", "experiment_events_no_update", "experiment_events_no_delete", "experiment_events_no_replace"})
_TRIGGERS: Final = frozenset(
    {
        *_TRIGGERS_V1,
        "sleep_journal_entries_no_update",
        "sleep_journal_entries_no_delete",
        "sleep_journal_entries_no_replace",
    }
)
_METADATA: Final = {
    "schema_id": EXPERIMENT_STORE_SCHEMA_ID,
    "schema_version": str(EXPERIMENT_STORE_SCHEMA_VERSION),
}


class ExperimentStoreError(RuntimeError):
    """Raised when the local experiment store cannot operate safely."""


class ExperimentNotFoundError(ExperimentStoreError):
    """Raised when a requested experiment identity is absent."""


@dataclass(frozen=True, slots=True)
class ReplayedExperiment:
    """Generic replay result retaining history and correction-resolved events."""

    experiment: ExperimentRecord
    history: tuple[ExperimentEvent, ...]
    effective_events: tuple[ExperimentEvent, ...]
    corrected_event_ids: tuple[str, ...]
    journal_history: tuple[SleepJournalEntry, ...] = ()
    effective_journal_entries: tuple[SleepJournalEntry, ...] = ()

    def __post_init__(self) -> None:
        validate_experiment_history(self.experiment, self.history)
        if type(self.effective_events) is not tuple or any(not isinstance(value, ExperimentEvent) for value in self.effective_events):
            raise ExperimentStoreError("Effective experiment events must be an immutable event tuple.")
        if type(self.corrected_event_ids) is not tuple or any(type(value) is not str or not value for value in self.corrected_event_ids):
            raise ExperimentStoreError("Corrected experiment-event identifiers must be an immutable text tuple.")
        corrected = tuple(event.correction_of_event_id for event in self.history if event.correction_of_event_id is not None)
        expected_effective = tuple(event for event in self.history if event.record_id not in set(corrected))
        if self.corrected_event_ids != corrected or self.effective_events != expected_effective:
            raise ExperimentStoreError("The replay projection does not match the preserved correction history.")
        journal_ids = tuple(event.payload.journal_entry_record_id for event in self.history if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED)
        effective_ids = tuple(event.payload.journal_entry_record_id for event in self.effective_events if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED)
        if tuple(value.record_id for value in self.journal_history) != journal_ids or tuple(value.record_id for value in self.effective_journal_entries) != effective_ids:
            raise ExperimentStoreError("Replayed journal entries do not match their append-only experiment events.")

    def events(self, event_type: ExperimentEventType, *, effective_only: bool = True) -> tuple[ExperimentEvent, ...]:
        """Return events of one type in ledger order."""

        if not isinstance(event_type, ExperimentEventType):
            raise ExperimentStoreError("A replay query requires a supported experiment event type.")
        source = self.effective_events if effective_only else self.history
        return tuple(event for event in source if event.event_type is event_type)

    def latest_event(self, event_type: ExperimentEventType, *, effective_only: bool = True) -> ExperimentEvent | None:
        """Return the latest event of one type without applying lifecycle rules."""

        matching = self.events(event_type, effective_only=effective_only)
        return matching[-1] if matching else None


class ExperimentStore:
    """A local SQLite store with creation, append, read, and replay operations only."""

    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path).expanduser()
        if path.name != LOCAL_EXPERIMENT_DATABASE_FILENAME:
            raise ExperimentStoreError(f"The experiment store filename must be {LOCAL_EXPERIMENT_DATABASE_FILENAME!r}.")
        self.database_path = path.resolve()
        if not self.database_path.parent.is_dir():
            raise ExperimentStoreError("The experiment store parent directory does not exist.")
        try:
            self._connection: sqlite3.Connection | None = sqlite3.connect(self.database_path, isolation_level=None)
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA recursive_triggers = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._prepare_schema()
        except (sqlite3.Error, OSError, ExperimentStoreError) as error:
            connection = getattr(self, "_connection", None)
            if connection is not None:
                connection.close()
            self._connection = None
            if isinstance(error, ExperimentStoreError):
                raise
            raise ExperimentStoreError("Unable to open the local experiment store safely.") from error

    def __enter__(self) -> "ExperimentStore":
        self._require_connection()
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the local database connection; repeated calls are harmless."""

        connection = self._connection
        if connection is not None:
            connection.close()
            self._connection = None

    def create_experiment(self, experiment: ExperimentRecord) -> None:
        """Insert one new immutable experiment identity."""

        if not isinstance(experiment, ExperimentRecord):
            raise ExperimentStoreError("Only an ExperimentRecord can be created in the experiment store.")
        serialized = _serialize_record(experiment)
        connection = self._require_connection()
        try:
            with _transaction(connection, immediate=True):
                connection.execute(
                    "INSERT INTO experiments (record_id, created_at_ms, record_json) VALUES (?, ?, ?)",
                    (experiment.record_id, experiment.created_at_ms, serialized),
                )
        except (sqlite3.Error, OverflowError) as error:
            raise ExperimentStoreError("The experiment identity already exists or could not be appended safely.") from error

    def get_experiment(self, experiment_record_id: str) -> ExperimentRecord:
        """Read one stored experiment identity."""

        _store_text(experiment_record_id, "experiment identifier")
        connection = self._require_connection()
        with _transaction(connection):
            return self._load_experiment(connection, experiment_record_id)

    def append_event(self, event: ExperimentEvent) -> None:
        """Atomically validate and append one event to its experiment history."""

        if not isinstance(event, ExperimentEvent):
            raise ExperimentStoreError("Only an ExperimentEvent can be appended to the experiment store.")
        if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED:
            raise ExperimentStoreError("A sleep-journal event must be appended atomically with its journal entry.")
        serialized = _serialize_record(event)
        connection = self._require_connection()
        try:
            with _transaction(connection, immediate=True):
                experiment = self._load_experiment(connection, event.experiment_record_id)
                history = self._load_history(connection, experiment)
                append_experiment_event(experiment, history, event)
                self._insert_event(connection, event, serialized)
        except (sqlite3.Error, OverflowError, ExperimentModelError) as error:
            raise ExperimentStoreError("The experiment event could not be appended without changing prior history.") from error

    def append_journal_entry(self, event: ExperimentEvent, entry: SleepJournalEntry) -> None:
        """Atomically append one journal entry and its referencing experiment event."""

        if not isinstance(event, ExperimentEvent) or event.event_type is not ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED or not isinstance(event.payload, SleepJournalEntryRecordedPayload):
            raise ExperimentStoreError("Journal persistence requires a sleep-journal-entry-recorded event.")
        if not isinstance(entry, SleepJournalEntry) or (event.payload.journal_entry_record_id, event.payload.night_record_id) != (entry.record_id, entry.night_record_id):
            raise ExperimentStoreError("The journal event must reference the exact journal entry and therapy night.")
        event_json = _serialize_record(event)
        entry_json = _serialize_record(entry)
        connection = self._require_connection()
        try:
            with _transaction(connection, immediate=True):
                experiment = self._load_experiment(connection, event.experiment_record_id)
                append_experiment_event(experiment, self._load_history(connection, experiment), event)
                connection.execute("INSERT INTO sleep_journal_entries (record_id, night_record_id, reported_at_ms, reported_by, record_json) VALUES (?, ?, ?, ?, ?)", (entry.record_id, entry.night_record_id, entry.reported_at_ms, entry.reported_by, entry_json))
                self._insert_event(connection, event, event_json)
        except (sqlite3.Error, OverflowError, ExperimentModelError, SleepJournalModelError) as error:
            raise ExperimentStoreError("The journal entry and event could not be appended atomically.") from error

    def read_history(self, experiment_record_id: str) -> tuple[ExperimentEvent, ...]:
        """Read and validate the complete event history in sequence order."""

        _store_text(experiment_record_id, "experiment identifier")
        connection = self._require_connection()
        with _transaction(connection):
            experiment = self._load_experiment(connection, experiment_record_id)
            return self._load_history(connection, experiment)

    def replay(self, experiment_record_id: str) -> ReplayedExperiment:
        """Reconstruct generic effective state while retaining every stored event."""

        _store_text(experiment_record_id, "experiment identifier")
        connection = self._require_connection()
        with _transaction(connection):
            experiment = self._load_experiment(connection, experiment_record_id)
            history = self._load_history(connection, experiment)
            journal_by_id = self._load_journal_entries(connection, history)
        corrected = tuple(event.correction_of_event_id for event in history if event.correction_of_event_id is not None)
        corrected_set = set(corrected)
        effective = tuple(event for event in history if event.record_id not in corrected_set)
        journal_history = tuple(journal_by_id[event.payload.journal_entry_record_id] for event in history if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED)
        effective_journal = tuple(journal_by_id[event.payload.journal_entry_record_id] for event in effective if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED)
        return ReplayedExperiment(experiment, history, effective, corrected, journal_history, effective_journal)

    def _prepare_schema(self) -> None:
        connection = self._require_connection()
        existing_tables = _object_names(connection, "table")
        if not existing_tables:
            self._create_schema(connection)
        else:
            self._validate_or_migrate_schema(connection)

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        statements = (
            "CREATE TABLE pap_pilot_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID",
            "CREATE TABLE experiments (record_id TEXT PRIMARY KEY, created_at_ms INTEGER NOT NULL, record_json TEXT NOT NULL)",
            "CREATE TABLE experiment_events (record_id TEXT PRIMARY KEY, experiment_record_id TEXT NOT NULL REFERENCES experiments(record_id) ON DELETE RESTRICT, sequence_number INTEGER NOT NULL CHECK(sequence_number > 0), event_type TEXT NOT NULL, recorded_at_ms INTEGER NOT NULL, correction_of_event_id TEXT REFERENCES experiment_events(record_id) ON DELETE RESTRICT, record_json TEXT NOT NULL, UNIQUE(experiment_record_id, sequence_number))",
            "CREATE TABLE sleep_journal_entries (record_id TEXT PRIMARY KEY, night_record_id TEXT NOT NULL, reported_at_ms INTEGER NOT NULL, reported_by TEXT NOT NULL, record_json TEXT NOT NULL)",
            "CREATE TRIGGER experiments_no_update BEFORE UPDATE ON experiments BEGIN SELECT RAISE(ABORT, 'experiment records are append-only'); END",
            "CREATE TRIGGER experiments_no_delete BEFORE DELETE ON experiments BEGIN SELECT RAISE(ABORT, 'experiment records are append-only'); END",
            "CREATE TRIGGER experiments_no_replace BEFORE INSERT ON experiments WHEN EXISTS (SELECT 1 FROM experiments WHERE record_id = NEW.record_id) BEGIN SELECT RAISE(ABORT, 'experiment records are append-only'); END",
            "CREATE TRIGGER experiment_events_no_update BEFORE UPDATE ON experiment_events BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END",
            "CREATE TRIGGER experiment_events_no_delete BEFORE DELETE ON experiment_events BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END",
            "CREATE TRIGGER experiment_events_no_replace BEFORE INSERT ON experiment_events WHEN EXISTS (SELECT 1 FROM experiment_events WHERE record_id = NEW.record_id OR (experiment_record_id = NEW.experiment_record_id AND sequence_number = NEW.sequence_number)) BEGIN SELECT RAISE(ABORT, 'experiment events are append-only'); END",
            "CREATE TRIGGER sleep_journal_entries_no_update BEFORE UPDATE ON sleep_journal_entries BEGIN SELECT RAISE(ABORT, 'sleep journal entries are append-only'); END",
            "CREATE TRIGGER sleep_journal_entries_no_delete BEFORE DELETE ON sleep_journal_entries BEGIN SELECT RAISE(ABORT, 'sleep journal entries are append-only'); END",
            "CREATE TRIGGER sleep_journal_entries_no_replace BEFORE INSERT ON sleep_journal_entries WHEN EXISTS (SELECT 1 FROM sleep_journal_entries WHERE record_id = NEW.record_id) BEGIN SELECT RAISE(ABORT, 'sleep journal entries are append-only'); END",
        )
        try:
            with _transaction(connection, immediate=True):
                for statement in statements:
                    connection.execute(statement)
                connection.executemany("INSERT INTO pap_pilot_metadata (key, value) VALUES (?, ?)", tuple(sorted(_METADATA.items())))
        except sqlite3.Error as error:
            raise ExperimentStoreError("Unable to initialize the experiment-store schema.") from error

    def _validate_or_migrate_schema(self, connection: sqlite3.Connection) -> None:
        tables = _object_names(connection, "table")
        metadata = dict(connection.execute("SELECT key, value FROM pap_pilot_metadata").fetchall()) if "pap_pilot_metadata" in tables else {}
        version_one_columns = {
            "pap_pilot_metadata": ("key", "value"),
            "experiments": ("record_id", "created_at_ms", "record_json"),
            "experiment_events": ("record_id", "experiment_record_id", "sequence_number", "event_type", "recorded_at_ms", "correction_of_event_id", "record_json"),
        }
        version_one_shape = tables == _TABLES_V1 and all(tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')) == expected for table, expected in version_one_columns.items())
        if version_one_shape and metadata == {"schema_id": EXPERIMENT_STORE_SCHEMA_ID, "schema_version": "1"} and _object_names(connection, "trigger") == _TRIGGERS_V1:
            try:
                with _transaction(connection, immediate=True):
                    connection.execute("CREATE TABLE sleep_journal_entries (record_id TEXT PRIMARY KEY, night_record_id TEXT NOT NULL, reported_at_ms INTEGER NOT NULL, reported_by TEXT NOT NULL, record_json TEXT NOT NULL)")
                    connection.execute("CREATE TRIGGER sleep_journal_entries_no_update BEFORE UPDATE ON sleep_journal_entries BEGIN SELECT RAISE(ABORT, 'sleep journal entries are append-only'); END")
                    connection.execute("CREATE TRIGGER sleep_journal_entries_no_delete BEFORE DELETE ON sleep_journal_entries BEGIN SELECT RAISE(ABORT, 'sleep journal entries are append-only'); END")
                    connection.execute("CREATE TRIGGER sleep_journal_entries_no_replace BEFORE INSERT ON sleep_journal_entries WHEN EXISTS (SELECT 1 FROM sleep_journal_entries WHERE record_id = NEW.record_id) BEGIN SELECT RAISE(ABORT, 'sleep journal entries are append-only'); END")
                    connection.execute("UPDATE pap_pilot_metadata SET value = ? WHERE key = 'schema_version'", (str(EXPERIMENT_STORE_SCHEMA_VERSION),))
            except sqlite3.Error as error:
                raise ExperimentStoreError("Unable to migrate the experiment store to journal schema version 2.") from error
        self._validate_schema(connection)

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        if _object_names(connection, "table") != _TABLES:
            raise ExperimentStoreError("The selected database is not an exact supported PAP Pilot experiment store.")
        metadata = dict(connection.execute("SELECT key, value FROM pap_pilot_metadata").fetchall())
        if metadata != _METADATA:
            raise ExperimentStoreError("The experiment-store schema identity or version is unsupported.")
        expected_columns = {
            "pap_pilot_metadata": ("key", "value"),
            "experiments": ("record_id", "created_at_ms", "record_json"),
            "experiment_events": ("record_id", "experiment_record_id", "sequence_number", "event_type", "recorded_at_ms", "correction_of_event_id", "record_json"),
            "sleep_journal_entries": ("record_id", "night_record_id", "reported_at_ms", "reported_by", "record_json"),
        }
        for table, expected in expected_columns.items():
            columns = tuple(row[1] for row in connection.execute(f'PRAGMA table_info("{table}")'))
            if columns != expected:
                raise ExperimentStoreError("The experiment-store table layout is unsupported.")
        if _object_names(connection, "trigger") != _TRIGGERS:
            raise ExperimentStoreError("The experiment store is missing an append-only protection trigger.")

    @staticmethod
    def _insert_event(connection: sqlite3.Connection, event: ExperimentEvent, serialized: str) -> None:
        connection.execute("INSERT INTO experiment_events (record_id, experiment_record_id, sequence_number, event_type, recorded_at_ms, correction_of_event_id, record_json) VALUES (?, ?, ?, ?, ?, ?, ?)", (event.record_id, event.experiment_record_id, event.sequence_number, event.event_type.value, event.recorded_at_ms, event.correction_of_event_id, serialized))

    def _load_journal_entries(self, connection: sqlite3.Connection, history: tuple[ExperimentEvent, ...]) -> dict[str, SleepJournalEntry]:
        identifiers = tuple(event.payload.journal_entry_record_id for event in history if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED)
        entries = {}
        for record_id in identifiers:
            row = connection.execute("SELECT record_id, night_record_id, reported_at_ms, reported_by, record_json FROM sleep_journal_entries WHERE record_id = ?", (record_id,)).fetchone()
            if row is None:
                raise ExperimentStoreError("A sleep-journal event references a missing journal entry.")
            record = _deserialize_record(row[4])
            if not isinstance(record, SleepJournalEntry) or (record.record_id, record.night_record_id, record.reported_at_ms, record.reported_by) != row[:4]:
                raise ExperimentStoreError("Stored journal columns do not match the canonical journal entry.")
            entries[record_id] = record
        return entries

    def _load_experiment(self, connection: sqlite3.Connection, record_id: str) -> ExperimentRecord:
        row = connection.execute("SELECT record_id, created_at_ms, record_json FROM experiments WHERE record_id = ?", (record_id,)).fetchone()
        if row is None:
            raise ExperimentNotFoundError("The requested experiment does not exist.")
        record = _deserialize_record(row[2])
        if not isinstance(record, ExperimentRecord) or (record.record_id, record.created_at_ms) != (row[0], row[1]):
            raise ExperimentStoreError("Stored experiment columns do not match the canonical experiment record.")
        return record

    def _load_history(self, connection: sqlite3.Connection, experiment: ExperimentRecord) -> tuple[ExperimentEvent, ...]:
        rows = connection.execute(
            "SELECT record_id, experiment_record_id, sequence_number, event_type, recorded_at_ms, correction_of_event_id, record_json FROM experiment_events WHERE experiment_record_id = ? ORDER BY sequence_number",
            (experiment.record_id,),
        ).fetchall()
        events = []
        for row in rows:
            record = _deserialize_record(row[6])
            indexed = (row[0], row[1], row[2], row[3], row[4], row[5])
            if not isinstance(record, ExperimentEvent) or (record.record_id, record.experiment_record_id, record.sequence_number, record.event_type.value, record.recorded_at_ms, record.correction_of_event_id) != indexed:
                raise ExperimentStoreError("Stored event columns do not match the canonical experiment event.")
            events.append(record)
        try:
            return validate_experiment_history(experiment, tuple(events))
        except ExperimentModelError as error:
            raise ExperimentStoreError("The stored experiment history is structurally invalid.") from error

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise ExperimentStoreError("The experiment store is closed.")
        return self._connection


@contextmanager
def _transaction(connection: sqlite3.Connection, *, immediate: bool = False) -> Iterator[None]:
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def _object_names(connection: sqlite3.Connection, object_type: str) -> frozenset[str]:
    rows = connection.execute("SELECT name FROM sqlite_schema WHERE type = ? AND name NOT LIKE 'sqlite_%'", (object_type,)).fetchall()
    return frozenset(row[0] for row in rows)


_RECORD_TYPES: Final = {
    "experiment": ExperimentRecord,
    "experiment_event": ExperimentEvent,
    "sleep_journal_entry": SleepJournalEntry,
    "sleep_journal_confounder": SleepJournalConfounder,
    "experiment_setting": ExperimentSetting,
    "experiment_setting_change": ExperimentSettingChange,
    "experiment_evidence_interval": ExperimentEvidenceInterval,
    "experiment_proposal": ExperimentProposal,
    "problem_recorded_payload": ProblemRecordedPayload,
    "hypothesis_drafted_payload": HypothesisDraftedPayload,
    "experiment_proposed_payload": ExperimentProposedPayload,
    "experiment_decision_payload": ExperimentDecisionPayload,
    "experiment_revised_payload": ExperimentRevisedPayload,
    "setting_change_confirmed_payload": SettingChangeConfirmedPayload,
    "sleep_journal_entry_recorded_payload": SleepJournalEntryRecordedPayload,
    "observation_recorded_payload": ObservationRecordedPayload,
    "experiment_action_payload": ExperimentActionPayload,
    "evaluation_issued_payload": EvaluationIssuedPayload,
    "evaluation_superseded_payload": EvaluationSupersededPayload,
}
_RECORD_NAMES: Final = {value: key for key, value in _RECORD_TYPES.items()}


def _serialize_record(record: ExperimentRecord | ExperimentEvent | SleepJournalEntry) -> str:
    if type(record) not in {ExperimentRecord, ExperimentEvent, SleepJournalEntry}:
        raise ExperimentStoreError("Only top-level experiment identities, events, and journal entries can be persisted.")
    payload = {
        "format": EXPERIMENT_STORE_RECORD_FORMAT,
        "format_version": EXPERIMENT_STORE_RECORD_FORMAT_VERSION,
        "record": _encode_record(record),
    }
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ExperimentStoreError("The experiment record cannot be serialized safely.") from error


def _encode_record(record: object) -> dict[str, Any]:
    record_type = _RECORD_NAMES.get(type(record))
    if record_type is None or not is_dataclass(record):
        raise ExperimentStoreError("An experiment record contains an unsupported nested value.")
    encoded = {"record_type": record_type}
    for field in fields(record):
        encoded[field.name] = _encode_value(getattr(record, field.name))
    return encoded


def _encode_value(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if type(value) in _RECORD_NAMES:
        return _encode_record(value)
    if type(value) is tuple:
        return [_encode_value(item) for item in value]
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ExperimentStoreError("An experiment record contains a non-JSON or non-finite value.")


def _deserialize_record(serialized: object) -> ExperimentRecord | ExperimentEvent | SleepJournalEntry:
    if type(serialized) is not str:
        raise ExperimentStoreError("A stored experiment record must be JSON text.")
    try:
        payload = json.loads(serialized, object_pairs_hook=_unique_object, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ExperimentStoreError) as error:
        raise ExperimentStoreError("A stored experiment record is not strict JSON.") from error
    if type(payload) is not dict or set(payload) != {"format", "format_version", "record"}:
        raise ExperimentStoreError("A stored experiment record has an invalid envelope.")
    if payload["format"] != EXPERIMENT_STORE_RECORD_FORMAT or type(payload["format_version"]) is not int or payload["format_version"] != EXPERIMENT_STORE_RECORD_FORMAT_VERSION:
        raise ExperimentStoreError("The stored experiment-record format or version is unsupported.")
    record = _decode_record(payload["record"])
    if type(record) not in {ExperimentRecord, ExperimentEvent, SleepJournalEntry}:
        raise ExperimentStoreError("A stored top-level value is not an experiment identity, event, or journal entry.")
    return record


def _decode_record(payload: object) -> object:
    if type(payload) is not dict or type(payload.get("record_type")) is not str:
        raise ExperimentStoreError("A nested experiment value is not a typed record.")
    record_type = payload["record_type"]
    record_class = _RECORD_TYPES.get(record_type)
    if record_class is None:
        raise ExperimentStoreError("A stored experiment record type is unsupported.")
    expected_fields = tuple(fields(record_class))
    if set(payload) != {"record_type", *(field.name for field in expected_fields)}:
        raise ExperimentStoreError("A stored experiment record has missing or unknown fields.")
    values = {field.name: _decode_value(payload[field.name]) for field in expected_fields}
    if record_class is ExperimentEvent:
        try:
            values["event_type"] = ExperimentEventType(values["event_type"])
            values["source_class"] = SourceClass(values["source_class"])
        except (TypeError, ValueError) as error:
            raise ExperimentStoreError("A stored experiment event contains an unsupported enum value.") from error
    elif record_class is SleepJournalEntry:
        try:
            values["confounder_status"] = ConfounderReportStatus(values["confounder_status"])
            values["source_class"] = SourceClass(values["source_class"])
        except (TypeError, ValueError) as error:
            raise ExperimentStoreError("A stored journal entry contains an unsupported enum value.") from error
    elif record_class is SleepJournalConfounder:
        try:
            values["kind"] = ConfounderKind(values["kind"])
        except (TypeError, ValueError) as error:
            raise ExperimentStoreError("A stored journal confounder contains an unsupported kind.") from error
    try:
        return record_class(**values)
    except (ExperimentModelError, SleepJournalModelError, TypeError, ValueError) as error:
        raise ExperimentStoreError("A stored experiment record violates its versioned schema.") from error


def _decode_value(value: object) -> object:
    if type(value) is dict:
        return _decode_record(value)
    if type(value) is list:
        return tuple(_decode_value(item) for item in value)
    if value is None or type(value) in (bool, int, float, str):
        if type(value) is float and not math.isfinite(value):
            raise ExperimentStoreError("A stored experiment record contains a non-finite number.")
        return value
    raise ExperimentStoreError("A stored experiment record contains an unsupported JSON value.")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ExperimentStoreError("A stored experiment JSON object contains a duplicate field.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ExperimentStoreError(f"The non-finite JSON constant {value!r} is not allowed.")


def _store_text(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ExperimentStoreError(f"The {label} must be nonempty text.")
