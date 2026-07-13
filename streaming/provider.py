import asyncio
import re
from typing import Any, Dict, List, Optional

from moviebox.legacy.constants import SubjectType as SubjectTypeV1
from moviebox.legacy.core import Search as SearchV1
from moviebox.legacy.requests import Session as SessionV1
from moviebox.legacy.streams import (
    DownloadableMovieFilesDetail as LegacySingle,
    DownloadableTVSeriesFilesDetail as LegacyTV,
)
from moviebox.mobile.constants import (
    CustomResolutionType as CustomResolutionTypeV3,
    SubjectType as SubjectTypeV3,
)
from moviebox.mobile.core import (
    DownloadableVideoFilesDetail as MobileVideo,
    Search as SearchV3,
)
from moviebox.mobile.http_client import ProviderHttpClient as SessionV3
from moviebox.web.constants import SubjectType as SubjectTypeV2
from moviebox.web.core import Search as SearchV2, ItemDetails
from moviebox.web.requests import Session as SessionV2
from moviebox.web.streams import (
    DownloadableSingleFilesDetail as WebSingle,
    DownloadableTVSeriesFilesDetail as WebTV,
)

# Pattern to extract language from title brackets e.g. "Solo Leveling [Hindi]" or "(Hindi Dubbed)"
TITLE_LANG_PATTERN = re.compile(r"\[([^\]]+)\]\s*$|\(([A-Za-z\s]+)\)\s*$")


async def search_v2(title: str, year: str, is_movie: bool):
    matches = []
    try:
        s = SessionV2()
        st = SubjectTypeV2.MOVIES if is_movie else SubjectTypeV2.TV_SERIES
        sv = SearchV2(s, query=title, subject_type=st, per_page=10)
        res = await sv.get_content_model()
        count = 0
        for item in res.items:
            if not year or str(item.releaseDate.year) == str(year):
                matches.append({"item": item, "session": s, "version": "v2"})
                count += 1
                if count >= 3:
                    break
    except Exception:
        pass
    return matches


async def search_v1(title: str, year: str, is_movie: bool):
    matches = []
    try:
        s = SessionV1()
        st = SubjectTypeV1.MOVIES if is_movie else SubjectTypeV1.TV_SERIES
        sv = SearchV1(s, query=title, subject_type=st, per_page=10)
        res = await sv.get_content_model()
        count = 0
        for item in res.items:
            if not year or str(item.releaseDate.year) == str(year):
                matches.append({"item": item, "session": s, "version": "v1"})
                count += 1
                if count >= 3:
                    break
    except Exception:
        pass
    return matches


async def search_v3(title: str, year: str, is_movie: bool):
    matches = []
    try:
        s = SessionV3()
        await s.start()
        st = SubjectTypeV3.MOVIES if is_movie else SubjectTypeV3.TV_SERIES
        sv = SearchV3(s, query=title, subject_type=st, per_page=10)
        res = await sv.get_content_model()
        count = 0
        for item in res.items:
            if not year or str(item.release_date.year) == str(year):
                matches.append({"item": item, "session": s, "version": "v3"})
                count += 1
                if count >= 3:
                    break
    except Exception:
        pass
    return matches


LANG_PATH_PATTERN = re.compile(r"-(?:hindi|tamil|telugu|malayalam|kannada|bengali|marathi|punjabi|urdu|english|french|spanish|german|italian|portuguese|japanese|korean|chinese|arabic|turkish|thai)-")

def _match_score(match: dict) -> int:
    """Score a match — higher is better.
    Prefers exact title matches, active resources, and correct year.
    """
    item = match["item"]
    detail_path = getattr(item, "detailPath", "") or ""
    score = 0
    
    # Penalize language-tagged listings slightly to prioritize original if present,
    # but keep them highly ranked if they match
    if LANG_PATH_PATTERN.search(detail_path):
        score -= 1
        
    has_res = getattr(item, "hasResource", False) or getattr(item, "has_resource", False)
    if has_res:
        score += 10
        
    # High score for exact title matches
    title = getattr(item, "title", "").lower()
    return score

