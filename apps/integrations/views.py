import logging
import secrets
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.utils import timezone
from .models import PlatformToken
from .spotify import get_spotify_auth_url, exchange_spotify_code, get_spotify_client
from .youtube import get_youtube_auth_url, exchange_youtube_code, get_youtube_client

logger = logging.getLogger(__name__)


@login_required
def spotify_connect(request):
    state = secrets.token_urlsafe(16)
    request.session['spotify_oauth_state'] = state
    return redirect(get_spotify_auth_url(state=state))


@login_required
def spotify_callback(request):
    expected_state = request.session.pop('spotify_oauth_state', None)
    received_state = request.GET.get('state')
    error = request.GET.get('error')

    if error:
        messages.error(request, f'Spotify authorization was denied: {error}')
        return redirect('importer:dashboard')

    if not expected_state or expected_state != received_state:
        return HttpResponseBadRequest('Invalid OAuth state parameter.')

    code = request.GET.get('code')
    if not code:
        return HttpResponseBadRequest('Missing authorization code.')

    try:
        token_info = exchange_spotify_code(code)
        access_token = token_info['access_token']
        refresh_token = token_info.get('refresh_token', '')
        expires_in = token_info.get('expires_in', 3600)

        platform_token, _ = PlatformToken.objects.get_or_create(
            user=request.user,
            platform=PlatformToken.PLATFORM_SPOTIFY
        )
        platform_token.set_access_token(access_token)
        if refresh_token:
            platform_token.set_refresh_token(refresh_token)
        platform_token.expires_at = timezone.now() + timedelta(seconds=expires_in)

        try:
            sp = get_spotify_client(request.user)
            profile = sp.current_user()
            platform_token.platform_username = profile.get('display_name') or profile.get('id', '')
            platform_token.platform_user_id = profile.get('id', '')
        except Exception as profile_err:
            logger.warning("No se pudo obtener el perfil de Spotify para el usuario %s: %s", request.user.username, profile_err)

        platform_token.save()
        messages.success(request, f'Spotify connected successfully as {platform_token.platform_username or "user"}.')
    except Exception as e:
        messages.error(request, f'Failed to connect Spotify: {str(e)}')

    return redirect('importer:dashboard')


@login_required
def spotify_disconnect(request):
    if request.method == 'POST':
        PlatformToken.objects.filter(
            user=request.user,
            platform=PlatformToken.PLATFORM_SPOTIFY
        ).delete()
        messages.info(request, 'Spotify account disconnected.')
    return redirect('importer:dashboard')


@login_required
def youtube_connect(request):
    state = secrets.token_urlsafe(16)
    request.session['youtube_oauth_state'] = state
    return redirect(get_youtube_auth_url(state=state))


@login_required
def youtube_callback(request):
    expected_state = request.session.pop('youtube_oauth_state', None)
    received_state = request.GET.get('state')
    error = request.GET.get('error')

    if error:
        messages.error(request, f'Google authorization was denied: {error}')
        return redirect('importer:dashboard')

    if not expected_state or expected_state != received_state:
        return HttpResponseBadRequest('Invalid OAuth state parameter.')

    code = request.GET.get('code')
    if not code:
        return HttpResponseBadRequest('Missing authorization code.')

    try:
        token_info = exchange_youtube_code(code)
        access_token = token_info['token']
        refresh_token = token_info.get('refresh_token', '')
        expiry = token_info.get('expiry')

        platform_token, _ = PlatformToken.objects.get_or_create(
            user=request.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        )
        platform_token.set_access_token(access_token)
        if refresh_token:
            platform_token.set_refresh_token(refresh_token)

        platform_token.expires_at = expiry or (timezone.now() + timedelta(seconds=3600))

        try:
            yt = get_youtube_client(request.user)
            channel_response = yt.channels().list(part='snippet', mine=True).execute()
            items = channel_response.get('items', [])
            if items:
                snippet = items[0].get('snippet', {})
                platform_token.platform_username = snippet.get('title', '')
                platform_token.platform_user_id = items[0].get('id', '')
        except Exception as profile_err:
            logger.warning("No se pudo obtener el canal de YouTube para el usuario %s: %s", request.user.username, profile_err)

        platform_token.save()
        messages.success(request, f'YouTube connected successfully as {platform_token.platform_username or "user"}.')
    except Exception as e:
        messages.error(request, f'Failed to connect YouTube: {str(e)}')

    return redirect('importer:dashboard')


@login_required
def youtube_disconnect(request):
    if request.method == 'POST':
        PlatformToken.objects.filter(
            user=request.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        ).delete()
        messages.info(request, 'YouTube account disconnected.')
    return redirect('importer:dashboard')


@login_required
def connection_status(request):
    tokens = {
        token.platform: token
        for token in PlatformToken.objects.filter(user=request.user)
    }

    spotify_token = tokens.get(PlatformToken.PLATFORM_SPOTIFY)
    youtube_token = tokens.get(PlatformToken.PLATFORM_YOUTUBE)

    data = {
        'spotify': {
            'connected': spotify_token is not None,
            'username': spotify_token.platform_username if spotify_token else '',
            'expired': spotify_token.is_expired() if spotify_token else False,
        },
        'youtube': {
            'connected': youtube_token is not None,
            'username': youtube_token.platform_username if youtube_token else '',
            'expired': youtube_token.is_expired() if youtube_token else False,
        }
    }
    return JsonResponse(data)
