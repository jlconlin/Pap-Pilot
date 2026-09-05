"""Deterministic prospective eligibility checks for policy 0009."""

from dataclasses import dataclass
from enum import StrEnum
import math
from typing import Final

from pap_pilot.engine.experiments.model import ExperimentProposal, ExperimentSetting


PROSPECTIVE_SAFETY_POLICY_ID: Final = "pap-pilot.prospective-safety-policy"
PROSPECTIVE_SAFETY_POLICY_VERSION: Final = 1
PROSPECTIVE_SAFETY_ENGINE_VERSION: Final = "pap-pilot.prospective-safety-gate-v1"
MINIMUM_PROSPECTIVE_NIGHTS_PER_ARM: Final = 3
MINIMUM_PROSPECTIVE_USABLE_DURATION_MS: Final = 300_000
REQUIRED_PROSPECTIVE_SIGNALS: Final = ("flow_rate", "mask_pressure", "leak")
_REQUIRED_SETTINGS: Final = ("therapy_mode_code", "loader_mode_code", "epap", "ps_min", "ps_max", "max_ipap")


class ProspectiveSafetyFailureCode(StrEnum):
    UNSUPPORTED_SCOPE = "unsupported_scope"
    MULTI_VARIABLE_CHANGE = "multi_variable_change"
    INVALID_SETTING_BOUNDS = "invalid_setting_bounds"
    INSUFFICIENT_BASELINE_DATA = "insufficient_baseline_data"
    INSUFFICIENT_INTERVENTION_DATA = "insufficient_intervention_data"
    MISSING_REVERSION = "missing_reversion"
    INCONSISTENT_SETTINGS = "inconsistent_settings"
    UNSUPPORTED_DATA_SOURCE = "unsupported_data_source"
    UNRESOLVED_TIME_BOUNDARY = "unresolved_time_boundary"
    MISSING_STOP_RULE = "missing_stop_rule"


@dataclass(frozen=True, slots=True)
class ProspectiveNightEvidence:
    """Evidence required to count one night for prospective eligibility."""

    local_date: str
    usable_duration_ms: int
    available_signals: tuple[str, ...] = REQUIRED_PROSPECTIVE_SIGNALS
    included: bool = True
    settings: tuple[ExperimentSetting, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.local_date, str) or not self.local_date:
            raise ValueError("A prospective night requires a local date.")
        if type(self.usable_duration_ms) is not int or self.usable_duration_ms < 0:
            raise ValueError("Usable prospective duration must be a nonnegative integer.")
        if type(self.included) is not bool:
            raise ValueError("Prospective night inclusion must be boolean.")
        signals = tuple(sorted(set(self.available_signals)))
        if any(not isinstance(value, str) or not value for value in signals):
            raise ValueError("Prospective signal names must be nonempty strings.")
        object.__setattr__(self, "available_signals", signals)
        object.__setattr__(self, "settings", tuple(sorted(self.settings, key=lambda value: value.name)))


@dataclass(frozen=True, slots=True)
class ProspectiveSafetyEvidence:
    """Source-independent evidence supplied to the prospective safety gate."""

    baseline_nights: tuple[ProspectiveNightEvidence, ...]
    intervention_nights: tuple[ProspectiveNightEvidence, ...]
    reversion_settings: tuple[ExperimentSetting, ...] | None
    source_supported: bool = True
    time_boundaries_resolved: bool = True

    def __post_init__(self) -> None:
        for value, label in ((self.baseline_nights, "baseline"), (self.intervention_nights, "intervention")):
            if not isinstance(value, tuple) or any(not isinstance(night, ProspectiveNightEvidence) for night in value):
                raise ValueError(f"{label} nights must be prospective-night evidence records.")
        if self.reversion_settings is not None:
            object.__setattr__(self, "reversion_settings", tuple(sorted(self.reversion_settings, key=lambda value: value.name)))
        if type(self.source_supported) is not bool or type(self.time_boundaries_resolved) is not bool:
            raise ValueError("Prospective evidence support and boundary states must be boolean.")