async def find_fast_matches(title: str, year: str, is_movie: bool, pref_lang_codes: list[str] = None) -> list[dict]:
    """Fast mode: search by title, then fetch detail pages to discover ALL available dubs.
    
    MovieBox stores each language dub as a separate subject with its own subjectId
    and detailPath. The search API may not populate the full dubs list, but the
    detail page always does. So we:
    1. Query search-suggest (autocomplete API) to find exact database titles (with language codes).
    2. Search using SearchV2 with the expanded exact titles in parallel.
    3. Fetch detail pages for matches to discover the complete dubs list.
    4. Return original matches + one match per dub language.
    """
    pref_lang_codes = pref_lang_codes or []
    keywords_to_search = [title]

    # Step 1: Autocomplete suggestion search for precise matching
    try:
        s_suggest = SessionV2()
        suggest_url = "https://h5-api.aoneroom.com/wefeed-h5api-bff/subject/search-suggest"
        suggest_res = await s_suggest.post_to_api(suggest_url, json={"keyword": title, "perPage": 10})
        suggest_items = suggest_res.get("items", [])
        for entry in suggest_items:
            word = entry.get("word", "")
            if word and title.lower() in word.lower():
                # Avoid duplicates
                if word.lower() not in [kw.lower() for kw in keywords_to_search]:
                    keywords_to_search.append(word)
    except Exception as e:
        print(f"[Provider] Autocomplete check failed: {e}")

    # Step 2: Parallel SearchV2 requests on expanded keywords (limit to top 3 to keep it fast)
    search_matches = []
    seen_paths = set()

    async def _search_query(q_str):
        try:
            s = SessionV2()
            st = SubjectTypeV2.MOVIES if is_movie else SubjectTypeV2.TV_SERIES
            sv = SearchV2(s, query=q_str, subject_type=st, per_page=5)
            res = await sv.get_content_model()
            batch = []
            for item in res.items:
                item_year = getattr(item, "releaseDate", None)
                item_year_str = str(item_year.year) if item_year else ""
                
                # Loose checking: if year is passed, match it or allow if within 1 year range (handles future/past releases)
                if not year or not item_year_str or abs(int(item_year_str) - int(year)) <= 1:
                    batch.append({"item": item, "session": s, "version": "v2"})
            return batch
        except Exception as e:
            print(f"[Provider] Search error for query '{q_str}': {e}")
            return []

    search_tasks = [_search_query(kw) for kw in keywords_to_search[:3]]
    search_results = await asyncio.gather(*search_tasks)

    for batch in search_results:
        for m in batch:
            detail_path = getattr(m["item"], "detailPath", "")
            if detail_path and detail_path not in seen_paths:
                seen_paths.add(detail_path)
                search_matches.append(m)

    if not search_matches:
        return []

    # Step 3: For each match (up to top 3), fetch the detail page to discover ALL dubs
    all_matches = []
    seen_detail_paths = set()

    async def _discover_dubs(match):
        """Fetch detail page → get complete dubs list → create one match per dub."""
        item = match["item"]
        detail_path = getattr(item, "detailPath", "")
        session = match["session"]
        discovered = []

        # Always include the original match
        if detail_path and detail_path not in seen_detail_paths:
            seen_detail_paths.add(detail_path)
            discovered.append(match)

        # Check dubs from the search result first
        dubs = getattr(item, "dubs", None)

        # If search result doesn't have dubs, or has only 1, fetch the detail page
        if not dubs or len(dubs) <= 1:
            try:
                details = ItemDetails(session)
                detail_model = await details.get_content_model(detail_path)
                # The detail page's subject should have the full dubs list
                dubs = getattr(detail_model.subject, "dubs", None)
                print(f"[Provider] Detail page for '{getattr(item, 'title', '?')}' — dubs: {[getattr(d, 'lanName', '?') for d in (dubs or [])]}")
            except Exception as e:
                print(f"[Provider] Detail page fetch failed for {detail_path}: {e}")

        # Create a match for each dub that's different from the main item
        if dubs and len(dubs) > 1:
            for dub in dubs:
                dub_detail = getattr(dub, "detailPath", "")
                dub_lan = getattr(dub, "lanName", "")
                dub_original = getattr(dub, "original", False)

                if not dub_detail or not dub_lan:
                    continue
                if dub_detail in seen_detail_paths:
                    continue
                seen_detail_paths.add(dub_detail)

                # Tag this as a dub-expanded match so extract_streams knows
                # to fetch from this specific detailPath
                discovered.append({
                    "item": item,  # original item for reference
                    "session": session,
                    "version": "v2",
                    "dub_detail_path": dub_detail,
                    "dub_language": dub_lan,
                    "dub_original": dub_original,
                })

        return discovered

    # Run dub discovery in parallel for all search matches (limit to top 3)
    dub_tasks = [_discover_dubs(m) for m in search_matches[:3]]
    dub_results = await asyncio.gather(*dub_tasks)

    for batch in dub_results:
        all_matches.extend(batch)

    print(f"[Provider] Total matches after dub discovery: {len(all_matches)} "
          f"(from {len(search_matches)} search results)")

    return all_matches


async def find_all_matches(title: str, year: str, is_movie: bool) -> list[dict]:
    results = await asyncio.gather(
        search_v2(title, year, is_movie),
        search_v1(title, year, is_movie),
        search_v3(title, year, is_movie),
    )
    matches = []
    for r in results:
        matches.extend(r)
    # Sort: prefer clean listings (no language suffix in detailPath)
    matches.sort(key=_match_score, reverse=True)
    return matches


def _extract_title_language(title: str) -> str | None:
    """Extract language tag from title brackets, e.g. 'Solo Leveling [Hindi]' -> 'Hindi'."""
    match = TITLE_LANG_PATTERN.search(title)
    if match:
        return match.group(1) or match.group(2)
    return None


