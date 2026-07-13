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
from moviebox.web.core import Search as SearchV2, SearchWithFilter
from moviebox.web.requests import Session as SessionV2
from moviebox.web.streams import (
    DownloadableSingleFilesDetail as WebSingle,
    DownloadableTVSeriesFilesDetail as WebTV,
)
from moviebox.web.types import FilterParams

# Map ISO language codes to MovieBox filter API language values
LANG_CODE_TO_FILTER = {
    "en": "English dub",
    "hi": "Hindi dub",
    "fr": "French dub",
    "bn": "Bengali dub",
    "ur": "Urdu dub",
    "pa": "Punjabi dub",
    "ta": "Tamil dub",
    "te": "Telugu dub",
    "ml": "Malayalam dub",
    "kn": "Kannada dub",
    "ar": "Arabic dub",
    "tl": "Tagalog dub",
    "id": "Indonesian dub",
    "ru": "Russian dub",
    "es": "Spanish dub",
    "ku": "Kurdish sub",
}

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
    Prefers clean detailPath (no language suffix) and exact title match.
    """
    item = match["item"]
    detail_path = getattr(item, "detailPath", "") or ""
    score = 0
    # Penalize language-tagged listings (e.g. gram-chikitsalay-hindi-xxx)
    if LANG_PATH_PATTERN.search(detail_path):
        pass  # Language listings are now welcome
    return score

async def find_fast_matches(title: str, year: str, is_movie: bool, pref_lang_codes: list[str] = None) -> list[dict]:
    """Fast mode: get all matches including language-specific versions.
    
    When pref_lang_codes is provided (e.g. ["hi", "en", "ta"]), runs parallel
    language-filtered searches via SearchWithFilter alongside the main search
    to find dub variants the basic title search would miss.
    """
    pref_lang_codes = pref_lang_codes or []

    async def _title_search():
        """Normal title search — returns the default/original listings."""
        try:
            s = SessionV2()
            st = SubjectTypeV2.MOVIES if is_movie else SubjectTypeV2.TV_SERIES
            sv = SearchV2(s, query=title, subject_type=st, per_page=10)
            res = await sv.get_content_model()
            matches = []
            for item in res.items:
                if not year or str(item.releaseDate.year) == str(year):
                    matches.append({"item": item, "session": s, "version": "v2"})
            return matches
        except Exception:
            return []

    async def _filtered_search(lang_code: str):
        """Language-filtered search — finds dub-specific listings."""
        filter_value = LANG_CODE_TO_FILTER.get(lang_code)
        if not filter_value:
            return []
        try:
            s = SessionV2()
            st = SubjectTypeV2.MOVIES if is_movie else SubjectTypeV2.TV_SERIES
            fp = FilterParams(language=filter_value)
            sv = SearchWithFilter(subject_type=st, session=s, filter_params=fp, per_page=10)
            res = await sv.get_content_model()
            matches = []
            for item in res.items:
                # Filter search results don't have a query, so match by title similarity
                item_title = getattr(item, "title", "").lower()
                search_title = title.lower()
                # Accept if the search title appears in the item title or vice versa
                if search_title in item_title or item_title in search_title or _titles_match(search_title, item_title):
                    matches.append({
                        "item": item,
                        "session": s,
                        "version": "v2",
                        "filter_lang": lang_code,
                    })
            return matches
        except Exception:
            return []

    # Build task list: always do the main title search
    tasks = [_title_search()]

    # Add language-filtered searches for each non-"all" preferred language
    effective_langs = [l for l in pref_lang_codes if l != "all" and l in LANG_CODE_TO_FILTER]
    for lang_code in effective_langs:
        tasks.append(_filtered_search(lang_code))

    results = await asyncio.gather(*tasks)

    # Merge, deduplicate by detailPath
    seen_paths = set()
    all_matches = []
    for batch in results:
        for match in batch:
            detail_path = getattr(match["item"], "detailPath", "")
            if detail_path and detail_path in seen_paths:
                continue
            if detail_path:
                seen_paths.add(detail_path)
            all_matches.append(match)

    all_matches.sort(key=_match_score, reverse=True)
    return all_matches


def _titles_match(a: str, b: str) -> bool:
    """Fuzzy title match — checks if core words overlap significantly."""
    words_a = set(re.findall(r'[a-z0-9]+', a))
    words_b = set(re.findall(r'[a-z0-9]+', b))
    if not words_a or not words_b:
        return False
    # Remove common noise words
    noise = {"the", "a", "an", "and", "of", "in", "to", "for", "is", "on", "at"}
    words_a -= noise
    words_b -= noise
    if not words_a or not words_b:
        return len(words_a) == len(words_b)  # both empty after noise removal
    overlap = words_a & words_b
    return len(overlap) >= min(len(words_a), len(words_b)) * 0.6


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
        try:
            if is_movie:
                dl = WebSingle(match["session"], match["item"])
                res = await dl.get_content_model()
            else:
                dl = WebTV(match["session"], match["item"])
                res = await dl.get_content_model(season=season, episode=episode)
            return (res.downloads, match, res.captions)
        except Exception:
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

    # Collect dub detailPaths from v2 matches for additional language streams
    dub_fetches = []
    for match in matches:
        if match["version"] == "v2":
            item = match["item"]
            dubs = getattr(item, "dubs", None)
            if dubs and len(dubs) > 1:
                main_detail = getattr(item, "detailPath", "")
                for dub in dubs:
                    dub_detail = getattr(dub, "detailPath", "")
                    dub_lan = getattr(dub, "lanName", "")
                    if dub_detail and dub_detail != main_detail and dub_lan:
                        dub_fetches.append((match, dub_detail, dub_lan))

    for match in matches:
        if match["version"] == "v2":
            tasks.append(fetch_v2(match))
        elif match["version"] == "v1":
            tasks.append(fetch_v1(match))
        elif match["version"] == "v3":
            tasks.append(fetch_v3(match))

    # Add dub fetch tasks
    async def fetch_dub_streams(original_match, dub_detail_path, dub_language):
        """Fetch streams for a specific dub version — works for both movies and TV series."""
        try:
            from moviebox.web.core import ItemDetails
            from moviebox.web.streams import (
                DownloadableSingleFilesDetail,
                DownloadableTVSeriesFilesDetail,
            )
            from moviebox.web.requests import Session as WebSession

            session = WebSession()

            # Step 1: Get the dub's item details
            details = ItemDetails(session)
            model = await details.get_content_model(dub_detail_path)

            # Step 2: Fetch streams using the correct downloader for movies vs TV
            if is_movie:
                dl = DownloadableSingleFilesDetail(session, model.subject)
                res = await dl.get_content_model()
            else:
                dl = DownloadableTVSeriesFilesDetail(session, model.subject)
                res = await dl.get_content_model(season=season, episode=episode)

            # Tag with dub language
            dub_match = dict(original_match)
            dub_match["dub_language"] = dub_language
            return (res.downloads, dub_match, res.captions)
        except Exception:
            return ([], original_match, [])

    for match, dub_detail, dub_lan in dub_fetches:
        tasks.append(fetch_dub_streams(match, dub_detail, dub_lan))

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

    return all_streams
