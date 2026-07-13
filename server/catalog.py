"""Max WheyTV — Catalog endpoints (TMDB Discover + IPTV + FIFA + Anime)."""
import json
import os
import base64
import asyncio
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from server.config import TMDB_API_KEY

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Language code → display name for catalog releaseInfo tags
LANG_TAG = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "pt": "Portuguese", "ru": "Russian",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "ar": "Arabic",
    "tr": "Turkish", "th": "Thai", "pl": "Polish", "ta": "Tamil", "te": "Telugu",
    "bn": "Bengali", "ur": "Urdu", "pa": "Punjabi", "ml": "Malayalam",
    "kn": "Kannada", "tl": "Tagalog", "id": "Indonesian", "sv": "Swedish",
    "nl": "Dutch", "da": "Danish", "no": "Norwegian", "fi": "Finnish",
    "cs": "Czech", "ro": "Romanian", "hu": "Hungarian", "uk": "Ukrainian",
    "vi": "Vietnamese", "ms": "Malay", "he": "Hebrew", "fa": "Persian",
}


def parse_config(config_str: str) -> dict:
    try:
        padding = 4 - (len(config_str) % 4)
        if padding != 4:
            config_str += "=" * padding
        decoded = base64.urlsafe_b64decode(config_str).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return {}


# ─── TMDB → IMDB Resolution ──────────────────────────────────

