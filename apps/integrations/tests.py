from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from apps.core.crypto import encrypt_string, decrypt_string
from apps.integrations.models import PlatformToken

User = get_user_model()


class CryptoTests(TestCase):
    def test_encryption_and_decryption_roundtrip(self):
        secret = "my-secret-access-token-12345"
        encrypted = encrypt_string(secret)
        self.assertNotEqual(secret, encrypted)
        decrypted = decrypt_string(encrypted)
        self.assertEqual(secret, decrypted)

    def test_empty_string_handling(self):
        self.assertEqual(encrypt_string(""), "")
        self.assertEqual(decrypt_string(""), "")


class PlatformTokenModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password123")

    def test_token_encryption_helpers(self):
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY,
        )
        token.set_access_token("access-123")
        token.set_refresh_token("refresh-456")
        token.save()

        fetched = PlatformToken.objects.get(id=token.id)
        self.assertNotEqual(fetched.encrypted_access_token, "access-123")
        self.assertEqual(fetched.get_access_token(), "access-123")
        self.assertEqual(fetched.get_refresh_token(), "refresh-456")

    def test_is_expired(self):
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE,
            expires_at=timezone.now() - timedelta(minutes=5)
        )
        self.assertTrue(token.is_expired())

        token.expires_at = timezone.now() + timedelta(hours=1)
        self.assertFalse(token.is_expired())


class IntegrationsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="password123")

    def test_connection_status_requires_login(self):
        response = self.client.get(reverse('integrations:status'))
        self.assertEqual(response.status_code, 302)

    def test_connection_status_authenticated(self):
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse('integrations:status'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['spotify']['connected'])
        self.assertFalse(data['youtube']['connected'])

        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY,
            platform_username="spotify_user_test"
        )
        token.set_access_token("token")
        token.save()

        response2 = self.client.get(reverse('integrations:status'))
        data2 = response2.json()
        self.assertTrue(data2['spotify']['connected'])
        self.assertEqual(data2['spotify']['username'], "spotify_user_test")

    def test_disconnect_spotify(self):
        self.client.login(username="testuser", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY
        )
        token.set_access_token("token")
        token.save()

        self.assertEqual(PlatformToken.objects.filter(user=self.user, platform=PlatformToken.PLATFORM_SPOTIFY).count(), 1)
        post_response = self.client.post(reverse('integrations:spotify_disconnect'))
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(PlatformToken.objects.filter(user=self.user, platform=PlatformToken.PLATFORM_SPOTIFY).count(), 0)
