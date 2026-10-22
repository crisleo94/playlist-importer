from datetime import timedelta
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


def get_spotify_oauth(state: str = None) -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=settings.SPOTIFY_CLIENT_ID,
        client_secret=settings.SPOTIFY_CLIENT_SECRET,
        redirect_uri=settings.SPOTIFY_REDIRECT_URI,
        scope=' '.join(SPOTIFY_SCOPES),
        state=state,
        show_dialog=True,
    )


def get_spotify_auth_url(state: str) -> str:
    sp_oauth = get_spotify_oauth(state=state)
    return sp_oauth.get_authorize_url()


def exchange_spotify_code(code: str) -> dict:
    sp_oauth = get_spotify_oauth()
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
