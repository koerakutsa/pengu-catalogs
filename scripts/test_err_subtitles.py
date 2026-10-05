import unittest
from unittest.mock import patch

import generate_err_subtitles as err


class ErrSubtitleTests(unittest.TestCase):
    def test_repeated_cue_is_written_once_with_hls_timing(self):
        original = """WEBVTT

1
00:01:25.400 --> 00:01:31.120
Atlandi ookean
40 km Hispaania rannikust

1
00:01:25.400 --> 00:01:31.120
Atlandi ookean
40 km Hispaania rannikust
"""
        result = err.shift_vtt(original, 8000)
        self.assertEqual(result.count('Atlandi ookean'), 1)
        self.assertIn('00:01:33.400 --> 00:01:39.120', result)

    def test_offset_is_measured_from_hls_instead_of_assumed(self):
        original = 'WEBVTT\n\n1\n00:01:25.400 --> 00:01:31.120\nAtlandi ookean\n\n'
        master = '#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,LANGUAGE="et",URI="sub.m3u8"\n'
        playlist = '#EXTM3U\n' + ''.join(f'seg{i}.vtt\n' for i in range(1, 14))
        segment = 'WEBVTT\n\n1\n00:01:33.400 --> 00:01:39.120\nAtlandi ookean\n\n'

        def fake_fetch(url):
            if url.endswith('master.m3u8'):
                return master
            if url.endswith('sub.m3u8'):
                return playlist
            return segment if url.endswith('seg10.vtt') else 'WEBVTT\n\n'

        with patch.object(err, 'fetch_text', side_effect=fake_fetch):
            self.assertEqual(err.subtitle_offset('https://vod.err.ee/master.m3u8', 'ET', original), 8000)

    def test_only_measured_err_profiles_are_published(self):
        self.assertEqual(err.profile_offset('https://vod.err.ee/hls/x/2/v/PGEST/master.m3u8'), 8000)
        self.assertEqual(err.profile_offset('https://vod.err.ee/hls/x/2/v/master.m3u8'), 0)
        with self.assertRaises(ValueError):
            err.profile_offset('https://vod.err.ee/hls/x/2/v/OTHER/master.m3u8')


if __name__ == '__main__':
    unittest.main()
