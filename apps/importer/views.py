import logging
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST
from apps.importer.models import ImportJob, ImportJobItem
from apps.importer.tasks import run_playlist_import
from apps.integrations.models import PlatformToken
from apps.integrations.spotify import (
    get_user_spotify_playlists,
    get_spotify_playlist_tracks,
    get_spotify_playlist_details,
)
from apps.integrations.youtube import (
    get_user_youtube_playlists,
    get_youtube_playlist_tracks,
    get_youtube_playlist_details,
)
from apps.importer.matcher import preview_playlist_match
from apps.importer.parsers import parse_playlist_input

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
        if total_tracks is None:
            total_tracks = len(tracks)
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


@login_required
def preview_match_view(request, source_platform, playlist_id):
    playlist_name = request.GET.get('name', 'Playlist')
    preview_data = None
    target_playlists = []
    error_message = None

    if source_platform not in ('spotify', 'youtube'):
        return render(request, 'importer/components/preview_match_modal.html', {
            'source_platform': source_platform,
            'target_platform': '',
            'playlist_id': playlist_id,
            'playlist_name': playlist_name,
            'preview': None,
            'target_playlists': [],
            'error_message': 'Plataforma no soportada.',
        })

    target_platform = 'youtube' if source_platform == 'spotify' else 'spotify'

    target_token = PlatformToken.objects.filter(
        user=request.user,
        platform=target_platform
    ).first()

    if not target_token:
        target_name = 'YouTube Music' if target_platform == 'youtube' else 'Spotify'
        error_message = f"Debes conectar tu cuenta de {target_name} para poder transferir hacia ella."
    else:
        try:
            preview_data = preview_playlist_match(
                request.user,
                source_platform=source_platform,
                target_platform=target_platform,
                playlist_id=playlist_id,
                limit=15
            )

            if target_platform == 'youtube':
                target_playlists = get_user_youtube_playlists(request.user)
            else:
                target_playlists = get_user_spotify_playlists(request.user)
        except Exception as e:
            logger.warning("Error al generar vista previa de emparejamiento %s -> %s: %s", source_platform, target_platform, e)
            error_message = "No se pudo generar la vista previa de coincidencia. Por favor, intenta de nuevo."

    return render(request, 'importer/components/preview_match_modal.html', {
        'source_platform': source_platform,
        'target_platform': target_platform,
        'playlist_id': playlist_id,
        'playlist_name': playlist_name,
        'preview': preview_data,
        'target_playlists': target_playlists,
        'error_message': error_message,
    })


@login_required
def import_by_url_modal_view(request):
    return render(request, 'importer/components/import_url_modal.html')


@login_required
@require_POST
def import_by_url_view(request):
    raw_input = request.POST.get('playlist_url', '').strip()
    parsed = parse_playlist_input(raw_input)

    if not parsed:
        return render(request, 'importer/components/preview_match_modal.html', {
            'source_platform': '',
            'target_platform': '',
            'playlist_id': '',
            'playlist_name': 'Enlace inválido',
            'preview': None,
            'target_playlists': [],
            'error_message': 'No pudimos reconocer el enlace o ID de la playlist. Asegúrate de que sea un enlace válido de Spotify o YouTube / YouTube Music.',
        })

    source_platform, playlist_id = parsed
    target_platform = 'youtube' if source_platform == 'spotify' else 'spotify'

    source_token = PlatformToken.objects.filter(user=request.user, platform=source_platform).first()
    if not source_token:
        source_name = 'Spotify' if source_platform == 'spotify' else 'YouTube Music'
        return render(request, 'importer/components/preview_match_modal.html', {
            'source_platform': source_platform,
            'target_platform': target_platform,
            'playlist_id': playlist_id,
            'playlist_name': 'Cuenta no conectada',
            'preview': None,
            'target_playlists': [],
            'error_message': f"Debes conectar tu cuenta de {source_name} para inspeccionar y leer playlists de esa plataforma.",
        })

    target_token = PlatformToken.objects.filter(user=request.user, platform=target_platform).first()
    if not target_token:
        target_name = 'YouTube Music' if target_platform == 'youtube' else 'Spotify'
        return render(request, 'importer/components/preview_match_modal.html', {
            'source_platform': source_platform,
            'target_platform': target_platform,
            'playlist_id': playlist_id,
            'playlist_name': 'Cuenta destino requerida',
            'preview': None,
            'target_playlists': [],
            'error_message': f"Debes conectar tu cuenta de {target_name} para poder transferir hacia ella.",
        })

    playlist_name = 'Playlist'
    try:
        if source_platform == 'spotify':
            details = get_spotify_playlist_details(request.user, playlist_id)
            playlist_name = details.get('name', 'Playlist de Spotify')
        else:
            details = get_youtube_playlist_details(request.user, playlist_id)
            playlist_name = details.get('name', 'Playlist de YouTube')
    except Exception as e:
        logger.warning("No se pudo obtener detalles de playlist externa (%s, %s): %s", source_platform, playlist_id, e)

    preview_data = None
    target_playlists = []
    error_message = None

    try:
        preview_data = preview_playlist_match(
            request.user,
            source_platform=source_platform,
            target_platform=target_platform,
            playlist_id=playlist_id,
            limit=15
        )

        if target_platform == 'youtube':
            target_playlists = get_user_youtube_playlists(request.user)
        else:
            target_playlists = get_user_spotify_playlists(request.user)
    except Exception as e:
        logger.warning("Error al previsualizar playlist por URL %s (%s): %s", source_platform, playlist_id, e)
        error_message = "No se pudo leer la playlist. Verifica que sea pública o colaborativa y que tu cuenta tenga acceso a ella."

    return render(request, 'importer/components/preview_match_modal.html', {
        'source_platform': source_platform,
        'target_platform': target_platform,
        'playlist_id': playlist_id,
        'playlist_name': playlist_name,
        'preview': preview_data,
        'target_playlists': target_playlists,
        'error_message': error_message,
    })


