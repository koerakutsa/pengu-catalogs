import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import generate_meta
import enrich_catalog_metadata
from metadata_fields import duo_fields, err_fields


class MetadataTests(unittest.TestCase):
    def test_err_artwork_and_episode_thumbnail(self):
        photo = {"photoTypes": {"80": {"url": "https://img/portrait.jpg"},
                                "48": {"url": "https://img/wide.jpg"},
                                "34": {"url": "https://img/episode.jpg"}}}
        payload = {"data": {"mainContent": {
            "lead": "<p>Saate <b>kirjeldus</b></p>",
            "verticalPhotos": [photo], "horizontalPhotos": [photo],
        }, "seasonList": {"items": [{"contents": [{
            "id": 123, "heading": "Osa", "season": 1, "episode": 2,
            "horizontalPhotos": [photo], "subHeading": "Episoodi kirjeldus",
        }]}]}}}
        meta = {"id": "err:12", "type": "series", "name": "Saade"}
        with patch.object(generate_meta, "http_json", return_value=payload):
            videos = generate_meta.err_videos("err", "12", meta)
        self.assertEqual(meta["poster"], "https://img/portrait.jpg")
        self.assertEqual(meta["background"], "https://img/wide.jpg")
        self.assertEqual(meta["description"], "Saate kirjeldus")
        self.assertEqual(videos[0]["thumbnail"], "https://img/wide.jpg")
        self.assertEqual(videos[0]["overview"], "Episoodi kirjeldus")

    def test_duoplay_episode_image_and_synopsis(self):
        payload = {"synopsis": "Sarja tutvustus", "images": {"1200x630": "//img/root.jpg"},
                   "seasons": [{"number": 1, "episodes": [{
                       "episode_id": 7, "episode_nr": 2, "display_title": "Teine osa",
                       "image": {"1200x630": "//img/episode.jpg"},
                       "synopsis": "Osa kirjeldus",
                   }]}]}
        meta = {"id": "duoplay:42", "type": "series", "name": "Sari"}
        with patch.object(generate_meta, "http_json", return_value=payload):
            videos = generate_meta.duoplay_videos("42", meta)
        self.assertEqual(meta["description"], "Sarja tutvustus")
        self.assertEqual(videos[0]["thumbnail"], "https://img/episode.jpg")
        self.assertEqual(videos[0]["overview"], "Osa kirjeldus")

    def test_duoplay_landing_page_only_uses_parent_video_id(self):
        meta = {"id": "duoplay:6531", "type": "series", "name": "Kodustiil"}
        with patch.object(generate_meta, "http_json", return_value={"title": "Kodustiil"}), \
             patch.object(generate_meta, "duoplay_unique_max", return_value=0), \
             patch.object(generate_meta, "http_text", return_value='https://router.euddn.net/example/playlist.m3u8'):
            videos = generate_meta.duoplay_videos("6531", meta)
        self.assertEqual(videos[0]["id"], "duoplay:6531")
        self.assertEqual(videos[0]["title"], "Kodustiil")

    def test_existing_metadata_survives_missing_source_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cat = root / "catalog" / "series"
            out = root / "meta" / "series"
            cat.mkdir(parents=True)
            out.mkdir(parents=True)
            (cat / "duoplay.json").write_text(json.dumps({"metas": [{
                "id": "duoplay:42", "type": "series", "name": "Sari",
            }]}), encoding="utf-8")
            (out / "duoplay:42.json").write_text(json.dumps({"meta": {
                "description": "Olemasolev kirjeldus", "videos": [{
                    "id": "duoplay:42:ep:1", "title": "Osa 1", "season": 1,
                    "episode": 1, "thumbnail": "https://img/old.jpg",
                }],
            }}), encoding="utf-8")
            with patch.object(generate_meta, "CAT", root / "catalog"), \
                 patch.object(generate_meta, "META", root / "meta"), \
                 patch.object(generate_meta, "enrich_series", side_effect=lambda x: x):
                generate_meta.main()
            meta = json.loads((out / "duoplay:42.json").read_text(encoding="utf-8"))["meta"]
            self.assertEqual(meta["description"], "Olemasolev kirjeldus")
            self.assertEqual(meta["videos"][0]["thumbnail"], "https://img/old.jpg")

    def test_catalog_enrichment_updates_aliases_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for source in ("jupiter", "err-archive"):
                path = root / "catalog" / "movie" / f"{source}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                prefix = "err" if source == "jupiter" else "err-archive"
                path.write_text(json.dumps({"metas": [{
                    "id": f"{prefix}:123", "type": "movie", "name": "Film",
                    "poster": "https://img/current.jpg",
                }]}), encoding="utf-8")
            with patch.object(enrich_catalog_metadata, "CAT", root / "catalog"), \
                 patch.object(enrich_catalog_metadata, "META", root / "meta"), \
                 patch.object(enrich_catalog_metadata, "STATE", root / "metadata-state.json"), \
                 patch.object(enrich_catalog_metadata, "fetch_fields", return_value={
                     "poster": "https://img/new.jpg", "description": "Päris kirjeldus",
                 }) as fetch, \
                 patch("sys.argv", ["enrich_catalog_metadata.py", "--limit", "1"]):
                enrich_catalog_metadata.main()
            self.assertEqual(fetch.call_count, 1)
            for source in ("jupiter", "err-archive"):
                path = root / "catalog" / "movie" / f"{source}.json"
                item = json.loads(path.read_text(encoding="utf-8"))["metas"][0]
                self.assertEqual(item["poster"], "https://img/current.jpg")
                self.assertEqual(item["description"], "Päris kirjeldus")
            state = json.loads((root / "metadata-state.json").read_text(encoding="utf-8"))
            self.assertIn("err:123", state["checked"])


if __name__ == "__main__":
    unittest.main()
