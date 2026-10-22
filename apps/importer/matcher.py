import hashlib
import logging
import re
from difflib import SequenceMatcher
from django.core.cache import cache
from apps.integrations.spotify import get_spotify_client, get_spotify_playlist_tracks
from apps.integrations.youtube import get_youtube_client, get_youtube_playlist_tracks

logger = logging.getLogger(__name__)

MIN_SCORE_YOUTUBE_MATCH = 0.55
MIN_SCORE_SPOTIFY_MATCH = 0.50
KARAOKE_PENALTY_FACTOR = 0.50
ISRC_MATCH_BOOST_MIN_SIMILARITY = 0.35
ISRC_BOOSTED_SCORE = 0.85
CACHE_TTL_MATCH = 3600

NOISE_PATTERNS = [
    r'[\(\[]\s*(?:official\s+(?:music\s+)?video|official\s+audio|video\s+oficial|audio\s+oficial|lyric\s+video|video\s+con\s+letra|visualizer|hd|4k|hq|audio)\s*[\)\]]',
    r'[\(\[]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?(?:\s+version)?\s*[\)\]]',
    r'[-–—]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?(?:\s+version)?',
    r'\b\d{4}\s+remaster(?:ed)?(?:\s+version)?\b',
]

NOISE_REGEX = re.compile('|'.join(NOISE_PATTERNS), re.IGNORECASE)
FEAT_REGEX = re.compile(r'[\(\[](feat\.|ft\.|featuring).*?[\)\]]', re.IGNORECASE)


def _cache_key(prefix: str, raw_key: str) -> str:
    digest = hashlib.md5(raw_key.encode('utf-8')).hexdigest()
    return f"{prefix}:{digest}"


