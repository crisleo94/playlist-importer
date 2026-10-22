from django.test import SimpleTestCase
from apps.importer.parsers import parse_playlist_input


class PlaylistParserTests(SimpleTestCase):
    def test_empty_and_invalid_inputs(self):
        self.assertIsNone(parse_playlist_input(None))
        self.assertIsNone(parse_playlist_input(''))
        self.assertIsNone(parse_playlist_input('   '))
        self.assertIsNone(parse_playlist_input('not_a_valid_id_or_url'))
        self.assertIsNone(parse_playlist_input('https://google.com'))
        self.assertIsNone(parse_playlist_input('https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT'))
        self.assertIsNone(parse_playlist_input('https://www.youtube.com/watch?v=dQw4w9WgXcQ'))

    def test_spotify_web_urls(self):
        url = 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=e2f897df893c4e43'
        self.assertEqual(parse_playlist_input(url), ('spotify', '37i9dQZF1DXcBWIGoYBM5M'))

        url_no_query = 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'
        self.assertEqual(parse_playlist_input(url_no_query), ('spotify', '37i9dQZF1DXcBWIGoYBM5M'))

        url_no_scheme = 'open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'
        self.assertEqual(parse_playlist_input(url_no_scheme), ('spotify', '37i9dQZF1DXcBWIGoYBM5M'))

    def test_spotify_uri(self):
        uri = 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'
        self.assertEqual(parse_playlist_input(uri), ('spotify', '37i9dQZF1DXcBWIGoYBM5M'))

    def test_spotify_raw_id(self):
        raw_id = '37i9dQZF1DXcBWIGoYBM5M'
        self.assertEqual(parse_playlist_input(raw_id), ('spotify', '37i9dQZF1DXcBWIGoYBM5M'))

    def test_youtube_urls(self):
        # music.youtube.com
        url_music = 'https://music.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj&si=tracker'
        self.assertEqual(parse_playlist_input(url_music), ('youtube', 'PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'))

        # www.youtube.com
        url_yt = 'https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'
        self.assertEqual(parse_playlist_input(url_yt), ('youtube', 'PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'))

        # youtu.be / watch with list param
        url_watch = 'https://www.youtube.com/watch?v=video123&list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'
        self.assertEqual(parse_playlist_input(url_watch), ('youtube', 'PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'))

    def test_youtube_raw_id(self):
        raw_id = 'PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'
        self.assertEqual(parse_playlist_input(raw_id), ('youtube', 'PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'))

    def test_security_domain_spoofing_rejected(self):
        # Attacker trying to spoof domain via substring
        spoofed_yt = 'https://music.youtube.com.attacker.net/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj'
        self.assertIsNone(parse_playlist_input(spoofed_yt))

        spoofed_sp = 'https://open.spotify.com.attacker.net/playlist/37i9dQZF1DXcBWIGoYBM5M'
        self.assertIsNone(parse_playlist_input(spoofed_sp))

    def test_security_youtube_invalid_or_malicious_id_rejected(self):
        # Malicious payload in list parameter on legitimate YouTube domain
        xss_url = 'https://www.youtube.com/playlist?list=<script>alert(1)</script>'
        self.assertIsNone(parse_playlist_input(xss_url))

        invalid_id_url = 'https://music.youtube.com/playlist?list=invalid-random-id-123'
        self.assertIsNone(parse_playlist_input(invalid_id_url))
