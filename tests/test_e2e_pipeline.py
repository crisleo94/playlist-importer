from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, Client
from django.urls import reverse
from apps.importer.models import ImportJob, ImportJobItem
from apps.importer.tasks import run_playlist_import
from apps.integrations.models import PlatformToken

User = get_user_model()


class EndToEndPipelineIntegrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(username="e2e_user", password="secure_password_123")
        self.client.login(username="e2e_user", password="secure_password_123")

        # Configurar tokens de ambas plataformas para el usuario
        self.spotify_token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_SPOTIFY,
            platform_username="spotify_tester"
        )
        self.spotify_token.set_access_token("valid_spotify_access_token")
        self.spotify_token.set_refresh_token("valid_spotify_refresh_token")
        self.spotify_token.save()

        self.youtube_token = PlatformToken.objects.create(
            user=self.user,
            platform=PlatformToken.PLATFORM_YOUTUBE,
            platform_username="youtube_channel_tester"
        )
        self.youtube_token.set_access_token("valid_youtube_access_token")
        self.youtube_token.set_refresh_token("valid_youtube_refresh_token")
        self.youtube_token.save()

    def tearDown(self):
        cache.clear()

    @patch('apps.importer.tasks.add_video_to_youtube_playlist')
    @patch('apps.importer.tasks.create_youtube_playlist')
    @patch('apps.importer.tasks.match_spotify_track_to_youtube')
    @patch('apps.importer.tasks.get_spotify_playlist_tracks')
    @patch('apps.importer.views.get_user_youtube_playlists')
    @patch('apps.importer.views.preview_playlist_match')
    @patch('apps.importer.views.get_user_spotify_playlists')
    def test_complete_e2e_flow_spotify_to_youtube(
        self,
        mock_get_sp_playlists,
        mock_preview_match,
        mock_get_yt_playlists,
        mock_task_get_tracks,
        mock_task_match,
        mock_task_create_yt_pl,
        mock_task_add_video,
    ):
        # 1. Cargar el Dashboard principal
        dashboard_res = self.client.get(reverse('importer:dashboard'))
        self.assertEqual(dashboard_res.status_code, 200)
        self.assertContains(dashboard_res, "Playlists de Spotify")
        self.assertContains(dashboard_res, "Playlists de YouTube Music")

        # 2. Cargar listado de playlists de Spotify
        mock_get_sp_playlists.return_value = [
            {
                'id': 'sp_pl_rock',
                'name': 'Classic Rock 70s',
                'total_tracks': 2,
                'owner_name': 'spotify_tester',
                'image_url': 'http://example.com/rock.jpg',
                'external_url': 'https://open.spotify.com/playlist/sp_pl_rock',
            }
        ]
        sp_res = self.client.get(reverse('importer:spotify_playlists'))
        self.assertEqual(sp_res.status_code, 200)
        self.assertContains(sp_res, "Classic Rock 70s")
        self.assertContains(sp_res, "Transferir hacia YouTube Music")

        # 3. Abrir modal de previsualización en seco (dry-run)
        mock_get_yt_playlists.return_value = []
        mock_preview_match.return_value = {
            'source_platform': 'spotify',
            'target_platform': 'youtube',
            'playlist_id': 'sp_pl_rock',
            'total_tracks': 2,
            'matched_count': 2,
            'unmatched_count': 0,
            'match_rate': 100.0,
            'items': [
                {
                    'source': {'title': 'Bohemian Rhapsody', 'artist': 'Queen'},
                    'target': {'title': 'Queen - Bohemian Rhapsody', 'artist': 'Queen Official', 'score': 0.95},
                    'is_matched': True,
                },
                {
                    'source': {'title': 'Stairway to Heaven', 'artist': 'Led Zeppelin'},
                    'target': {'title': 'Led Zeppelin - Stairway to Heaven', 'artist': 'LedZeppelinVEVO', 'score': 0.92},
                    'is_matched': True,
                }
            ]
        }

        preview_url = reverse('importer:preview_match', kwargs={
            'source_platform': 'spotify',
            'playlist_id': 'sp_pl_rock'
        })
        preview_res = self.client.get(f"{preview_url}?name=Classic+Rock+70s")
        self.assertEqual(preview_res.status_code, 200)
        self.assertContains(preview_res, "Previsualización de Coincidencias")
        self.assertContains(preview_res, "100")
        self.assertContains(preview_res, "Iniciar Transferencia")

        # 4. Iniciar la transferencia (POST start_import)
        with patch('apps.importer.views.run_playlist_import.delay') as mock_delay:
            mock_delay.return_value = MagicMock(id='celery_e2e_task_1')

            start_res = self.client.post(reverse('importer:start_import'), {
                'source_platform': 'spotify',
                'source_playlist_id': 'sp_pl_rock',
                'source_playlist_name': 'Classic Rock 70s',
                'dest_mode': 'new',
                'new_playlist_name': 'Classic Rock 70s (YT Music)',
            })
            self.assertEqual(start_res.status_code, 200)
            self.assertContains(start_res, "Progreso de Importación")
            self.assertContains(start_res, 'hx-trigger="every 1.5s"')

            # Verificar que el job fue registrado
            job = ImportJob.objects.get(source_playlist_id='sp_pl_rock')
            self.assertEqual(job.status, ImportJob.STATUS_PENDING)
            self.assertEqual(job.destination_mode, 'new')
            mock_delay.assert_called_once_with(job.id)

        # 5. Ejecución simulada de la tarea Celery en segundo plano
        mock_task_get_tracks.return_value = [
            {'id': 'trk_1', 'title': 'Bohemian Rhapsody', 'artist': 'Queen', 'isrc': 'GBUM71029604'},
            {'id': 'trk_2', 'title': 'Stairway to Heaven', 'artist': 'Led Zeppelin', 'isrc': 'USAT20700010'},
        ]
        mock_task_create_yt_pl.return_value = {
            'id': 'yt_new_e2e_pl',
            'name': 'Classic Rock 70s (YT Music)'
        }
        mock_task_match.side_effect = [
            {'id': 'vid_queen_1', 'title': 'Bohemian Rhapsody', 'artist': 'Queen', 'score': 0.95, 'match_type': 'isrc'},
            {'id': 'vid_zep_2', 'title': 'Stairway to Heaven', 'artist': 'Led Zeppelin', 'score': 0.92, 'match_type': 'fuzzy'},
        ]
        mock_task_add_video.return_value = {'id': 'item_created'}

        run_playlist_import(job.id)
        job.refresh_from_db()

        # Validaciones de la base de datos tras la tarea
        self.assertEqual(job.status, ImportJob.STATUS_COMPLETED)
        self.assertEqual(job.total_tracks, 2)
        self.assertEqual(job.successful_tracks, 2)
        self.assertEqual(job.failed_tracks, 0)
        self.assertEqual(job.target_playlist_id, 'yt_new_e2e_pl')
        self.assertEqual(job.items.count(), 2)
        self.assertEqual(mock_task_add_video.call_count, 2)

        # 6. Polling del usuario hasta finalización
        progress_res = self.client.get(reverse('importer:import_progress', kwargs={'job_id': job.id}))
        self.assertEqual(progress_res.status_code, 200)
        self.assertContains(progress_res, "¡Importación Completada con Éxito!")
        self.assertNotContains(progress_res, 'hx-trigger="every 1.5s"')
        self.assertContains(progress_res, "Aceptar y Actualizar")

    @patch('apps.importer.tasks.add_tracks_to_spotify_playlist')
    @patch('apps.importer.tasks.match_youtube_track_to_spotify')
    @patch('apps.importer.tasks.get_youtube_playlist_tracks')
    def test_complete_e2e_flow_youtube_to_spotify_partial_matching(
        self,
        mock_get_yt_tracks,
        mock_match_yt_to_sp,
        mock_add_to_sp,
    ):
        # Flujo inverso con destino existente y match parcial
        job = ImportJob.objects.create(
            user=self.user,
            source_platform='youtube',
            target_platform='spotify',
            source_playlist_id='yt_pl_synth',
            source_playlist_name='Synthwave 80s',
            destination_mode='existing',
            target_playlist_id='sp_dest_existing',
            status=ImportJob.STATUS_PENDING
        )

        mock_get_yt_tracks.return_value = [
            {'id': 'v1', 'title': 'Kavinsky - Nightcall', 'artist': 'Kavinsky'},
            {'id': 'v2', 'title': 'Obscure VHS Audio Track 1984', 'artist': 'Unknown'},
        ]
        # Pista 1 emparejada, pista 2 no encontrada
        mock_match_yt_to_sp.side_effect = [
            {
                'id': 'sp_trk_kav',
                'uri': 'spotify:track:sp_trk_kav',
                'title': 'Nightcall',
                'artist': 'Kavinsky',
                'score': 0.94,
                'match_type': 'fuzzy'
            },
            None,
        ]

        run_playlist_import(job.id)
        job.refresh_from_db()

        self.assertEqual(job.status, ImportJob.STATUS_PARTIAL)
        self.assertEqual(job.total_tracks, 2)
        self.assertEqual(job.successful_tracks, 1)
        self.assertEqual(job.failed_tracks, 1)
        self.assertEqual(mock_add_to_sp.call_count, 1)

        # Polling del resultado parcial
        progress_res = self.client.get(reverse('importer:import_progress', kwargs={'job_id': job.id}))
        self.assertEqual(progress_res.status_code, 200)
        self.assertContains(progress_res, "Importación Parcialmente Completada")
        self.assertContains(progress_res, "Obscure VHS Audio Track 1984")
        self.assertContains(progress_res, "Sin coincidencia")
