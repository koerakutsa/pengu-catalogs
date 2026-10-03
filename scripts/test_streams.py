import unittest
from unittest.mock import patch

import generate_streams
from normalize_duoplay_streams import normalize


class DuoStreamTests(unittest.TestCase):
    def test_synthetic_first_episode_uses_landing_page_if_no_episode_list(self):
        manifest = 'https://router.euddn.net/example/playlist.m3u8?c=7F01'

        def fake_request(url, referer, timeout=20):
            if '?ep=1' in url:
                return 'Antud episoodi ei leitud'
            if '/catchup/6531' in url:
                return '{}'
            if url.endswith('/6531'):
                return manifest
            raise AssertionError(url)

        with patch.object(generate_streams, 'request', side_effect=fake_request):
            stream = generate_streams.duo_stream('6531', '1')
        self.assertEqual(stream['url'], manifest)
        self.assertNotIn('Origin', stream['behaviorHints']['proxyHeaders']['request'])

    def test_real_episode_list_does_not_fall_back_to_wrong_episode(self):
        def fake_request(url, referer, timeout=20):
            if '?ep=1' in url:
                return 'Antud episoodi ei leitud'
            if '/catchup/6531' in url:
                return '{"seasons":[{"episodes":[{"episode_id":2}]}]}'
            raise AssertionError(url)

        with patch.object(generate_streams, 'request', side_effect=fake_request):
            self.assertIsNone(generate_streams.duo_stream('6531', '1'))

    def test_normalizer_preserves_subtitles_and_removes_broken_variant(self):
        payload = {'streams': [
            {'url': 'https://router.euddn.net/playlist.m3u8',
             'subtitles': [{'id': 'duoplay-et', 'url': 'https://example.org/sub.vtt'}],
             'behaviorHints': {'proxyHeaders': {'request': {
                 'Origin': 'https://duoplay.ee', 'Referer': 'https://duoplay.ee/'}}}},
            {'url': 'https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/playlists/movie/duoplay%3A11812.m3u8'},
        ]}
        result, changed = normalize(payload)
        self.assertTrue(changed)
        self.assertEqual(len(result['streams']), 1)
        self.assertEqual(result['streams'][0]['subtitles'][0]['id'], 'duoplay-et')
        self.assertEqual(result['streams'][0]['behaviorHints']['proxyHeaders']['request'],
                         {'Referer': 'https://duoplay.ee/'})


if __name__ == '__main__':
    unittest.main()
