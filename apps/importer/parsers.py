import re
from urllib.parse import parse_qs, urlparse

SPOTIFY_ID_REGEX = re.compile(r'^[a-zA-Z0-9]{22}$')
YOUTUBE_ID_REGEX = re.compile(r'^(PL|UU|LL|FL|RD|OLAK)[a-zA-Z0-9_-]{10,}$')


def _is_spotify_host(hostname: str) -> bool:
    return hostname == 'spotify.com' or hostname.endswith('.spotify.com')


def _is_youtube_host(hostname: str) -> bool:
    return hostname == 'youtube.com' or hostname.endswith('.youtube.com') or hostname == 'youtu.be'


def parse_playlist_input(raw_input: str) -> tuple[str, str] | None:
    if not raw_input or not isinstance(raw_input, str):
        return None

    cleaned = raw_input.strip()
    if not cleaned:
        return None

    # 1. Spotify URI: spotify:playlist:XXXX
    if cleaned.startswith('spotify:playlist:'):
        playlist_id = cleaned.split(':')[-1].split('?')[0].strip()
        if SPOTIFY_ID_REGEX.match(playlist_id):
            return 'spotify', playlist_id

    # 2. Parse URL
    if '://' in cleaned or cleaned.startswith(('open.spotify.com', 'spotify.com', 'music.youtube.com', 'youtube.com', 'www.youtube.com', 'youtu.be')):
        candidate_url = cleaned if '://' in cleaned else f"https://{cleaned}"
        try:
            parsed = urlparse(candidate_url)
            hostname = (parsed.hostname or '').lower()

            # Spotify
            if _is_spotify_host(hostname):
                parts = [p for p in parsed.path.split('/') if p]
                if len(parts) >= 2 and parts[0] == 'playlist':
                    playlist_id = parts[1].split('?')[0].strip()
                    if SPOTIFY_ID_REGEX.match(playlist_id):
                        return 'spotify', playlist_id

            # YouTube / YouTube Music
            if _is_youtube_host(hostname):
                query_params = parse_qs(parsed.query)
                list_ids = query_params.get('list', [])
                if list_ids:
                    playlist_id = list_ids[0].strip()
                    if YOUTUBE_ID_REGEX.match(playlist_id):
                        return 'youtube', playlist_id
        except Exception:
            pass

    # 3. Raw IDs
    if SPOTIFY_ID_REGEX.match(cleaned):
        return 'spotify', cleaned

    if YOUTUBE_ID_REGEX.match(cleaned):
        return 'youtube', cleaned

    return None
