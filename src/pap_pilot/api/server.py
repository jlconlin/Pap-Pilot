"""Local read-only HTTP boundary for PAP Pilot engine results."""

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Final, Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel, ConfigDict
import uvicorn

from pap_pilot.engine.reports import (
    RetrospectiveEvidenceReport,
    build_ps_min_retrospective_evidence_report,
    serialize_retrospective_evidence_report,
)


LOCAL_API_VERSION: Final = 1
LOCAL_API_DEFAULT_HOST: Final = "127.0.0.1"
LOCAL_API_DEFAULT_PORT: Final = 8765
LOCAL_API_HEALTH_PATH: Final = "/api/v1/health"
PS_MIN_EXPERIMENT_SUMMARY_PATH: Final = "/api/v1/experiments/ps-min-2-to-1/summary"
_JSON_RESPONSE_HEADERS: Final = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
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


def create_app(report: RetrospectiveEvidenceReport | None = None) -> FastAPI:
    """Create the two-route API and freeze its report response bytes."""

    selected_report = build_ps_min_retrospective_evidence_report() if report is None else report
    if not isinstance(selected_report, RetrospectiveEvidenceReport):
        raise LocalApiConfigurationError("The experiment-summary endpoint requires a retrospective evidence report.")
    summary_json = serialize_retrospective_evidence_report(selected_report)
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

    return application


app = create_app()


def main() -> None:
    """Run the local API with settings that cannot select a public host."""

    settings = LocalApiSettings()
    uvicorn.run(app, host=settings.host, port=settings.port, reload=False, access_log=False)
