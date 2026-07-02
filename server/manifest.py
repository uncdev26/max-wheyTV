"""Max WheyTV — Manifest. TMDB catalog + IPTV + streams."""
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
    movies_enabled = config.get("movies", True)
    iptv_enabled = config.get("iptv", True)
    fifa_enabled = config.get("fifa", True)
    anime_enabled = config.get("anime", True)
    languages = config.get("languages", ["all"])

    catalogs = []

    # Movie catalogs (TMDB Discover — ALL languages)
    if movies_enabled:
        catalogs.extend([
            {"id": "mwh_popular",    "type": "movie",  "name": "🔥 Popular Movies"},
            {"id": "mwh_trending",   "type": "movie",  "name": "📈 Trending Now"},
            {"id": "mwh_top_rated",  "type": "movie",  "name": "⭐ Top Rated"},
            {"id": "mwh_new",        "type": "movie",  "name": "🆕 New Releases"},
        ])

        # Language-specific catalogs
        if "all" not in languages:
            lang_names = {
                "hi": "Hindi", "en": "English", "es": "Spanish", "fr": "French",
                "de": "German", "pt": "Portuguese", "ru": "Russian", "ja": "Japanese",
                "ko": "Korean", "zh": "Chinese", "ar": "Arabic", "tr": "Turkish",
                "ta": "Tamil", "te": "Telugu", "th": "Thai",
            }
            for lang in languages:
                if lang in lang_names:
                    catalogs.append({"id": f"mwh_lang_{lang}", "type": "movie", "name": f"🎬 {lang_names[lang]} Movies"})

        # Series catalogs
        catalogs.extend([
            {"id": "mwh_popular_series", "type": "series", "name": "📺 Popular Series"},
            {"id": "mwh_airing_today",   "type": "series", "name": "📅 Airing Today"},
        ])

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
        description="Universal streaming — Movies, Series & Live TV from every corner of the world.",
        resources=[
            # Movies/Series: catalog + stream (Cinemeta handles metadata)
            {"name": "catalog", "types": ["movie", "series"], "idPrefixes": ["tt", "tmdb_"]},
            {"name": "stream",  "types": ["movie", "series"], "idPrefixes": ["tt", "tmdb_"]},
            # IPTV: full catalog + meta + stream
            {"name": "catalog", "types": ["tv"], "idPrefixes": ["mwh_"]},
            {"name": "meta",    "types": ["tv"], "idPrefixes": ["mwh_"]},
            {"name": "stream",  "types": ["tv"], "idPrefixes": ["mwh_"]},
        ],
        types=["movie", "series", "tv"],
        catalogs=catalogs,
        idPrefixes=["tt", "mwh_", "tmdb_"],
        background="https://raw.githubusercontent.com/Stremio/stremio-art/main/originals/Ahlen%20Ken%20A.%20Batalon.png",
        behaviorHints={"configurable": True, "configurationRequired": False},
    )
