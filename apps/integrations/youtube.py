from datetime import timedelta, timezone as dt_timezone
from urllib.parse import urlparse
import google.oauth2.credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from django.conf import settings
from django.utils import timezone
from .models import PlatformToken

YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube',
    'https://www.googleapis.com/auth/youtube.force-ssl',
    'https://www.googleapis.com/auth/userinfo.profile',
]

LOCAL_DEV_HOSTS = {'localhost:8000', '127.0.0.1:8000'}


def _to_aware_utc(dt):
    if dt and timezone.is_naive(dt):
        return dt.replace(tzinfo=dt_timezone.utc)
    return dt


def _pick_thumbnail(thumbnails: dict) -> str | None:
    if not isinstance(thumbnails, dict):
        return None
    for key in ('medium', 'high', 'default'):
        if key in thumbnails and thumbnails[key].get('url'):
            return thumbnails[key]['url']
    return None


def resolve_redirect_uri(base_redirect_uri: str, request_host: str = None) -> str:
    if not settings.DEBUG or not request_host or request_host not in LOCAL_DEV_HOSTS:
        return base_redirect_uri
    parsed = urlparse(base_redirect_uri)
    return parsed._replace(netloc=request_host).geturl()


def _get_client_config(redirect_uri: str = None) -> dict:
    effective_redirect_uri = redirect_uri or settings.GOOGLE_REDIRECT_URI
    return {
        'web': {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [effective_redirect_uri],
        }
    }


def get_youtube_flow(state: str = None, redirect_uri: str = None) -> Flow:
    effective_redirect_uri = redirect_uri or settings.GOOGLE_REDIRECT_URI
    flow = Flow.from_client_config(
        _get_client_config(redirect_uri=effective_redirect_uri),
        scopes=YOUTUBE_SCOPES,
        state=state,
    )
    flow.redirect_uri = effective_redirect_uri
    return flow


def get_youtube_auth_url(state: str, redirect_uri: str = None) -> tuple[str, str]:
    flow = get_youtube_flow(state=state, redirect_uri=redirect_uri)
    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )
    return authorization_url, flow.code_verifier


def exchange_youtube_code(code: str, code_verifier: str = None, redirect_uri: str = None) -> dict:
    flow = get_youtube_flow(redirect_uri=redirect_uri)
    if code_verifier:
        flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    credentials = flow.credentials

    return {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes,
        'expiry': _to_aware_utc(credentials.expiry),
    }


def refresh_youtube_token(platform_token: PlatformToken) -> str:
    refresh_token = platform_token.get_refresh_token()
    if not refresh_token:
        raise ValueError('No refresh token available for YouTube.')

    credentials = google.oauth2.credentials.Credentials(
        token=platform_token.get_access_token(),
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=YOUTUBE_SCOPES,
    )

    request = Request()
    credentials.refresh(request)

    platform_token.set_access_token(credentials.token)
    if credentials.expiry:
        platform_token.expires_at = _to_aware_utc(credentials.expiry)
    else:
        platform_token.expires_at = timezone.now() + timedelta(seconds=3600)
    platform_token.save()

    return credentials.token


def get_youtube_client(user):
    platform_token = PlatformToken.objects.filter(
        user=user,
        platform=PlatformToken.PLATFORM_YOUTUBE
    ).first()

    if not platform_token:
        raise ValueError('YouTube account is not connected.')

    if platform_token.is_expired():
        refresh_youtube_token(platform_token)

    credentials = google.oauth2.credentials.Credentials(
        token=platform_token.get_access_token(),
        refresh_token=platform_token.get_refresh_token(),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=YOUTUBE_SCOPES,
    )

    return build('youtube', 'v3', credentials=credentials)


def get_user_youtube_playlists(user, search_query: str = '', max_playlists: int = 250) -> list[dict]:
    yt = get_youtube_client(user)
    playlists = []
    page_token = None

    while True:
        request_params = {
            'part': 'snippet,contentDetails,status',
            'mine': True,
            'maxResults': 50,
        }
        if page_token:
            request_params['pageToken'] = page_token

        response = yt.playlists().list(**request_params).execute()
        items = response.get('items', [])

        for item in items:
            snippet = item.get('snippet', {})
            content_details = item.get('contentDetails', {})
            status = item.get('status', {})

            title = snippet.get('title') or 'Sin título'
            if search_query and search_query.lower() not in title.lower():
                continue

            playlist_id = item.get('id')
            playlists.append({
                'id': playlist_id,
                'name': title,
                'description': snippet.get('description') or '',
                'total_tracks': content_details.get('itemCount', 0),
                'image_url': _pick_thumbnail(snippet.get('thumbnails', {})),
                'privacy_status': status.get('privacyStatus', 'public'),
                'channel_title': snippet.get('channelTitle', ''),
                'external_url': f"https://music.youtube.com/playlist?list={playlist_id}",
            })

            if len(playlists) >= max_playlists:
                break

        page_token = response.get('nextPageToken')
        if not page_token or len(playlists) >= max_playlists:
            break

    return playlists


def get_youtube_playlist_tracks(user, playlist_id: str, limit: int = 100) -> list[dict]:
    yt = get_youtube_client(user)
    tracks = []
    page_token = None

    while len(tracks) < limit:
        max_batch = min(50, limit - len(tracks))
        request_params = {
            'part': 'snippet,contentDetails',
            'playlistId': playlist_id,
            'maxResults': max_batch,
        }
        if page_token:
            request_params['pageToken'] = page_token

        response = yt.playlistItems().list(**request_params).execute()
        items = response.get('items', [])
        if not items:
            break

        for item in items:
            snippet = item.get('snippet', {})
            title = snippet.get('title')
            if not title or title in ('Private video', 'Deleted video'):
                continue

            tracks.append({
                'id': snippet.get('resourceId', {}).get('videoId'),
                'title': title,
                'artist': snippet.get('videoOwnerChannelTitle', 'Artista desconocido'),
                'image_url': _pick_thumbnail(snippet.get('thumbnails', {})),
            })

            if len(tracks) >= limit:
                break

        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return tracks


def create_youtube_playlist(user, name: str, description: str = '', privacy_status: str = 'private', yt_client=None) -> dict:
    yt = yt_client if yt_client is not None else get_youtube_client(user)
    body = {
        'snippet': {
            'title': name,
            'description': description or 'Imported via Playlist Importer',
        },
        'status': {
            'privacyStatus': privacy_status,
        }
    }
    response = yt.playlists().insert(part='snippet,status', body=body).execute()
    return {
        'id': response['id'],
        'name': response.get('snippet', {}).get('title', name),
        'external_url': f"https://music.youtube.com/playlist?list={response['id']}",
    }


def add_video_to_youtube_playlist(user, playlist_id: str, video_id: str, yt_client=None) -> dict:
    yt = yt_client if yt_client is not None else get_youtube_client(user)
    body = {
        'snippet': {
            'playlistId': playlist_id,
            'resourceId': {
                'kind': 'youtube#video',
                'videoId': video_id,
            }
        }
    }
    return yt.playlistItems().insert(part='snippet', body=body).execute()