def extract_match_language_info(match: dict) -> dict:
    """Extract audio language and subtitle languages from a single matched item."""
    item = match["item"]
    version = match["version"]

    audio_lang = None
    subtitle_langs = []
    seen_subs = set()

    # 1. Check if this is a dub-expanded match (most specific)
    dub_language = match.get("dub_language")
    if dub_language:
        audio_lang = dub_language
    
    # 2. Try to get audio language from dubs field
    if not audio_lang:
        dubs = getattr(item, "dubs", None)
        if dubs:
            dub_names = []
            for dub in dubs:
                lan_name = getattr(dub, "lanName", None)
                if lan_name and lan_name not in dub_names:
                    dub_names.append(lan_name)
            
            if len(dub_names) == 1:
                audio_lang = dub_names[0]
            elif len(dub_names) > 1:
                audio_lang = ", ".join(dub_names)
    
    # 2. Fallback: extract from title brackets
    if not audio_lang:
        title = getattr(item, "title", "")
        lang_from_title = _extract_title_language(title)
        if lang_from_title:
            audio_lang = lang_from_title

    # 3. Extract subtitle languages
    if version in ("v2", "v1", "v3"):
        subs = getattr(item, "subtitles", None)
        if subs:
            for s in subs:
                s_clean = s.strip()
                if s_clean and s_clean not in seen_subs:
                    seen_subs.add(s_clean)
                    subtitle_langs.append(s_clean)

    return {
        "audio_lang": audio_lang,
        "subtitle_langs": subtitle_langs,
    }


async def extract_streams(
    matches: list[dict], is_movie: bool, season: int = 1, episode: int = 1
):
    tasks = []

    async def fetch_v2(match):
        """Fetch streams for a v2 match — either from the original item or a dub's detailPath."""
        try:
            session = match["session"]
            dub_detail_path = match.get("dub_detail_path")

            if dub_detail_path:
                # This is a dub-expanded match — fetch the dub's detail page first,
                # then get its downloads. This gives us a DIFFERENT stream URL
                # for this language.
                details = ItemDetails(session)
                detail_model = await details.get_content_model(dub_detail_path)
                dub_item = detail_model.subject

                if is_movie:
                    dl = WebSingle(session, dub_item)
                    res = await dl.get_content_model()
                else:
                    dl = WebTV(session, dub_item)
                    res = await dl.get_content_model(season=season, episode=episode)
            else:
                # Normal match — fetch downloads directly from the search result item
                if is_movie:
                    dl = WebSingle(session, match["item"])
                    res = await dl.get_content_model()
                else:
                    dl = WebTV(session, match["item"])
                    res = await dl.get_content_model(season=season, episode=episode)

            return (res.downloads, match, res.captions)
        except Exception as e:
            dub_lang = match.get("dub_language", "?")
            print(f"[Provider] fetch_v2 failed (lang={dub_lang}): {e}")
            return ([], match, [])

    async def fetch_v1(match):
        try:
            if is_movie:
                dl = LegacySingle(match["session"], match["item"])
                res = await dl.get_content_model()
            else:
                dl = LegacyTV(match["session"], match["item"])
                res = await dl.get_content_model(season=season, episode=episode)
            return (res.downloads, match, res.captions)
        except Exception:
            return ([], match, [])

    async def fetch_v3(match):
        resolutions_to_try = [
            CustomResolutionTypeV3.BEST,
            CustomResolutionTypeV3._720P,
            CustomResolutionTypeV3._480P,
            CustomResolutionTypeV3._360P,
        ]
        for res_type in resolutions_to_try:
            try:
                dl = MobileVideo(match["session"], resolution=res_type)
                if is_movie:
                    res = await dl.get_content_model(
                        subject_id=str(match["item"].subject_id)
                    )
                else:
                    res = await dl.get_content_model(
                        subject_id=str(match["item"].subject_id),
                        season=season,
                        episode=episode,
                    )
                await match["session"].close()
                return (res.list, match, [])
            except Exception as e:
                if "406" not in str(e):
                    break
        try:
            await match["session"].close()
        except Exception:
            pass
        return ([], match, [])

    # Build fetch tasks — v2 handles both normal and dub-expanded matches
    for match in matches:
        if match["version"] == "v2":
            tasks.append(fetch_v2(match))
        elif match["version"] == "v1":
            tasks.append(fetch_v1(match))
        elif match["version"] == "v3":
            tasks.append(fetch_v3(match))

    results = await asyncio.gather(*tasks)

    all_streams = []
    for downloads, match, captions in results:
        lang_info = extract_match_language_info(match)
        for dl in downloads:
            all_streams.append(
                {
                    "download": dl,
                    "audio_lang": lang_info["audio_lang"],
                    "subtitle_langs": lang_info["subtitle_langs"],
                    "captions": captions,
                }
            )

    print(f"[Provider] Total streams extracted: {len(all_streams)}")
    return all_streams
