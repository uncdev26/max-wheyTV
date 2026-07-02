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
    """Return metadata for any ID format."""
    try:
        # ── IPTV channels ────────────────────────────────────
        if id.startswith("mwh_iptv_"):
            return get_iptv_meta(id)

        if id.startswith("mwh_fifa_"):
            return get_fifa_meta(id)

        # ── Anime (MAL) ──────────────────────────────────────
        if id.startswith("mwh_mal_"):
            return await get_anime_meta(id)

        # ── Movies/Series (mwh_ prefix with IMDB ID) ─────────

        # ── Direct IMDB ID ───────────────────────────────────
        if id.startswith("tt"):
            return await get_tmdb_meta(id, type)

        # ── TMDB IDs ─────────────────────────────────────────
        if id.startswith("tmdb_"):
            tmdb_id = id.replace("tmdb_", "")
            return await get_tmdb_meta_by_id(tmdb_id, type)

    except Exception as e:
        print(f"[Meta] Error for {id}: {e}")

    return JSONResponse({"meta": {"id": id, "type": type, "name": "Unknown"}})


def get_iptv_meta(id: str):
    """Get IPTV channel metadata."""
    try:
        parts = id.replace("mwh_iptv_", "").split("_", 1)
        idx = int(parts[0])
        country = parts[1] if len(parts) > 1 else "all"

        streams = load_iptv(country)
        if idx < len(streams):
            s = streams[idx]
            name = s.get("name", "Unknown")
            quality = s.get("quality", "")
            latency = s.get("latency_ms", "")
            logo = s.get("logo") or s.get("tvg_logo") or get_channel_logo(name)

            return JSONResponse({"meta": {
                "id": id, "type": "tv", "name": name,
                "poster": logo,
                "background": logo,
                "description": f"Watch {name} ({quality}) — {latency}ms latency",
            }})
    except Exception as e:
        print(f"[Meta] IPTV error: {e}")

    return JSONResponse({"meta": {"id": id, "type": "tv", "name": "Live TV"}})


def get_fifa_meta(id: str):
    """Get FIFA channel metadata."""
    try:
        idx = int(id.replace("mwh_fifa_", ""))
        streams = load_fifa()
        if idx < len(streams):
            s = streams[idx]
            return JSONResponse({"meta": {
                "id": id, "type": "tv", "name": s.get("name", "FIFA"),
                "poster": "https://img.icons8.com/color/200/soccer-ball.png",
                "background": "https://img.icons8.com/color/200/soccer-ball.png",
                "description": f"{s.get('quality', '')} | FIFA & Football",
                "posterShape": "square",
            }})
    except:
        pass
    return JSONResponse({"meta": {"id": id, "type": "tv", "name": "FIFA"}})


