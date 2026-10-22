import logging
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import render
from apps.integrations.models import PlatformToken
from apps.integrations.spotify import get_user_spotify_playlists, get_spotify_playlist_tracks
from apps.integrations.youtube import get_user_youtube_playlists, get_youtube_playlist_tracks

logger = logging.getLogger(__name__)

CACHE_TTL_PLAYLISTS = 120


@login_required
def dashboard_view(request):
    tokens = {
        token.platform: token
        for token in PlatformToken.objects.filter(user=request.user)
    }

    context = {
        'spotify_token': tokens.get(PlatformToken.PLATFORM_SPOTIFY),
        'youtube_token': tokens.get(PlatformToken.PLATFORM_YOUTUBE),
    }
    return render(request, 'importer/dashboard.html', context)


@login_required
def spotify_playlists_view(request):
    query = request.GET.get('q', '').strip()
    force_refresh = request.GET.get('refresh', '').lower() == 'true'
    cache_key = f"user_playlists_spotify_{request.user.id}"

    spotify_token = PlatformToken.objects.filter(
        user=request.user,
        platform=PlatformToken.PLATFORM_SPOTIFY
    ).first()

    if not spotify_token:
        return render(request, 'importer/components/spotify_playlists.html', {
            'connected': False,
            'playlists': [],
            'query': query,
        })

    try:
        all_playlists = None if force_refresh else cache.get(cache_key)
        if all_playlists is None:
            all_playlists = get_user_spotify_playlists(request.user)
            cache.set(cache_key, all_playlists, CACHE_TTL_PLAYLISTS)

        if query:
            filtered_playlists = [p for p in all_playlists if query.lower() in p['name'].lower()]
        else:
            filtered_playlists = all_playlists

        error_message = None
    except Exception as e:
        logger.warning("Error al obtener playlists de Spotify para %s: %s", request.user.username, e)
        filtered_playlists = []
        error_message = "No se pudo cargar tu biblioteca de Spotify. Por favor, intenta nuevamente."

    return render(request, 'importer/components/spotify_playlists.html', {
        'connected': True,
        'playlists': filtered_playlists,
        'query': query,
        'error_message': error_message,
    })


@login_required
def youtube_playlists_view(request):
    query = request.GET.get('q', '').strip()
    force_refresh = request.GET.get('refresh', '').lower() == 'true'
    cache_key = f"user_playlists_youtube_{request.user.id}"

    youtube_token = PlatformToken.objects.filter(
        user=request.user,
        platform=PlatformToken.PLATFORM_YOUTUBE
    ).first()

    if not youtube_token:
        return render(request, 'importer/components/youtube_playlists.html', {
            'connected': False,
            'playlists': [],
            'query': query,
        })

    try:
        all_playlists = None if force_refresh else cache.get(cache_key)
        if all_playlists is None:
            all_playlists = get_user_youtube_playlists(request.user)
            cache.set(cache_key, all_playlists, CACHE_TTL_PLAYLISTS)

        if query:
            filtered_playlists = [p for p in all_playlists if query.lower() in p['name'].lower()]
        else:
            filtered_playlists = all_playlists

        error_message = None
    except Exception as e:
        logger.warning("Error al obtener playlists de YouTube para %s: %s", request.user.username, e)
        filtered_playlists = []
        error_message = "No se pudo cargar tu biblioteca de YouTube Music. Por favor, intenta nuevamente."

    return render(request, 'importer/components/youtube_playlists.html', {
        'connected': True,
        'playlists': filtered_playlists,
        'query': query,
        'error_message': error_message,
    })


@login_required
def playlist_tracks_modal_view(request, platform, playlist_id):
    tracks = []
    error_message = None
    playlist_name = request.GET.get('name', 'Playlist')
    total_tracks = int(request.GET.get('total', 0)) if request.GET.get('total', '').isdigit() else None

    if platform not in ('spotify', 'youtube'):
        error_message = 'Plataforma no soportada.'
        return render(request, 'importer/components/playlist_tracks_modal.html', {
            'platform': platform,
            'playlist_id': playlist_id,
            'playlist_name': playlist_name,
            'tracks': tracks,
            'error_message': error_message,
            'total_tracks': total_tracks,
        })

    try:
        if platform == 'spotify':
            tracks = get_spotify_playlist_tracks(request.user, playlist_id, limit=100)
        elif platform == 'youtube':
            tracks = get_youtube_playlist_tracks(request.user, playlist_id, limit=100)
    except Exception as e:
        logger.warning("Error al obtener canciones de %s (%s): %s", platform, playlist_id, e)
        error_message = "No se pudieron obtener las canciones de la lista seleccionada."

    return render(request, 'importer/components/playlist_tracks_modal.html', {
        'platform': platform,
        'playlist_id': playlist_id,
        'playlist_name': playlist_name,
        'tracks': tracks,
        'total_tracks': total_tracks,
        'error_message': error_message,
    })
