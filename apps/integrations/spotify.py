from datetime import timedelta
from urllib.parse import urlparse
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from django.conf import settings
from django.utils import timezone
from .models import PlatformToken

SPOTIFY_SCOPES = [
    'playlist-read-private',
    'playlist-read-collaborative',
    'playlist-modify-public',
    'playlist-modify-private',
]

LOCAL_DEV_HOSTS = {'localhost:8000', '127.0.0.1:8000'}


def resolve_redirect_uri(base_redirect_uri: str, request_host: str = None) -> str:
    if not settings.DEBUG or not request_host or request_host not in LOCAL_DEV_HOSTS:
        return base_redirect_uri
    parsed = urlparse(base_redirect_uri)
    return parsed._replace(netloc=request_host).geturl()


def get_spotify_oauth(state: str = None, redirect_uri: str = None) -> SpotifyOAuth:
    effective_redirect_uri = redirect_uri or settings.SPOTIFY_REDIRECT_URI
    return SpotifyOAuth(
        client_id=settings.SPOTIFY_CLIENT_ID,
        client_secret=settings.SPOTIFY_CLIENT_SECRET,
        redirect_uri=effective_redirect_uri,
        scope=' '.join(SPOTIFY_SCOPES),
        state=state,
        show_dialog=True,
    )


def get_spotify_auth_url(state: str, redirect_uri: str = None) -> str:
    sp_oauth = get_spotify_oauth(state=state, redirect_uri=redirect_uri)
    return sp_oauth.get_authorize_url()


def exchange_spotify_code(code: str, redirect_uri: str = None) -> dict:
    sp_oauth = get_spotify_oauth(redirect_uri=redirect_uri)
    token_info = sp_oauth.get_access_token(code, as_dict=True, check_cache=False)
    return token_info


def refresh_spotify_token(platform_token: PlatformToken) -> str:
    refresh_token = platform_token.get_refresh_token()
    if not refresh_token:
        raise ValueError('No refresh token available for Spotify.')

    sp_oauth = get_spotify_oauth()
    new_token_info = sp_oauth.refresh_access_token(refresh_token)

    platform_token.set_access_token(new_token_info['access_token'])
    if 'refresh_token' in new_token_info:
        platform_token.set_refresh_token(new_token_info['refresh_token'])

    expires_in = new_token_info.get('expires_in', 3600)
    platform_token.expires_at = timezone.now() + timedelta(seconds=expires_in)
    platform_token.save()

    return new_token_info['access_token']


def get_spotify_client(user) -> spotipy.Spotify:
    platform_token = PlatformToken.objects.filter(
        user=user,
        platform=PlatformToken.PLATFORM_SPOTIFY
    ).first()

    if not platform_token:
        raise ValueError('Spotify account is not connected.')

    if platform_token.is_expired():
        access_token = refresh_spotify_token(platform_token)
    else:
        access_token = platform_token.get_access_token()

    return spotipy.Spotify(auth=access_token)


def get_user_spotify_playlists(user, search_query: str = '', max_playlists: int = 250) -> list[dict]:
    sp = get_spotify_client(user)
    playlists = []
    offset = 0
    batch_limit = 50

    while len(playlists) < max_playlists:
        results = sp.current_user_playlists(limit=batch_limit, offset=offset)
        items = results.get('items', [])
        if not items:
            break

        for item in items:
            if not item:
                continue
            name = item.get('name') or 'Sin título'
            if search_query and search_query.lower() not in name.lower():
                continue

            images = item.get('images') or []
            image_url = images[0].get('url') if images else None

            owner = item.get('owner', {}).get('display_name') or 'Spotify'
            tracks_total = item.get('tracks', {}).get('total', 0)

            playlists.append({
                'id': item.get('id'),
                'name': name,
                'description': item.get('description') or '',
                'total_tracks': tracks_total,
                'image_url': image_url,
                'owner_name': owner,
                'external_url': item.get('external_urls', {}).get('spotify', ''),
            })

            if len(playlists) >= max_playlists:
                break

        if not results.get('next') or len(items) < batch_limit:
            break
        offset += len(items)

    return playlists


def get_spotify_playlist_details(user, playlist_id: str) -> dict:
    sp = get_spotify_client(user)
    playlist = sp.playlist(playlist_id, fields='id,name,description,images,tracks.total')
    images = playlist.get('images') or []
    image_url = images[0].get('url') if images else None
    return {
        'id': playlist.get('id', playlist_id),
        'name': playlist.get('name') or 'Playlist de Spotify',
        'description': playlist.get('description') or '',
        'total_tracks': playlist.get('tracks', {}).get('total', 0),
        'image_url': image_url,
    }


def get_spotify_playlist_tracks(user, playlist_id: str, limit: int = 100) -> list[dict]:
    sp = get_spotify_client(user)
    tracks = []
    offset = 0

    while len(tracks) < limit:
        batch_limit = min(100, limit - len(tracks))
        results = sp.playlist_items(playlist_id, limit=batch_limit, offset=offset)
        items = results.get('items', [])
        if not items:
            break

        for entry in items:
            track = entry.get('track')
            if not track or track.get('is_local'):
                continue

            artists = [a.get('name') for a in track.get('artists', []) if a.get('name')]
            album = track.get('album', {})
            album_images = album.get('images', [])

            tracks.append({
                'id': track.get('id'),
                'title': track.get('name'),
                'artist': ', '.join(artists) if artists else 'Artista desconocido',
                'album': album.get('name', ''),
                'duration_ms': track.get('duration_ms', 0),
                'isrc': track.get('external_ids', {}).get('isrc', ''),
                'image_url': album_images[0].get('url') if album_images else None,
            })

            if len(tracks) >= limit:
                break

        if not results.get('next') or len(items) < batch_limit:
            break
        offset += len(items)

    return tracks


def create_spotify_playlist(user, name: str, description: str = '', public: bool = False, sp_client=None) -> dict:
    sp = sp_client if sp_client is not None else get_spotify_client(user)
    current_user = sp.me()
    user_id = current_user['id']
    playlist = sp.user_playlist_create(
        user=user_id,
        name=name,
        public=public,
        description=description or 'Imported via Playlist Importer'
    )
    return {
        'id': playlist['id'],
        'name': playlist['name'],
        'external_url': playlist.get('external_urls', {}).get('spotify', ''),
    }


def add_tracks_to_spotify_playlist(user, playlist_id: str, track_uris: list[str], sp_client=None) -> None:
    if not track_uris:
        return
    sp = sp_client if sp_client is not None else get_spotify_client(user)
    for i in range(0, len(track_uris), 100):
        chunk = track_uris[i:i + 100]
        sp.playlist_add_items(playlist_id, chunk)
