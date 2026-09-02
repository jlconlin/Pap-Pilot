"""Versioned deterministic quality findings for normalized PAP records."""

from pap_pilot.engine.quality.model import (
    QUALITY_ENGINE_VERSION,
    QUALITY_RULE_SET_ID,
    QUALITY_RULE_SET_VERSION,
    SHORT_SESSION_THRESHOLD_MS,
    ClockCorrectionEvidence,
    ClockCorrectionEvidenceState,
    QualityFinding,
    QualityImpact,
    QualityModelError,
    QualityRule,
    QualityStatus,
    QualityValue,
    StructuralQualityReport,
    TimeBasis,
)
from pap_pilot.engine.quality.structural import (
    evaluate_clock_correction_integrity,
    evaluate_flow_pressure_alignment,
    evaluate_missing_required_signals,
    evaluate_short_session,
    evaluate_split_session_night,
    evaluate_structural_quality,
)

__all__ = [
    "QUALITY_ENGINE_VERSION",
    "QUALITY_RULE_SET_ID",
    "QUALITY_RULE_SET_VERSION",
    "SHORT_SESSION_THRESHOLD_MS",
    "ClockCorrectionEvidence",
    "ClockCorrectionEvidenceState",
    "QualityFinding",
    "QualityImpact",
    "QualityModelError",
    "QualityRule",
    "QualityStatus",
    "QualityValue",
    "StructuralQualityReport",
    "TimeBasis",
    "evaluate_clock_correction_integrity",
    "evaluate_flow_pressure_alignment",
    "evaluate_missing_required_signals",
    "evaluate_short_session",
    "evaluate_split_session_night",
    "evaluate_structural_quality",
]
