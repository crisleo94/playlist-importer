import datetime
from datetime import timedelta
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.core.crypto import encrypt_string, decrypt_string, _get_fernet
from apps.integrations.models import PlatformToken
from apps.integrations.spotify import resolve_redirect_uri as resolve_spotify_uri
from apps.integrations.youtube import resolve_redirect_uri as resolve_youtube_uri

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

    @override_settings(FIELD_ENCRYPTION_KEY=None)
    def test_fails_fast_when_key_is_missing(self):
        with self.assertRaises(ImproperlyConfigured):
            _get_fernet()

    @override_settings(FIELD_ENCRYPTION_KEY="invalid-non-base64-key")
    def test_fails_fast_when_key_is_invalid(self):
        with self.assertRaises(ImproperlyConfigured):
            _get_fernet()


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

    @override_settings(DEBUG=True)
    def test_resolve_redirect_uri_in_debug_allowed_hosts(self):
        self.assertEqual(
            resolve_spotify_uri('http://localhost:8000/integrations/spotify/callback/', '127.0.0.1:8000'),
            'http://127.0.0.1:8000/integrations/spotify/callback/'
        )
        self.assertEqual(
            resolve_youtube_uri('http://localhost:8000/integrations/youtube/callback/', 'localhost:8000'),
            'http://localhost:8000/integrations/youtube/callback/'
        )
        # Host outside local dev whitelist is rejected even in DEBUG
        self.assertEqual(
            resolve_spotify_uri('http://localhost:8000/integrations/spotify/callback/', 'evil.com'),
            'http://localhost:8000/integrations/spotify/callback/'
        )

    @override_settings(DEBUG=False)
    def test_resolve_redirect_uri_in_production_is_static(self):
        # In production (DEBUG=False), never rewrite redirect_uri based on Host header
        self.assertEqual(
            resolve_spotify_uri('https://myapp.com/integrations/spotify/callback/', '127.0.0.1:8000'),
            'https://myapp.com/integrations/spotify/callback/'
        )
        self.assertEqual(
            resolve_youtube_uri('https://myapp.com/integrations/youtube/callback/', 'sub.myapp.com'),
            'https://myapp.com/integrations/youtube/callback/'
        )

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

    def test_disconnect_youtube(self):
        self.client.login(username="testuser", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        )
        token.set_access_token("token")
        token.save()

        self.assertEqual(PlatformToken.objects.filter(user=self.user, platform=PlatformToken.PLATFORM_YOUTUBE).count(), 1)
        post_response = self.client.post(reverse('integrations:youtube_disconnect'))
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(PlatformToken.objects.filter(user=self.user, platform=PlatformToken.PLATFORM_YOUTUBE).count(), 0)

    def test_spotify_callback_invalid_state(self):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['spotify_oauth_state'] = 'correct_state'
        session.save()

        response = self.client.get(reverse('integrations:spotify_callback'), {'state': 'wrong_state', 'code': 'valid_code'})
        self.assertEqual(response.status_code, 400)

    def test_spotify_callback_missing_code(self):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['spotify_oauth_state'] = 'valid_state'
        session.save()

        response = self.client.get(reverse('integrations:spotify_callback'), {'state': 'valid_state'})
        self.assertEqual(response.status_code, 400)

    @patch('apps.integrations.views.exchange_spotify_code')
    @patch('apps.integrations.views.get_spotify_client')
    def test_spotify_callback_success(self, mock_get_client, mock_exchange):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['spotify_oauth_state'] = 'valid_state'
        session.save()

        mock_exchange.return_value = {
            'access_token': 'test_sp_access',
            'refresh_token': 'test_sp_refresh',
            'expires_in': 3600,
        }
        mock_sp = MagicMock()
        mock_sp.current_user.return_value = {'display_name': 'SpotifyTester', 'id': 'spot_123'}
        mock_get_client.return_value = mock_sp

        response = self.client.get(reverse('integrations:spotify_callback'), {'state': 'valid_state', 'code': 'auth_code'})
        self.assertRedirects(response, reverse('importer:dashboard'))

        token = PlatformToken.objects.get(user=self.user, platform=PlatformToken.PLATFORM_SPOTIFY)
        self.assertEqual(token.get_access_token(), 'test_sp_access')
        self.assertEqual(token.get_refresh_token(), 'test_sp_refresh')
        self.assertEqual(token.platform_username, 'SpotifyTester')
        self.assertFalse(token.is_expired())

    @patch('apps.integrations.views.exchange_spotify_code')
    @patch('apps.integrations.views.get_spotify_client')
    def test_spotify_callback_noslash_route(self, mock_get_client, mock_exchange):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['spotify_oauth_state'] = 'valid_state'
        session.save()

        mock_exchange.return_value = {
            'access_token': 'test_sp_access_noslash',
            'refresh_token': 'test_sp_refresh_noslash',
            'expires_in': 3600,
        }
        mock_sp = MagicMock()
        mock_sp.current_user.return_value = {'display_name': 'SpotifyNoSlash', 'id': 'spot_noslash'}
        mock_get_client.return_value = mock_sp

        response = self.client.get(reverse('integrations:spotify_callback_noslash'), {'state': 'valid_state', 'code': 'auth_code'})
        self.assertRedirects(response, reverse('importer:dashboard'))

        token = PlatformToken.objects.get(user=self.user, platform=PlatformToken.PLATFORM_SPOTIFY)
        self.assertEqual(token.platform_username, 'SpotifyNoSlash')

    def test_youtube_connect_stores_pkce_verifier(self):
        self.client.login(username="testuser", password="password123")
        with patch('apps.integrations.views.get_youtube_auth_url', return_value=('https://accounts.google.com/auth', 'mock_verifier_xyz')):
            response = self.client.get(reverse('integrations:youtube_connect'))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self.client.session.get('youtube_code_verifier'), 'mock_verifier_xyz')

    def test_youtube_callback_invalid_state(self):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['youtube_oauth_state'] = 'correct_state'
        session.save()

        response = self.client.get(reverse('integrations:youtube_callback'), {'state': 'wrong_state', 'code': 'valid_code'})
        self.assertEqual(response.status_code, 400)

    def test_youtube_callback_missing_code(self):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['youtube_oauth_state'] = 'valid_state'
        session.save()

        response = self.client.get(reverse('integrations:youtube_callback'), {'state': 'valid_state'})
        self.assertEqual(response.status_code, 400)

    @patch('apps.integrations.views.exchange_youtube_code')
    @patch('apps.integrations.views.get_youtube_client')
    def test_youtube_callback_success_with_naive_expiry_normalization(self, mock_get_client, mock_exchange):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['youtube_oauth_state'] = 'valid_state'
        session['youtube_code_verifier'] = 'saved_pkce_verifier'
        session.save()

        # Simulate google-auth returning naive datetime in UTC
        naive_utc_expiry = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        mock_exchange.return_value = {
            'token': 'test_yt_access',
            'refresh_token': 'test_yt_refresh',
            'expiry': naive_utc_expiry,
        }
        mock_yt = MagicMock()
        mock_channels = MagicMock()
        mock_channels.list.return_value.execute.return_value = {
            'items': [{'id': 'yt_chan_123', 'snippet': {'title': 'My Channel'}}]
        }
        mock_yt.channels.return_value = mock_channels
        mock_get_client.return_value = mock_yt

        response = self.client.get(reverse('integrations:youtube_callback'), {'state': 'valid_state', 'code': 'auth_code'})
        self.assertRedirects(response, reverse('importer:dashboard'))

        mock_exchange.assert_called_once()
        _, kwargs = mock_exchange.call_args
        self.assertEqual(kwargs.get('code_verifier'), 'saved_pkce_verifier')

        token = PlatformToken.objects.get(user=self.user, platform=PlatformToken.PLATFORM_YOUTUBE)
        self.assertEqual(token.get_access_token(), 'test_yt_access')
        self.assertEqual(token.get_refresh_token(), 'test_yt_refresh')
        self.assertEqual(token.platform_username, 'My Channel')

        # Must be timezone-aware and comparable in memory without TypeError
        self.assertFalse(timezone.is_naive(token.expires_at))
        self.assertFalse(token.is_expired())

    @patch('apps.integrations.views.exchange_youtube_code')
    @patch('apps.integrations.views.get_youtube_client')
    def test_youtube_callback_noslash_route(self, mock_get_client, mock_exchange):
        self.client.login(username="testuser", password="password123")
        session = self.client.session
        session['youtube_oauth_state'] = 'valid_state'
        session.save()

        mock_exchange.return_value = {
            'token': 'test_yt_access_noslash',
            'refresh_token': 'test_yt_refresh_noslash',
            'expiry': timezone.now() + timedelta(hours=1),
        }
        mock_yt = MagicMock()
        mock_channels = MagicMock()
        mock_channels.list.return_value.execute.return_value = {
            'items': [{'id': 'yt_noslash_123', 'snippet': {'title': 'Channel NoSlash'}}]
        }
        mock_yt.channels.return_value = mock_channels
        mock_get_client.return_value = mock_yt

        response = self.client.get(reverse('integrations:youtube_callback_noslash'), {'state': 'valid_state', 'code': 'auth_code'})
        self.assertRedirects(response, reverse('importer:dashboard'))

        token = PlatformToken.objects.get(user=self.user, platform=PlatformToken.PLATFORM_YOUTUBE)
        self.assertEqual(token.platform_username, 'Channel NoSlash')
