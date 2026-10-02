#!/usr/bin/env python3
"""Expose published DuoPlay VTT through an HLS subtitle rendition for TV players.

Nuvio TV versions that ignore stream-level external subtitles can still select
an HLS subtitle rendition. The original DuoPlay stream stays available.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.parse
from pathlib import Path

from generate_streams import DUO_SITE, ROOT, STREAM, request
from generate_duoplay_subtitles import BASE, SUBTITLES, with_query

PLAYLISTS = ROOT / "playlists"
PLAYLIST_BASE = "https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/playlists"
TIMECODE = re.compile(r"-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
URI = re.compile(r'URI="([^"]+)"')


def subtitle_playlist(vtt: str, subtitle_url: str, duration_hint: int = 0) -> str:
    ends = [int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            for h, m, s, ms in TIMECODE.findall(vtt)]
    if not ends:
        raise ValueError("WebVTT has no cues")
    duration = max(1, math.ceil(max(ends)) + 1, duration_hint)
    return ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-PLAYLIST-TYPE:VOD\n"
            f"#EXT-X-TARGETDURATION:{duration}\n#EXT-X-MEDIA-SEQUENCE:0\n"
            f"#EXTINF:{duration}.000,\n{subtitle_url}\n#EXT-X-ENDLIST\n")


def tv_master(master: str, source_url: str, subtitle_playlist_url: str) -> str:
    lines = []
    replaced = False
    for line in master.splitlines():
        if line.startswith("#EXT-X-MEDIA:") and "TYPE=SUBTITLES" in line and re.search(r'LANGUAGE="(?:est|et)"', line, re.I):
            line = URI.sub('URI="' + subtitle_playlist_url + '"', line, count=1)
            line = re.sub(r'NAME="[^"]*"', 'NAME="Eesti (GitHub)"', line, count=1)
            replaced = True
        elif "URI=\"" in line:
            line = URI.sub(lambda match: 'URI="' + with_query(urllib.parse.urljoin(source_url, match.group(1)), source_url) + '"', line)
        elif line and not line.startswith("#"):
            line = with_query(urllib.parse.urljoin(source_url, line), source_url)
        lines.append(line)
    if not replaced:
        raise ValueError("Source HLS master has no Estonian subtitle rendition")
    return "\n".join(lines) + "\n"


def source_subtitle_duration(master: str, source_url: str) -> int:
    line = next((line for line in master.splitlines() if line.startswith("#EXT-X-MEDIA:")
                 and "TYPE=SUBTITLES" in line and re.search(r'LANGUAGE="(?:est|et)"', line, re.I)), None)
    match = URI.search(line or "")
    if not match:
        return 0
    playlist_url = with_query(urllib.parse.urljoin(source_url, match.group(1)), source_url)
    playlist = request(playlist_url, DUO_SITE + "/")
    return math.ceil(sum(float(value) for value in re.findall(r"#EXTINF:([\d.]+)", playlist)))


def main() -> None:
    limit = max(1, int(os.environ.get("HLS_SUBTITLE_BATCH_SIZE", "300")))
    added = errors = 0
    for typ in ("movie", "series"):
        for vtt_path in sorted((SUBTITLES / typ).glob("duoplay:*.vtt")):
            if added >= limit:
                break
            identifier = vtt_path.stem
            stream_path = STREAM / typ / (identifier + ".json")
            if not stream_path.is_file():
                continue
            payload = json.loads(stream_path.read_text(encoding="utf-8"))
            streams = payload.get("streams") or []
            original = next((row for row in streams if row.get("url", "").startswith("https://router.euddn.net/")), None)
            if not original:
                continue
            tv_path = PLAYLISTS / typ / (identifier + ".m3u8")
            sub_path = PLAYLISTS / typ / (identifier + "-et.m3u8")
            quoted = urllib.parse.quote(identifier, safe="")
            tv_url = f"{PLAYLIST_BASE}/{typ}/{quoted}.m3u8"
            sub_url = f"{PLAYLIST_BASE}/{typ}/{quoted}-et.m3u8"
            vtt_url = f"{BASE}/{typ}/{quoted}.vtt"
            if tv_path.is_file() and sub_path.is_file() and any(row.get("url") == tv_url for row in streams):
                continue
            try:
                source_url = original["url"]
                master = request(source_url, DUO_SITE + "/")
                vtt = vtt_path.read_text(encoding="utf-8")
                tv_text = tv_master(master, source_url, sub_url)
                try:
                    duration = source_subtitle_duration(master, source_url)
                except (OSError, ValueError):
                    duration = 0
                sub_text = subtitle_playlist(vtt, vtt_url, duration)
                tv_path.parent.mkdir(parents=True, exist_ok=True)
                tv_path.write_text(tv_text, encoding="utf-8")
                sub_path.write_text(sub_text, encoding="utf-8")
                streams[:] = [row for row in streams if row.get("url") != tv_url]
                streams.append({
                    "name": "DuoPlay",
                    "title": "DuoPlay · HLS · Eesti (GitHub)",
                    "url": tv_url,
                    "behaviorHints": original.get("behaviorHints", {}),
                })
                stream_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
                added += 1
            except (OSError, ValueError) as exc:
                errors += 1
                print(f"{identifier}: {exc}", flush=True)
        if added >= limit:
            break
    print(f"TV HLS subtitle variants added={added} errors={errors}", flush=True)


if __name__ == "__main__":
    main()
