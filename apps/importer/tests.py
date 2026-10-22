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
        self.assertContains(response, "15 pistas")
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
        self.assertContains(response, "Mostrando 1 de 150 pistas")

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
        self.assertEqual(clean_title("Hotel California - 2013 Remaster"), "Hotel California")
        self.assertEqual(clean_title("Hotel California (2013 Remaster)"), "Hotel California")
        self.assertEqual(clean_title("Hotel California - 2013 Remastered Version"), "Hotel California")
        self.assertEqual(clean_title("Hotel California [2013 Remastered Version]"), "Hotel California")
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
        cache.clear()
        self.user = User.objects.create_user(username="matcher_user", password="password123")

    def tearDown(self):
        cache.clear()

    @patch('apps.importer.matcher.get_youtube_client')
    def test_match_spotify_track_to_youtube_isrc_boost_with_similarity(self, mock_get_yt):
        mock_yt = MagicMock()
        mock_get_yt.return_value = mock_yt
        mock_yt.search().list().execute.return_value = {
            'items': [
                {
                    'id': {'videoId': 'vid_isrc_123'},
                    'snippet': {
                        'title': 'Queen - Bohemian Rhapsody (Official Video)',
                        'description': 'Provided to YouTube by UMG. ISRC: GBUM71029604',
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
        self.assertGreaterEqual(matched['score'], 0.85)

    @patch('apps.importer.matcher.get_youtube_client')
    def test_match_spotify_track_to_youtube_fuzzy_match_single_query_and_cache(self, mock_get_yt):
        mock_yt = MagicMock()
        mock_get_yt.return_value = mock_yt
        mock_list = mock_yt.search().list
        mock_list.reset_mock()
        mock_list.return_value.execute.return_value = {
            'items': [
                {
                    'id': {'videoId': 'vid_fuzzy_456'},
                    'snippet': {
                        'title': 'The Weeknd - Blinding Lights (Audio)',
                        'description': 'Audio official',
                        'channelTitle': 'TheWeekndVEVO',
                    }
                }
            ]
        }

        track = {
            'id': 'trk_weeknd_1',
            'title': 'Blinding Lights',
            'artist': 'The Weeknd',
            'isrc': 'USUM71900764',
        }

        # First call calls YouTube API
        matched = match_spotify_track_to_youtube(self.user, track)
        self.assertIsNotNone(matched)
        self.assertEqual(matched['id'], 'vid_fuzzy_456')
        self.assertEqual(matched['match_type'], 'fuzzy')
        self.assertEqual(mock_list.call_count, 1)

        # Second call uses cache, no redundant search.list API call (saves 100 quota units)
        cached_matched = match_spotify_track_to_youtube(self.user, track)
        self.assertIsNotNone(cached_matched)
        self.assertEqual(cached_matched['id'], 'vid_fuzzy_456')
        self.assertEqual(mock_list.call_count, 1)

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

    @patch('apps.importer.matcher.get_youtube_client')
    @patch('apps.importer.matcher.match_spotify_track_to_youtube')
    @patch('apps.importer.matcher.get_spotify_playlist_tracks')
    def test_preview_playlist_match_spotify_to_youtube(self, mock_get_tracks, mock_match, mock_get_yt):
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


from apps.importer.models import ImportJob, ImportJobItem
from apps.importer.tasks import run_playlist_import
from apps.integrations.spotify import create_spotify_playlist, add_tracks_to_spotify_playlist
from apps.integrations.youtube import create_youtube_playlist, add_video_to_youtube_playlist


class ImportModelsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="model_user", password="password123")

    def test_import_job_properties(self):
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_1',
            source_playlist_name='Rock Classics',
            total_tracks=10,
            processed_tracks=5,
            status=ImportJob.STATUS_PROCESSING
        )
        self.assertEqual(job.progress_percentage, 50)
        self.assertFalse(job.is_finished)

        job.status = ImportJob.STATUS_COMPLETED
        self.assertTrue(job.is_finished)

        # Division by zero safety
        job.total_tracks = 0
        self.assertEqual(job.progress_percentage, 0)

    def test_import_job_item_creation(self):
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_1',
            source_playlist_name='Rock Classics',
        )
        item = ImportJobItem.objects.create(
            job=job,
            source_title='Bohemian Rhapsody',
            source_artist='Queen',
            target_title='Bohemian Rhapsody (Video)',
            status=ImportJobItem.STATUS_ADDED
        )
        self.assertIn("Bohemian Rhapsody", str(item))
        self.assertEqual(item.status, ImportJobItem.STATUS_ADDED)


class IntegrationsWriteHelpersTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="write_user", password="password123")

    @patch('apps.integrations.spotify.get_spotify_client')
    def test_create_spotify_playlist(self, mock_get_sp):
        mock_sp = MagicMock()
        mock_get_sp.return_value = mock_sp
        mock_sp.me.return_value = {'id': 'spot_uid'}
        mock_sp.user_playlist_create.return_value = {
            'id': 'new_sp_pl',
            'name': 'My New Spotify List',
            'external_urls': {'spotify': 'https://open.spotify.com/playlist/new_sp_pl'}
        }

        res = create_spotify_playlist(self.user, 'My New Spotify List')
        self.assertEqual(res['id'], 'new_sp_pl')
        self.assertEqual(res['name'], 'My New Spotify List')
        mock_sp.user_playlist_create.assert_called_once()

    @patch('apps.integrations.spotify.get_spotify_client')
    def test_add_tracks_to_spotify_playlist_chunks_calls(self, mock_get_sp):
        mock_sp = MagicMock()
        mock_get_sp.return_value = mock_sp

        # 150 tracks should chunk into 2 calls (100 + 50)
        uris = [f"spotify:track:{i}" for i in range(150)]
        add_tracks_to_spotify_playlist(self.user, 'pl_123', uris)
        self.assertEqual(mock_sp.playlist_add_items.call_count, 2)

    @patch('apps.integrations.youtube.get_youtube_client')
    def test_create_youtube_playlist(self, mock_get_yt):
        mock_yt = MagicMock()
        mock_get_yt.return_value = mock_yt
        mock_yt.playlists().insert().execute.return_value = {
            'id': 'yt_new_pl',
            'snippet': {'title': 'My New YouTube List'}
        }

        res = create_youtube_playlist(self.user, 'My New YouTube List')
        self.assertEqual(res['id'], 'yt_new_pl')
        self.assertEqual(res['name'], 'My New YouTube List')

    @patch('apps.integrations.youtube.get_youtube_client')
    def test_add_video_to_youtube_playlist(self, mock_get_yt):
        mock_yt = MagicMock()
        mock_get_yt.return_value = mock_yt
        mock_yt.playlistItems().insert().execute.return_value = {'id': 'item_123'}

        res = add_video_to_youtube_playlist(self.user, 'yt_pl', 'video_abc')
        self.assertEqual(res['id'], 'item_123')


class CeleryImportTaskTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="task_user", password="password123")

    def tearDown(self):
        cache.clear()

    def test_run_playlist_import_nonexistent_job(self):
        # Should not raise exception
        run_playlist_import(999999)

    def test_run_playlist_import_already_finished(self):
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_1',
            source_playlist_name='List',
            status=ImportJob.STATUS_COMPLETED
        )
        run_playlist_import(job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, ImportJob.STATUS_COMPLETED)

    @patch('apps.importer.tasks.add_video_to_youtube_playlist')
    @patch('apps.importer.tasks.create_youtube_playlist')
    @patch('apps.importer.tasks.match_spotify_track_to_youtube')
    @patch('apps.importer.tasks.get_spotify_playlist_tracks')
    @patch('apps.importer.tasks.get_youtube_client')
    def test_run_playlist_import_spotify_to_youtube_happy_path(
        self, mock_yt_client, mock_get_tracks, mock_match, mock_create_yt, mock_add_video
    ):
        mock_get_tracks.return_value = [
            {'id': 't1', 'title': 'Song 1', 'artist': 'Artist 1', 'isrc': 'ISRC1'},
            {'id': 't2', 'title': 'Song 2', 'artist': 'Artist 2', 'isrc': 'ISRC2'},
        ]
        mock_create_yt.return_value = {'id': 'yt_created_1', 'name': 'Rock Mix (Imported)'}
        mock_match.side_effect = [
            {'id': 'vid_1', 'title': 'Song 1', 'artist': 'Artist 1', 'score': 0.95, 'match_type': 'isrc'},
            {'id': 'vid_2', 'title': 'Song 2', 'artist': 'Artist 2', 'score': 0.88, 'match_type': 'fuzzy'},
        ]

        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_src',
            source_playlist_name='Rock Mix',
            destination_mode='new',
            status=ImportJob.STATUS_PENDING
        )

        run_playlist_import(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ImportJob.STATUS_COMPLETED)
        self.assertEqual(job.total_tracks, 2)
        self.assertEqual(job.successful_tracks, 2)
        self.assertEqual(job.failed_tracks, 0)
        self.assertEqual(job.target_playlist_id, 'yt_created_1')
        self.assertEqual(mock_add_video.call_count, 2)
        self.assertEqual(job.items.count(), 2)

    @patch('apps.importer.tasks.add_tracks_to_spotify_playlist')
    @patch('apps.importer.tasks.match_youtube_track_to_spotify')
    @patch('apps.importer.tasks.get_youtube_playlist_tracks')
    @patch('apps.importer.tasks.get_spotify_client')
    def test_run_playlist_import_partial_matching(
        self, mock_sp_client, mock_get_tracks, mock_match, mock_add_tracks
    ):
        mock_get_tracks.return_value = [
            {'id': 'v1', 'title': 'Known Song', 'artist': 'Band'},
            {'id': 'v2', 'title': 'Obscure Track Nobody Knows', 'artist': 'Unknown'},
        ]
        # First track matches, second track does not
        mock_match.side_effect = [
            {'id': 'sp_trk_1', 'uri': 'spotify:track:sp_trk_1', 'title': 'Known Song', 'artist': 'Band', 'score': 0.9},
            None,
        ]

        job = ImportJob.objects.create(
            user=self.user,
            source_platform='youtube',
            target_platform='spotify',
            source_playlist_id='yt_src',
            source_playlist_name='Drive Vibes',
            destination_mode='existing',
            target_playlist_id='sp_existing_id',
            status=ImportJob.STATUS_PENDING
        )

        run_playlist_import(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ImportJob.STATUS_PARTIAL)
        self.assertEqual(job.total_tracks, 2)
        self.assertEqual(job.successful_tracks, 1)
        self.assertEqual(job.failed_tracks, 1)
        self.assertEqual(job.items.filter(status=ImportJobItem.STATUS_NOT_FOUND).count(), 1)


    @patch('apps.importer.tasks.get_spotify_playlist_tracks')
    def test_run_playlist_import_soft_time_limit_exceeded(self, mock_get_tracks):
        from celery.exceptions import SoftTimeLimitExceeded
        mock_get_tracks.side_effect = SoftTimeLimitExceeded()

        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_timeout',
            source_playlist_name='Timeout List',
            status=ImportJob.STATUS_PENDING
        )

        run_playlist_import(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ImportJob.STATUS_FAILED)
        self.assertIn("límite permitido", job.error_message)

class ImportViewsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(username="view_user", password="password123")

    def tearDown(self):
        cache.clear()

    def test_start_import_requires_login(self):
        url = reverse('importer:start_import')
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, 302)

    def test_start_import_requires_post(self):
        self.client.login(username="view_user", password="password123")
        url = reverse('importer:start_import')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_start_import_invalid_platform(self):
        self.client.login(username="view_user", password="password123")
        url = reverse('importer:start_import')
        response = self.client.post(url, {
            'source_platform': 'invalid_app',
            'source_playlist_id': '123'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Datos de importación inválidos")

    def test_start_import_target_not_connected(self):
        self.client.login(username="view_user", password="password123")
        url = reverse('importer:start_import')
        response = self.client.post(url, {
            'source_platform': 'spotify',
            'source_playlist_id': 'sp_123',
            'source_playlist_name': 'My List',
            'dest_mode': 'new',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Debes conectar tu cuenta de YouTube Music")

    @patch('apps.importer.views.run_playlist_import.delay')
    def test_start_import_happy_path_enqueues_celery(self, mock_delay):
        self.client.login(username="view_user", password="password123")
        # Target (youtube) token exists
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        )
        token.set_access_token("valid_token")
        token.save()

        mock_delay.return_value = MagicMock(id='celery_task_uuid_123')

        url = reverse('importer:start_import')
        response = self.client.post(url, {
            'source_platform': 'spotify',
            'source_playlist_id': 'sp_123',
            'source_playlist_name': 'My Rock List',
            'dest_mode': 'new',
            'new_playlist_name': 'My Rock List (YT)',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Progreso de Importación")
        self.assertContains(response, "My Rock List")
        self.assertContains(response, 'hx-trigger="every 1.5s"')

        job = ImportJob.objects.filter(user=self.user).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.celery_task_id, 'celery_task_uuid_123')
        mock_delay.assert_called_once_with(job.id)

    def test_import_progress_view_in_progress(self):
        self.client.login(username="view_user", password="password123")
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_1',
            source_playlist_name='In Flight Playlist',
            total_tracks=20,
            processed_tracks=10,
            successful_tracks=9,
            failed_tracks=1,
            current_track_name='Currently Processing Song',
            status=ImportJob.STATUS_PROCESSING
        )

        url = reverse('importer:import_progress', kwargs={'job_id': job.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Transfiriendo canciones...")
        self.assertContains(response, "50%")
        self.assertContains(response, "Currently Processing Song")
        self.assertContains(response, 'hx-trigger="every 1.5s"')

    def test_import_progress_view_finished_completed(self):
        self.client.login(username="view_user", password="password123")
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_1',
            source_playlist_name='Finished Playlist',
            total_tracks=15,
            processed_tracks=15,
            successful_tracks=15,
            failed_tracks=0,
            status=ImportJob.STATUS_COMPLETED
        )

        url = reverse('importer:import_progress', kwargs={'job_id': job.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "¡Importación Completada con Éxito!")
        self.assertNotContains(response, 'hx-trigger="every 1.5s"')
        self.assertContains(response, "Aceptar y Actualizar")

    def test_import_progress_view_finished_partial_shows_unmatched_items(self):
        self.client.login(username="view_user", password="password123")
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='youtube',
            target_platform='spotify',
            source_playlist_id='yt_1',
            source_playlist_name='Partial Playlist',
            total_tracks=10,
            processed_tracks=10,
            successful_tracks=8,
            failed_tracks=2,
            status=ImportJob.STATUS_PARTIAL
        )
        ImportJobItem.objects.create(
            job=job,
            source_title='Unmatched Rare Demo',
            source_artist='Underground Band',
            status=ImportJobItem.STATUS_NOT_FOUND
        )

        url = reverse('importer:import_progress', kwargs={'job_id': job.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Importación Parcialmente Completada")
        self.assertContains(response, "Unmatched Rare Demo")
        self.assertContains(response, "Underground Band")
        self.assertContains(response, "Sin coincidencia")


    @patch('apps.importer.views.run_playlist_import.delay')
    def test_start_import_double_submit_prevents_duplicate_job_and_task(self, mock_delay):
        self.client.login(username="view_user", password="password123")
        token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE
        )
        token.set_access_token("valid_token")
        token.save()

        mock_delay.return_value = MagicMock(id='task_uuid')
        url = reverse('importer:start_import')
        payload = {
            'source_platform': 'spotify',
            'source_playlist_id': 'sp_dup_1',
            'source_playlist_name': 'Dup List',
            'dest_mode': 'new',
            'new_playlist_name': 'Dup List (YT)',
        }

        # First submit
        r1 = self.client.post(url, payload)
        self.assertEqual(r1.status_code, 200)

        # Immediate double submit (double click / network retry)
        r2 = self.client.post(url, payload)
        self.assertEqual(r2.status_code, 200)

        # Only 1 job created and 1 Celery task enqueued
        self.assertEqual(ImportJob.objects.filter(user=self.user, source_playlist_id='sp_dup_1').count(), 1)
        self.assertEqual(mock_delay.call_count, 1)

    def test_import_progress_view_cross_user_forbidden(self):
        attacker = User.objects.create_user(username="attacker", password="password123")
        self.client.login(username="attacker", password="password123")

        # Job belongs to self.user, not attacker
        victim_job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_priv',
            source_playlist_name='Private User List',
            status=ImportJob.STATUS_PROCESSING
        )

        url = reverse('importer:import_progress', kwargs={'job_id': victim_job.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_import_progress_view_finished_shows_failed_insertion(self):
        self.client.login(username="view_user", password="password123")
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='spotify',
            target_platform='youtube',
            source_playlist_id='sp_1',
            source_playlist_name='Job with Insert Failure',
            total_tracks=1,
            processed_tracks=1,
            successful_tracks=0,
            failed_tracks=1,
            status=ImportJob.STATUS_FAILED
        )
        ImportJobItem.objects.create(
            job=job,
            source_title='Song Quota Blocked',
            source_artist='Artist',
            status=ImportJobItem.STATUS_FAILED,
            error_message='YouTube API quota exceeded'
        )

        url = reverse('importer:import_progress', kwargs={'job_id': job.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fallo de inserción")


class ImportByUrlTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(username="url_user", password="password123")
        self.client.login(username="url_user", password="password123")

    def tearDown(self):
        cache.clear()

    def test_import_by_url_modal_view_renders(self):
        url = reverse('importer:import_by_url_modal')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cargar Playlist por Enlace o ID")

    def test_import_by_url_invalid_input(self):
        url = reverse('importer:import_by_url')
        response = self.client.post(url, {'playlist_url': 'invalid_string'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No pudimos reconocer el enlace o ID")

    def test_import_by_url_missing_source_token(self):
        url = reverse('importer:import_by_url')
        # Spotify valid ID without Spotify token connected
        response = self.client.post(url, {'playlist_url': '37i9dQZF1DXcBWIGoYBM5M'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Debes conectar tu cuenta de Spotify")

    def test_import_by_url_missing_target_token(self):
        # Connect source token (Spotify) but no target token (YouTube)
        PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY,
            platform_username="spotify_tester"
        )
        url = reverse('importer:import_by_url')
        response = self.client.post(url, {'playlist_url': 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=123'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Debes conectar tu cuenta de YouTube Music")

    @patch('apps.importer.views.get_spotify_playlist_details')
    @patch('apps.importer.views.preview_playlist_match')
    @patch('apps.importer.views.get_user_youtube_playlists')
    def test_import_by_url_spotify_success(self, mock_get_yt_pl, mock_preview, mock_details):
        PlatformToken.objects.create(user=self.user, platform=PlatformToken.PLATFORM_SPOTIFY)
        PlatformToken.objects.create(user=self.user, platform=PlatformToken.PLATFORM_YOUTUBE)

        mock_details.return_value = {'name': 'Shared Chill List'}
        mock_get_yt_pl.return_value = [{'id': 'yt_1', 'name': 'My YT Dest'}]
        mock_preview.return_value = {
            'source_platform': 'spotify',
            'target_platform': 'youtube',
            'playlist_id': '37i9dQZF1DXcBWIGoYBM5M',
            'total_tracks': 1,
            'matched_count': 1,
            'unmatched_count': 0,
            'match_rate': 100.0,
            'items': [
                {
                    'source': {'title': 'Track A', 'artist': 'Artist A'},
                    'target': {'title': 'Track A YT', 'score': 0.95},
                    'is_matched': True,
                }
            ],
        }

        url = reverse('importer:import_by_url')
        response = self.client.post(url, {'playlist_url': 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Shared Chill List")
        self.assertContains(response, "Track A")
        self.assertContains(response, "Iniciar Transferencia")

    @patch('apps.importer.views.get_youtube_playlist_details')
    @patch('apps.importer.views.preview_playlist_match')
    @patch('apps.importer.views.get_user_spotify_playlists')
    def test_import_by_url_youtube_success(self, mock_get_sp_pl, mock_preview, mock_details):
        PlatformToken.objects.create(user=self.user, platform=PlatformToken.PLATFORM_SPOTIFY)
        PlatformToken.objects.create(user=self.user, platform=PlatformToken.PLATFORM_YOUTUBE)

        mock_details.return_value = {'name': 'Collab YT Party'}
        mock_get_sp_pl.return_value = [{'id': 'sp_1', 'name': 'My SP Dest'}]
        mock_preview.return_value = {
            'source_platform': 'youtube',
            'target_platform': 'spotify',
            'playlist_id': 'PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj',
            'total_tracks': 1,
            'matched_count': 1,
            'unmatched_count': 0,
            'match_rate': 100.0,
            'items': [
                {
                    'source': {'title': 'Video B', 'artist': 'Channel B'},
                    'target': {'title': 'Track B', 'score': 0.90},
                    'is_matched': True,
                }
            ],
        }

        url = reverse('importer:import_by_url')
        response = self.client.post(url, {'playlist_url': 'https://music.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj&si=tracker'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Collab YT Party")
        self.assertContains(response, "Video B")
        self.assertContains(response, "Iniciar Transferencia")


class QuotaAndRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="quota_user", password="password123")
        token_sp = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY,
            platform_username="spot_user"
        )
        token_sp.set_access_token("valid_sp_token")
        token_sp.save()

        token_yt = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE,
            platform_username="yt_user"
        )
        token_yt.set_access_token("valid_yt_token")
        token_yt.save()

    def tearDown(self):
        cache.clear()

    def test_is_quota_or_rate_limit_error_detection(self):
        from apps.importer.matcher import is_quota_or_rate_limit_error, QuotaOrRateLimitExceeded

        # 1. Custom QuotaOrRateLimitExceeded
        self.assertTrue(is_quota_or_rate_limit_error(QuotaOrRateLimitExceeded('spotify', '429 error')))

        # 2. SpotifyException structured attribute http_status=429
        mock_spotipy_exc = Exception("Rate limit reached")
        mock_spotipy_exc.http_status = 429
        self.assertTrue(is_quota_or_rate_limit_error(mock_spotipy_exc))

        # 3. Google HttpError structured attribute resp.status=403 with quota reason
        mock_resp = MagicMock(status=403)
        mock_google_exc = Exception("<HttpError 403: 'quotaExceeded'>")
        mock_google_exc.resp = mock_resp
        self.assertTrue(is_quota_or_rate_limit_error(mock_google_exc))

        # 4. Text fallback
        self.assertTrue(is_quota_or_rate_limit_error(Exception("user_rate_limit_exceeded")))
        self.assertTrue(is_quota_or_rate_limit_error(Exception("Error 429: Too Many Requests")))

        # 5. Normal exception should return False
        self.assertFalse(is_quota_or_rate_limit_error(ValueError("Invalid track name")))
        self.assertFalse(is_quota_or_rate_limit_error(KeyError("missing key")))

    @patch('apps.importer.matcher.get_spotify_client')
    def test_match_youtube_track_raises_quota_on_429(self, mock_sp_client):
        from apps.importer.matcher import match_youtube_track_to_spotify, QuotaOrRateLimitExceeded

        mock_sp = MagicMock()
        mock_exc = Exception("Spotify rate limit")
        mock_exc.http_status = 429
        mock_sp.search.side_effect = mock_exc
        mock_sp_client.return_value = mock_sp

        track = {'title': 'Song A', 'artist': 'Artist A'}
        with self.assertRaises(QuotaOrRateLimitExceeded):
            match_youtube_track_to_spotify(self.user, track, sp_client=mock_sp)

    @patch('apps.importer.matcher.get_youtube_client')
    def test_match_spotify_track_raises_quota_on_quota_exceeded(self, mock_yt_client):
        from apps.importer.matcher import match_spotify_track_to_youtube, QuotaOrRateLimitExceeded

        mock_yt = MagicMock()
        mock_exc = Exception("The request cannot be completed because quotaExceeded has occurred.")
        mock_exc.resp = MagicMock(status=403)
        mock_yt.search().list().execute.side_effect = mock_exc
        mock_yt_client.return_value = mock_yt

        track = {'title': 'Song B', 'artist': 'Artist B'}
        with self.assertRaises(QuotaOrRateLimitExceeded):
            match_spotify_track_to_youtube(self.user, track, yt_client=mock_yt)

    @patch('apps.importer.tasks.get_spotify_client')
    @patch('apps.importer.tasks.create_spotify_playlist')
    @patch('apps.importer.tasks.get_youtube_playlist_tracks')
    @patch('apps.importer.tasks.match_youtube_track_to_spotify')
    def test_run_playlist_import_search_quota_exceeded_aborts_early(self, mock_match, mock_get_tracks, mock_create_pl, mock_get_client):
        mock_create_pl.return_value = {'id': 'created_sp_id', 'name': 'SP List'}
        from apps.importer.tasks import run_playlist_import
        from apps.importer.matcher import QuotaOrRateLimitExceeded

        # 5 tracks in source playlist
        mock_get_tracks.return_value = [
            {'id': f't_{i}', 'title': f'Song {i}', 'artist': f'Artist {i}'}
            for i in range(5)
        ]

        # First track throws QuotaOrRateLimitExceeded
        mock_match.side_effect = QuotaOrRateLimitExceeded('spotify', 'Spotify rate limit 429')

        job = ImportJob.objects.create(
            user=self.user,
            source_platform=ImportJob.PLATFORM_YOUTUBE,
            target_platform=ImportJob.PLATFORM_SPOTIFY,
            source_playlist_id='yt_list_123',
            source_playlist_name='YT Big List',
            status=ImportJob.STATUS_PENDING,
        )

        run_playlist_import(job.id)
        job.refresh_from_db()

        # Crucial: Must stop after 1 track, NOT burn all 5 tracks!
        self.assertEqual(job.processed_tracks, 1)
        self.assertEqual(job.successful_tracks, 0)
        self.assertEqual(job.failed_tracks, 1)
        self.assertIn("Límite de cuota", job.error_message)
        self.assertEqual(job.status, ImportJob.STATUS_FAILED)

        item = job.items.first()
        self.assertIsNotNone(item)
        self.assertTrue(item.is_quota_error)
        self.assertIn("Límite de cuota", item.error_message)

    @patch('apps.importer.tasks.get_youtube_client')
    @patch('apps.importer.tasks.create_youtube_playlist')
    @patch('apps.importer.tasks.get_spotify_playlist_tracks')
    @patch('apps.importer.tasks.match_spotify_track_to_youtube')
    @patch('apps.importer.tasks.add_video_to_youtube_playlist')
    def test_run_playlist_import_insert_quota_exceeded_aborts_early(self, mock_add_video, mock_match, mock_get_tracks, mock_create_pl, mock_get_client):
        mock_create_pl.return_value = {'id': 'created_yt_id', 'name': 'YT List'}
        from apps.importer.tasks import run_playlist_import

        mock_get_tracks.return_value = [
            {'id': f'sp_{i}', 'title': f'Song {i}', 'artist': f'Artist {i}'}
            for i in range(4)
        ]
        mock_match.return_value = {'id': 'yt_vid_1', 'title': 'Matched Title', 'artist': 'Artist'}

        mock_exc = Exception("quotaExceeded: Daily limit exceeded")
        mock_exc.resp = MagicMock(status=403)
        mock_add_video.side_effect = mock_exc

        job = ImportJob.objects.create(
            user=self.user,
            source_platform=ImportJob.PLATFORM_SPOTIFY,
            target_platform=ImportJob.PLATFORM_YOUTUBE,
            source_playlist_id='sp_list_123',
            source_playlist_name='SP List',
            status=ImportJob.STATUS_PENDING,
        )

        run_playlist_import(job.id)
        job.refresh_from_db()

        self.assertEqual(job.processed_tracks, 1)
        self.assertEqual(job.successful_tracks, 0)
        self.assertEqual(job.failed_tracks, 1)
        self.assertIn("Límite de cuota", job.error_message)

        item = job.items.first()
        self.assertIsNotNone(item)
        self.assertTrue(item.is_quota_error)
