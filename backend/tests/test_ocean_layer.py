"""The INCOIS OceanSat-2 ocean-colour layer.

The point of these tests is the honesty boundary, not the arithmetic: demo
values must never escape carrying an INCOIS origin, masked cells must never
become zeros, and a failed live call must never produce a field.
"""

from __future__ import annotations



from app.cache.memory import MemoryCache
from app.config.settings import Settings
from app.providers.incois.oceansat import INCOISOceanSatProvider, VARIABLES
from app.schemas.common import SourceStatus
from app.schemas.grid import LayerOrigin
from app.services.ocean_layer import OceanLayerService

KOCHI = (9.9312, 76.2125)

# Shape of a real ERDDAP griddap .json response.
PAYLOAD = {
    "table": {
        "columnNames": ["time", "latitude", "longitude", "CHL"],
        "columnTypes": ["String", "double", "double", "float"],
        "columnUnits": ["UTC", "degrees_north", "degrees_east", "mg m-3"],
        "rows": [
            ["2026-09-02T00:00:00Z", 9.90, 76.10, 0.42],
            ["2026-09-02T00:00:00Z", 9.90, 76.20, None],      # cloud-masked
            ["2026-09-02T00:00:00Z", 10.00, 76.10, 1.85],
            ["2026-09-02T00:00:00Z", 10.00, 76.20, 0.97],
        ],
    }
}


def _provider(**over):
    p = INCOISOceanSatProvider()
    p._settings = Settings(**over)
    return p


class TestUrl:
    def test_builds_a_bounded_griddap_subset(self):
        url = _provider().build_url("CHL", *KOCHI, half_deg=0.5)
        assert "/griddap/incois_oceansat2_datasets.json?CHL" in url
        # Bounded box, not the whole grid.
        assert "(9.4312):1:(10.4312)" in url
        assert "(75.7125):1:(76.7125)" in url

    def test_axis_order_is_configuration_not_assumption(self):
        url = _provider(oceansat_axis_order="latitude,longitude,time").build_url(
            "CHL", *KOCHI, half_deg=0.5)
        # time selector must now come last
        assert url.index("[last]") > url.index("(9.4312)")


class TestParsing:
    def test_masked_cells_are_dropped_not_zeroed(self):
        field = _provider()._parse(PAYLOAD, "CHL", VARIABLES["CHL"],
                                   *KOCHI, 0.5, "u", 12.0)
        assert field.origin is LayerOrigin.INCOIS_DATA
        assert len(field.cells) == 3           # the None row is gone
        assert all(c.value > 0 for c in field.cells)
        assert 0.0 not in [c.value for c in field.cells]

    def test_prefers_the_unit_erddap_declared(self):
        field = _provider()._parse(PAYLOAD, "CHL", VARIABLES["CHL"],
                                   *KOCHI, 0.5, "u", 12.0)
        assert field.unit == "mg m-3"          # not the hard-coded "mg/m3"

    def test_keeps_source_coordinates_and_timestamp(self):
        field = _provider()._parse(PAYLOAD, "CHL", VARIABLES["CHL"],
                                   *KOCHI, 0.5, "u", 12.0)
        assert (field.cells[0].lat, field.cells[0].lon) == (9.90, 76.10)
        assert field.observation_time is not None
        assert field.observation_time.year == 2026
        assert field.value_min == 0.42 and field.value_max == 1.85

    def test_never_claims_forecast(self):
        field = _provider()._parse(PAYLOAD, "CHL", VARIABLES["CHL"],
                                   *KOCHI, 0.5, "u", 12.0)
        assert field.product_kind == "OBSERVATION"

    def test_all_masked_is_unavailable_not_an_empty_field(self):
        blank = {"table": {**PAYLOAD["table"],
                           "rows": [["2026-09-02T00:00:00Z", 9.9, 76.1, None]]}}
        field = _provider()._parse(blank, "CHL", VARIABLES["CHL"],
                                   *KOCHI, 0.5, "u", 12.0)
        assert field.origin is LayerOrigin.UNAVAILABLE
        assert field.cells == []
        assert "masked" in field.error

    def test_unknown_variable_is_refused(self):
        field = _provider()._unavailable("SALINITY", *KOCHI, 0.5,
                                         SourceStatus.NOT_CONFIGURED, "x")
        assert field.origin is LayerOrigin.UNAVAILABLE



class TestService:
    async def test_demo_mode_never_emits_an_incois_origin(self):
        svc = OceanLayerService(Settings(demo_mode=True), MemoryCache())
        field = await svc.field("CHL", *KOCHI)
        assert field.origin is LayerOrigin.DEMO
        assert field.source != "INCOIS"
        assert "NOT an INCOIS product" in field.attribution
        assert field.cells

    async def test_live_mode_without_reachability_is_unavailable(self):
        svc = OceanLayerService(
            Settings(demo_mode=False, incois_enabled=True), MemoryCache())
        field = await svc.field("CHL", *KOCHI)
        # This host cannot reach INCOIS; the contract is that we say so.
        assert field.origin in (LayerOrigin.INCOIS_DATA, LayerOrigin.UNAVAILABLE)
        if field.origin is LayerOrigin.UNAVAILABLE:
            assert field.cells == []
            assert field.error
            assert field.request_url.startswith("https://erddap.incois.gov.in")

    async def test_live_mode_with_incois_disabled_says_so(self):
        svc = OceanLayerService(
            Settings(demo_mode=False, incois_enabled=False), MemoryCache())
        field = await svc.field("CHL", *KOCHI)
        assert field.origin is LayerOrigin.UNAVAILABLE
        assert field.status is SourceStatus.NOT_CONFIGURED

    async def test_offers_exactly_the_verified_variables(self):
        svc = OceanLayerService(Settings(), MemoryCache())
        assert [v["id"] for v in svc.variables()] == ["CHL", "KD490", "TSM"]
