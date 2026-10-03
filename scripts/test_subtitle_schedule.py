"""Regression check for new DuoPlay streams during a partial subtitle backfill."""
import unittest

from generate_duoplay_subtitles import select_tasks


class SubtitleScheduleTest(unittest.TestCase):
    def test_new_movie_and_episode_precede_old_series_cursor(self):
        wanted = [
            ("movie", "duoplay:11812"),
            ("series", "duoplay:10050"),
            ("series", "duoplay:12000"),
            ("series", "duoplay:90000"),
        ]
        previous = {"last": ["series", "duoplay:12000"]}
        changed = {("movie", "duoplay:11812"), ("series", "duoplay:10050")}
        tasks, last, urgent = select_tasks(wanted, previous, changed, 2)
        self.assertEqual(set(tasks), changed)
        self.assertEqual(last, previous["last"])
        self.assertEqual(urgent, changed)


if __name__ == "__main__":
    unittest.main()
