"""Focused tests for versioned normalized engine records."""

from dataclasses import FrozenInstanceError
import json
import math
import unittest

from pap_pilot.engine import (
    NORMALIZED_FORMAT,
    NORMALIZED_FORMAT_VERSION,
    NORMALIZED_RECORD_VERSION,
    EventRecord,
    IntervalClosure,
    NightRecord,
    NormalizedModelError,
    ProvenanceRecord,
    ProvenanceValue,
    SessionRecord,
    SettingRecord,
    SignalRecord,
    SignalRepresentation,
    SignalSegmentRecord,
    SourceClass,
    SourceReference,
    deserialize_normalized_record,
    serialize_normalized_record,
)


class NormalizedModelTests(unittest.TestCase):
    """Verify immutable records, canonical JSON, and lossless provenance."""

    def setUp(self) -> None:
        self.references = (
            SourceReference("sessions", "session-source-17"),
            SourceReference("profiles", "profile-source-3"),
            SourceReference("machines", "machine-source-9"),
        )
        self.source_values = (
            ProvenanceValue("loader_name", "ResMed"),
            ProvenanceValue("channel_code", "FlowRate"),
        )
        self.provenance = ProvenanceRecord(
            record_id="provenance:session-1",
            source_classes=(SourceClass.OSCAR_NORMALIZED, SourceClass.MACHINE_RECORDED),
            source_system="OSCAR",
            source_references=self.references,
            source_system_version="2.0.0",
            source_schema_version="17",
            parent_provenance_ids=("provenance:import", "provenance:device"),
            source_values=self.source_values,
        )
        self.mode = SettingRecord(
            record_id="setting:therapy-mode",
            name="therapy_mode",
            value="asv_fixed_epap",
            unit=None,
            provenance=self.provenance,
        )
        self.ps_min = SettingRecord(
            record_id="setting:ps-min",
            name="ps_min",
            value=1.0,
            unit="cm H₂O",
            provenance=self.provenance,
        )
        self.event = EventRecord(
            record_id="event:oa-1",
            event_kind="obstructive_apnea",
            start_time_ms=1_300,
            duration_ms=10_000,
            provenance=self.provenance,
        )
        self.flow_segment = SignalSegmentRecord(
            record_id="segment:flow-1",
            start_time_ms=1_000,
            end_time_ms=1_161,
            interval_closure=IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
            sample_times_ms=(1_000.0, 1_040.25, 1_080.5, 1_120.75),
            values=(1, -2.5, 3, -1),
            sample_interval_ms=40.25,
            provenance=self.provenance,
        )
        self.leak_segment = SignalSegmentRecord(
            record_id="segment:leak-1",
            start_time_ms=1_200,
            end_time_ms=1_600,
            interval_closure=IntervalClosure.START_AND_END_INCLUSIVE,
            sample_times_ms=(1_200, 1_400, 1_600),
            values=(0, 1.2, 2.4),
            sample_interval_ms=None,
            provenance=self.provenance,
        )
        self.flow = SignalRecord(
            record_id="signal:flow-rate",
            signal_kind="flow_rate",
            unit="L/min",
            representation=SignalRepresentation.UNIFORM_WAVEFORM,
            segments=(self.flow_segment,),
            provenance=self.provenance,
        )
        self.leak = SignalRecord(
            record_id="signal:leak-rate",
            signal_kind="leak_rate",
            unit="L/min",
            representation=SignalRepresentation.TIMED_UPDATES,
            segments=(self.leak_segment,),
            provenance=self.provenance,
            value_semantics="unintentional",
        )
        self.session = SessionRecord(
            record_id="session:1",
            device_id="device:aircurve-1",
            start_time_ms=900,
            end_time_ms=20_000,
            settings=(self.ps_min, self.mode),
            events=(self.event,),
            signals=(self.leak, self.flow),
            provenance=self.provenance,
        )
        self.night = NightRecord(
            record_id="night:2026-08-31",
            local_date="2026-08-31",
            timezone="America/Denver",
            day_boundary_local_time="12:00:00",
            sessions=(self.session,),
            provenance=self.provenance,
        )

    def test_every_record_type_has_a_deterministic_round_trip(self) -> None:
        records = (
            *self.references,
            *self.source_values,
            self.provenance,
            self.mode,
            self.event,
            self.flow_segment,
            self.flow,
            self.session,
            self.night,
        )

        for record in records:
            with self.subTest(record_type=record.RECORD_TYPE):
                serialized = serialize_normalized_record(record)
                self.assertEqual(serialized, serialize_normalized_record(record))
                self.assertEqual(deserialize_normalized_record(serialized), record)
                self.assertNotIn("\n", serialized)
                self.assertNotIn(": ", serialized)

    def test_night_round_trip_preserves_nested_provenance_and_unicode_units(self) -> None:
        serialized = serialize_normalized_record(self.night)
        restored = deserialize_normalized_record(serialized)

        self.assertEqual(restored, self.night)
        self.assertIn("cm H₂O", serialized)
        self.assertEqual(
            restored.sessions[0].signals[0].segments[0].sample_times_ms,
            (1_000.0, 1_040.25, 1_080.5, 1_120.75),
        )
        self.assertEqual(restored.sessions[0].settings[1].provenance, self.provenance)
        self.assertEqual(restored.sessions[0].signals[0].segments[0].provenance, self.provenance)
        self.assertEqual(
            restored.sessions[0].events[0].provenance.source_references,
            self.provenance.source_references,
        )
        self.assertEqual(restored.sessions[0].provenance.source_values, self.provenance.source_values)

    def test_serialization_has_an_explicit_versioned_envelope(self) -> None:
        payload = json.loads(serialize_normalized_record(self.night))

        self.assertEqual(payload["format"], NORMALIZED_FORMAT)
        self.assertEqual(payload["format_version"], NORMALIZED_FORMAT_VERSION)
        self.assertEqual(payload["record"]["record_type"], "night")
        self.assertEqual(
            payload["record"]["record_version"],
            NORMALIZED_RECORD_VERSION,
        )
        self.assertEqual(
            payload["record"]["sessions"][0]["record_version"],
            NORMALIZED_RECORD_VERSION,
        )

    def test_source_classes_keep_required_information_origins_distinct(self) -> None:
        self.assertEqual(
            {source_class.value for source_class in SourceClass},
            {
                "machine_recorded",
                "machine_labeled",
                "oscar_normalized",
                "oscar_derived",
                "companion_derived",
                "ai_generated",
                "user_reported",
                "external_sensor",
            },
        )

    def test_constructor_canonicalizes_unordered_record_collections(self) -> None:
        self.assertEqual(
            tuple(value.value for value in self.provenance.source_classes),
            ("machine_recorded", "oscar_normalized"),
        )
        self.assertEqual(
            tuple(
                value.source_record_type
                for value in self.provenance.source_references
            ),
            ("machines", "profiles", "sessions"),
        )
        self.assertEqual(self.provenance.parent_provenance_ids, ("provenance:device", "provenance:import"))
        self.assertEqual(
            tuple(value.record_id for value in self.session.settings),
            ("setting:ps-min", "setting:therapy-mode"),
        )
        self.assertEqual(
            tuple(value.record_id for value in self.session.signals),
            ("signal:flow-rate", "signal:leak-rate"),
        )

    def test_noncanonical_json_input_reserializes_canonically(self) -> None:
        canonical = serialize_normalized_record(self.night)
        noncanonical = json.dumps(json.loads(canonical), ensure_ascii=False, indent=4, sort_keys=False)

        self.assertEqual(serialize_normalized_record(deserialize_normalized_record(noncanonical)), canonical)

    def test_records_are_deeply_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.night.local_date = "2026-09-01"  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            self.night.sessions.append(self.session)  # type: ignore[attr-defined]

    def test_unknown_missing_duplicate_and_unsupported_fields_fail(self) -> None:
        payload = json.loads(serialize_normalized_record(self.night))
        payload["unknown"] = True
        with self.assertRaises(NormalizedModelError):
            deserialize_normalized_record(json.dumps(payload))

        payload = json.loads(serialize_normalized_record(self.night))
        del payload["record"]["timezone"]
        with self.assertRaises(NormalizedModelError):
            deserialize_normalized_record(json.dumps(payload))

        duplicate = '{"format":"pap-pilot.normalized","format":"pap-pilot.normalized","format_version":1,"record":{}}'
        with self.assertRaises(NormalizedModelError):
            deserialize_normalized_record(duplicate)

        payload = json.loads(serialize_normalized_record(self.night))
        payload["format_version"] = True
        with self.assertRaises(NormalizedModelError):
            deserialize_normalized_record(json.dumps(payload))

        payload = json.loads(serialize_normalized_record(self.night))
        payload["record"]["record_version"] = 2
        with self.assertRaises(NormalizedModelError):
            deserialize_normalized_record(json.dumps(payload))

        payload = json.loads(serialize_normalized_record(self.night))
        payload["record"]["record_type"] = "unsupported"
        with self.assertRaises(NormalizedModelError):
            deserialize_normalized_record(json.dumps(payload))

    def test_nonfinite_and_wrong_scalar_types_fail(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(NormalizedModelError):
                SettingRecord("setting:bad", "bad", value, None, self.provenance)

        with self.assertRaises(NormalizedModelError):
            deserialize_normalized_record('{"format":"pap-pilot.normalized","format_version":1,"record":NaN}')
        with self.assertRaises(NormalizedModelError):
            EventRecord("event:bad", "bad", True, 0, self.provenance)

    def test_structural_invariants_fail_without_adding_quality_rules(self) -> None:
        with self.assertRaises(NormalizedModelError):
            SessionRecord("session:bad", "device:1", 2_000, 1_000, (), (), (), self.provenance)
        with self.assertRaises(NormalizedModelError):
            EventRecord("event:bad", "bad", 1_000, -1, self.provenance)
        with self.assertRaises(NormalizedModelError):
            NightRecord("night:empty", "2026-08-31", "America/Denver", "12:00:00", (), self.provenance)
        with self.assertRaises(NormalizedModelError):
            SignalSegmentRecord(
                "segment:bad",
                1_000,
                1_100,
                IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
                (1_000, 1_040),
                (1.0,),
                40.0,
                self.provenance,
            )
        with self.assertRaises(NormalizedModelError):
            SignalRecord(
                "signal:bad",
                "leak_rate",
                "L/min",
                SignalRepresentation.TIMED_UPDATES,
                (self.flow_segment,),
                self.provenance,
            )
        with self.assertRaises(NormalizedModelError):
            SignalSegmentRecord(
                "segment:inconsistent-rate",
                1_000,
                1_120,
                IntervalClosure.START_INCLUSIVE_END_EXCLUSIVE,
                (1_000.0, 1_041.0, 1_080.0),
                (1.0, 2.0, 3.0),
                40.0,
                self.provenance,
            )
        with self.assertRaises(NormalizedModelError):
            SessionRecord(
                "session:duplicate",
                "device:1",
                1_000,
                2_000,
                (self.mode, self.mode),
                (),
                (),
                self.provenance,
            )
        duplicate_source_name = ProvenanceValue("loader_name", "Other")
        with self.assertRaises(NormalizedModelError):
            ProvenanceRecord(
                record_id="provenance:duplicate-source-name",
                source_classes=(SourceClass.OSCAR_NORMALIZED,),
                source_system="OSCAR",
                source_references=self.references,
                source_values=(self.source_values[0], duplicate_source_name),
            )
        duplicate_name = SettingRecord(
            "setting:ps-min-duplicate",
            self.ps_min.name,
            self.ps_min.value,
            self.ps_min.unit,
            self.provenance,
        )
        with self.assertRaises(NormalizedModelError):
            SessionRecord(
                "session:duplicate-name",
                "device:1",
                1_000,
                2_000,
                (self.ps_min, duplicate_name),
                (),
                (),
                self.provenance,
            )


if __name__ == "__main__":
    unittest.main()
