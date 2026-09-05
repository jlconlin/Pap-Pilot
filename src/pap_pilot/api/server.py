"""Local HTTP boundary for reports and tightly scoped append-only experiment events."""

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Final, Literal, Sequence
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr
import uvicorn

from pap_pilot.engine.experiments import ConfounderKind, ConfounderReportStatus, ExperimentEvent, ExperimentEventType, ExperimentModelError, ExperimentNotFoundError, ExperimentStore, ExperimentStoreError, NoteRecordedPayload, SettingChangeConfirmedPayload, SleepJournalConfounder, SleepJournalEntry, SleepJournalEntryRecordedPayload, build_boundary_correction_events, reconstruct_ps_min_experiment_fixture
from pap_pilot.engine.model import SourceClass
from pap_pilot.engine.reports import (
    RetrospectiveEvidenceReport,
    build_ps_min_retrospective_evidence_report,
    serialize_retrospective_evidence_report,
)
from pap_pilot.ui import load_overview_asset
from pap_pilot.workflow import load_retrospective_workspace


LOCAL_API_VERSION: Final = 1
LOCAL_API_DEFAULT_HOST: Final = "127.0.0.1"
LOCAL_API_DEFAULT_PORT: Final = 8765
LOCAL_API_HEALTH_PATH: Final = "/api/v1/health"
PS_MIN_EXPERIMENT_SUMMARY_PATH: Final = "/api/v1/experiments/ps-min-2-to-1/summary"
PS_MIN_EXPERIMENT_HISTORY_PATH: Final = "/api/v1/experiments/ps-min-2-to-1/history"
PS_MIN_BOUNDARY_CORRECTION_PATH: Final = "/api/v1/experiments/ps-min-2-to-1/boundary-corrections"
PS_MIN_JOURNAL_PATH: Final = "/api/v1/experiments/ps-min-2-to-1/journal"
LOCAL_OVERVIEW_PATH: Final = "/"
LOCAL_OVERVIEW_STYLES_PATH: Final = "/assets/overview.css"
LOCAL_OVERVIEW_SCRIPT_PATH: Final = "/assets/overview.mjs"
_JSON_RESPONSE_HEADERS: Final = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
_UI_RESPONSE_HEADERS: Final = {
    **_JSON_RESPONSE_HEADERS,
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    "Referrer-Policy": "no-referrer",
}


class LocalApiConfigurationError(ValueError):
    """Raised when local API configuration could expose the service publicly."""


@dataclass(frozen=True, slots=True)
class LocalApiSettings:
    """Validated server settings restricted to numeric loopback addresses."""

    host: str = LOCAL_API_DEFAULT_HOST
    port: int = LOCAL_API_DEFAULT_PORT

    def __post_init__(self) -> None:
        if type(self.host) is not str or not self.host.strip():
            raise LocalApiConfigurationError("The local API host must be a numeric loopback address.")
        try:
            address = ip_address(self.host)
        except ValueError as error:
            raise LocalApiConfigurationError("The local API host must be a numeric loopback address.") from error
        if not address.is_loopback:
            raise LocalApiConfigurationError("The local API cannot bind to a non-loopback address.")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise LocalApiConfigurationError("The local API port must be an integer from 1 through 65535.")


class HealthResponse(BaseModel):
    """Explicit response contract for the local liveness endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok"] = "ok"
    service: Literal["pap-pilot"] = "pap-pilot"
    api_version: Literal[LOCAL_API_VERSION] = LOCAL_API_VERSION


class BoundaryCorrectionRequest(BaseModel):
    """The only user-editable fields accepted by the S36 mutation boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    corrected_event_id: StrictStr = Field(min_length=1, max_length=256)
    applied_at_ms: StrictInt
    note: StrictStr = Field(min_length=1, max_length=4000)


class JournalConfounderRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: StrictStr = Field(min_length=1, max_length=64)
    details: StrictStr | None = Field(default=None, max_length=4000)


