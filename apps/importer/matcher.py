import re
from difflib import SequenceMatcher
from apps.integrations.spotify import get_spotify_client, get_spotify_playlist_tracks
from apps.integrations.youtube import get_youtube_client, get_youtube_playlist_tracks

NOISE_PATTERNS = [
    r'\(official\s+video\)',
    r'\[official\s+video\]',
    r'\(official\s+music\s+video\)',
    r'\[official\s+music\s+video\]',
    r'\(official\s+audio\)',
    r'\[official\s+audio\]',
    r'\(video\s+oficial\)',
    r'\[video\s+oficial\]',
    r'\(audio\s+oficial\)',
    r'\[audio\s+oficial\]',
    r'\(lyric\s+video\)',
    r'\[lyric\s+video\]',
    r'\(video\s+con\s+letra\)',
    r'\[video\s+con\s+letra\]',
    r'\(visualizer\)',
    r'\[visualizer\]',
    r'\(remastered(\s+\d{4})?\)',
    r'\[remastered(\s+\d{4})?\]',
    r'\(remaster(\s+\d{4})?\)',
    r'\[remaster(\s+\d{4})?\]',
    r'\b\d{4}\s+remaster\b',
    r'\(hd\)',
    r'\[hd\]',
    r'\(4k\)',
    r'\[4k\]',
    r'\(hq\)',
    r'\[hq\]',
    r'\(audio\)',
    r'\[audio\]',
]

NOISE_REGEX = re.compile('|'.join(NOISE_PATTERNS), re.IGNORECASE)
FEAT_REGEX = re.compile(r'[\(\[](feat\.|ft\.|featuring).*?[\)\]]', re.IGNORECASE)


def clean_title(title: str) -> str:
    if not title:
        return ''
    cleaned = NOISE_REGEX.sub('', title)
    cleaned = FEAT_REGEX.sub('', cleaned)
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
        title = parts[1].strip()
        return artist, title

    if ':' in cleaned:
        parts = cleaned.split(':', 1)
        artist = clean_artist(parts[0].strip())
        title = parts[1].strip()
        return artist, title

    return clean_artist(channel_title), cleaned


def compute_similarity(str1: str, str2: str) -> float:
    if not str1 or not str2:
        return 0.0
    s1 = str1.lower().strip()
    s2 = str2.lower().strip()
    return SequenceMatcher(None, s1, s2).ratio()


def match_spotify_track_to_youtube(user, track: dict) -> dict | None:
    yt = get_youtube_client(user)
    artist = track.get('artist', '')
    title = track.get('title', '')
    isrc = track.get('isrc', '')

    cleaned_title = clean_title(title)
    cleaned_artist = clean_artist(artist)

    candidates = []

    # Strategy 1: Search by ISRC if available
    if isrc:
        try:
            res = yt.search().list(
                q=isrc,
                type='video',
                part='snippet',
                maxResults=3
            ).execute()
            for item in res.get('items', []):
                snippet = item.get('snippet', {})
                candidates.append({
                    'video_id': item['id']['videoId'],
                    'title': snippet.get('title', ''),
                    'channel': snippet.get('channelTitle', ''),
                    'match_type': 'isrc',
                })
        except Exception:
            pass

    # Strategy 2: Search by cleaned Artist + Title
    if not candidates:
        query = f"{cleaned_artist} {cleaned_title}".strip()
        try:
            res = yt.search().list(
                q=query,
                type='video',
                part='snippet',
                maxResults=5
            ).execute()
            for item in res.get('items', []):
                snippet = item.get('snippet', {})
                candidates.append({
                    'video_id': item['id']['videoId'],
                    'title': snippet.get('title', ''),
                    'channel': snippet.get('channelTitle', ''),
                    'match_type': 'fuzzy',
                })
        except Exception:
            pass

    if not candidates:
        return None

    best_match = None
    best_score = -1.0

    target_phrase = f"{cleaned_artist} {cleaned_title}".lower()

    for cand in candidates:
        cand_title = clean_title(cand['title']).lower()
        score = compute_similarity(target_phrase, cand_title)

        # Penalize karaoke, covers or instrumental unless in original title
        for penalty_term in ('karaoke', 'tribute', 'instrumental cover', 'tutorial'):
            if penalty_term in cand_title and penalty_term not in target_phrase:
                score *= 0.5

        if cand['match_type'] == 'isrc':
            score = max(score, 0.95)

        if score > best_score:
            best_score = score
            best_match = {
                'id': cand['video_id'],
                'title': cand['title'],
                'artist': cand['channel'],
                'score': round(score, 2),
                'match_type': cand['match_type'],
            }

    if best_match and best_score >= 0.55:
        return best_match

    return None


def match_youtube_track_to_spotify(user, track: dict) -> dict | None:
    sp = get_spotify_client(user)
    raw_title = track.get('title', '')
    raw_artist = track.get('artist', '')

    parsed_artist, parsed_title = parse_youtube_title(raw_title, raw_artist)
    cleaned_title = clean_title(parsed_title)
    cleaned_artist = clean_artist(parsed_artist)

    items = []

    # Strategy 1: Targeted field search
    if cleaned_artist and cleaned_title:
        try:
            query = f"track:{cleaned_title} artist:{cleaned_artist}"
            res = sp.search(q=query, type='track', limit=5)
            items = res.get('tracks', {}).get('items', [])
        except Exception:
            items = []

    # Strategy 2: Broad query fallback
    if not items:
        try:
            query = f"{cleaned_artist} {cleaned_title}".strip() or cleaned_title
            res = sp.search(q=query, type='track', limit=5)
            items = res.get('tracks', {}).get('items', [])
        except Exception:
            items = []

    if not items:
        return None

    best_match = None
    best_score = -1.0
    target_phrase = f"{cleaned_artist} {cleaned_title}".lower()

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

    if best_match and best_score >= 0.50:
        return best_match

    return None


def preview_playlist_match(user, source_platform: str, target_platform: str, playlist_id: str, limit: int = 50) -> dict:
    if source_platform == 'spotify':
        source_tracks = get_spotify_playlist_tracks(user, playlist_id, limit=limit)
    elif source_platform == 'youtube':
        source_tracks = get_youtube_playlist_tracks(user, playlist_id, limit=limit)
    else:
        raise ValueError(f"Plataforma origen no soportada: {source_platform}")

    results = []
    matched_count = 0

    for track in source_tracks:
        if source_platform == 'spotify' and target_platform == 'youtube':
            matched = match_spotify_track_to_youtube(user, track)
        elif source_platform == 'youtube' and target_platform == 'spotify':
            matched = match_youtube_track_to_spotify(user, track)
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