async def tmdb_to_imdb_batch(client, tmdb_ids, content_type="movie"):
    """Resolve TMDB IDs to IMDB IDs in parallel."""
    async def one(tid):
        try:
            endpoint = "movie" if content_type == "movie" else "tv"
            r = await client.get(f"https://api.themoviedb.org/3/{endpoint}/{tid}/external_ids",
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


# ─── TMDB Discover ───────────────────────────────────────────

async def tmdb_discover(client, content_type="movie", params=None):
    """Discover movies/series from TMDB."""
    base_params = {
        "api_key": TMDB_API_KEY,
        "sort_by": "popularity.desc",
        "vote_count.gte": "50",
    }
    if params:
        base_params.update(params)

    try:
        r = await client.get(f"https://api.themoviedb.org/3/discover/{content_type}", params=base_params, timeout=10)
        if r.status_code == 200:
            results = r.json().get("results", [])
            # Resolve TMDB IDs to IMDB IDs in batch
            tmdb_ids = [str(item.get("id")) for item in results]
            imdb_ids = await tmdb_to_imdb_batch(client, tmdb_ids, content_type)

            metas = []
            for item, imdb_id in zip(results, imdb_ids):
                tmdb_id = item.get("id")
                title = item.get("title") or item.get("name", "")
                poster = item.get("poster_path")
                backdrop = item.get("backdrop_path")
                year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
                rating = item.get("vote_average")
                overview = item.get("overview", "")

                # Use IMDB ID if available, else TMDB ID
                meta_id = imdb_id if imdb_id else f"tmdb_{tmdb_id}"

                # Add language tag to releaseInfo
                lang_code = item.get("original_language", "")
                lang_name = LANG_TAG.get(lang_code, lang_code.upper())
                release = f"{year} • {lang_name}" if year else lang_name

                metas.append({
                    "id": meta_id,
                    "type": content_type,
                    "name": title,
                    "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                    "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                    "releaseInfo": release,
                    "imdbRating": str(round(rating, 1)) if rating else None,
                    "description": overview[:300] if overview else "",
                })
            return metas
    except Exception as e:
        print(f"[TMDB] Discover error: {e}")
    return []


async def tmdb_trending(client, content_type="movie", time_window="week"):
    """Get trending content from TMDB."""
    try:
        r = await client.get(f"https://api.themoviedb.org/3/trending/{content_type}/{time_window}",
            params={"api_key": TMDB_API_KEY}, timeout=10)
        if r.status_code == 200:
            results = r.json().get("results", [])
            # Resolve TMDB IDs to IMDB IDs in batch
            tmdb_ids = [str(item.get("id")) for item in results]
            imdb_ids = await tmdb_to_imdb_batch(client, tmdb_ids, content_type)

            metas = []
            for item, imdb_id in zip(results, imdb_ids):
                tmdb_id = item.get("id")
                title = item.get("title") or item.get("name", "")
                poster = item.get("poster_path")
                backdrop = item.get("backdrop_path")
                year = (item.get("release_date") or item.get("first_air_date") or "")[:4]
                rating = item.get("vote_average")

                meta_id = imdb_id if imdb_id else f"tmdb_{tmdb_id}"

                lang_code = item.get("original_language", "")
                lang_name = LANG_TAG.get(lang_code, lang_code.upper())
                release = f"{year} • {lang_name}" if year else lang_name

                metas.append({
                    "id": meta_id,
                    "type": content_type,
                    "name": title,
                    "poster": f"https://image.tmdb.org/t/p/w500{poster}" if poster else None,
                    "background": f"https://image.tmdb.org/t/p/original{backdrop}" if backdrop else None,
                    "releaseInfo": release,
                    "imdbRating": str(round(rating, 1)) if rating else None,
                })
            return metas
    except Exception as e:
        print(f"[TMDB] Trending error: {e}")
    return []


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

    async with httpx.AsyncClient(timeout=httpx.Timeout(10), follow_redirects=True) as client:

        # ── TMDB Movie Catalogs ──────────────────────────────
        if catalog_id == "mwh_popular":
            # Fetch from multiple languages to ensure diversity
            all_metas = []
            for lang in ["en", "hi", "es", "fr", "de", "pt", "ru", "ja", "ko", "zh", "ar", "tr", "ta", "te"]:
                metas = await tmdb_discover(client, "movie", {
                    "with_original_language": lang,
                    "sort_by": "popularity.desc",
                    "vote_count.gte": "10",
                })
                all_metas.extend(metas[:10])
            # Sort by rating and deduplicate
            seen = set()
            unique = []
            for m in all_metas:
                if m["id"] not in seen:
                    seen.add(m["id"])
                    unique.append(m)
            return JSONResponse({"metas": unique[:100]})

        if catalog_id == "mwh_trending":
            # Fetch trending from multiple languages
            all_metas = []
            for lang in ["en", "hi", "es", "fr", "de", "ja", "ko", "zh", "ar", "tr"]:
                metas = await tmdb_discover(client, "movie", {
                    "with_original_language": lang,
                    "sort_by": "popularity.desc",
                    "vote_count.gte": "5",
                })
                all_metas.extend(metas[:8])
            seen = set()
            unique = []
            for m in all_metas:
                if m["id"] not in seen:
                    seen.add(m["id"])
                    unique.append(m)
            return JSONResponse({"metas": unique[:100]})

        if catalog_id == "mwh_top_rated":
            # Fetch top rated from multiple languages
            all_metas = []
            for lang in ["en", "hi", "es", "fr", "de", "ja", "ko", "zh", "ar", "tr"]:
                metas = await tmdb_discover(client, "movie", {
                    "with_original_language": lang,
                    "sort_by": "vote_average.desc",
                    "vote_count.gte": "50",
                })
                all_metas.extend(metas[:8])
            seen = set()
            unique = []
            for m in all_metas:
                if m["id"] not in seen:
                    seen.add(m["id"])
                    unique.append(m)
            return JSONResponse({"metas": unique[:100]})

        if catalog_id == "mwh_new":
            metas = await tmdb_discover(client, "movie", {"sort_by": "release_date.desc", "release_date.lte": "2026-12-31"})
            return JSONResponse({"metas": metas[:100]})

        # ── Language-specific catalogs ───────────────────────
        if catalog_id.startswith("mwh_lang_"):
            lang = catalog_id.replace("mwh_lang_", "")
            metas = await tmdb_discover(client, "movie", {"with_original_language": lang, "sort_by": "popularity.desc"})
            return JSONResponse({"metas": metas[:100]})

        # ── TMDB Series Catalogs ─────────────────────────────
        if catalog_id == "mwh_popular_series":
            metas = await tmdb_discover(client, "tv", {"sort_by": "popularity.desc"})
            return JSONResponse({"metas": metas[:100]})

        if catalog_id == "mwh_airing_today":
            metas = await tmdb_discover(client, "tv", {"sort_by": "popularity.desc", "air_date.gte": "2026-06-01"})
            return JSONResponse({"metas": metas[:100]})

        # ── IPTV ─────────────────────────────────────────────
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

        # ── FIFA ─────────────────────────────────────────────
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

        # ── Anime (Jikan) ────────────────────────────────────
        if catalog_id.startswith("mwh_anime"):
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
