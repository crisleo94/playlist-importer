import logging
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from apps.integrations.models import PlatformToken
from apps.integrations.spotify import get_user_spotify_playlists, get_spotify_playlist_tracks
from apps.integrations.youtube import get_user_youtube_playlists, get_youtube_playlist_tracks

logger = logging.getLogger(__name__)


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
        playlists = get_user_spotify_playlists(request.user, search_query=query)
        error_message = None
    except Exception as e:
        logger.warning("Error al obtener playlists de Spotify para %s: %s", request.user.username, e)
        playlists = []
        error_message = str(e)

    return render(request, 'importer/components/spotify_playlists.html', {
        'connected': True,
        'playlists': playlists,
        'query': query,
        'error_message': error_message,
    })


@login_required
def youtube_playlists_view(request):
    query = request.GET.get('q', '').strip()
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
        playlists = get_user_youtube_playlists(request.user, search_query=query)
        error_message = None
    except Exception as e:
        logger.warning("Error al obtener playlists de YouTube para %s: %s", request.user.username, e)
        playlists = []
        error_message = str(e)

    return render(request, 'importer/components/youtube_playlists.html', {
        'connected': True,
        'playlists': playlists,
        'query': query,
        'error_message': error_message,
    })


@login_required
def playlist_tracks_modal_view(request, platform, playlist_id):
    tracks = []
    error_message = None
    playlist_name = request.GET.get('name', 'Playlist')

    try:
        if platform == 'spotify':
            tracks = get_spotify_playlist_tracks(request.user, playlist_id)
        elif platform == 'youtube':
            tracks = get_youtube_playlist_tracks(request.user, playlist_id)
        else:
            error_message = 'Plataforma no soportada.'
    except Exception as e:
        logger.warning("Error al obtener canciones de %s (%s): %s", platform, playlist_id, e)
        error_message = str(e)

    return render(request, 'importer/components/playlist_tracks_modal.html', {
        'platform': platform,
        'playlist_id': playlist_id,
        'playlist_name': playlist_name,
        'tracks': tracks,
        'error_message': error_message,
    })