async def get_anime_meta(id: str):
    """Get anime metadata from Jikan."""
    try:
        mal_id = id.replace("mwh_mal_", "")
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
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
                        "id": f"mwh_mal_{mal_id}:{i+1}",
                        "title": f"Episode {i+1}",
                        "season": 1, "episode": i + 1,
                    })
                return JSONResponse({"meta": {
                    "id": id, "type": "series", "name": title,
                    "poster": poster, "background": poster,
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


async def get_tmdb_meta(imdb_id: str, type: str):
    """Get movie/series metadata from TMDB."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            r = await client.get(f"https://api.themoviedb.org/3/find/{imdb_id}",
                params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"}, timeout=8)
            if r.status_code != 200:
                return JSONResponse({"meta": {"id": imdb_id, "type": type, "name": "Unknown"}})

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
                        "id": imdb_id, "type": "movie", "name": data.get("title", ""),
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
                                    "id": f"{imdb_id}:{s_num}:{ep.get('episode_number')}",
                                    "title": ep.get("name", ""),
                                    "season": s_num, "episode": ep.get("episode_number"),
                                    "released": (ep.get("air_date") or "")[:10],
                                })
                    return JSONResponse({"meta": {
                        "id": imdb_id, "type": "series", "name": data.get("name", ""),
                        "releaseInfo": (data.get("first_air_date") or "")[:4],
                        "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                        "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                        "description": (data.get("overview") or "")[:500],
                        "genres": [g["name"] for g in data.get("genres", [])],
                        "imdbRating": str(round(data.get("vote_average", 0), 1)) if data.get("vote_average") else None,
                        "videos": videos[:200], "posterShape": "poster",
                    }})

    except Exception as e:
        print(f"[Meta] TMDB error: {e}")

    return JSONResponse({"meta": {"id": imdb_id, "type": type, "name": "Unknown"}})


async def get_tmdb_meta_by_id(tmdb_id: str, type: str):
    """Get metadata directly from TMDB ID."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            endpoint = "movie" if type == "movie" else "tv"
            r = await client.get(f"https://api.themoviedb.org/3/{endpoint}/{tmdb_id}",
                params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=8)
            if r.status_code == 200:
                data = r.json()
                poster = data.get("poster_path")
                backdrop = data.get("backdrop_path")
                title = data.get("title") or data.get("name", "")
                year = (data.get("release_date") or data.get("first_air_date") or "")[:4]
                rating = data.get("vote_average")
                overview = data.get("overview", "")
                genres = [g["name"] for g in data.get("genres", [])]

                meta = {
                    "id": f"tmdb_{tmdb_id}", "type": type, "name": title,
                    "releaseInfo": year,
                    "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                    "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                    "description": overview[:500] if overview else "",
                    "genres": genres,
                    "imdbRating": str(round(rating, 1)) if rating else None,
                    "posterShape": "poster",
                }

                # Add episodes for series
                if type == "series":
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
                                    "id": f"tmdb_{tmdb_id}:{s_num}:{ep.get('episode_number')}",
                                    "title": ep.get("name", ""),
                                    "season": s_num, "episode": ep.get("episode_number"),
                                    "released": (ep.get("air_date") or "")[:10],
                                })
                    meta["videos"] = videos[:200]

                return JSONResponse({"meta": meta})
    except Exception as e:
        print(f"[Meta] TMDB error: {e}")
    return JSONResponse({"meta": {"id": f"tmdb_{tmdb_id}", "type": type, "name": "Unknown"}})


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

    # ── IPTV ─────────────────────────────────────────────────
    if id.startswith("mwh_iptv_"):
        return get_iptv_stream(id, min_res)

    if id.startswith("mwh_fifa_"):
        return get_fifa_stream(id, min_res)

    # ── Anime ────────────────────────────────────────────────
    if id.startswith("mwh_mal_"):
        return await get_anime_stream(id)

    # ── Movies/Series ────────────────────────────────────────
    if id.startswith("tt"):
        imdb_id = id.replace("mwh_", "")
        return await get_moviebox_stream(request, type, imdb_id, config)

    return JSONResponse({"streams": []})


def get_iptv_stream(id: str, min_res: str):
    try:
        parts = id.replace("mwh_iptv_", "").split("_", 1)
        idx = int(parts[0])
        country = parts[1] if len(parts) > 1 else "all"
        streams = load_iptv(country)
        streams = filter_streams(streams, min_res)
        if idx < len(streams):
            s = streams[idx]
            name = s.get("name", "Unknown")
            quality = s.get("quality", "")
            latency = s.get("latency_ms", "")
            logo = s.get("logo") or s.get("tvg_logo") or get_channel_logo(name)
            return JSONResponse({"streams": [{
                "name": "Max WheyTV",
                "title": f"📺 {name} | {quality} | {latency}ms",
                "url": s["url"],
                "isLive": True,
                "poster": logo,
                "behaviorHints": {"notWebReady": True},
            }]})
    except Exception as e:
        print(f"[Stream] IPTV error: {e}")
    return JSONResponse({"streams": []})


def get_fifa_stream(id: str, min_res: str):
    try:
        idx = int(id.replace("mwh_fifa_", ""))
        streams = filter_streams(load_fifa(), min_res)
        if idx < len(streams):
            s = streams[idx]
            return JSONResponse({"streams": [{
                "name": "Max WheyTV",
                "title": f"⚽ {s.get('name', 'FIFA')} | {s.get('quality', '')}",
                "url": s["url"],
                "isLive": True,
                "poster": "https://img.icons8.com/color/200/soccer-ball.png",
                "behaviorHints": {"notWebReady": True},
            }]})
    except Exception as e:
        print(f"[Stream] FIFA error: {e}")
    return JSONResponse({"streams": []})


async def get_anime_stream(id: str):
    try:
        parts = id.split(":")
        mal_id = parts[0].replace("mwh_mal_", "")
        episode = int(parts[1]) if len(parts) > 1 else 1

        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            r = await client.get(f"https://api.jikan.moe/v4/anime/{mal_id}", timeout=10)
            if r.status_code == 200:
                anime = r.json().get("data", {})
                title = anime.get("title_english") or anime.get("title", "")
                if title:
                    return await search_moviebox(title, "series", 1, episode, "", ["all"], True)
    except Exception as e:
        print(f"[Stream] Anime error: {e}")
    return JSONResponse({"streams": []})


async def get_moviebox_stream(request: Request, type: str, imdb_id: str, config: dict):
    pref_langs = config.get("languages", [config.get("language", "all")])
    if isinstance(pref_langs, str):
        pref_langs = [pref_langs]
    all_langs = "all" in pref_langs

    parts = imdb_id.split(":")
    actual_imdb = parts[0]
    season = int(parts[1]) if len(parts) > 1 else 1
    episode = int(parts[2]) if len(parts) > 2 else 1

    # Resolve IMDB to title
    title = ""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            r = await client.get(f"https://api.themoviedb.org/3/find/{actual_imdb}",
                params={"api_key": TMDB_API_KEY, "external_source": "imdb_id"}, timeout=8)
            if r.status_code == 200:
                results = r.json().get("movie_results", []) or r.json().get("tv_results", [])
                if results:
                    title = results[0].get("title") or results[0].get("name", "")
    except:
        pass

    if not title:
        return JSONResponse({"streams": []})

    return await search_moviebox(title, type, season, episode, actual_imdb, pref_langs, all_langs)


async def search_moviebox(title: str, type: str, season: int, episode: int,
                           imdb_id: str = "", pref_langs: list = None, all_langs: bool = True):
    pref_langs = pref_langs or ["all"]
    LANG_MAP = {
        "en": "english", "hi": "hindi", "es": "spanish", "fr": "french",
        "de": "german", "it": "italian", "pt": "portuguese", "ru": "russian",
        "ja": "japanese", "ko": "korean", "zh": "chinese", "ar": "arabic",
        "tr": "turkish", "th": "thai", "pl": "polish", "ta": "tamil", "te": "telugu",
    }
    pref_lang_names = [LANG_MAP.get(l, l) for l in pref_langs]

    try:
        from streaming.provider import find_fast_matches, extract_streams

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
            return False

        # Sort: user's audio language first, then by resolution
        def sort_key(x):
            audio = x.get("audio_lang", "")
            res = getattr(x["download"], "resolution", 0)
            
            if all_langs:
                # No language filter: prioritize streams WITH audio lang, then by resolution
                has_audio = 1 if audio else 0
                return (-has_audio, -res)
            else:
                # Language filter: prioritize matching audio, then non-matching
                if audio and lang_matches(audio):
                    return (0, -res)  # Best: matching audio language
                elif not audio and not x.get("subtitle_langs"):
                    return (1, -res)  # OK: no lang info (might be original)
                else:
                    return (2, -res)  # Last: non-matching or subtitle-only
        
        stream_results.sort(key=sort_key)

        streams = []
        seen = set()
        for sd in stream_results:
            dl = sd["download"]
            url = str(dl.url)
            base = url.split("?")[0]
            if base in seen:
                continue
            seen.add(base)

            resolution = getattr(dl, "resolution", 0)
            size = getattr(dl, "size", 0)
            audio = sd.get("audio_lang", "")
            subs = sd.get("subtitle_langs", [])

            if not all_langs and not lang_matches(audio):
                continue

            res_text = f"{resolution}p" if resolution else "?"
            size_text = f"{size / (1024*1024):.0f} MB" if size else ""

            # Stream title: quality + size + audio/subtitle info
            desc = f"🎬 {res_text}"
            if size_text:
                desc += f" • 💾 {size_text}"
            if audio:
                desc += f" • 🔊 {audio}"
            elif False:  # Subtitles hidden
                desc += f" • 💬 Subs: {', '.join(subs[:4])}"
            else:
                desc += f" • 🔊 Original"

            streams.append({
                "name": "Max WheyTV",
                "title": desc,
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

def load_iptv(country="all"):
    if country == "all":
        all_streams = []
        for fname in sorted(os.listdir(DATA_DIR)):
            if fname.startswith("hq_") and fname.endswith(".json"):
                with open(os.path.join(DATA_DIR, fname)) as f:
                    all_streams.extend(json.load(f))
        return all_streams
    filepath = os.path.join(DATA_DIR, f"hq_{country}.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return []


def load_fifa():
    filepath = os.path.join(DATA_DIR, "fifa_streams.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return []


def filter_streams(streams, min_res="1080p"):
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


def get_channel_logo(name: str) -> str:
    """Get a generic logo for a channel by name."""
    name_lower = name.lower()
    if any(x in name_lower for x in ["sport", "espn", "sky sport", "bein", "dazn"]):
        return "https://img.icons8.com/color/96/trophy.png"
    if any(x in name_lower for x in ["news", "cnn", "bbc", "ndtv", "fox news"]):
        return "https://img.icons8.com/color/96/news.png"
    if any(x in name_lower for x in ["movie", "cinema", "film"]):
        return "https://img.icons8.com/color/96/movie.png"
    if any(x in name_lower for x in ["music", "mtv", "vh1"]):
        return "https://img.icons8.com/color/96/musical-notes.png"
    if any(x in name_lower for x in ["kids", "cartoon", "nick", "disney"]):
        return "https://img.icons8.com/color/96/teddy-bear.png"
    return "https://img.icons8.com/color/96/tv.png"
