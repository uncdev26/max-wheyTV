"""Max WheyTV — Meta & Stream endpoints."""
import json
import base64
import re
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from server.config import (
    TMDB_API_KEY, TVDB_API_KEY, RPDB_KEY,
    MOVIEBOX_API, MOVIEBOX_HEADERS,
)

router = APIRouter()


def parse_config(config_str: str) -> dict:
    try:
        padding = 4 - (len(config_str) % 4)
        if padding != 4:
            config_str += "=" * padding
        decoded = base64.urlsafe_b64decode(config_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


# ─── META ENDPOINT ───────────────────────────────────────────

@router.get("/meta/{type}/{id}.json")
async def meta_endpoint(request: Request, type: str, id: str):
    """Return metadata for movies (TMDB), series (TVDB), and IPTV channels."""
    try:
        # IPTV channels
        if id.startswith("mwh_iptv_") or id.startswith("mwh_fifa_"):
            return JSONResponse({"meta": {
                "id": id, "type": type, "name": id.replace("mwh_iptv_", "").replace("mwh_fifa_", "FIFA "),
            }})

        # Anime with MAL ID
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
                            videos.append({
                                "id": f"mal_{mal_id}:{i+1}",
                                "title": f"Episode {i+1}",
                                "season": 1,
                                "episode": i + 1,
                            })
                        return JSONResponse({"meta": {
                            "id": id, "type": "series", "name": title,
                            "poster": poster,
                            "releaseInfo": str(year) if year else "",
                            "imdbRating": str(score) if score else None,
                            "genres": genres,
                            "description": synopsis[:500] if synopsis else "",
                            "videos": videos,
                            "posterShape": "poster",
                        }})
                except Exception as e:
                    print(f"[Meta] Jikan error: {e}")
            return JSONResponse({"meta": {"id": id, "type": "series", "name": "Unknown"}})

        # Movie/Series with IMDB ID
        if id.startswith("tt"):
            async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
                if type == "movie":
                    return await get_movie_meta(client, id)
                elif type == "series":
                    return await get_series_meta(client, id)

    except Exception as e:
        print(f"[Meta] Error: {e}")

    return JSONResponse({"meta": {"id": id, "type": type, "name": "Unknown"}})


async def get_movie_meta(client, imdb_id):
    """Get movie metadata from TMDB."""
    try:
        r = await client.get(f"https://api.themoviedb.org/3/find/{imdb_id}",
            params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"}, timeout=8)
        if r.status_code == 200:
            results = r.json().get("movie_results", [])
            if results:
                tmdb_id = results[0]["id"]
                d = await client.get(f"https://api.themoviedb.org/3/movie/{tmdb_id}",
                    params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
                if d.status_code == 200:
                    data = d.json()
                    poster = data.get("poster_path")
                    backdrop = data.get("backdrop_path")
                    return JSONResponse({"meta": {
                        "id": imdb_id, "type": "movie",
                        "name": data.get("title", ""),
                        "releaseInfo": (data.get("release_date") or "")[:4],
                        "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                        "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                        "description": (data.get("overview") or "")[:500],
                        "genres": [g["name"] for g in data.get("genres", [])],
                        "imdbRating": str(round(data.get("vote_average", 0), 1)) if data.get("vote_average") else None,
                        "posterShape": "poster",
                    }})
    except:
        pass
    return JSONResponse({"meta": {"id": imdb_id, "type": "movie", "name": "Unknown"}})


async def get_series_meta(client, imdb_id):
    """Get series metadata from TVDB."""
    try:
        # First try TMDB for series
        r = await client.get(f"https://api.themoviedb.org/3/find/{imdb_id}",
            params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"}, timeout=8)
        if r.status_code == 200:
            results = r.json().get("tv_results", [])
            if results:
                tmdb_id = results[0]["id"]
                d = await client.get(f"https://api.themoviedb.org/3/tv/{tmdb_id}",
                    params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
                if d.status_code == 200:
                    data = d.json()
                    poster = data.get("poster_path")
                    backdrop = data.get("backdrop_path")

                    # Build episodes list
                    videos = []
                    seasons = data.get("seasons", [])
                    for season in seasons:
                        s_num = season.get("season_number", 0)
                        if s_num == 0:
                            continue
                        s_detail = await client.get(
                            f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{s_num}",
                            params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
                        if s_detail.status_code == 200:
                            for ep in s_detail.json().get("episodes", []):
                                videos.append({
                                    "id": f"{imdb_id}:{s_num}:{ep.get('episode_number')}",
                                    "title": ep.get("name", ""),
                                    "season": s_num,
                                    "episode": ep.get("episode_number"),
                                    "released": (ep.get("air_date") or "")[:10],
                                    "overview": (ep.get("overview") or "")[:200],
                                })

                    return JSONResponse({"meta": {
                        "id": imdb_id, "type": "series",
                        "name": data.get("name", ""),
                        "releaseInfo": (data.get("first_air_date") or "")[:4],
                        "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                        "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                        "description": (data.get("overview") or "")[:500],
                        "genres": [g["name"] for g in data.get("genres", [])],
                        "imdbRating": str(round(data.get("vote_average", 0), 1)) if data.get("vote_average") else None,
                        "videos": videos[:200],
                        "posterShape": "poster",
                    }})
    except:
        pass
    return JSONResponse({"meta": {"id": imdb_id, "type": "series", "name": "Unknown"}})


# ─── STREAM ENDPOINT ─────────────────────────────────────────

@router.get("/{config}/stream/{type}/{id}.json")
async def stream_with_config(request: Request, config: str, type: str, id: str):
    return await handle_stream(request, type, id, config)


@router.get("/stream/{type}/{id}.json")
async def stream_no_config(request: Request, type: str, id: str):
    return await handle_stream(request, type, id, "")


async def handle_stream(request: Request, type: str, id: str, config_str: str):
    config = parse_config(config_str)

    # IPTV streams
    if id.startswith("mwh_iptv_") or id.startswith("mwh_fifa_"):
        return await get_iptv_stream(id)

    # Anime streams via MovieBox (search by title)
    if id.startswith("mal_"):
        mal_id = id.split(":")[0].replace("mal_", "")
        season = 1
        episode = 1
        parts = id.split(":")
        if len(parts) > 1:
            episode = int(parts[1])
        # Get anime title from Jikan
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
                r = await client.get(f"https://api.jikan.moe/v4/anime/{mal_id}", timeout=10)
                if r.status_code == 200:
                    anime = r.json().get("data", {})
                    title = anime.get("title_english") or anime.get("title", "")
                    if title:
                        # Search MovieBox for the anime
                        from streaming.provider import find_fast_matches, extract_streams
                        matches = await find_fast_matches(title, "", is_movie=False)
                        if matches:
                            stream_results = await extract_streams(matches, False, season, episode)
                            streams = []
                            seen = set()
                            for sd in stream_results:
                                dl = sd["download"]
                                url = str(dl.url)
                                base = url.split("?")[0]
                                if base in seen:
                                    continue
                                seen.add(base)
                                res = getattr(dl, "resolution", 0)
                                res_text = f"{res}p" if res else "?"
                                audio = sd.get("audio_lang", "")
                                streams.append({
                                    "name": "Max WheyTV",
                                    "title": f"🎬 {res_text} | 🔊 {audio or 'Original'}",
                                    "url": url,
                                    "behaviorHints": {
                                        "notWebReady": True,
                                        "proxyHeaders": {"request": {
                                            "Referer": "https://fmoviesunblocked.net/",
                                            "User-Agent": "Mozilla/5.0",
                                        }},
                                    },
                                })
                            return JSONResponse({"streams": streams})
        except Exception as e:
            print(f"[Stream] Anime error: {e}")
        return JSONResponse({"streams": []})

    # Movie/Series streams via MovieBox
    if id.startswith("tt"):
        return await get_moviebox_stream(request, type, id, config)

    return JSONResponse({"streams": []})


async def get_iptv_stream(id: str):
    """Get IPTV stream URL."""
    import os
    benchmark_dir = "data"

    try:
        # FIFA streams
        if id.startswith("mwh_fifa_"):
            idx = int(id.replace("mwh_fifa_", ""))
            with open(os.path.join(benchmark_dir, "fifa_streams.json")) as f:
                streams = json.load(f)
            if idx < len(streams):
                s = streams[idx]
                return JSONResponse({"streams": [{
                    "name": "Max WheyTV",
                    "title": f"⚽ {s.get('name', 'FIFA')}",
                    "url": s["url"],
                    "isLive": True,
                }]})

        # IPTV streams
        if id.startswith("mwh_iptv_"):
            idx = int(id.replace("mwh_iptv_", ""))
            # Load all HQ streams
            with open(os.path.join(benchmark_dir, "hq_streams.json")) as f:
                streams = json.load(f)
            if idx < len(streams):
                s = streams[idx]
                return JSONResponse({"streams": [{
                    "name": "Max WheyTV",
                    "title": f"📺 {s.get('name', 'Live TV')} | {s.get('quality', '')} | {s.get('latency_ms', '')}ms",
                    "url": s["url"],
                    "isLive": True,
                }]})
    except:
        pass

    return JSONResponse({"streams": []})


async def get_moviebox_stream(request: Request, type: str, imdb_id: str, config: dict):
    """Get MovieBox streams for a movie/series."""
    min_res = config.get("resolution", "all")
    pref_langs = config.get("languages", [config.get("language", "all")])
    if isinstance(pref_langs, str):
        pref_langs = [pref_langs]
    all_langs = "all" in pref_langs

    LANG_MAP = {
        "en": "english", "hi": "hindi", "es": "spanish", "fr": "french",
        "de": "german", "it": "italian", "pt": "portuguese", "ru": "russian",
        "ja": "japanese", "ko": "korean", "zh": "chinese", "ar": "arabic",
        "tr": "turkish", "th": "thai", "pl": "polish", "ta": "tamil", "te": "telugu",
    }
    pref_lang_names = [LANG_MAP.get(l, l) for l in pref_langs]

    # Platform detection
    platform = config.get("platform", "auto")
    if platform == "auto":
        ua = (request.headers.get("user-agent") or "").lower()
        if "android tv" in ua or "fire tv" in ua:
            platform = "tv"
        elif "android" in ua or "iphone" in ua:
            platform = "mobile"
        else:
            platform = "desktop"
    fast_mode = platform in ("tv", "mobile")

    # Parse series ID
    parts = id.split(":")
    actual_imdb = parts[0]
    season = int(parts[1]) if len(parts) > 1 else 1
    episode = int(parts[2]) if len(parts) > 2 else 1

    # Resolve IMDB to title via TMDB
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

    # Fetch streams from MovieBox
    try:
        from streaming.provider import find_fast_matches, find_all_matches, extract_streams

        if fast_mode:
            matches = await find_fast_matches(title, year, is_movie=(type == "movie"))
        else:
            matches = await find_all_matches(title, year, is_movie=(type == "movie"))

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

        def sort_key(x):
            res = getattr(x["download"], "resolution", 0)
            lang_match = 0
            audio_lang = x.get("audio_lang")
            if not all_langs and lang_matches(audio_lang):
                lang_match = 1
            return (lang_match, res)

        stream_results.sort(key=sort_key, reverse=True)

        streams = []
        seen_urls = set()

        for stream_data in stream_results:
            dl = stream_data["download"]
            audio_lang = stream_data["audio_lang"]
            subtitle_langs = stream_data["subtitle_langs"]

            url_str = str(dl.url)
            base_dl_url = url_str.split("?")[0] if "?" in url_str else url_str
            if base_dl_url in seen_urls:
                continue
            seen_urls.add(base_dl_url)

            resolution = getattr(dl, "resolution", 0)
            size = getattr(dl, "size", 0)

            if min_res == "4k" and resolution < 2160:
                continue
            elif min_res == "1080p" and resolution < 1080:
                continue
            elif min_res == "720p" and resolution < 720:
                continue

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
            desc = "\n".join(desc_parts)

            streams.append({
                "name": "Max WheyTV",
                "title": desc,
                "url": url_str,
                "poster": f"https://api.ratingposterdb.com/{RPDB_KEY}/imdb/poster-default/{actual_imdb}.jpg",
                "behaviorHints": {
                    "notWebReady": True,
                    "filename": url_str.split("/")[-1].split("?")[0] if "/" in url_str else None,
                    "proxyHeaders": {
                        "request": {
                            "Referer": "https://fmoviesunblocked.net/",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        }
                    },
                },
            })

        return JSONResponse({"streams": streams})

    except Exception as e:
        print(f"[Stream] Error: {e}")
        return JSONResponse({"streams": []})
