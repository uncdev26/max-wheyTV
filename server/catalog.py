"""Max WheyTV — Catalog endpoints (IPTV, FIFA, Anime only)."""
import json
import os
import base64
import asyncio
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

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


# ─── IPTV ────────────────────────────────────────────────────

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


# ─── Anime (Jikan) ───────────────────────────────────────────

def anime_to_meta(anime):
    mal_id = anime.get("mal_id")
    title = anime.get("title_english") or anime.get("title", "")
    images = anime.get("images", {}).get("jpg", {})
    poster = images.get("large_image_url") or images.get("image_url")
    score = anime.get("score")
    synopsis = anime.get("synopsis", "")
    year = anime.get("year") or (anime.get("aired", {}).get("from", "") or "")[:4]

    return {
        "id": f"mwh_mal_{mal_id}",
        "type": "series",
        "name": title,
        "poster": poster,
        "background": poster,
        "releaseInfo": str(year) if year else "",
        "imdbRating": str(score) if score else None,
        "description": synopsis[:300] if synopsis else "",
    }


# ─── Routes ──────────────────────────────────────────────────

@router.get("/{config}/catalog/{type}/{catalog_id}.json")
async def cat_with_config(request: Request, config: str, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, config)


@router.get("/catalog/{type}/{catalog_id}.json")
async def cat_no_config(request: Request, type: str, catalog_id: str):
    return await handle_catalog(request, type, catalog_id, "")


async def handle_catalog(request: Request, type: str, catalog_id: str, config_str: str):
    config = parse_config(config_str)
    min_res = config.get("resolution", "1080p")

    # ── IPTV ─────────────────────────────────────────────────
    if catalog_id.startswith("mwh_iptv_"):
        country_key = catalog_id.replace("mwh_iptv_", "")
        streams = filter_streams(load_iptv(country_key), min_res)
        metas = []
        for i, s in enumerate(streams[:200]):
            metas.append({
                "id": f"mwh_iptv_{i}_{country_key}",
                "type": "tv",
                "name": s.get("name", "Unknown"),
                "poster": s.get("poster") or s.get("logo") or "https://img.icons8.com/color/200/tv.png",
                "background": s.get("poster") or s.get("logo") or "https://img.icons8.com/color/200/tv.png",
                "genres": [s.get("country", "General")],
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
                "poster": s.get("poster") or "https://img.icons8.com/color/200/soccer-ball.png",
                "background": s.get("poster") or "https://img.icons8.com/color/200/soccer-ball.png",
                "genres": ["Sports", "Football"],
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

    return JSONResponse({"metas": []})
