from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse
from apps.integrations.models import PlatformToken
from apps.importer.matcher import (
    clean_title,
    clean_artist,
    parse_youtube_title,
    compute_similarity,
    match_spotify_track_to_youtube,
    match_youtube_track_to_spotify,
    preview_playlist_match,
)

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


class MatcherCleaningAndParsingTests(TestCase):
    def test_clean_title(self):
        self.assertEqual(clean_title("Bohemian Rhapsody (Official Video)"), "Bohemian Rhapsody")
        self.assertEqual(clean_title("Starboy [Official Music Video]"), "Starboy")
        self.assertEqual(clean_title("One Dance (feat. Wizkid & Kyla)"), "One Dance")
        self.assertEqual(clean_title("Hotel California - 2013 Remaster"), "Hotel California -")
        self.assertEqual(clean_title("Despacito (Video Oficial) [4K]"), "Despacito")
        self.assertEqual(clean_title(""), "")

    def test_clean_artist(self):
        self.assertEqual(clean_artist("Queen - Topic"), "Queen")
        self.assertEqual(clean_artist("DuaLipaVEVO"), "DuaLipa")
        self.assertEqual(clean_artist("The Weeknd"), "The Weeknd")
        self.assertEqual(clean_artist(""), "")

    def test_parse_youtube_title(self):
        artist, title = parse_youtube_title("Queen - Bohemian Rhapsody (Official Video)")
        self.assertEqual(artist, "Queen")
        self.assertEqual(title, "Bohemian Rhapsody")

        artist, title = parse_youtube_title("Kavinsky: Nightcall")
        self.assertEqual(artist, "Kavinsky")
        self.assertEqual(title, "Nightcall")

        artist, title = parse_youtube_title("Midnight City", channel_title="M83 - Topic")
        self.assertEqual(artist, "M83")
        self.assertEqual(title, "Midnight City")

    def test_compute_similarity(self):
        self.assertAlmostEqual(compute_similarity("Queen Bohemian Rhapsody", "queen bohemian rhapsody"), 1.0)
        self.assertGreater(compute_similarity("Queen Bohemian Rhapsody", "Queen - Bohemian Rhapsody (Audio)"), 0.7)
        self.assertEqual(compute_similarity("", "Test"), 0.0)
        self.assertEqual(compute_similarity("Test", ""), 0.0)


class MatcherAlgorithmTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="matcher_user", password="password123")

    @patch('apps.importer.matcher.get_youtube_client')
    def test_match_spotify_track_to_youtube_isrc_success(self, mock_get_yt):
        mock_yt = MagicMock()
        mock_get_yt.return_value = mock_yt
        mock_yt.search().list().execute.return_value = {
            'items': [
                {
                    'id': {'videoId': 'vid_isrc_123'},
                    'snippet': {
                        'title': 'Queen - Bohemian Rhapsody (Official Video)',
                        'channelTitle': 'Queen Official',
                    }
                }
            ]
        }

        track = {
            'title': 'Bohemian Rhapsody',
            'artist': 'Queen',
            'isrc': 'GBUM71029604',
        }

        matched = match_spotify_track_to_youtube(self.user, track)
        self.assertIsNotNone(matched)
        self.assertEqual(matched['id'], 'vid_isrc_123')
        self.assertEqual(matched['match_type'], 'isrc')
        self.assertGreaterEqual(matched['score'], 0.95)

    @patch('apps.importer.matcher.get_youtube_client')
    def test_match_spotify_track_to_youtube_fuzzy_fallback(self, mock_get_yt):
        mock_yt = MagicMock()
        mock_get_yt.return_value = mock_yt
        mock_yt.search().list().execute.side_effect = [
            {'items': []},
            {
                'items': [
                    {
                        'id': {'videoId': 'vid_fuzzy_456'},
                        'snippet': {
                            'title': 'The Weeknd - Blinding Lights (Audio)',
                            'channelTitle': 'TheWeekndVEVO',
                        }
                    }
                ]
            }
        ]

        track = {
            'title': 'Blinding Lights',
            'artist': 'The Weeknd',
            'isrc': 'USUM71900764',
        }

        matched = match_spotify_track_to_youtube(self.user, track)
        self.assertIsNotNone(matched)
        self.assertEqual(matched['id'], 'vid_fuzzy_456')
        self.assertEqual(matched['match_type'], 'fuzzy')

    @patch('apps.importer.matcher.get_youtube_client')
    def test_match_spotify_track_to_youtube_penalizes_karaoke_and_covers(self, mock_get_yt):
        mock_yt = MagicMock()
        mock_get_yt.return_value = mock_yt
        mock_yt.search().list().execute.return_value = {
            'items': [
                {
                    'id': {'videoId': 'vid_karaoke'},
                    'snippet': {
                        'title': 'The Weeknd - Blinding Lights Karaoke Instrumental',
                        'channelTitle': 'Karaoke Hits',
                    }
                }
            ]
        }

        track = {
            'title': 'Blinding Lights',
            'artist': 'The Weeknd',
            'isrc': '',
        }

        matched = match_spotify_track_to_youtube(self.user, track)
        self.assertIsNone(matched)

    @patch('apps.importer.matcher.get_spotify_client')
    def test_match_youtube_track_to_spotify_targeted_search(self, mock_get_sp):
        mock_sp = MagicMock()
        mock_get_sp.return_value = mock_sp
        mock_sp.search.return_value = {
            'tracks': {
                'items': [
                    {
                        'id': 'sp_trk_1',
                        'uri': 'spotify:track:sp_trk_1',
                        'name': 'Midnight City',
                        'artists': [{'name': 'M83'}],
                        'external_ids': {'isrc': 'FR6V81100078'},
                    }
                ]
            }
        }

        track = {
            'title': 'M83 - Midnight City (Official Video)',
            'artist': 'M83',
        }

        matched = match_youtube_track_to_spotify(self.user, track)
        self.assertIsNotNone(matched)
        self.assertEqual(matched['id'], 'sp_trk_1')
        self.assertEqual(matched['title'], 'Midnight City')
        self.assertEqual(matched['artist'], 'M83')
        self.assertEqual(matched['isrc'], 'FR6V81100078')

    @patch('apps.importer.matcher.get_spotify_client')
    def test_match_youtube_track_to_spotify_broad_search_fallback(self, mock_get_sp):
        mock_sp = MagicMock()
        mock_get_sp.return_value = mock_sp
        mock_sp.search.side_effect = [
            {'tracks': {'items': []}},
            {
                'tracks': {
                    'items': [
                        {
                            'id': 'sp_trk_broad',
                            'uri': 'spotify:track:sp_trk_broad',
                            'name': 'Nightcall',
                            'artists': [{'name': 'Kavinsky'}],
                            'external_ids': {'isrc': 'FR6V81000001'},
                        }
                    ]
                }
            }
        ]

        track = {
            'title': 'Nightcall',
            'artist': 'Kavinsky',
        }

        matched = match_youtube_track_to_spotify(self.user, track)
        self.assertIsNotNone(matched)
        self.assertEqual(matched['id'], 'sp_trk_broad')

    @patch('apps.importer.matcher.get_spotify_client')
    def test_match_youtube_track_to_spotify_no_match(self, mock_get_sp):
        mock_sp = MagicMock()
        mock_get_sp.return_value = mock_sp
        mock_sp.search.return_value = {'tracks': {'items': []}}

        track = {
            'title': 'Obscure Indescribable Nonexistent Song 999999',
            'artist': 'Nobody',
        }

        matched = match_youtube_track_to_spotify(self.user, track)
        self.assertIsNone(matched)


class PreviewPlaylistMatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="prev_user", password="password123")

    @patch('apps.importer.matcher.match_spotify_track_to_youtube')
    @patch('apps.importer.matcher.get_spotify_playlist_tracks')
    def test_preview_playlist_match_spotify_to_youtube(self, mock_get_tracks, mock_match):
        mock_get_tracks.return_value = [
            {'id': '1', 'title': 'Song A', 'artist': 'Artist A', 'isrc': 'ISRC1'},
            {'id': '2', 'title': 'Song B', 'artist': 'Artist B', 'isrc': 'ISRC2'},
        ]
        mock_match.side_effect = [
            {'id': 'yt_1', 'title': 'Song A', 'artist': 'Artist A', 'score': 0.9, 'match_type': 'fuzzy'},
            None,
        ]

        result = preview_playlist_match(self.user, 'spotify', 'youtube', 'pl_123', limit=10)
        self.assertEqual(result['source_platform'], 'spotify')
        self.assertEqual(result['target_platform'], 'youtube')
        self.assertEqual(result['total_tracks'], 2)
        self.assertEqual(result['matched_count'], 1)
        self.assertEqual(result['unmatched_count'], 1)
        self.assertEqual(result['match_rate'], 50.0)
        self.assertEqual(len(result['items']), 2)
        self.assertTrue(result['items'][0]['is_matched'])
        self.assertFalse(result['items'][1]['is_matched'])

    def test_preview_playlist_match_unsupported_platform(self):
        with self.assertRaises(ValueError):
            preview_playlist_match(self.user, 'tidal', 'youtube', 'pl_xyz')


class PreviewMatchModalViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="modal_user", password="password123")

    def test_preview_requires_login(self):
        url = reverse('importer:preview_match', kwargs={'source_platform': 'spotify', 'playlist_id': 'sp_1'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_preview_unsupported_platform(self):
        self.client.login(username="modal_user", password="password123")
        url = reverse('importer:preview_match', kwargs={'source_platform': 'soundcloud', 'playlist_id': 'sc_1'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Plataforma no soportada.")

    def test_preview_target_unconnected(self):
        self.client.login(username="modal_user", password="password123")
        url = reverse('importer:preview_match', kwargs={'source_platform': 'spotify', 'playlist_id': 'sp_1'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Debes conectar tu cuenta de YouTube Music")

    @patch('apps.importer.views.get_user_youtube_playlists')
    @patch('apps.importer.views.preview_playlist_match')
    def test_preview_happy_path(self, mock_preview, mock_get_target_playlists):
        self.client.login(username="modal_user", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        )
        token.set_access_token("valid_token")
        token.save()

        mock_preview.return_value = {
            'source_platform': 'spotify',
            'target_platform': 'youtube',
            'playlist_id': 'sp_1',
            'total_tracks': 10,
            'matched_count': 9,
            'unmatched_count': 1,
            'match_rate': 90.0,
            'items': [
                {
                    'source': {'title': 'Song 1', 'artist': 'Artist 1'},
                    'target': {'title': 'Song 1 (Video)', 'artist': 'Artist 1', 'score': 0.95, 'match_type': 'fuzzy'},
                    'is_matched': True,
                }
            ],
        }
        mock_get_target_playlists.return_value = [
            {'id': 'yt_dest_1', 'name': 'Dest Playlist'}
        ]

        url = reverse('importer:preview_match', kwargs={'source_platform': 'spotify', 'playlist_id': 'sp_1'})
        response = self.client.get(f"{url}?name=My+Awesome+Mix")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Previsualización de Coincidencias")
        self.assertContains(response, "My Awesome Mix")
        self.assertContains(response, "Tasa de acierto")
        self.assertContains(response, "Dest Playlist")
        self.assertContains(response, "Iniciar Transferencia")

    @patch('apps.importer.views.preview_playlist_match')
    def test_preview_exception_handling_sanitizes_message(self, mock_preview):
        self.client.login(username="modal_user", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        )
        token.set_access_token("valid_token")
        token.save()

        mock_preview.side_effect = Exception("Internal RateLimit 429 quota failure with private key")

        url = reverse('importer:preview_match', kwargs={'source_platform': 'spotify', 'playlist_id': 'sp_1'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo generar la vista previa de coincidencia")
        self.assertNotContains(response, "Internal RateLimit 429")
