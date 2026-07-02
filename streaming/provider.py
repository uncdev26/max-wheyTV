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
from moviebox.web.core import Search as SearchV2
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
    Prefers clean detailPath (no language suffix) and exact title match.
    """
    item = match["item"]
    detail_path = getattr(item, "detailPath", "") or ""
    score = 0
    # Penalize language-tagged listings (e.g. gram-chikitsalay-hindi-xxx)
    if LANG_PATH_PATTERN.search(detail_path):
        score -= 100
    return score

async def find_fast_matches(title: str, year: str, is_movie: bool) -> list[dict]:
    """Fast mode: single API (v2 only), 3 results max. ~1-2s instead of 5-15s."""
    try:
        s = SessionV2()
        st = SubjectTypeV2.MOVIES if is_movie else SubjectTypeV2.TV_SERIES
        sv = SearchV2(s, query=title, subject_type=st, per_page=3)
        res = await sv.get_content_model()
        matches = []
        for item in res.items:
            if not year or str(item.releaseDate.year) == str(year):
                matches.append({"item": item, "session": s, "version": "v2"})
                if len(matches) >= 2:
                    break
        matches.sort(key=_match_score, reverse=True)
        return matches
    except Exception:
        return []


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
            return (res.downloads, match)
        except Exception:
            return ([], match)

    async def fetch_v1(match):
        try:
            if is_movie:
                dl = LegacySingle(match["session"], match["item"])
                res = await dl.get_content_model()
            else:
                dl = LegacyTV(match["session"], match["item"])
                res = await dl.get_content_model(season=season, episode=episode)
            return (res.downloads, match)
        except Exception:
            return ([], match)

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
                return (res.list, match)
            except Exception as e:
                if "406" not in str(e):
                    break
        try:
            await match["session"].close()
        except Exception:
            pass
        return ([], match)

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
        """Fetch streams for a specific dub version."""
        try:
            from moviebox.web.core import SingleItemDetails
            from moviebox.web.streams import DownloadableSingleFilesDetail
            from moviebox.web.requests import Session as WebSession

            session = WebSession()
            await session.create()

            # Step 1: Get the dub's item details
            details = SingleItemDetails(session)
            model = await details.get_content_model(dub_detail_path)

            # Step 2: Fetch streams using the dub's item
            dl = DownloadableSingleFilesDetail(session, model.subject)
            res = await dl.get_content_model()
            await session.close()

            # Tag with dub language
            dub_match = dict(original_match)
            dub_match["dub_language"] = dub_language
            return (res.downloads, dub_match)
        except Exception as e:
            try:
                await session.close()
            except:
                pass
            return ([], original_match)

    for match, dub_detail, dub_lan in dub_fetches:
        tasks.append(fetch_dub_streams(match, dub_detail, dub_lan))

    results = await asyncio.gather(*tasks)

    all_streams = []
    for downloads, match in results:
        lang_info = extract_match_language_info(match)
        for dl in downloads:
            all_streams.append(
                {
                    "download": dl,
                    "audio_lang": lang_info["audio_lang"],
                    "subtitle_langs": lang_info["subtitle_langs"],
                }
            )

    return all_streams