class MorningJournalRequest(BaseModel):
    """Small structured local morning check-in; prose is retained but never parsed."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    night_record_id: StrictStr = Field(min_length=1, max_length=256)
    awakenings_count: StrictInt | None = Field(default=None, ge=0)
    sleep_quality: StrictInt | None = Field(default=None, ge=1, le=5)
    morning_energy: StrictInt | None = Field(default=None, ge=1, le=5)
    daytime_tiredness: StrictInt | None = Field(default=None, ge=1, le=5)
    confounder_status: Literal["not_reported", "none_reported", "reported"] = "not_reported"
    confounders: list[JournalConfounderRequest] = Field(default_factory=list)
    original_note: StrictStr | None = Field(default=None, max_length=4000)


def create_app(report: RetrospectiveEvidenceReport | None = None, *, database_path: str | Path | None = None) -> FastAPI:
    """Create the local API and freeze its deterministic report response bytes."""

    selected_report = build_ps_min_retrospective_evidence_report() if report is None else report
    if not isinstance(selected_report, RetrospectiveEvidenceReport):
        raise LocalApiConfigurationError("The experiment-summary endpoint requires a retrospective evidence report.")
    summary_json = serialize_retrospective_evidence_report(selected_report)
    overview_html = load_overview_asset("overview.html")
    overview_styles = load_overview_asset("overview.css")
    overview_script = load_overview_asset("overview.mjs")
    application = FastAPI(
        title="PAP Pilot local API",
        version=str(LOCAL_API_VERSION),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get(LOCAL_API_HEALTH_PATH, response_model=HealthResponse)
    def health(response: Response) -> HealthResponse:
        response.headers.update(_JSON_RESPONSE_HEADERS)
        return HealthResponse()

    @application.get(PS_MIN_EXPERIMENT_SUMMARY_PATH, response_class=Response)
    def ps_min_experiment_summary() -> Response:
        return Response(content=summary_json, media_type="application/json", headers=_JSON_RESPONSE_HEADERS)

    @application.get(PS_MIN_EXPERIMENT_HISTORY_PATH, response_class=JSONResponse)
    def ps_min_experiment_history() -> JSONResponse:
        replayed = _replay_workspace(database_path)
        return JSONResponse(content=_history_response(replayed), headers=_JSON_RESPONSE_HEADERS)

    @application.post(PS_MIN_BOUNDARY_CORRECTION_PATH, response_class=JSONResponse)
    def add_ps_min_boundary_correction(request: BoundaryCorrectionRequest) -> JSONResponse:
        if database_path is None:
            raise HTTPException(status_code=503, detail="The local experiment database is not configured.")
        try:
            with ExperimentStore(database_path) as store:
                _ensure_fixture_history(store)
                replayed = store.replay(reconstruct_ps_min_experiment_fixture().experiment.record_id)
                recorded_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                correction_id = f"event:boundary-correction:{uuid4()}"
                note_id = f"event:note:{uuid4()}"
                events = build_boundary_correction_events(
                    replayed,
                    corrected_event_id=request.corrected_event_id,
                    applied_at_ms=request.applied_at_ms,
                    note=request.note,
                    recorded_at_ms=recorded_at_ms,
                    correction_event_id=correction_id,
                    note_event_id=note_id,
                )
                store.append_events(events)
                updated = store.replay(replayed.experiment.record_id)
        except ExperimentModelError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ExperimentStoreError as error:
            raise HTTPException(status_code=409, detail="The append-only correction could not be saved.") from error
        return JSONResponse(content=_history_response(updated), status_code=201, headers=_JSON_RESPONSE_HEADERS)

    @application.post(PS_MIN_JOURNAL_PATH, response_class=JSONResponse)
    def add_morning_journal(request: MorningJournalRequest) -> JSONResponse:
        if database_path is None:
            raise HTTPException(status_code=503, detail="The local experiment database is not configured.")
        try:
            confounder_kind = tuple(ConfounderKind(value.kind) for value in request.confounders)
            if len(set(confounder_kind)) != len(confounder_kind):
                raise ValueError("Journal confounder kinds must be unique.")
            if request.confounder_status == "reported" and not request.confounders:
                raise ValueError("Reported confounders require entries.")
            if request.confounder_status != "reported" and request.confounders:
                raise ValueError("Only reported confounders may carry entries.")
            confounders = tuple(SleepJournalConfounder(kind, item.details) for kind, item in zip(confounder_kind, request.confounders))
            with ExperimentStore(database_path) as store:
                _ensure_fixture_history(store)
                experiment_id = reconstruct_ps_min_experiment_fixture().experiment.record_id
                recorded_at_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
                journal_id = f"journal:{uuid4()}"
                entry = SleepJournalEntry(journal_id, request.night_record_id, recorded_at_ms, "user:local", request.awakenings_count, request.sleep_quality, request.morning_energy, request.daytime_tiredness, ConfounderReportStatus(request.confounder_status), confounders, request.original_note, (f"provenance:{journal_id}",))
                event = ExperimentEvent(f"event:{journal_id}", experiment_id, len(store.read_history(experiment_id)) + 1, ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED, recorded_at_ms, "user:local", SleepJournalEntryRecordedPayload(entry.record_id, entry.night_record_id), SourceClass.USER_REPORTED, (experiment_id, entry.record_id, entry.night_record_id), entry.source_provenance_ids)
                store.append_journal_entry(event, entry)
                updated = store.replay(experiment_id)
        except (ValueError, ExperimentModelError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ExperimentStoreError as error:
            raise HTTPException(status_code=409, detail="The morning journal entry could not be saved.") from error
        return JSONResponse(content=_history_response(updated), status_code=201, headers=_JSON_RESPONSE_HEADERS)

    @application.get(LOCAL_OVERVIEW_PATH, response_class=HTMLResponse)
    def experiment_overview() -> HTMLResponse:
        return HTMLResponse(content=overview_html, headers=_UI_RESPONSE_HEADERS)

    @application.get(LOCAL_OVERVIEW_STYLES_PATH, response_class=Response)
    def experiment_overview_styles() -> Response:
        return Response(content=overview_styles, media_type="text/css", headers=_UI_RESPONSE_HEADERS)

    @application.get(LOCAL_OVERVIEW_SCRIPT_PATH, response_class=Response)
    def experiment_overview_script() -> Response:
        return Response(content=overview_script, media_type="text/javascript", headers=_UI_RESPONSE_HEADERS)

    return application


def create_configured_app(configuration_path: str | Path) -> FastAPI:
    """Create an app from explicit protected source and workspace inputs."""

    workspace = load_retrospective_workspace(configuration_path)
    return create_app(
        workspace.report,
        database_path=workspace.configuration.experiment_database_path,
    )


def _replay_workspace(database_path: str | Path | None):
    if database_path is None:
        raise HTTPException(status_code=503, detail="The local experiment database is not configured.")
    try:
        with ExperimentStore(database_path) as store:
            _ensure_fixture_history(store)
            return store.replay(reconstruct_ps_min_experiment_fixture().experiment.record_id)
    except ExperimentStoreError as error:
        raise HTTPException(status_code=503, detail="The local experiment database is unavailable.") from error


def _ensure_fixture_history(store: ExperimentStore) -> None:
    fixture = reconstruct_ps_min_experiment_fixture()
    try:
        experiment = store.get_experiment(fixture.experiment.record_id)
    except ExperimentNotFoundError:
        store.create_experiment(fixture.experiment)
        experiment = fixture.experiment
    if experiment != fixture.experiment:
        raise ExperimentStoreError("The retained PS Min workspace identity does not match the fixture.")
    history = store.read_history(experiment.record_id)
    shared_length = min(len(history), len(fixture.history))
    if history[:shared_length] != fixture.history[:shared_length]:
        raise ExperimentStoreError("The retained PS Min workspace history does not match the fixture prefix.")
    if len(history) < len(fixture.history):
        store.append_events(fixture.history[len(history) :])


def _history_response(replayed) -> dict[str, object]:
    corrected = set(replayed.corrected_event_ids)
    effective_boundary = replayed.latest_event(ExperimentEventType.SETTING_CHANGE_CONFIRMED_APPLIED)
    history = []
    for event in replayed.history:
        item: dict[str, object] = {
            "record_id": event.record_id,
            "sequence_number": event.sequence_number,
            "event_type": event.event_type.value,
            "recorded_at_ms": event.recorded_at_ms,
            "recorded_by": event.recorded_by,
            "correction_of_event_id": event.correction_of_event_id,
            "effective": event.record_id not in corrected,
        }
        if isinstance(event.payload, SettingChangeConfirmedPayload):
            item["applied_at_ms"] = event.payload.applied_at_ms
        if isinstance(event.payload, NoteRecordedPayload):
            item["note"] = event.payload.note
            item["related_event_id"] = event.payload.related_event_id
        if event.event_type is ExperimentEventType.SLEEP_JOURNAL_ENTRY_RECORDED:
            item["journal_entry_record_id"] = event.payload.journal_entry_record_id
            item["night_record_id"] = event.payload.night_record_id
        history.append(item)
    boundary = None if effective_boundary is None else {
        "record_id": effective_boundary.record_id,
        "applied_at_ms": effective_boundary.payload.applied_at_ms,
        "setting_name": effective_boundary.payload.applied_change.previous.name,
        "previous_value": effective_boundary.payload.applied_change.previous.value,
        "corrected_value": effective_boundary.payload.applied_change.proposed.value,
        "unit": effective_boundary.payload.applied_change.previous.unit,
    }
    return {
        "format": "pap-pilot.experiment-history-json",
        "format_version": 1,
        "experiment_record_id": replayed.experiment.record_id,
        "can_correct_boundary": effective_boundary is not None,
        "effective_boundary": boundary,
        "history": history,
        "journal_entries": [
            {
                "record_id": entry.record_id,
                "night_record_id": entry.night_record_id,
                "reported_at_ms": entry.reported_at_ms,
                "awakenings_count": entry.awakenings_count,
                "sleep_quality": entry.sleep_quality,
                "morning_energy": entry.morning_energy,
                "daytime_tiredness": entry.daytime_tiredness,
                "confounder_status": entry.confounder_status.value,
                "confounders": [{"kind": value.kind.value, "details": value.details} for value in entry.confounders],
                "original_note": entry.original_note,
            }
            for entry in replayed.effective_journal_entries
        ],
    }


app = create_app(database_path=Path.cwd() / "pap_pilot.sqlite3")


def main(argv: Sequence[str] | None = None) -> None:
    """Run the local API with settings that cannot select a public host."""

    parser = argparse.ArgumentParser(
        prog="pap-pilot-api",
        description="Serve the local PAP Pilot retrospective overview.",
    )
    parser.add_argument(
        "--workspace-config",
        type=Path,
        help="versioned JSON configuration for an evaluated retrospective workspace",
    )
    arguments = parser.parse_args(argv)
    settings = LocalApiSettings()
    selected_app = (
        app
        if arguments.workspace_config is None
        else create_configured_app(arguments.workspace_config)
    )
    uvicorn.run(selected_app, host=settings.host, port=settings.port, reload=False, access_log=False)
