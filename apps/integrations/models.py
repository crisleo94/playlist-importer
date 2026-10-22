from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from apps.core.crypto import encrypt_string, decrypt_string


class PlatformToken(models.Model):
    PLATFORM_SPOTIFY = 'spotify'
    PLATFORM_YOUTUBE = 'youtube'
    PLATFORM_CHOICES = [
        (PLATFORM_SPOTIFY, 'Spotify'),
        (PLATFORM_YOUTUBE, 'YouTube'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='platform_tokens'
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    encrypted_access_token = models.TextField()
    encrypted_refresh_token = models.TextField(blank=True, default='')
    token_type = models.CharField(max_length=50, default='Bearer')
    expires_at = models.DateTimeField(null=True, blank=True)
    platform_username = models.CharField(max_length=255, blank=True, default='')
    platform_user_id = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'platform')
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} - {self.get_platform_display()}"

    def get_access_token(self) -> str:
        return decrypt_string(self.encrypted_access_token)

    def set_access_token(self, token: str):
        self.encrypted_access_token = encrypt_string(token)

    def get_refresh_token(self) -> str:
        return decrypt_string(self.encrypted_refresh_token)

    def set_refresh_token(self, token: str):
        self.encrypted_refresh_token = encrypt_string(token)

    def save(self, *args, **kwargs):
        if self.expires_at and timezone.is_naive(self.expires_at):
            from datetime import timezone as dt_timezone
            self.expires_at = self.expires_at.replace(tzinfo=dt_timezone.utc)
        super().save(*args, **kwargs)

    def is_expired(self, buffer_seconds: int = 60) -> bool:
        if not self.expires_at:
            return False
        expires = self.expires_at
        if timezone.is_naive(expires):
            from datetime import timezone as dt_timezone
            expires = expires.replace(tzinfo=dt_timezone.utc)
        return timezone.now() >= (expires - timedelta(seconds=buffer_seconds))
