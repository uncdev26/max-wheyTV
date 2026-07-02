"""Max WheyTV — Catalog endpoints."""
import json
import os
import base64
import re
import asyncio
import time
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from server.config import (
    TMDB_API_KEY, RPDB_KEY,
    MOVIEBOX_API, MOVIEBOX_HEADERS, MOVIEBOX_SECTIONS,
)

router = APIRouter()

# ─── Cache ───────────────────────────────────────────────────
_catalog_cache = {}
_cache_time = 0
CACHE_TTL = 3600
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


def clean_title(t: str) -> str:
    t = re.sub(r'\s*\[.*?\]\s*', '', t).strip()
    t = re.sub(r'\s*(CAM|HDCAM|HDTS|WEBRip|WEB-DL|BluRay|HDRip|DVDRip)\s*$', '', t, flags=re.I).strip()
    for s in [' Hindi', ' Tamil', ' Telugu', ' Spanish', ' French', ' German', ' Arabic', ' Dubbed', ' Dual Audio']:
        if t.lower().endswith(s.lower()):
            t = t[:-len(s)].strip()
    return t


# ─── MovieBox Catalog ────────────────────────────────────────

async def fetch_moviebox_page(client, gid, page=1, per_page=50):
    try:
        r = await client.get(MOVIEBOX_API, params={"id": gid, "page": page, "perPage": per_page}, headers=MOVIEBOX_HEADERS, timeout=12)
        if r.status_code == 200:
            data = r.json().get("data", {})
            return data.get("subjectList", []), data.get("pager", {})
    except:
        pass
    return [], {}


