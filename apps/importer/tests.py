from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse
from apps.integrations.models import PlatformToken

User = get_user_model()


class ImporterDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(username="testuser", password="password123")

    def tearDown(self):
        cache.clear()

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('importer:dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_view_authenticated(self):
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse('importer:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cuentas Vinculadas")
        self.assertContains(response, "Playlists de Spotify")
        self.assertContains(response, "Playlists de YouTube Music")

    def test_spotify_playlists_requires_login(self):
        response = self.client.get(reverse('importer:spotify_playlists'))
        self.assertEqual(response.status_code, 302)

    def test_spotify_playlists_unconnected(self):
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse('importer:spotify_playlists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Spotify no conectado")

    @patch('apps.importer.views.get_user_spotify_playlists')
    def test_spotify_playlists_connected_and_search_cached(self, mock_get_playlists):
        self.client.login(username="testuser", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY,
            platform_username="spot_user"
        )
        token.set_access_token("token")
        token.save()

        mock_get_playlists.return_value = [
            {
                'id': 'sp_1',
                'name': 'Rock Classics',
                'description': 'Best of Rock',
                'total_tracks': 25,
                'image_url': 'http://example.com/rock.jpg',
                'owner_name': 'spot_user',
                'external_url': 'https://open.spotify.com/playlist/sp_1',
            },
            {
                'id': 'sp_2',
                'name': 'Lo-Fi Chill',
                'description': 'Study beats',
                'total_tracks': 40,
                'image_url': None,
                'owner_name': 'spot_user',
                'external_url': 'https://open.spotify.com/playlist/sp_2',
            }
        ]

        # First request populates cache
        response = self.client.get(reverse('importer:spotify_playlists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rock Classics")
        self.assertContains(response, "Lo-Fi Chill")
        self.assertEqual(mock_get_playlists.call_count, 1)

        # Subsequent keystroke search uses cached playlists without calling external API again
        response_q = self.client.get(reverse('importer:spotify_playlists'), {'q': 'Rock'})
        self.assertEqual(response_q.status_code, 200)
        self.assertContains(response_q, "Rock Classics")
        self.assertNotContains(response_q, "Lo-Fi Chill")
        self.assertEqual(mock_get_playlists.call_count, 1)

    @patch('apps.importer.views.get_user_spotify_playlists')
    def test_spotify_playlists_exception_handling_sanitizes_message(self, mock_get_playlists):
        self.client.login(username="testuser", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY
        )
        token.set_access_token("token")
        token.save()

        mock_get_playlists.side_effect = Exception("Internal HTTP 429 quota_exceeded_secret_uri")
        response = self.client.get(reverse('importer:spotify_playlists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo cargar tu biblioteca de Spotify")
        self.assertNotContains(response, "quota_exceeded_secret_uri")

    def test_youtube_playlists_requires_login(self):
        response = self.client.get(reverse('importer:youtube_playlists'))
        self.assertEqual(response.status_code, 302)

    def test_youtube_playlists_unconnected(self):
        self.client.login(username="testuser", password="password123")
        response = self.client.get(reverse('importer:youtube_playlists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "YouTube Music no conectado")

    @patch('apps.importer.views.get_user_youtube_playlists')
    def test_youtube_playlists_connected(self, mock_get_playlists):
        self.client.login(username="testuser", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE,
            platform_username="yt_chan"
        )
        token.set_access_token("token")
        token.save()

        mock_get_playlists.return_value = [
            {
                'id': 'yt_1',
                'name': 'Synthwave Nights',
                'description': 'Retro vibes',
                'total_tracks': 15,
                'image_url': 'http://example.com/synth.jpg',
                'privacy_status': 'public',
                'channel_title': 'yt_chan',
                'external_url': 'https://music.youtube.com/playlist?list=yt_1',
            }
        ]

        response = self.client.get(reverse('importer:youtube_playlists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Synthwave Nights")
        self.assertContains(response, "15 temas")
        self.assertContains(response, "public")

    @patch('apps.importer.views.get_user_youtube_playlists')
    def test_youtube_playlists_exception_handling_sanitizes_message(self, mock_get_playlists):
        self.client.login(username="testuser", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        )
        token.set_access_token("token")
        token.save()

        mock_get_playlists.side_effect = Exception("Google Cloud Quota Exceeded 403 Forbidden")
        response = self.client.get(reverse('importer:youtube_playlists'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo cargar tu biblioteca de YouTube Music")
        self.assertNotContains(response, "Google Cloud Quota Exceeded")

    def test_playlist_tracks_modal_requires_login(self):
        url = reverse('importer:playlist_tracks_modal', kwargs={'platform': 'spotify', 'playlist_id': 'sp_1'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_playlist_tracks_modal_unsupported_platform(self):
        self.client.login(username="testuser", password="password123")
        url = reverse('importer:playlist_tracks_modal', kwargs={'platform': 'unsupported_foo', 'playlist_id': 'xyz'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plataforma no soportada.")

    @patch('apps.importer.views.get_spotify_playlist_tracks')
    def test_playlist_tracks_modal_spotify(self, mock_get_tracks):
        self.client.login(username="testuser", password="password123")
        mock_get_tracks.return_value = [
            {
                'id': 'trk_1',
                'title': 'Bohemian Rhapsody',
                'artist': 'Queen',
                'album': 'A Night at the Opera',
                'duration_ms': 354000,
                'isrc': 'GBUM71029604',
                'image_url': 'http://example.com/queen.jpg',
            }
        ]

        url = reverse('importer:playlist_tracks_modal', kwargs={'platform': 'spotify', 'playlist_id': 'sp_1'})
        response = self.client.get(f"{url}?name=Queen+Best&total=150")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bohemian Rhapsody")
        self.assertContains(response, "Queen")
        self.assertContains(response, "GBUM71029604")
        self.assertContains(response, "Mostrando 1 de 150 temas")

    @patch('apps.importer.views.get_youtube_playlist_tracks')
    def test_playlist_tracks_modal_youtube(self, mock_get_tracks):
        self.client.login(username="testuser", password="password123")
        mock_get_tracks.return_value = [
            {
                'id': 'vid_1',
                'title': 'Nightcall - Kavinsky',
                'artist': 'Kavinsky',
                'image_url': None,
            }
        ]

        url = reverse('importer:playlist_tracks_modal', kwargs={'platform': 'youtube', 'playlist_id': 'yt_1'})
        response = self.client.get(f"{url}?name=Drive+OST")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nightcall - Kavinsky")
        self.assertContains(response, "Drive OST")

    @patch('apps.importer.views.get_spotify_playlist_tracks')
    def test_playlist_tracks_modal_exception_handling_sanitizes_message(self, mock_get_tracks):
        self.client.login(username="testuser", password="password123")
        mock_get_tracks.side_effect = Exception("Database connection failure in backend")

        url = reverse('importer:playlist_tracks_modal', kwargs={'platform': 'spotify', 'playlist_id': 'sp_err'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudieron obtener las canciones de la lista seleccionada.")
        self.assertNotContains(response, "Database connection failure in backend")
