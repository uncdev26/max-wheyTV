"""Max WheyTV — Meta & Stream endpoints."""
import json
import os
import base64
import re
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from server.config import TMDB_API_KEY, TVDB_API_KEY, RPDB_KEY

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def parse_config(config_str: str) -> dict:
    try:
        padding = 4 - (len(config_str) % 4)
        if padding != 4:
            config_str += "=" * padding
        decoded = base64.urlsafe_b64decode(config_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


# ─── META ────────────────────────────────────────────────────

@router.get("/meta/{type}/{id}.json")
async def meta_endpoint(request: Request, type: str, id: str):
    try:
        # IPTV channels — minimal meta
        if id.startswith("mwh_iptv_") or id.startswith("mwh_fifa_"):
            return JSONResponse({"meta": {"id": id, "type": type, "name": id.split("_", 2)[-1].replace("_", " ").title()}})

        # Anime (MAL)
        if id.startswith("mal_"):
            mal_id = id.replace("mal_", "")
            async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
                try:
                    r = await client.get(f"https://api.jikan.moe/v4/anime/{mal_id}/full", timeout=10)
                    if r.status_code == 200:
                        anime = r.json().get("data", {})
                        title = anime.get("title_english") or anime.get("title", "")
                        images = anime.get("images", {}).get("jpg", {})
                        poster = images.get("large_image_url")
                        episodes = anime.get("episodes") or 0
                        synopsis = anime.get("synopsis", "")
                        score = anime.get("score")
                        year = anime.get("year") or (anime.get("aired", {}).get("from", "") or "")[:4]
                        genres = [g["name"] for g in anime.get("genres", [])]
                        videos = []
                        for i in range(min(episodes, 200)):
                            videos.append({"id": f"mal_{mal_id}:{i+1}", "title": f"Episode {i+1}", "season": 1, "episode": i + 1})
                        return JSONResponse({"meta": {
                            "id": id, "type": "series", "name": title,
                            "poster": poster, "releaseInfo": str(year) if year else "",
                            "imdbRating": str(score) if score else None,
                            "genres": genres, "description": synopsis[:500] if synopsis else "",
                            "videos": videos, "posterShape": "poster",
                        }})
                except Exception as e:
                    print(f"[Meta] Jikan error: {e}")
            return JSONResponse({"meta": {"id": id, "type": "series", "name": "Unknown"}})

        # Movies/Series with IMDB ID
        if id.startswith("tt"):
            async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
                # Find on TMDB
                r = await client.get(f"https://api.themoviedb.org/3/find/{id}",
                    params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"}, timeout=8)
                if r.status_code == 200:
                    movie_results = r.json().get("movie_results", [])
                    tv_results = r.json().get("tv_results", [])

                    if movie_results:
                        tmdb_id = movie_results[0]["id"]
                        d = await client.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}",
                            params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
                        if d.status_code == 200:
                            data = d.json()
                            poster = data.get("poster_path")
                            backdrop = data.get("backdrop_path")
                            return JSONResponse({"meta": {
                                "id": id, "type": "movie", "name": data.get("title", ""),
                                "releaseInfo": (data.get("release_date") or "")[:4],
                                "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                                "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                                "description": (data.get("overview") or "")[:500],
                                "genres": [g["name"] for g in data.get("genres", [])],
                                "imdbRating": str(round(data.get("vote_average", 0), 1)) if data.get("vote_average") else None,
                                "posterShape": "poster",
                            }})

                    if tv_results:
                        tmdb_id = tv_results[0]["id"]
                        d = await client.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                            params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
                        if d.status_code == 200:
                            data = d.json()
                            poster = data.get("poster_path")
                            backdrop = data.get("backdrop_path")

                            # Build episode list
                            videos = []
                            for season in data.get("seasons", []):
                                s_num = season.get("season_number", 0)
                                if s_num == 0:
                                    continue
                                s_detail = await client.get(
                                    f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{s_num}",
                                    params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
                                if s_detail.status_code == 200:
                                    for ep in s_detail.json().get("episodes", []):
                                        videos.append({
                                            "id": f"{id}:{s_num}:{ep.get('episode_number')}",
                                            "title": ep.get("name", ""),
                                            "season": s_num,
                                            "episode": ep.get("episode_number"),
                                            "released": (ep.get("air_date") or "")[:10],
                                        })

                            return JSONResponse({"meta": {
                                "id": id, "type": "series", "name": data.get("name", ""),
                                "releaseInfo": (data.get("first_air_date") or "")[:4],
                                "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                                "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                                "description": (data.get("overview") or "")[:500],
                                "genres": [g["name"] for g in data.get("genres", [])],
                                "imdbRating": str(round(data.get("vote_average", 0), 1)) if data.get("vote_average") else None,
                                "videos": videos[:200], "posterShape": "poster",
                            }})

    except Exception as e:
        print(f"[Meta] Error: {e}")

    return JSONResponse({"meta": {"id": id, "type": type, "name": "Unknown"}})


# ─── STREAM ──────────────────────────────────────────────────

@router.get("/{config}/stream/{type}/{id}.json")
async def stream_with_config(request: Request, config: str, type: str, id: str):
    return await handle_stream(request, type, id, config)


@router.get("/stream/{type}/{id}.json")
async def stream_no_config(request: Request, type: str, id: str):
    return await handle_stream(request, type, id, "")


async def handle_stream(request: Request, type: str, id: str, config_str: str):
    config = parse_config(config_str)
    min_res = config.get("resolution", "1080p")

    # ── IPTV streams ─────────────────────────────────────────
    if id.startswith("mwh_iptv_"):
        return get_iptv_stream(id, min_res)

    if id.startswith("mwh_fifa_"):
        return get_fifa_stream(id, min_res)

    # ── Anime streams via MovieBox ───────────────────────────
    if id.startswith("mal_"):
        return await get_anime_stream(id)

    # ── Movie/Series streams via MovieBox ────────────────────
    if id.startswith("tt"):
        return await get_moviebox_stream(request, type, id, config)

    return JSONResponse({"streams": []})


def get_iptv_stream(id: str, min_res: str):
    """Get IPTV stream by ID."""
    try:
        # ID format: mwh_iptv_{index}_{country}
        parts = id.replace("mwh_iptv_", "").split("_", 1)
        idx = int(parts[0])
        country = parts[1] if len(parts) > 1 else "all"

        if country == "all":
            streams = load_all_iptv()
        else:
            streams = load_country_iptv(country)

        streams = filter_streams_by_resolution(streams, min_res)

        if idx < len(streams):
            s = streams[idx]
            return JSONResponse({"streams": [{
                "name": "Max WheyTV",
                "title": f"📺 {s.get('name', 'Live TV')} | {s.get('quality', '')} | {s.get('latency_ms', '')}ms",
                "url": s["url"],
                "isLive": True,
            }]})
    except Exception as e:
        print(f"[Stream] IPTV error: {e}")
    return JSONResponse({"streams": []})


def get_fifa_stream(id: str, min_res: str):
    """Get FIFA stream by ID."""
    try:
        idx = int(id.replace("mwh_fifa_", ""))
        filepath = os.path.join(DATA_DIR, "fifa_streams.json")
        if os.path.exists(filepath):
            with open(filepath) as f:
                streams = json.load(f)
            streams = filter_streams_by_resolution(streams, min_res)
            if idx < len(streams):
                s = streams[idx]
                return JSONResponse({"streams": [{
                    "name": "Max WheyTV",
                    "title": f"⚽ {s.get('name', 'FIFA')} | {s.get('quality', '')}",
                    "url": s["url"],
                    "isLive": True,
                }]})
    except Exception as e:
        print(f"[Stream] FIFA error: {e}")
    return JSONResponse({"streams": []})


async def get_anime_stream(id: str):
    """Get anime stream by searching MovieBox."""
    try:
        parts = id.split(":")
        mal_id = parts[0].replace("mal_", "")
        episode = int(parts[1]) if len(parts) > 1 else 1

        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            r = await client.get(f"https://api.jikan.moe/v4/anime/{mal_id}", timeout=10)
            if r.status_code == 200:
                anime = r.json().get("data", {})
                title = anime.get("title_english") or anime.get("title", "")
                if title:
                    return await search_moviebox_for_streams(title, "series", 1, episode)
    except Exception as e:
        print(f"[Stream] Anime error: {e}")
    return JSONResponse({"streams": []})


async def get_moviebox_stream(request: Request, type: str, imdb_id: str, config: dict):
    """Get MovieBox streams for a movie/series."""
    pref_langs = config.get("languages", [config.get("language", "all")])
    if isinstance(pref_langs, str):
        pref_langs = [pref_langs]
    all_langs = "all" in pref_langs

    # Parse series ID
    parts = imdb_id.split(":")
    actual_imdb = parts[0]
    season = int(parts[1]) if len(parts) > 1 else 1
    episode = int(parts[2]) if len(parts) > 2 else 1

    # Resolve IMDB to title
    title = ""
    year = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            r = await client.get(f"https://api.themoviedb.org/3/find/{actual_imdb}",
                params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"}, timeout=8)
            if r.status_code == 200:
                results = r.json().get("movie_results", []) or r.json().get("tv_results", [])
                if results:
                    title = results[0].get("title") or results[0].get("name", "")
                    year = (results[0].get("release_date") or results[0].get("first_air_date") or "")[:4]
    except:
        pass

    if not title:
        return JSONResponse({"streams": []})

    return await search_moviebox_for_streams(title, type, season, episode, actual_imdb, pref_langs, all_langs)


async def search_moviebox_for_streams(title: str, type: str, season: int, episode: int,
                                       imdb_id: str = "", pref_langs: list = None, all_langs: bool = True):
    """Search MovieBox and return streams."""
    pref_langs = pref_langs or ["all"]
    LANG_MAP = {
        "en": "english", "hi": "hindi", "es": "spanish", "fr": "french",
        "de": "german", "it": "italian", "pt": "portuguese", "ru": "russian",
        "ja": "japanese", "ko": "korean", "zh": "chinese", "ar": "arabic",
        "tr": "turkish", "th": "thai", "pl": "polish", "ta": "tamil", "te": "telugu",
    }
    pref_lang_names = [LANG_MAP.get(l, l) for l in pref_langs]

    try:
        from streaming.provider import find_fast_matches, find_all_matches, extract_streams

        matches = await find_fast_matches(title, "", is_movie=(type == "movie"))
        if not matches:
            return JSONResponse({"streams": []})

        stream_results = await extract_streams(matches, type == "movie", season, episode)

        def lang_matches(audio_lang):
            if not audio_lang:
                return "orig" in pref_langs
            al = audio_lang.lower()
            for lp in pref_lang_names:
                if lp in al:
                    return True
            for lp in pref_langs:
                if lp != "all" and lp != "orig" and lp in al:
                    return True
            return False

        stream_results.sort(key=lambda x: (0 if (not all_langs and lang_matches(x.get("audio_lang"))) else 1, -getattr(x["download"], "resolution", 0)))

        streams = []
        seen_urls = set()

        for sd in stream_results:
            dl = sd["download"]
            audio_lang = sd.get("audio_lang")
            subtitle_langs = sd.get("subtitle_langs", [])
            url = str(dl.url)
            base_url = url.split("?")[0]
            if base_url in seen_urls:
                continue
            seen_urls.add(base_url)

            resolution = getattr(dl, "resolution", 0)
            size = getattr(dl, "size", 0)

            if not all_langs and not lang_matches(audio_lang):
                continue

            res_text = f"{resolution}p" if resolution else "?"
            size_text = f"{size / (1024*1024):.0f} MB" if size else ""
            lang_text = f"🔊 {audio_lang}" if audio_lang else ""

            desc_parts = [f"🎬 {res_text}"]
            if size_text:
                desc_parts[0] += f" • 💾 {size_text}"
            if lang_text:
                desc_parts.append(lang_text)
            if subtitle_langs:
                desc_parts.append(f"💬 {', '.join(subtitle_langs[:3])}")

            streams.append({
                "name": "Max WheyTV",
                "title": "\n".join(desc_parts),
                "url": url,
                "poster": f"https://api.ratingposterdb.com/t0-free-rpdb/imdb/poster-default/{imdb_id}.jpg" if imdb_id else None,
                "behaviorHints": {
                    "notWebReady": True,
                    "proxyHeaders": {"request": {
                        "Referer": "https://fmoviesunblocked.net/",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    }},
                },
            })

        return JSONResponse({"streams": streams})

    except Exception as e:
        print(f"[Stream] MovieBox error: {e}")
        return JSONResponse({"streams": []})


# ─── Helpers ─────────────────────────────────────────────────

def load_all_iptv():
    all_streams = []
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.startswith("hq_") and fname.endswith(".json"):
            with open(os.path.join(DATA_DIR, fname)) as f:
                all_streams.extend(json.load(f))
    return all_streams


def load_country_iptv(country):
    filepath = os.path.join(DATA_DIR, f"hq_{country}.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return []


def filter_streams_by_resolution(streams, min_res):
    if min_res == "all":
        return streams
    filtered = []
    for s in streams:
        q = s.get("quality", "Unknown")
        name = s.get("name", "").lower()
        if "geo-blocked" in name:
            continue
        if min_res == "4k" and q == "4K":
            filtered.append(s)
        elif min_res == "1080p" and q in ("4K", "1080p"):
            filtered.append(s)
        elif min_res == "720p" and q in ("4K", "1080p", "720p"):
            filtered.append(s)
    return filtered