@dataclass(frozen=True, slots=True)
class ProspectiveSafetyGateResult:
    """Deterministic, structured result; failures never become advisory prose."""

    eligible: bool
    failure_codes: tuple[ProspectiveSafetyFailureCode, ...]
    policy_id: str = PROSPECTIVE_SAFETY_POLICY_ID
    policy_version: int = PROSPECTIVE_SAFETY_POLICY_VERSION
    engine_version: str = PROSPECTIVE_SAFETY_ENGINE_VERSION

    def __post_init__(self) -> None:
        if type(self.eligible) is not bool or self.policy_id != PROSPECTIVE_SAFETY_POLICY_ID or self.policy_version != PROSPECTIVE_SAFETY_POLICY_VERSION:
            raise ValueError("Unsupported prospective safety result identity.")
        codes = tuple(dict.fromkeys(self.failure_codes))
        if any(not isinstance(code, ProspectiveSafetyFailureCode) for code in codes):
            raise ValueError("Prospective safety failures must use the versioned failure vocabulary.")
        if self.eligible != (not codes):
            raise ValueError("Prospective eligibility must agree with failure codes.")
        object.__setattr__(self, "failure_codes", codes)


def evaluate_prospective_safety(proposal: ExperimentProposal, evidence: ProspectiveSafetyEvidence) -> ProspectiveSafetyGateResult:
    """Evaluate one proposal against the accepted policy without changing any device state."""

    failures: list[ProspectiveSafetyFailureCode] = []
    change = proposal.proposed_change
    baseline = {setting.name: setting for setting in proposal.baseline_settings}
    held_fixed = {setting.name: setting for setting in proposal.settings_held_fixed}

    if len(proposal.baseline_settings) != len(_REQUIRED_SETTINGS) or set(baseline) != set(_REQUIRED_SETTINGS) or len(held_fixed) != 5 or set(held_fixed) != set(_REQUIRED_SETTINGS) - {"ps_min"}:
        failures.append(ProspectiveSafetyFailureCode.MULTI_VARIABLE_CHANGE)
    if change.previous.name != "ps_min" or change.previous.value != 2.0 or change.proposed.value != 1.0 or change.previous.unit != "cm H₂O" or change.proposed.unit != "cm H₂O":
        failures.append(ProspectiveSafetyFailureCode.UNSUPPORTED_SCOPE)
    if baseline.get("therapy_mode_code", ExperimentSetting("x", 0)).value != 6 or baseline.get("loader_mode_code", ExperimentSetting("x", 0)).value != 7:
        failures.append(ProspectiveSafetyFailureCode.UNSUPPORTED_SCOPE)
    try:
        epap = float(baseline["epap"].value)
        ps_max = float(baseline["ps_max"].value)
        max_ipap = float(baseline["max_ipap"].value)
        ps_min = float(change.proposed.value)
        if not all(math.isfinite(value) for value in (epap, ps_max, max_ipap, ps_min)) or ps_min < 0 or ps_min > ps_max or epap + ps_max != max_ipap:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        failures.append(ProspectiveSafetyFailureCode.INVALID_SETTING_BOUNDS)
    if not proposal.stop_conditions:
        failures.append(ProspectiveSafetyFailureCode.MISSING_STOP_RULE)
    if evidence.reversion_settings is None or tuple(evidence.reversion_settings) != tuple(proposal.baseline_settings):
        failures.append(ProspectiveSafetyFailureCode.MISSING_REVERSION)
    if not evidence.source_supported:
        failures.append(ProspectiveSafetyFailureCode.UNSUPPORTED_DATA_SOURCE)
    if not evidence.time_boundaries_resolved:
        failures.append(ProspectiveSafetyFailureCode.UNRESOLVED_TIME_BOUNDARY)

    def valid_nights(nights: tuple[ProspectiveNightEvidence, ...]) -> tuple[ProspectiveNightEvidence, ...]:
        return tuple(night for night in nights if night.included and night.usable_duration_ms >= MINIMUM_PROSPECTIVE_USABLE_DURATION_MS and set(REQUIRED_PROSPECTIVE_SIGNALS).issubset(night.available_signals))

    if len(valid_nights(evidence.baseline_nights)) < max(MINIMUM_PROSPECTIVE_NIGHTS_PER_ARM, proposal.minimum_valid_nights):
        failures.append(ProspectiveSafetyFailureCode.INSUFFICIENT_BASELINE_DATA)
    if len(valid_nights(evidence.intervention_nights)) < max(MINIMUM_PROSPECTIVE_NIGHTS_PER_ARM, proposal.minimum_valid_nights):
        failures.append(ProspectiveSafetyFailureCode.INSUFFICIENT_INTERVENTION_DATA)
    return ProspectiveSafetyGateResult(not failures, tuple(failures))

