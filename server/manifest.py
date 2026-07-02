"""Max WheyTV — Manifest. Streams only for movies/series. Full IPTV/FIFA/Anime."""
from pydantic import BaseModel


class Manifest(BaseModel):
    id: str
    version: str
    name: str
    description: str
    resources: list
    types: list[str]
    catalogs: list
    idPrefixes: list[str]
    logo: str | None = None
    background: str | None = None
    behaviorHints: dict | None = None


def get_manifest(config: dict = None) -> Manifest:
    config = config or {}
    iptv_enabled = config.get("iptv", True)
    fifa_enabled = config.get("fifa", True)
    anime_enabled = config.get("anime", True)

    catalogs = []

    # Anime catalogs
    if anime_enabled:
        catalogs.extend([
            {"id": "mwh_anime_top",      "type": "series", "name": "🏆 Top Anime"},
            {"id": "mwh_anime_seasonal", "type": "series", "name": "🌸 Seasonal Anime"},
        ])

    # IPTV catalogs
    if iptv_enabled:
        iptv_countries = config.get("iptv_countries", ["All"])
        if "All" in iptv_countries:
            catalogs.append({"id": "mwh_iptv_all", "type": "tv", "name": "📺 All Live TV"})
        else:
            for country in iptv_countries:
                safe = country.lower().replace(" ", "_")
                catalogs.append({"id": f"mwh_iptv_{safe}", "type": "tv", "name": f"📺 {country} TV"})

    # FIFA
    if fifa_enabled:
        catalogs.append({"id": "mwh_fifa", "type": "tv", "name": "⚽ FIFA & Football"})

    return Manifest(
        id="com.maxwheytv.addon",
        version="1.0.0",
        name="Max WheyTV",
        description="Universal streaming — IPTV, FIFA, Anime & MovieBox streams.",
        resources=[
            # Movie/Series streams only (no catalog — use Netflix addon for catalogs)
            {"name": "stream", "types": ["movie", "series"], "idPrefixes": ["tt"]},
            # IPTV: full catalog + meta + stream
            {"name": "catalog", "types": ["tv"], "idPrefixes": ["mwh_"]},
            {"name": "meta",    "types": ["tv"], "idPrefixes": ["mwh_"]},
            {"name": "stream",  "types": ["tv"], "idPrefixes": ["mwh_"]},
        ],
        types=["movie", "series", "tv"],
        catalogs=catalogs,
        idPrefixes=["tt", "mwh_"],
        background="https://raw.githubusercontent.com/Stremio/stremio-art/main/originals/Ahlen%20Ken%20A.%20Batalon.png",
        behaviorHints={"configurable": True, "configurationRequired": False},
    )
