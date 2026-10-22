from datetime import timedelta
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
        'expiry': credentials.expiry,
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
        platform_token.expires_at = credentials.expiry
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
