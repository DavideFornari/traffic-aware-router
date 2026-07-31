"""TomTom Flow Segment Data client.

Endpoint and response schema verified against TomTom's live documentation
(docs.tomtom.com/traffic-api, "Flow Segment Data", v4) rather than assumed:

    GET https://api.tomtom.com/traffic/services/4/flowSegmentData/{style}/{zoom}/json
        ?key=...&point={lat},{lon}&unit=kmph

returning `{"flowSegmentData": {"currentSpeed", "freeFlowSpeed",
"currentTravelTime", "freeFlowTravelTime", "confidence", "roadClosure",
"coordinates": {"coordinate": [{"latitude", "longitude"}, ...]}}}`.

Free tier: 20,000 requests/month, no credit card required (docs.tomtom.com/
pricing, checked at implementation time — reverify before relying on this
in production, since TomTom can change it).

Hard constraint from CLAUDE.md: the app must run without a TomTom API key.
`TomTomClient(api_key=None)` (or omitting it, e.g. no `TOMTOM_API_KEY` env
var set) makes every call a no-op returning `None` instead of raising —
callers fall back to free-flow-only routing, not a crash.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

BASE_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData"
DEFAULT_STYLE = "absolute"
DEFAULT_ZOOM = 15
DEFAULT_TIMEOUT_S = 5.0


class TomTomAPIError(Exception):
    """Raised when TomTom responds with a non-2xx status or malformed body."""


@dataclass(frozen=True)
class FlowSegment:
    """A `flowSegmentData` response: the road nearest a queried point."""

    current_speed_kph: float
    free_flow_speed_kph: float
    current_travel_time_s: float
    free_flow_travel_time_s: float
    confidence: float
    road_closure: bool
    coordinates: list[tuple[float, float]]  # (lat, lon), WGS84, in segment order


class TomTomClient:
    """Thin wrapper around the Flow Segment Data endpoint.

    Reads `TOMTOM_API_KEY` from the environment if `api_key` isn't given
    explicitly. Never commit a real key or a `.env` file (see CLAUDE.md).
    """

    def __init__(
        self,
        api_key: str | None = None,
        style: str = DEFAULT_STYLE,
        zoom: int = DEFAULT_ZOOM,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("TOMTOM_API_KEY")
        self.style = style
        self.zoom = zoom
        self._client = httpx.Client(timeout=timeout_s)

    @property
    def is_available(self) -> bool:
        return self.api_key is not None

    def get_flow_segment(self, lat: float, lon: float) -> FlowSegment | None:
        """Flow data for the road nearest `(lat, lon)`, or `None` with no key."""
        if not self.is_available:
            return None

        url = f"{BASE_URL}/{self.style}/{self.zoom}/json"
        params = {"key": self.api_key, "point": f"{lat},{lon}", "unit": "kmph"}

        response = self._client.get(url, params=params)
        if response.status_code != httpx.codes.OK:
            raise TomTomAPIError(
                f"TomTom Flow Segment Data returned {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()["flowSegmentData"]
            coordinates = [
                (c["latitude"], c["longitude"]) for c in data["coordinates"]["coordinate"]
            ]
            return FlowSegment(
                current_speed_kph=data["currentSpeed"],
                free_flow_speed_kph=data["freeFlowSpeed"],
                current_travel_time_s=data["currentTravelTime"],
                free_flow_travel_time_s=data["freeFlowTravelTime"],
                confidence=data["confidence"],
                road_closure=data["roadClosure"],
                coordinates=coordinates,
            )
        except (KeyError, TypeError) as exc:
            raise TomTomAPIError(f"Malformed Flow Segment Data response: {exc}") from exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TomTomClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
