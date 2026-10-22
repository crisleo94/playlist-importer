from django.conf import settings
from django.db import models


class ImportJob(models.Model):
    PLATFORM_SPOTIFY = 'spotify'
    PLATFORM_YOUTUBE = 'youtube'
    PLATFORM_CHOICES = [
        (PLATFORM_SPOTIFY, 'Spotify'),
        (PLATFORM_YOUTUBE, 'YouTube Music'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_PARTIAL = 'partial'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendiente'),
        (STATUS_PROCESSING, 'Procesando'),
        (STATUS_COMPLETED, 'Completado'),
        (STATUS_PARTIAL, 'Parcialmente completado'),
        (STATUS_FAILED, 'Fallido'),
    ]

    DEST_MODE_NEW = 'new'
    DEST_MODE_EXISTING = 'existing'
    DEST_MODE_CHOICES = [
        (DEST_MODE_NEW, 'Nueva Playlist'),
        (DEST_MODE_EXISTING, 'Playlist Existente'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='import_jobs'
    )
    source_platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    target_platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    source_playlist_id = models.CharField(max_length=255)
    source_playlist_name = models.CharField(max_length=255)
    target_playlist_id = models.CharField(max_length=255, blank=True, default='')
    target_playlist_name = models.CharField(max_length=255, blank=True, default='')
    destination_mode = models.CharField(
        max_length=20,
        choices=DEST_MODE_CHOICES,
        default=DEST_MODE_NEW
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )
    total_tracks = models.PositiveIntegerField(default=0)
    processed_tracks = models.PositiveIntegerField(default=0)
    successful_tracks = models.PositiveIntegerField(default=0)
    failed_tracks = models.PositiveIntegerField(default=0)
    current_track_name = models.CharField(max_length=255, blank=True, default='')
    error_message = models.TextField(blank=True, default='')
    celery_task_id = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Import {self.source_playlist_name} ({self.source_platform} -> {self.target_platform}) [{self.status}]"

    @property
    def progress_percentage(self) -> int:
        if self.total_tracks == 0:
            return 0
        return min(100, int((self.processed_tracks / self.total_tracks) * 100))

    @property
    def is_finished(self) -> bool:
        return self.status in (self.STATUS_COMPLETED, self.STATUS_PARTIAL, self.STATUS_FAILED)


class ImportJobItem(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_MATCHED = 'matched'
    STATUS_NOT_FOUND = 'not_found'
    STATUS_ADDED = 'added'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pendiente'),
        (STATUS_MATCHED, 'Emparejada'),
        (STATUS_NOT_FOUND, 'No encontrada'),
        (STATUS_ADDED, 'Agregada con éxito'),
        (STATUS_FAILED, 'Error al agregar'),
    ]

    job = models.ForeignKey(
        ImportJob,
        on_delete=models.CASCADE,
        related_name='items'
    )
    source_track_id = models.CharField(max_length=255, blank=True, default='')
    source_title = models.CharField(max_length=255)
    source_artist = models.CharField(max_length=255, blank=True, default='')
    source_isrc = models.CharField(max_length=50, blank=True, default='')
    target_track_id = models.CharField(max_length=255, blank=True, default='')
    target_track_uri = models.CharField(max_length=255, blank=True, default='')
    target_title = models.CharField(max_length=255, blank=True, default='')
    target_artist = models.CharField(max_length=255, blank=True, default='')
    match_type = models.CharField(max_length=20, blank=True, default='')
    match_score = models.FloatField(default=0.0)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.source_title} -> {self.target_title or 'N/A'} [{self.status}]"
