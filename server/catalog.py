"""Max WheyTV — Catalog endpoints."""
import json
import base64
import re
import asyncio
import time
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from server.config import (
    TMDB_API_KEY, TVDB_API_KEY, RPDB_KEY,
    MOVIEBOX_API, MOVIEBOX_HEADERS, MOVIEBOX_SECTIONS,
    TMDB_GENRES, COUNTRY_CODES,
)

router = APIRouter()

# ─── Cache ───────────────────────────────────────────────────
_catalog_cache = {}
_cache_time = 0
CACHE_TTL = 3600  # 1 hour


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


# ─── MovieBox Catalog Builder ────────────────────────────────

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
    while page <= 10:
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


# ─── IPTV Catalog ────────────────────────────────────────────

def load_iptv_streams():
    """Load IPTV streams from benchmark data."""
    streams = {}
    import os
    benchmark_dir = "/home/asdev/entertainment/iptv_benchmark"

    for fname in os.listdir(benchmark_dir):
        if fname.startswith("hq_") and fname.endswith(".json") and fname != "hq_streams.json":
            country = fname.replace("hq_", "").replace(".json", "").replace("_", " ").title()
            try:
                with open(os.path.join(benchmark_dir, fname)) as f:
                    data = json.load(f)
                streams[country] = data
            except:
                pass

    # Load FIFA
    try:
        with open(os.path.join(benchmark_dir, "fifa_streams.json")) as f:
            streams["FIFA"] = json.load(f)
    except:
        pass

    return streams


_iptv_cache = {}
_iptv_cache_time = 0


def get_iptv_streams():
    global _iptv_cache, _iptv_cache_time
    if time.time() - _iptv_cache_time > 3600:
        _iptv_cache = load_iptv_streams()
        _iptv_cache_time = time.time()
    return _iptv_cache


# ─── Catalog Routes ──────────────────────────────────────────

@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def cat_with_config(request: Request, config: str, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, config)


@router.get("/catalog/{type}/{catalog_id}.json")
async def cat_no_config(request: Request, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, "")


async def handle_catalog(request: Request, type: str, catalog_id: str, config_str: str):
    global _cache_time
    config = parse_config(config_str)

    # IPTV catalogs
    if catalog_id.startswith("mwh_iptv_"):
        country_key = catalog_id.replace("mwh_iptv_", "").replace("_", " ").title()
        iptv = get_iptv_streams()

        if country_key == "All":
            # Return all countries combined
            all_streams = []
            for country, streams in iptv.items():
                if country != "FIFA":
                    all_streams.extend(streams)
        else:
            all_streams = iptv.get(country_key, [])

        # Filter by category if configured
        categories = config.get("iptv_categories", [])
        if categories:
            filtered = []
            for s in all_streams:
                # IPTV streams don't have category in benchmark data, include all
                filtered.append(s)
            all_streams = filtered

        metas = []
        for i, s in enumerate(all_streams[:500]):
            metas.append({
                "id": f"mwh_iptv_{i}",
                "type": "tv",
                "name": s.get("name", "Unknown"),
                "poster": None,
            })
        return JSONResponse({"metas": metas})

    # FIFA catalog
    if catalog_id == "mwh_fifa":
        iptv = get_iptv_streams()
        fifa = iptv.get("FIFA", [])
        metas = []
        for i, s in enumerate(fifa):
            metas.append({
                "id": f"mwh_fifa_{i}",
                "type": "tv",
                "name": s.get("name", "Unknown"),
                "poster": None,
            })
        return JSONResponse({"metas": metas})

    # MovieBox catalogs
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

    return JSONResponse({"metas": metas})


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
        print(f"[Catalog] Refreshed: {total} items across {len(MOVIEBOX_SECTIONS)} sections")
