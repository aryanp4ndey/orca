"""Geospatial Agent.

Owns every spatial answer in ORCA, and owns it deterministically.  The planner
decides *which* spatial question to ask; this agent computes it with closed-form
geodesy.  No language model performs coordinate arithmetic, polygon tests or
boundary determination anywhere in the system.

Outputs: the marine retrieval point, distance to coast, derived maritime band,
zone memberships and proximities, nearest landing centre, and - for a route
question - distance and bearing to the destination.
"""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.geo.gazetteer import get_gazetteer
from app.geo.geodesy import compass_point, distance_km, distance_nm, initial_bearing_deg
from app.geo.layers import get_baseline, layer_catalogue, maritime_band, zones_near
from app.observability.trace import Trace
from app.reasoning.evidence_builder import computed_evidence
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.common import AgentStatus, Capability


class GeospatialAgent(BaseAgent):
    name = "geospatial_agent"
    capability = Capability.GEOSPATIAL
    responsibility = (
        "Resolve the place to a marine retrieval point and compute every spatial "
        "quantity the rest of the pipeline needs: distances, bearings, "
        "distance-to-coast, maritime band, zone membership and proximity")
    consumes = ("place name or coordinates",)
    produces = ("point", "distance_to_coast_km", "maritime_band", "zones",
                "nearest_landing_centre", "destination distance/bearing")
    sources = ("ORCA gazetteer", "ORCA boundary layers")
    failure_behaviour = (
        "If no location can be resolved the agent fails and every downstream "
        "retrieval step is skipped - ORCA asks the user where they are rather "
        "than guessing a coastline")

    async def run(self, request: AgentRequest, trace: Trace) -> AgentResponse:
        ctx = request.context
        if ctx.location is None:
            return AgentResponse(
                agent=self.name, capability=self.capability,
                status=AgentStatus.FAILED, confidence=0.0,
                warnings=["No location in the query, in the session, or from the device."],
                error="location_not_found")

        point = ctx.location.point
        gz = get_gazetteer()
        evidence = []

        with trace.span("geo_compute", "compute"):
            band_id, band_label, coast_km = maritime_band(point)
            zones = zones_near(point, radius_km=request.options.get("zone_radius_km", 60.0))
            nearest = gz.nearest(point, limit=3)
            nearest_place, nearest_km = nearest[0]

        evidence.append(computed_evidence(
            "distance_to_coast_km", round(coast_km, 2), "km", self.name,
            transformation=("shortest great-circle distance from the query point to the "
                            "ORCA coastal baseline polyline"),
            dataset=f"{get_baseline().dataset_id}@{get_baseline().version}",
            location=point,
            notes="Baseline is approximate (order 10 km) and non-authoritative."))
        evidence.append(computed_evidence(
            "maritime_band", band_label, None, self.name,
            transformation=("UNCLOS distance definitions applied to the approximate "
                            "ORCA coastal baseline"),
            dataset="derived_maritime_bands", location=point,
            notes="Indicative band, not a determination of notified maritime limits."))

        destination_data = None
        if ctx.destination is not None:
            d_km = distance_km(point, ctx.destination.point, precise=True)
            bearing = initial_bearing_deg(point, ctx.destination.point)
            destination_data = {
                "name": ctx.destination.name,
                "point": ctx.destination.point.model_dump(),
                "distance_km": round(d_km, 2),
                "distance_nm": round(distance_nm(point, ctx.destination.point, True), 2),
                "bearing_deg": round(bearing, 1),
                "compass": compass_point(bearing),
            }
            evidence.append(computed_evidence(
                "route_distance_km", round(d_km, 2), "km", self.name,
                transformation="Vincenty inverse on the WGS84 ellipsoid",
                location=point))

        restricted = [z for z in zones
                      if z.category in ("restricted", "fishing_ban") and z.relation == "inside"]
        warnings = []
        for z in restricted:
            warnings.append(
                f"The point falls inside '{z.zone_name}'. This layer is illustrative, "
                "not an official notified area - confirm with the relevant authority.")

        return AgentResponse(
            agent=self.name, capability=self.capability, status=AgentStatus.OK,
            data={
                "point": point.model_dump(),
                "location": ctx.location.model_dump(mode="json"),
                "distance_to_coast_km": round(coast_km, 2),
                "maritime_band": {"id": band_id, "label": band_label,
                                  "authoritative": False},
                "zones": [z.model_dump(mode="json") for z in zones],
                "nearest_landing_centre": {
                    "name": nearest_place.name, "state": nearest_place.state,
                    "distance_km": round(nearest_km, 2),
                    "bearing_deg": round(initial_bearing_deg(point, nearest_place.point), 1),
                    "compass": compass_point(initial_bearing_deg(point, nearest_place.point)),
                },
                "nearby_places": [{"name": p.name, "distance_km": round(d, 1)}
                                  for p, d in nearest],
                "destination": destination_data,
                "layers": [l.model_dump(mode="json") for l in layer_catalogue()],
            },
            evidence=evidence, warnings=warnings, confidence=ctx.location.confidence,
            source_status={"GIS": "OK"})
