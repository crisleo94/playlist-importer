from datetime import timedelta, timezone as dt_timezone
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


def _to_aware_utc(dt):
    if dt and timezone.is_naive(dt):
        return dt.replace(tzinfo=dt_timezone.utc)
    return dt


def _get_client_config() -> dict:
    return {
        'web': {
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [settings.GOOGLE_REDIRECT_URI],
        }
    }


def get_youtube_flow(state: str = None) -> Flow:
    flow = Flow.from_client_config(
        _get_client_config(),
        scopes=YOUTUBE_SCOPES,
        state=state,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    return flow


def get_youtube_auth_url(state: str) -> str:
    flow = get_youtube_flow(state=state)
    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )
    return authorization_url


def exchange_youtube_code(code: str) -> dict:
    flow = get_youtube_flow()
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


def get_user_youtube_playlists(user, search_query: str = '') -> list[dict]:
    yt = get_youtube_client(user)
    response = yt.playlists().list(
        part='snippet,contentDetails,status',
        mine=True,
        maxResults=50
    ).execute()

    items = response.get('items', [])
    playlists = []

    for item in items:
        snippet = item.get('snippet', {})
        content_details = item.get('contentDetails', {})
        status = item.get('status', {})

        title = snippet.get('title') or 'Sin título'
        if search_query and search_query.lower() not in title.lower():
            continue

        thumbnails = snippet.get('thumbnails', {})
        image_url = None
        for key in ('medium', 'high', 'default'):
            if key in thumbnails:
                image_url = thumbnails[key].get('url')
                break

        playlist_id = item.get('id')
        playlists.append({
            'id': playlist_id,
            'name': title,
            'description': snippet.get('description') or '',
            'total_tracks': content_details.get('itemCount', 0),
            'image_url': image_url,
            'privacy_status': status.get('privacyStatus', 'public'),
            'channel_title': snippet.get('channelTitle', ''),
            'external_url': f"https://music.youtube.com/playlist?list={playlist_id}",
        })

    return playlists


def get_youtube_playlist_tracks(user, playlist_id: str, limit: int = 50) -> list[dict]:
    yt = get_youtube_client(user)
    response = yt.playlistItems().list(
        part='snippet,contentDetails',
        playlistId=playlist_id,
        maxResults=min(limit, 50)
    ).execute()

    items = response.get('items', [])
    tracks = []

    for item in items:
        snippet = item.get('snippet', {})
        title = snippet.get('title')
        if not title or title == 'Private video' or title == 'Deleted video':
            continue

        thumbnails = snippet.get('thumbnails', {})
        image_url = None
        for key in ('medium', 'high', 'default'):
            if key in thumbnails:
                image_url = thumbnails[key].get('url')
                break

        tracks.append({
            'id': snippet.get('resourceId', {}).get('videoId'),
            'title': title,
            'artist': snippet.get('videoOwnerChannelTitle', 'Artista desconocido'),
            'image_url': image_url,
        })

    return tracks