async def resolve_batch(client, titles_years):
    async def one(title, year):
        try:
            r = await client.get("https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title, "year": year}, timeout=8)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    return str(results[0]["id"])
            r2 = await client.get("https://api.themoviedb.org/3/search/movie",
                params={"api_key": TMDB_API_KEY, "query": title}, timeout=8)
            if r2.status_code == 200:
                results2 = r2.json().get("results", [])
                if results2:
                    return str(results2[0]["id"])
        except:
            pass
        return None
    results = []
    for i in range(0, len(titles_years), 20):
        batch = titles_years[i:i+20]
        results.extend(await asyncio.gather(*[one(t, y) for t, y in batch]))
    return results


async def tmdb_to_imdb_batch(client, tmdb_ids):
    async def one(tid):
        try:
            r = await client.get(f"https://api.themoviedb.org/3/movie/{tid}/external_ids",
                params={"api_key": TMDB_API_KEY}, timeout=8)
            if r.status_code == 200:
                return r.json().get("imdb_id")
        except:
            pass
        return None
    results = []
    for i in range(0, len(tmdb_ids), 20):
        batch = tmdb_ids[i:i+20]
        results.extend(await asyncio.gather(*[one(t) for t in batch]))
    return results


async def build_moviebox_section(client, gid, item_type):
    all_items = []
    page = 1
    while page <= 5:
        items, pager = await fetch_moviebox_page(client, gid, page)
        if not items:
            break
        all_items.extend(items)
        if not pager.get("hasMore", False):
            break
        page += 1

    if not all_items:
        return []

    ty = [(clean_title(i.get("title", "")), (i.get("releaseDate") or "")[:4]) for i in all_items]
    tmdb_ids = await resolve_batch(client, ty)
    imdb_ids = await tmdb_to_imdb_batch(client, [t for t in tmdb_ids if t])

    metas = []
    imdb_idx = 0
    for item, tid in zip(all_items, tmdb_ids):
        if not tid:
            continue
        imdb = imdb_ids[imdb_idx] if imdb_idx < len(imdb_ids) else None
        imdb_idx += 1
        if not imdb:
            continue
        cover = item.get("cover", {})
        poster = cover.get("url") if isinstance(cover, dict) else None
        metas.append({
            "id": imdb,
            "type": item_type,
            "name": clean_title(item.get("title", "")),
            "poster": poster,
        })
    return metas


# ─── Jikan Anime ─────────────────────────────────────────────

async def fetch_jikan(client, endpoint, limit=25):
    try:
        r = await client.get(f"https://api.jikan.moe/v4/{endpoint}", timeout=10)
        if r.status_code == 200:
            return r.json().get("data", [])
    except:
        pass
    return []


def anime_to_meta(anime):
    mal_id = anime.get("mal_id")
    title = anime.get("title_english") or anime.get("title", "")
    images = anime.get("images", {}).get("jpg", {})
    poster = images.get("large_image_url") or images.get("image_url")
    score = anime.get("score")
    episodes = anime.get("episodes") or 0
    synopsis = anime.get("synopsis", "")
    year = anime.get("year") or (anime.get("aired", {}).get("from", "") or "")[:4]
    genres = [g["name"] for g in anime.get("genres", [])]

    return {
        "id": f"mal_{mal_id}",
        "type": "series",
        "name": title,
        "poster": poster,
        "releaseInfo": str(year) if year else "",
        "imdbRating": str(score) if score else None,
        "genres": genres,
        "description": synopsis[:300] if synopsis else "",
    }


# ─── IPTV Catalog ────────────────────────────────────────────

def load_iptv_country(country):
    """Load IPTV streams for a specific country."""
    safe = country.lower().replace(" ", "_")
    filepath = os.path.join(DATA_DIR, f"hq_{safe}.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return []


def load_iptv_all():
    """Load all IPTV streams."""
    all_streams = []
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.startswith("hq_") and fname.endswith(".json"):
            with open(os.path.join(DATA_DIR, fname)) as f:
                all_streams.extend(json.load(f))
    return all_streams


def load_fifa():
    filepath = os.path.join(DATA_DIR, "fifa_streams.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return []


# ─── Routes ──────────────────────────────────────────────────

@router.on_event("startup")
async def startup():
    asyncio.create_task(refresh_catalog())


@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def cat_with_config(request: Request, config: str, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, config)


@router.get("/catalog/{type}/{catalog_id}.json")
async def cat_no_config(request: Request, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, "")


async def handle_catalog(request: Request, type: str, catalog_id: str, config_str: str):
    global _cache_time
    config = parse_config(config_str)
    min_res = config.get("resolution", "1080p")

    # ── IPTV ─────────────────────────────────────────────────
    if catalog_id.startswith("mwh_iptv_"):
        country_key = catalog_id.replace("mwh_iptv_", "")

        if country_key == "all":
            streams = load_iptv_all()
        else:
            streams = load_iptv_country(country_key)

        # Filter by resolution
        streams = filter_by_resolution(streams, min_res)

        metas = []
        for i, s in enumerate(streams[:200]):
            metas.append({
                "id": f"mwh_iptv_{i}_{country_key}",
                "type": "tv",
                "name": s.get("name", "Unknown"),
                "poster": None,
            })
        return JSONResponse({"metas": metas})

    # ── FIFA ─────────────────────────────────────────────────
    if catalog_id == "mwh_fifa":
        streams = load_fifa()
        streams = filter_by_resolution(streams, min_res)
        metas = []
        for i, s in enumerate(streams):
            metas.append({
                "id": f"mwh_fifa_{i}",
                "type": "tv",
                "name": s.get("name", "Unknown"),
                "poster": None,
            })
        return JSONResponse({"metas": metas})

    # ── Anime (Jikan) ────────────────────────────────────────
    if catalog_id in ("mwh_anime_top", "mwh_anime_seasonal", "mwh_anime"):
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            if catalog_id == "mwh_anime_top":
                anime_list = await fetch_jikan(client, "top/anime?limit=25")
            elif catalog_id == "mwh_anime_seasonal":
                anime_list = await fetch_jikan(client, "seasons/now?limit=25")
            else:
                anime_list = await fetch_jikan(client, "top/anime?limit=25")
            metas = [anime_to_meta(a) for a in anime_list]
            return JSONResponse({"metas": metas})

    # ── MovieBox ─────────────────────────────────────────────
    section_key = catalog_id.replace("mwh_", "")
    if section_key not in MOVIEBOX_SECTIONS:
        return JSONResponse({"metas": []})

    section = MOVIEBOX_SECTIONS[section_key]

    if time.time() - _cache_time > CACHE_TTL:
        asyncio.create_task(refresh_catalog())

    metas = _catalog_cache.get(section_key, [])
    if not metas and not _catalog_cache:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15), follow_redirects=True) as client:
            metas = await build_moviebox_section(client, section["gid"], section["type"])
            _catalog_cache[section_key] = metas

    return JSONResponse({"metas": metas[:200]})


def filter_by_resolution(streams, min_res):
    """Filter streams by minimum resolution."""
    if min_res == "all":
        return streams
    filtered = []
    for s in streams:
        q = s.get("quality", "Unknown")
        name = s.get("name", "").lower()
        lat = s.get("latency_ms", 9999)

        # Skip geo-blocked
        if "geo-blocked" in name:
            continue

        # Resolution check
        if min_res == "4k":
            if q == "4K":
                filtered.append(s)
        elif min_res == "1080p":
            if q in ("4K", "1080p"):
                filtered.append(s)
        elif min_res == "720p":
            if q in ("4K", "1080p", "720p"):
                filtered.append(s)
        else:
            filtered.append(s)

    return filtered


async def refresh_catalog():
    global _catalog_cache, _cache_time
    async with httpx.AsyncClient(timeout=httpx.Timeout(15), follow_redirects=True) as client:
        tasks = {k: build_moviebox_section(client, v["gid"], v["type"]) for k, v in MOVIEBOX_SECTIONS.items()}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        new_cache = {}
        total = 0
        for key, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                new_cache[key] = []
            else:
                new_cache[key] = result
                total += len(result)
        _catalog_cache = new_cache
        _cache_time = time.time()
        print(f"[Catalog] Refreshed: {total} MovieBox items")