@login_required
@require_POST
def start_import_view(request):
    source_platform = request.POST.get('source_platform', '')
    source_playlist_id = request.POST.get('source_playlist_id', '')
    source_playlist_name = request.POST.get('source_playlist_name', 'Playlist')
    dest_mode = request.POST.get('dest_mode', ImportJob.DEST_MODE_NEW)
    new_playlist_name = request.POST.get('new_playlist_name', '').strip() or source_playlist_name
    selected_playlist_id = request.POST.get('selected_playlist_id', '').strip()

    if source_platform not in ('spotify', 'youtube') or not source_playlist_id:
        return render(request, 'importer/components/import_progress.html', {
            'error_message': 'Datos de importación inválidos.',
        })

    target_platform = 'youtube' if source_platform == 'spotify' else 'spotify'
    target_token = PlatformToken.objects.filter(user=request.user, platform=target_platform).first()
    if not target_token:
        target_name = 'YouTube Music' if target_platform == 'youtube' else 'Spotify'
        return render(request, 'importer/components/import_progress.html', {
            'error_message': f"Debes conectar tu cuenta de {target_name} antes de iniciar la importación.",
        })

    # Prevención de doble-submit o jobs concurrentes duplicados para la misma lista
    existing_job = ImportJob.objects.filter(
        user=request.user,
        source_platform=source_platform,
        source_playlist_id=source_playlist_id,
        target_platform=target_platform,
        status__in=[ImportJob.STATUS_PENDING, ImportJob.STATUS_PROCESSING]
    ).first()
    if existing_job:
        return render(request, 'importer/components/import_progress.html', {
            'job': existing_job,
        })

    job = ImportJob.objects.create(
        user=request.user,
        source_platform=source_platform,
        target_platform=target_platform,
        source_playlist_id=source_playlist_id,
        source_playlist_name=source_playlist_name,
        destination_mode=dest_mode,
        target_playlist_id=selected_playlist_id if dest_mode == ImportJob.DEST_MODE_EXISTING else '',
        target_playlist_name=new_playlist_name if dest_mode == ImportJob.DEST_MODE_NEW else '',
        status=ImportJob.STATUS_PENDING,
    )

    task = run_playlist_import.delay(job.id)
    job.celery_task_id = task.id or ''
    job.save(update_fields=['celery_task_id'])

    return render(request, 'importer/components/import_progress.html', {
        'job': job,
    })


@login_required
def import_progress_view(request, job_id):
    job = get_object_or_404(ImportJob, id=job_id, user=request.user)
    unmatched_items = []
    if job.is_finished:
        unmatched_items = list(job.items.filter(status__in=[ImportJobItem.STATUS_NOT_FOUND, ImportJobItem.STATUS_FAILED])[:50])

    return render(request, 'importer/components/import_progress.html', {
        'job': job,
        'unmatched_items': unmatched_items,
    })
