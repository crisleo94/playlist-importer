import logging
import time
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from apps.importer.matcher import (
    match_spotify_track_to_youtube,
    match_youtube_track_to_spotify,
    QuotaOrRateLimitExceeded,
    is_quota_or_rate_limit_error,
)
from apps.importer.models import ImportJob, ImportJobItem
from apps.integrations.spotify import (
    get_spotify_client,
    get_spotify_playlist_tracks,
    create_spotify_playlist,
    add_tracks_to_spotify_playlist,
)
from apps.integrations.youtube import (
    get_youtube_client,
    get_youtube_playlist_tracks,
    create_youtube_playlist,
    add_video_to_youtube_playlist,
)

logger = logging.getLogger(__name__)


@shared_task(bind=True, time_limit=900, soft_time_limit=840)
def run_playlist_import(self, job_id: int):
    try:
        job = ImportJob.objects.select_related('user').get(id=job_id)
    except ImportJob.DoesNotExist:
        logger.error("ImportJob id=%s no existe.", job_id)
        return

    if job.is_finished:
        logger.info("ImportJob id=%s ya se encuentra finalizado (%s).", job_id, job.status)
        return

    job.status = ImportJob.STATUS_PROCESSING
    job.celery_task_id = self.request.id or ''
    job.save(update_fields=['status', 'celery_task_id', 'updated_at'])

    try:
        # 1. Obtener canciones de la lista origen
        if job.source_platform == ImportJob.PLATFORM_SPOTIFY:
            source_tracks = get_spotify_playlist_tracks(job.user, job.source_playlist_id, limit=200)
        elif job.source_platform == ImportJob.PLATFORM_YOUTUBE:
            source_tracks = get_youtube_playlist_tracks(job.user, job.source_playlist_id, limit=200)
        else:
            raise ValueError(f"Plataforma origen inválida: {job.source_platform}")

        job.total_tracks = len(source_tracks)
        job.save(update_fields=['total_tracks', 'updated_at'])

        if not source_tracks:
            job.status = ImportJob.STATUS_COMPLETED
            job.save(update_fields=['status', 'updated_at'])
            return

        # 2. Inicializar cliente destino y crear playlist si aplica
        target_client = None
        if job.target_platform == ImportJob.PLATFORM_SPOTIFY:
            target_client = get_spotify_client(job.user)
            if job.destination_mode == ImportJob.DEST_MODE_NEW and not job.target_playlist_id:
                name = job.target_playlist_name or f"{job.source_playlist_name} (Imported)"
                created = create_spotify_playlist(job.user, name=name, sp_client=target_client)
                job.target_playlist_id = created['id']
                job.target_playlist_name = created['name']
                job.save(update_fields=['target_playlist_id', 'target_playlist_name', 'updated_at'])

        elif job.target_platform == ImportJob.PLATFORM_YOUTUBE:
            target_client = get_youtube_client(job.user)
            if job.destination_mode == ImportJob.DEST_MODE_NEW and not job.target_playlist_id:
                name = job.target_playlist_name or f"{job.source_playlist_name} (Imported)"
                created = create_youtube_playlist(job.user, name=name, yt_client=target_client)
                job.target_playlist_id = created['id']
                job.target_playlist_name = created['name']
                job.save(update_fields=['target_playlist_id', 'target_playlist_name', 'updated_at'])

        # 3. Iterar pistas, emparejar y transferir
        spotify_uri_batch = []
        pending_spotify_items = []

        # Pistas ya agregadas a este mismo destino en un job anterior (reanudación):
        # se evita volver a buscarlas e insertarlas, sin gastar cuota de ninguna API.
        already_added_source_ids = set(
            ImportJobItem.objects.filter(
                job__user=job.user,
                job__source_platform=job.source_platform,
                job__target_platform=job.target_platform,
                job__target_playlist_id=job.target_playlist_id,
                status=ImportJobItem.STATUS_ADDED,
            ).exclude(job=job).exclude(source_track_id='').values_list('source_track_id', flat=True)
        )

        for track in source_tracks:
            track_title = track.get('title', 'Canción sin título')
            track_artist = track.get('artist', '')
            track_id = track.get('id', '')

            if track_id and track_id in already_added_source_ids:
                ImportJobItem.objects.create(
                    job=job,
                    source_track_id=track_id,
                    source_title=track_title,
                    source_artist=track_artist,
                    source_isrc=track.get('isrc', ''),
                    status=ImportJobItem.STATUS_ADDED,
                )
                job.successful_tracks += 1
                job.processed_tracks += 1
                job.save(update_fields=['processed_tracks', 'successful_tracks', 'failed_tracks', 'updated_at'])
                continue

            job.current_track_name = track_title
            job.save(update_fields=['current_track_name', 'updated_at'])

            try:
                matched = None
                if job.source_platform == ImportJob.PLATFORM_SPOTIFY and job.target_platform == ImportJob.PLATFORM_YOUTUBE:
                    matched = match_spotify_track_to_youtube(job.user, track, yt_client=target_client)
                elif job.source_platform == ImportJob.PLATFORM_YOUTUBE and job.target_platform == ImportJob.PLATFORM_SPOTIFY:
                    time.sleep(0.08)
                    matched = match_youtube_track_to_spotify(job.user, track, sp_client=target_client)
            except Exception as e:
                if is_quota_or_rate_limit_error(e):
                    target_name = "YouTube Music" if job.target_platform == ImportJob.PLATFORM_YOUTUBE else "Spotify"
                    job.error_message = f"Límite de cuota o peticiones de {target_name} alcanzado. Se detuvo la transferencia para proteger la cuenta."
                    item = ImportJobItem.objects.create(
                        job=job,
                        source_track_id=track_id,
                        source_title=track_title,
                        source_artist=track_artist,
                        source_isrc=track.get('isrc', ''),
                        status=ImportJobItem.STATUS_FAILED,
                        error_message=f"Límite de cuota de {target_name} alcanzado",
                        is_quota_error=True,
                    )
                    job.failed_tracks += 1
                    job.processed_tracks += 1
                    job.save(update_fields=['processed_tracks', 'successful_tracks', 'failed_tracks', 'error_message', 'updated_at'])
                    break
                else:
                    logger.warning("Error inesperado en emparejamiento de pista '%s': %s", track_title, e)
                    matched = None

            if matched:
                item = ImportJobItem.objects.create(
                    job=job,
                    source_track_id=track_id,
                    source_title=track_title,
                    source_artist=track_artist,
                    source_isrc=track.get('isrc', ''),
                    target_track_id=matched.get('id', ''),
                    target_track_uri=matched.get('uri', ''),
                    target_title=matched.get('title', ''),
                    target_artist=matched.get('artist', ''),
                    match_type=matched.get('match_type', 'fuzzy'),
                    match_score=matched.get('score', 0.0),
                    status=ImportJobItem.STATUS_MATCHED,
                )

                # Transferir a destino
                if job.target_platform == ImportJob.PLATFORM_YOUTUBE:
                    try:
                        add_video_to_youtube_playlist(
                            job.user,
                            job.target_playlist_id,
                            matched['id'],
                            yt_client=target_client
                        )
                        item.status = ImportJobItem.STATUS_ADDED
                        job.successful_tracks += 1
                        time.sleep(0.15)
                        item.save(update_fields=['status'])
                    except Exception as e:
                        logger.warning("Error al insertar video en YouTube playlist: %s", e)
                        is_quota = is_quota_or_rate_limit_error(e)
                        item.status = ImportJobItem.STATUS_FAILED
                        item.error_message = "Límite de cuota diaria de YouTube alcanzado" if is_quota else str(e)
                        item.is_quota_error = is_quota
                        item.save(update_fields=['status', 'error_message', 'is_quota_error'])
                        job.failed_tracks += 1
                        if is_quota:
                            job.error_message = "Límite de cuota diaria de YouTube Music alcanzado (Google Cloud). Se detuvo la transferencia para proteger la cuenta."
                            job.processed_tracks += 1
                            job.save(update_fields=['processed_tracks', 'successful_tracks', 'failed_tracks', 'error_message', 'updated_at'])
                            break

                elif job.target_platform == ImportJob.PLATFORM_SPOTIFY:
                    if matched.get('uri'):
                        spotify_uri_batch.append(matched['uri'])
                        pending_spotify_items.append(item)

                        if len(spotify_uri_batch) >= 25:
                            try:
                                add_tracks_to_spotify_playlist(
                                    job.user,
                                    job.target_playlist_id,
                                    spotify_uri_batch,
                                    sp_client=target_client
                                )
                                for pending in pending_spotify_items:
                                    pending.status = ImportJobItem.STATUS_ADDED
                                    pending.save(update_fields=['status'])
                                    job.successful_tracks += 1
                                spotify_uri_batch = []
                                pending_spotify_items = []
                            except Exception as e:
                                logger.warning("Error al insertar lote en Spotify playlist: %s", e)
                                is_quota = is_quota_or_rate_limit_error(e)
                                err_msg = "Límite de peticiones de Spotify alcanzado (HTTP 429)" if is_quota else str(e)
                                for pending in pending_spotify_items:
                                    pending.status = ImportJobItem.STATUS_FAILED
                                    pending.error_message = err_msg
                                    pending.is_quota_error = is_quota
                                    pending.save(update_fields=['status', 'error_message', 'is_quota_error'])
                                    job.failed_tracks += 1
                                spotify_uri_batch = []
                                pending_spotify_items = []
                                if is_quota:
                                    job.error_message = "Límite de peticiones de Spotify alcanzado (HTTP 429). Se detuvo la transferencia."
                                    job.processed_tracks += 1
                                    job.save(update_fields=['processed_tracks', 'successful_tracks', 'failed_tracks', 'error_message', 'updated_at'])
                                    break
            else:
                ImportJobItem.objects.create(
                    job=job,
                    source_track_id=track_id,
                    source_title=track_title,
                    source_artist=track_artist,
                    source_isrc=track.get('isrc', ''),
                    status=ImportJobItem.STATUS_NOT_FOUND,
                )
                job.failed_tracks += 1

            job.processed_tracks += 1
            job.save(update_fields=['processed_tracks', 'successful_tracks', 'failed_tracks', 'updated_at'])

        # Volcar remanente de Spotify
        if spotify_uri_batch and pending_spotify_items:
            try:
                add_tracks_to_spotify_playlist(
                    job.user,
                    job.target_playlist_id,
                    spotify_uri_batch,
                    sp_client=target_client
                )
                for pending in pending_spotify_items:
                    pending.status = ImportJobItem.STATUS_ADDED
                    pending.save(update_fields=['status'])
                    job.successful_tracks += 1
            except Exception as e:
                logger.warning("Error al insertar lote final en Spotify playlist: %s", e)
                is_quota = is_quota_or_rate_limit_error(e)
                err_msg = "Límite de peticiones de Spotify alcanzado (HTTP 429)" if is_quota else str(e)
                for pending in pending_spotify_items:
                    pending.status = ImportJobItem.STATUS_FAILED
                    pending.error_message = err_msg
                    pending.is_quota_error = is_quota
                    pending.save(update_fields=['status', 'error_message', 'is_quota_error'])
                    job.failed_tracks += 1
                if is_quota:
                    job.error_message = "Límite de peticiones de Spotify alcanzado (HTTP 429). Se detuvo la transferencia."

        # 4. Estado final
        if job.successful_tracks == job.total_tracks and job.total_tracks > 0:
            job.status = ImportJob.STATUS_COMPLETED
        elif job.successful_tracks > 0:
            job.status = ImportJob.STATUS_PARTIAL
        else:
            job.status = ImportJob.STATUS_FAILED

        job.current_track_name = ''
        job.save(update_fields=['status', 'successful_tracks', 'failed_tracks', 'current_track_name', 'updated_at'])

    except SoftTimeLimitExceeded:
        logger.error("Tiempo límite excedido en Celery task de importación job_id=%s", job_id)
        job.status = ImportJob.STATUS_FAILED
        job.error_message = "El tiempo de importación ha excedido el límite permitido (timeout de ejecución)."
        job.current_track_name = ''
        job.save(update_fields=['status', 'error_message', 'current_track_name', 'updated_at'])
    except Exception as e:
        logger.exception("Fallo crítico en tarea Celery de importación job_id=%s: %s", job_id, e)
        job.status = ImportJob.STATUS_FAILED
        job.error_message = "Ocurrió un error inesperado durante la importación. Por favor, reintenta."
        job.current_track_name = ''
        job.save(update_fields=['status', 'error_message', 'current_track_name', 'updated_at'])
