"""Load one explicitly configured retrospective workspace for the local UI."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Final

from pap_pilot.adapter import OscarCohortSelection, extract_normalized_oscar_cohort
from pap_pilot.engine.analysis import AnalysisAvailability, AnalysisExperimentReference, AnalysisResourceKind, AnalysisWorkspace, analysis_resource_id
from pap_pilot.engine.experiments import PS_MIN_RETROSPECTIVE_FIXTURE_ID, ExperimentPeriod, ExperimentStore, reconstruct_ps_min_experiment_fixture
from pap_pilot.engine.reports import (
    EvaluatedRetrospectiveEvidenceReport,
    RetrospectiveRepresentativeIntervalSelection,
    build_evaluated_retrospective_evidence_report,
)
from pap_pilot.workflow.retrospective import evaluate_selected_oscar_retrospective_experiment
from pap_pilot.workflow.analysis import compose_analysis_workspace
from pap_pilot.workflow.night_detail import AnalysisNightDetail, compose_analysis_night_details


RETROSPECTIVE_WORKSPACE_CONFIGURATION_FORMAT: Final = "pap-pilot.retrospective-workspace"
RETROSPECTIVE_WORKSPACE_CONFIGURATION_VERSION: Final = 1
_CONFIGURATION_FIELDS: Final = frozenset(
    {
        "format",
        "format_version",
        "oscar_database_path",
        "oscar_copy_is_fixed_and_disposable",
        "experiment_database_path",
        "selected_session_database_ids",
        "representative_intervals",
    }
)
_INTERVAL_FIELDS: Final = frozenset(
    {
        "record_id",
        "period",
        "session_database_id",
        "start_ms",
        "end_ms",
        "signal_kinds",
    }
)


class RetrospectiveWorkspaceConfigurationError(ValueError):
    """Raised when the local workspace cannot be loaded without guessing."""


@dataclass(frozen=True, slots=True)
class ConfiguredRepresentativeInterval:
    """One explicit source-session interval before normalized IDs are known."""

    record_id: str
    period: ExperimentPeriod
    session_database_id: int
    start_ms: int | float
    end_ms: int | float
    signal_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrospectiveWorkspaceConfiguration:
    """Strict paths and selections required to reconstruct one local report."""

    oscar_database_path: Path
    experiment_database_path: Path
    selected_session_database_ids: tuple[int, ...]
    representative_intervals: tuple[ConfiguredRepresentativeInterval, ...]


@dataclass(frozen=True, slots=True)
class ConfiguredRetrospectiveWorkspace:
    """Generic analysis and compatibility report rebuilt from protected inputs."""

    configuration: RetrospectiveWorkspaceConfiguration
    report: EvaluatedRetrospectiveEvidenceReport
    analysis_workspace: AnalysisWorkspace
    analysis_night_details: tuple[AnalysisNightDetail, ...]


def load_retrospective_workspace(
    configuration_path: str | Path,
) -> ConfiguredRetrospectiveWorkspace:
    """Rebuild an evaluated report from a fixed OSCAR copy and persisted history."""

    configuration = load_retrospective_workspace_configuration(configuration_path)
    cohort = extract_normalized_oscar_cohort(
        configuration.oscar_database_path,
        OscarCohortSelection(configuration.selected_session_database_ids),
        trusted_immutable_copy=True,
    )
    fixture = reconstruct_ps_min_experiment_fixture()
    with ExperimentStore(configuration.experiment_database_path) as store:
        replayed = store.replay(fixture.experiment.record_id)
    evaluation = evaluate_selected_oscar_retrospective_experiment(cohort, replayed)

    session_context = {}
    for night in cohort.nights:
        for session in night.sessions:
            database_id = _source_session_database_id(session)
            if database_id in session_context:
                raise RetrospectiveWorkspaceConfigurationError(
                    "The selected OSCAR cohort repeats a source session identifier."
                )
            session_context[database_id] = (night.record_id, session.record_id)
    selections = []
    for configured in configuration.representative_intervals:
        context = session_context.get(configured.session_database_id)
        if context is None:
            raise RetrospectiveWorkspaceConfigurationError(
                "Every representative interval must name a selected OSCAR session."
            )
        night_record_id, session_record_id = context
        selections.append(
            RetrospectiveRepresentativeIntervalSelection(
                record_id=configured.record_id,
                period=configured.period,
                night_record_id=night_record_id,
                session_record_id=session_record_id,
                start_ms=configured.start_ms,
                end_ms=configured.end_ms,
                signal_kinds=configured.signal_kinds,
            )
        )
    report = build_evaluated_retrospective_evidence_report(evaluation, tuple(selections))
    experiment_reference = AnalysisExperimentReference(
        experiment_record_id=evaluation.experiment_record_id,
        label="PS Min 2 to 1 retrospective compatibility experiment",
        resource_id=analysis_resource_id(AnalysisResourceKind.EXPERIMENT, evaluation.experiment_record_id),
        summary_record_id=report.record_id,
        availability=AnalysisAvailability.AVAILABLE,
        source_record_ids=(evaluation.experiment_record_id, report.record_id),
        source_provenance_ids=report.provenance.source_provenance_ids,
        compatibility_fixture_id=PS_MIN_RETROSPECTIVE_FIXTURE_ID,
        limitations=("Compatibility fixture; it is not the generic workspace identity.",),
    )
    analysis_workspace = compose_analysis_workspace(
        evaluation.selected_nights,
        structural_quality_reports=(
            *evaluation.allocation_structural_quality_reports,
            *evaluation.metric_structural_quality_reports,
        ),
        signal_quality_reports=evaluation.signal_quality_reports,
        metric_results=evaluation.metric_results,
        journal_entries=evaluation.effective_journal_entries,
        experiments=(experiment_reference,),
    )
    analysis_night_details = compose_analysis_night_details(
        evaluation.selected_nights,
        structural_quality_reports=(
            *evaluation.allocation_structural_quality_reports,
            *evaluation.metric_structural_quality_reports,
        ),
        signal_quality_reports=evaluation.signal_quality_reports,
    )
    return ConfiguredRetrospectiveWorkspace(configuration, report, analysis_workspace, analysis_night_details)


def load_retrospective_workspace_configuration(
    configuration_path: str | Path,
) -> RetrospectiveWorkspaceConfiguration:
    """Parse the versioned JSON configuration without accepting implicit inputs."""

    path = Path(configuration_path).expanduser().resolve()
    if not path.is_file():
        raise RetrospectiveWorkspaceConfigurationError(
            "The retrospective workspace configuration must be an existing file."
        )
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonfinite_number,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RetrospectiveWorkspaceConfigurationError(
            "The retrospective workspace configuration is not readable JSON."
        ) from error
    root = _exact_object(value, _CONFIGURATION_FIELDS, "workspace configuration")
    if root["format"] != RETROSPECTIVE_WORKSPACE_CONFIGURATION_FORMAT:
        raise RetrospectiveWorkspaceConfigurationError(
            "The retrospective workspace configuration format is unsupported."
        )
    if type(root["format_version"]) is not int or root["format_version"] != RETROSPECTIVE_WORKSPACE_CONFIGURATION_VERSION:
        raise RetrospectiveWorkspaceConfigurationError(
            "The retrospective workspace configuration version is unsupported."
        )
    if root["oscar_copy_is_fixed_and_disposable"] is not True:
        raise RetrospectiveWorkspaceConfigurationError(
            "Configured evaluation requires an explicit assertion that the OSCAR database is a fixed disposable copy made with OSCAR closed."
        )

    oscar_database_path = _resolved_data_path(
        root["oscar_database_path"], path.parent, "OSCAR database"
    )
    experiment_database_path = _resolved_data_path(
        root["experiment_database_path"], path.parent, "experiment database"
    )
    if oscar_database_path == experiment_database_path:
        raise RetrospectiveWorkspaceConfigurationError(
            "The OSCAR copy and PAP Pilot experiment database must be different files."
        )
    if not oscar_database_path.is_file():
        raise RetrospectiveWorkspaceConfigurationError(
            "The configured OSCAR database copy does not exist."
        )
    if not experiment_database_path.is_file():
        raise RetrospectiveWorkspaceConfigurationError(
            "The configured PAP Pilot experiment database does not exist."
        )

    selected = _positive_integer_array(
        root["selected_session_database_ids"], "selected OSCAR session identifiers"
    )
    intervals_value = root["representative_intervals"]
    if type(intervals_value) is not list or len(intervals_value) != 2:
        raise RetrospectiveWorkspaceConfigurationError(
            "The workspace configuration requires exactly two representative intervals."
        )
    intervals = tuple(_configured_interval(value) for value in intervals_value)
    if tuple(value.period for value in intervals) != tuple(ExperimentPeriod):
        raise RetrospectiveWorkspaceConfigurationError(
            "Representative intervals must list baseline then intervention exactly once."
        )
    if len({value.record_id for value in intervals}) != len(intervals):
        raise RetrospectiveWorkspaceConfigurationError(
            "Representative interval identifiers must be unique."
        )
    return RetrospectiveWorkspaceConfiguration(
        oscar_database_path=oscar_database_path,
        experiment_database_path=experiment_database_path,
        selected_session_database_ids=selected,
        representative_intervals=intervals,
    )


def _configured_interval(value: object) -> ConfiguredRepresentativeInterval:
    item = _exact_object(value, _INTERVAL_FIELDS, "representative interval")
    record_id = _nonempty_text(item["record_id"], "representative interval identifier")
    try:
        period = ExperimentPeriod(item["period"])
    except (TypeError, ValueError) as error:
        raise RetrospectiveWorkspaceConfigurationError(
            "A representative interval period must be baseline or intervention."
        ) from error
    session_database_id = _positive_integer(
        item["session_database_id"], "representative interval OSCAR session identifier"
    )
    start_ms = _finite_timestamp(item["start_ms"], "representative interval start")
    end_ms = _finite_timestamp(item["end_ms"], "representative interval end")
    signal_kinds_value = item["signal_kinds"]
    if type(signal_kinds_value) is not list:
        raise RetrospectiveWorkspaceConfigurationError(
            "Representative interval signal kinds must be a JSON array."
        )
    signal_kinds = tuple(
        _nonempty_text(signal_kind, "representative interval signal kind")
        for signal_kind in signal_kinds_value
    )
    return ConfiguredRepresentativeInterval(
        record_id=record_id,
        period=period,
        session_database_id=session_database_id,
        start_ms=start_ms,
        end_ms=end_ms,
        signal_kinds=signal_kinds,
    )


def _source_session_database_id(session: object) -> int:
    references = session.provenance.source_references
    values = tuple(
        reference.source_record_id
        for reference in references
        if reference.source_record_type == "sessions.id"
    )
    if len(values) != 1:
        raise RetrospectiveWorkspaceConfigurationError(
            "Every normalized session must retain exactly one OSCAR sessions.id reference."
        )
    try:
        return _positive_integer(int(values[0]), "normalized OSCAR session identifier")
    except ValueError as error:
        raise RetrospectiveWorkspaceConfigurationError(
            "A normalized OSCAR session identifier is malformed."
        ) from error


def _resolved_data_path(value: object, parent: Path, label: str) -> Path:
    text = _nonempty_text(value, f"{label} path")
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = parent / candidate
    return candidate.resolve()


def _exact_object(value: object, fields: frozenset[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise RetrospectiveWorkspaceConfigurationError(
            f"The {label} must contain exactly: {', '.join(sorted(fields))}."
        )
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = {}
    for key, item in pairs:
        if key in value:
            raise RetrospectiveWorkspaceConfigurationError(
                f"The retrospective workspace configuration repeats the {key!r} field."
            )
        value[key] = item
    return value


def _reject_nonfinite_number(token: str) -> object:
    raise RetrospectiveWorkspaceConfigurationError(
        f"The retrospective workspace configuration contains non-finite {token}."
    )


def _positive_integer_array(value: object, label: str) -> tuple[int, ...]:
    if type(value) is not list or not value:
        raise RetrospectiveWorkspaceConfigurationError(
            f"The {label} must be a nonempty JSON array."
        )
    result = tuple(_positive_integer(item, label) for item in value)
    if len(set(result)) != len(result):
        raise RetrospectiveWorkspaceConfigurationError(f"The {label} must be unique.")
    return result


def _positive_integer(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RetrospectiveWorkspaceConfigurationError(
            f"The {label} must be a positive integer."
        )
    return value


def _finite_timestamp(value: object, label: str) -> int | float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RetrospectiveWorkspaceConfigurationError(
            f"The {label} must be a finite JSON number."
        )
    return value


def _nonempty_text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise RetrospectiveWorkspaceConfigurationError(
            f"The {label} must be nonempty text."
        )
    return value
