"""Focused HTTP and binding-safety tests for the local API shell."""

from unittest.mock import patch
import unittest

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from pap_pilot.api import (
    LOCAL_API_DEFAULT_HOST,
    LOCAL_API_DEFAULT_PORT,
    LOCAL_API_HEALTH_PATH,
    LOCAL_API_VERSION,
    PS_MIN_EXPERIMENT_SUMMARY_PATH,
    LocalApiConfigurationError,
    LocalApiSettings,
    app,
    create_app,
    main,
)
from pap_pilot.engine import build_ps_min_retrospective_evidence_report, serialize_retrospective_evidence_report


class LocalApiTests(unittest.TestCase):
    """Verify the API is local, read-only, minimal, and lossless."""

    def test_health_endpoint_has_an_explicit_stable_response(self) -> None:
        with TestClient(create_app()) as client:
            response = client.get(LOCAL_API_HEALTH_PATH)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "pap-pilot", "api_version": LOCAL_API_VERSION})
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_experiment_summary_is_the_exact_canonical_s32_report(self) -> None:
        expected = serialize_retrospective_evidence_report(build_ps_min_retrospective_evidence_report()).encode("utf-8")
        with TestClient(create_app()) as client:
            first = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH)
            second = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, expected)
        self.assertEqual(second.content, expected)
        self.assertEqual(first.headers["content-type"], "application/json")
        self.assertEqual(first.headers["cache-control"], "no-store")
        self.assertEqual(first.headers["x-content-type-options"], "nosniff")

    def test_report_is_built_when_the_app_is_created_not_per_request(self) -> None:
        application = create_app()
        with patch("pap_pilot.api.server.build_ps_min_retrospective_evidence_report", side_effect=AssertionError("request-time rebuild")):
            with TestClient(application) as client:
                response = client.get(PS_MIN_EXPERIMENT_SUMMARY_PATH)

        self.assertEqual(response.status_code, 200)

    def test_api_exposes_exactly_two_get_routes_and_no_documentation_ui(self) -> None:
        application = create_app()
        routes = {(route.path, frozenset(route.methods)) for route in application.routes if isinstance(route, APIRoute)}

        self.assertEqual(
            routes,
            {
                (LOCAL_API_HEALTH_PATH, frozenset({"GET"})),
                (PS_MIN_EXPERIMENT_SUMMARY_PATH, frozenset({"GET"})),
            },
        )
        with TestClient(application) as client:
            for path in ("/", "/docs", "/redoc", "/openapi.json"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 404)

    def test_mutation_methods_are_unavailable(self) -> None:
        with TestClient(create_app()) as client:
            for path in (LOCAL_API_HEALTH_PATH, PS_MIN_EXPERIMENT_SUMMARY_PATH):
                for method in ("post", "put", "patch", "delete"):
                    with self.subTest(path=path, method=method):
                        self.assertEqual(client.request(method.upper(), path, json={"ignored": True}).status_code, 405)

    def test_default_server_configuration_is_numeric_ipv4_loopback(self) -> None:
        settings = LocalApiSettings()

        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.host, LOCAL_API_DEFAULT_HOST)
        self.assertEqual(settings.port, LOCAL_API_DEFAULT_PORT)

    def test_command_runs_only_the_validated_default_binding(self) -> None:
        with patch("pap_pilot.api.server.uvicorn.run") as run:
            main()

        run.assert_called_once_with(app, host=LOCAL_API_DEFAULT_HOST, port=LOCAL_API_DEFAULT_PORT, reload=False, access_log=False)

    def test_only_numeric_loopback_hosts_are_accepted(self) -> None:
        self.assertEqual(LocalApiSettings("127.0.0.2").host, "127.0.0.2")
        self.assertEqual(LocalApiSettings("::1").host, "::1")
        for host in ("0.0.0.0", "::", "192.168.1.20", "localhost", "pap-pilot.local", ""):
            with self.subTest(host=host), self.assertRaises(LocalApiConfigurationError):
                LocalApiSettings(host=host)

    def test_invalid_ports_are_rejected(self) -> None:
        for port in (0, 65536, -1, 8765.0, "8765", True):
            with self.subTest(port=port), self.assertRaises(LocalApiConfigurationError):
                LocalApiSettings(port=port)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
