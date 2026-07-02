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


async def build_moviebox_section(client, gid, item_type):
    """Fetch MovieBox catalog and resolve to TMDB IDs for metadata."""
    all_items = []
    page = 1
    while page <= 3:
        items, pager = await fetch_moviebox_page(client, gid, page)
        if not items:
            break
        all_items.extend(items)
        if not pager.get("hasMore", False):
            break
        page += 1

    if not all_items:
        return [], []

    # Resolve titles to TMDB IDs
    titles_years = [(clean_title(i.get("title", "")), (i.get("releaseDate") or "")[:4]) for i in all_items]
    tmdb_ids = await resolve_batch(client, titles_years)

    # Get IMDB IDs from TMDB
    valid_tmdb = [t for t in tmdb_ids if t]
    imdb_ids = await tmdb_to_imdb_batch(client, valid_tmdb)

    metas = []
    moviebox_items = []  # Store for meta resolution
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
        title = clean_title(item.get("title", ""))
        year = (item.get("releaseDate") or "")[:4]

        # Use mwh_ prefix ID (not tt) so Stremio calls OUR meta endpoint
        meta_id = f"mwh_{imdb}"

        metas.append({
            "id": meta_id,
            "type": item_type,
            "name": title,
            "poster": poster,
            "releaseInfo": year,
            "background": poster,
        })
        moviebox_items.append({"id": meta_id, "imdb": imdb, "title": title, "year": year})

    return metas, moviebox_items


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


# ─── Jikan Anime ─────────────────────────────────────────────

def anime_to_meta(anime):
    mal_id = anime.get("mal_id")
    title = anime.get("title_english") or anime.get("title", "")
    images = anime.get("images", {}).get("jpg", {})
    poster = images.get("large_image_url") or images.get("image_url")
    score = anime.get("score")
    synopsis = anime.get("synopsis", "")
    year = anime.get("year") or (anime.get("aired", {}).get("from", "") or "")[:4]
    genres = [g["name"] for g in anime.get("genres", [])]

    return {
        "id": f"mwh_mal_{mal_id}",
        "type": "series",
        "name": title,
        "poster": poster,
        "releaseInfo": str(year) if year else "",
        "imdbRating": str(score) if score else None,
        "genres": genres,
        "description": synopsis[:300] if synopsis else "",
        "background": poster,
    }


# ─── IPTV ────────────────────────────────────────────────────

def load_iptv_streams(country="all"):
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
        streams = load_iptv_streams(country_key)
        streams = filter_streams(streams, min_res)

        metas = []
        for i, s in enumerate(streams[:200]):
            metas.append({
                "id": f"mwh_iptv_{i}_{country_key}",
                "type": "tv",
                "name": s.get("name", "Unknown"),
                "poster": s.get("logo") or s.get("tvg_logo") or "https://img.icons8.com/color/96/tv.png",
                "background": "https://img.icons8.com/color/96/tv.png",
            })
        return JSONResponse({"metas": metas})

    # ── FIFA ─────────────────────────────────────────────────
    if catalog_id == "mwh_fifa":
        streams = filter_streams(load_fifa(), min_res)
        metas = []
        for i, s in enumerate(streams):
            metas.append({
                "id": f"mwh_fifa_{i}",
                "type": "tv",
                "name": s.get("name", "Unknown"),
                "poster": "https://img.icons8.com/color/96/soccer-ball.png",
                "background": "https://img.icons8.com/color/96/soccer-ball.png",
            })
        return JSONResponse({"metas": metas})

    # ── Anime (Jikan) ────────────────────────────────────────
    if catalog_id.startswith("mwh_anime"):
        async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:
            if catalog_id == "mwh_anime_top":
                endpoint = "top/anime?limit=25"
            elif catalog_id == "mwh_anime_seasonal":
                endpoint = "seasons/now?limit=25"
            else:
                endpoint = "top/anime?limit=25"
            try:
                r = await client.get(f"https://api.jikan.moe/v4/{endpoint}", timeout=10)
                anime_list = r.json().get("data", []) if r.status_code == 200 else []
            except:
                anime_list = []
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
            metas, _ = await build_moviebox_section(client, section["gid"], section["type"])
            _catalog_cache[section_key] = metas

    return JSONResponse({"metas": metas[:200]})


async def refresh_catalog():
    global _catalog_cache, _cache_time
    async with httpx.AsyncClient(timeout=httpx.Timeout(15), follow_redirects=True) as client:
        new_cache = {}
        total = 0
        for key, section in MOVIEBOX_SECTIONS.items():
            try:
                metas, _ = await build_moviebox_section(client, section["gid"], section["type"])
                new_cache[key] = metas
                total += len(metas)
            except:
                new_cache[key] = []
        _catalog_cache = new_cache
        _cache_time = time.time()
        print(f"[Catalog] Refreshed: {total} MovieBox items")