def clean_title(title: str) -> str:
    if not title:
        return ''
    cleaned = NOISE_REGEX.sub('', title)
    cleaned = FEAT_REGEX.sub('', cleaned)
    cleaned = re.sub(r'[\(\[]\s*[\)\]]', '', cleaned)
    cleaned = re.sub(r'[\s\-–—:]+$', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def clean_artist(artist: str) -> str:
    if not artist:
        return ''
    cleaned = re.sub(r' - Topic$', '', artist, flags=re.IGNORECASE)
    cleaned = re.sub(r'VEVO$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def parse_youtube_title(raw_title: str, channel_title: str = '') -> tuple[str, str]:
    cleaned = clean_title(raw_title)

    if ' - ' in cleaned:
        parts = cleaned.split(' - ', 1)
        artist = clean_artist(parts[0].strip())
        title = clean_title(parts[1].strip())
        return artist, title

    if ':' in cleaned:
        parts = cleaned.split(':', 1)
        artist = clean_artist(parts[0].strip())
        title = clean_title(parts[1].strip())
        return artist, title

    return clean_artist(channel_title), cleaned


def compute_similarity(str1: str, str2: str) -> float:
    if not str1 or not str2:
        return 0.0
    s1 = str1.lower().strip()
    s2 = str2.lower().strip()
    return SequenceMatcher(None, s1, s2).ratio()


def match_spotify_track_to_youtube(user, track: dict, yt_client=None) -> dict | None:
    artist = track.get('artist', '')
    title = track.get('title', '')
    isrc = track.get('isrc', '').strip()

    cleaned_title = clean_title(title)
    cleaned_artist = clean_artist(artist)
    query = f"{cleaned_artist} {cleaned_title}".strip()
    if not query:
        query = isrc
    if not query:
        return None

    cache_key = _cache_key("sp2yt", track.get('id') or isrc or query)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != '__NONE__' else None

    yt = yt_client if yt_client is not None else get_youtube_client(user)
    candidates = []

    try:
        res = yt.search().list(
            q=query,
            type='video',
            part='snippet',
            maxResults=5
        ).execute()
        for item in res.get('items', []):
            snippet = item.get('snippet', {})
            cand_title = snippet.get('title', '')
            cand_desc = snippet.get('description', '')
            is_isrc_match = bool(isrc and (isrc.lower() in cand_title.lower() or isrc.lower() in cand_desc.lower()))
            candidates.append({
                'video_id': item['id']['videoId'],
                'title': cand_title,
                'channel': snippet.get('channelTitle', ''),
                'match_type': 'isrc' if is_isrc_match else 'fuzzy',
            })
    except Exception as e:
        logger.warning("Error en búsqueda de YouTube para '%s': %s", query, e)

    best_match = None
    best_score = -1.0
    target_phrase = f"{cleaned_artist} {cleaned_title}".lower().strip()

    for cand in candidates:
        cand_title = clean_title(cand['title']).lower()
        score = compute_similarity(target_phrase, cand_title)

        for penalty_term in ('karaoke', 'tribute', 'instrumental cover', 'tutorial'):
            if penalty_term in cand_title and penalty_term not in target_phrase:
                score *= KARAOKE_PENALTY_FACTOR

        if cand['match_type'] == 'isrc' and score >= ISRC_MATCH_BOOST_MIN_SIMILARITY:
            score = max(score, ISRC_BOOSTED_SCORE)

        if score > best_score:
            best_score = score
            best_match = {
                'id': cand['video_id'],
                'title': cand['title'],
                'artist': cand['channel'],
                'score': round(score, 2),
                'match_type': cand['match_type'],
            }

    result = best_match if (best_match and best_score >= MIN_SCORE_YOUTUBE_MATCH) else None
    cache.set(cache_key, result if result is not None else '__NONE__', timeout=CACHE_TTL_MATCH)
    return result


def match_youtube_track_to_spotify(user, track: dict, sp_client=None) -> dict | None:
    raw_title = track.get('title', '')
    raw_artist = track.get('artist', '')

    parsed_artist, parsed_title = parse_youtube_title(raw_title, raw_artist)
    cleaned_title = clean_title(parsed_title)
    cleaned_artist = clean_artist(parsed_artist)
    query_phrase = f"{cleaned_artist} {cleaned_title}".strip() or cleaned_title
    if not query_phrase:
        return None

    cache_key = _cache_key("yt2sp", track.get('id') or query_phrase)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached if cached != '__NONE__' else None

    sp = sp_client if sp_client is not None else get_spotify_client(user)
    items = []

    # Strategy 1: Targeted field search
    if cleaned_artist and cleaned_title:
        try:
            query = f"track:{cleaned_title} artist:{cleaned_artist}"
            res = sp.search(q=query, type='track', limit=5)
            items = res.get('tracks', {}).get('items', [])
        except Exception as e:
            logger.warning("Error en búsqueda dirigida de Spotify para '%s': %s", query, e)

    # Strategy 2: Broad query fallback
    if not items:
        try:
            res = sp.search(q=query_phrase, type='track', limit=5)
            items = res.get('tracks', {}).get('items', [])
        except Exception as e:
            logger.warning("Error en búsqueda amplia de Spotify para '%s': %s", query_phrase, e)

    best_match = None
    best_score = -1.0
    target_phrase = query_phrase.lower()

    for item in items:
        item_artists = ', '.join(a.get('name', '') for a in item.get('artists', []))
        item_title = item.get('name', '')
        cand_phrase = f"{item_artists} {item_title}".lower()

        score = compute_similarity(target_phrase, cand_phrase)

        if score > best_score:
            best_score = score
            best_match = {
                'id': item.get('id'),
                'uri': item.get('uri'),
                'title': item_title,
                'artist': item_artists,
                'isrc': item.get('external_ids', {}).get('isrc', ''),
                'score': round(score, 2),
                'match_type': 'fuzzy',
            }

    result = best_match if (best_match and best_score >= MIN_SCORE_SPOTIFY_MATCH) else None
    cache.set(cache_key, result if result is not None else '__NONE__', timeout=CACHE_TTL_MATCH)
    return result


def preview_playlist_match(user, source_platform: str, target_platform: str, playlist_id: str, limit: int = 15) -> dict:
    if source_platform == 'spotify':
        source_tracks = get_spotify_playlist_tracks(user, playlist_id, limit=limit)
    elif source_platform == 'youtube':
        source_tracks = get_youtube_playlist_tracks(user, playlist_id, limit=limit)
    else:
        raise ValueError(f"Plataforma origen no soportada: {source_platform}")

    target_client = None
    try:
        if source_platform == 'spotify' and target_platform == 'youtube':
            target_client = get_youtube_client(user)
        elif source_platform == 'youtube' and target_platform == 'spotify':
            target_client = get_spotify_client(user)
    except Exception as e:
        logger.warning("No se pudo obtener cliente destino para %s: %s", target_platform, e)

    results = []
    matched_count = 0

    for track in source_tracks:
        if source_platform == 'spotify' and target_platform == 'youtube':
            matched = match_spotify_track_to_youtube(user, track, yt_client=target_client)
        elif source_platform == 'youtube' and target_platform == 'spotify':
            matched = match_youtube_track_to_spotify(user, track, sp_client=target_client)
        else:
            matched = None

        if matched:
            matched_count += 1

        results.append({
            'source': track,
            'target': matched,
            'is_matched': matched is not None,
        })

    total = len(source_tracks)
    rate = round((matched_count / total * 100), 1) if total > 0 else 0.0

    return {
        'source_platform': source_platform,
        'target_platform': target_platform,
        'playlist_id': playlist_id,
        'total_tracks': total,
        'matched_count': matched_count,
        'unmatched_count': total - matched_count,
        'match_rate': rate,
        'items': results,
    }
