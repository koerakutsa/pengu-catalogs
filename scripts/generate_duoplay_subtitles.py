#!/usr/bin/env python3
"""Publish plain WebVTT tracks for DuoPlay streams in bounded batches.

DuoPlay HLS subtitles are gzip-compressed WebVTT chunks behind CDN redirects.
Some TV players advertise the HLS track but cannot render those chunks.
"""
from __future__ import annotations

import concurrent.futures
from bisect import bisect_right
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from generate_streams import DUO_SITE, M3U_RE, ROOT, STREAM, request

SUBTITLES = ROOT / "subtitles"
STATE = ROOT / "subtitle-state.json"
BASE = "https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/subtitles"
PLAYER_UA = "Mozilla/5.0"
MEDIA_URI = re.compile(r'URI="([^"]+)"')
TIMECODE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


NO_REDIRECT = urllib.request.build_opener(NoRedirect)


def with_query(url: str, source: str) -> str:
    """DuoPlay requires the master playlist's c= query on child resources."""
    parsed = urllib.parse.urlsplit(url)
    source_query = urllib.parse.parse_qs(urllib.parse.urlsplit(source).query)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    existing = {key for key, _ in query}
    for key in ("c", "s"):
        if key in source_query and key not in existing:
            query.append((key, source_query[key][0]))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


def fetch_chunk(url: str) -> bytes:
    headers = {"User-Agent": PLAYER_UA, "Referer": DUO_SITE + "/"}
    for attempt in range(3):
        try:
            try:
                with NO_REDIRECT.open(urllib.request.Request(url, headers=headers), timeout=20) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                if exc.code not in (301, 302, 303, 307, 308):
                    raise
                destination = exc.headers.get("Location", "")
                host = urllib.parse.urlsplit(destination).hostname or ""
                if not host.endswith(".euddn.net"):
                    raise ValueError("Unexpected DuoPlay subtitle CDN redirect")
            # This CDN sometimes rejects its first redirected request even when
            # the following identical URL succeeds with a Referer.
            for cdn_headers in ({"User-Agent": PLAYER_UA}, headers):
                try:
                    with urllib.request.urlopen(urllib.request.Request(destination, headers=cdn_headers), timeout=20) as response:
                        return response.read()
                except urllib.error.HTTPError as exc:
                    if exc.code != 403 or cdn_headers is headers:
                        raise
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(0.3 * (attempt + 1))
    raise RuntimeError("Subtitle chunk fetch failed")


def track_text(manifest: str) -> str | None:
    master = request(manifest, DUO_SITE + "/")
    line = next(
        (line for line in master.splitlines() if line.startswith("#EXT-X-MEDIA:")
         and "TYPE=SUBTITLES" in line and re.search(r'LANGUAGE="(?:est|et)"', line, re.I)),
        None,
    )
    if not line:
        return None
    match = MEDIA_URI.search(line)
    if not match:
        return None
    playlist_url = with_query(urllib.parse.urljoin(manifest, match.group(1)), manifest)
    playlist = request(playlist_url, DUO_SITE + "/")
    segments = [line.strip() for line in playlist.splitlines() if line.strip() and not line.startswith("#")]
    if not segments or len(segments) > 200:
        return None
    parts = []
    for segment in segments:
        segment_url = with_query(urllib.parse.urljoin(playlist_url, segment), manifest)
        if urllib.parse.urlsplit(segment_url).hostname != urllib.parse.urlsplit(manifest).hostname:
            raise ValueError("Unexpected subtitle segment host")
        body = fetch_chunk(segment_url)
        if body.startswith(b"\x1f\x8b"):
            body = gzip.decompress(body)
        text = body.decode("utf-8-sig").replace("\r\n", "\n")
        if not text.startswith("WEBVTT"):
            raise ValueError("Subtitle segment is not WebVTT")
        _, _, cues = text.partition("\n\n")
        if cues.strip():
            parts.append(cues.strip())
    joined = "WEBVTT\n\n" + "\n\n".join(parts) + "\n"
    return joined if TIMECODE.search(joined) else None


def resolve(task: tuple[str, str]) -> tuple[str, str, str | None, str | None]:
    typ, identifier = task
    try:
        parts = identifier.split(":")
        path = "/" + parts[1]
        if len(parts) > 2:
            path += "?ep=" + urllib.parse.quote(parts[-1])
        page = request(DUO_SITE + path, DUO_SITE + "/")
        match = M3U_RE.search(page.replace("\\/", "/"))
        if not match:
            return typ, identifier, None, None
        return typ, identifier, track_text(match.group(0).replace("&amp;", "&")), None
    except Exception as exc:
        return typ, identifier, None, str(exc)


def main() -> None:
    batch = max(1, int(os.environ.get("SUBTITLE_BATCH_SIZE", "300")))
    workers = min(6, max(1, int(os.environ.get("SUBTITLE_WORKERS", "3"))))
    wanted = []
    for typ in ("movie", "series"):
        for path in (STREAM / typ).glob("duoplay:*.json"):
            target = SUBTITLES / typ / (path.stem + ".vtt")
            if target.is_file():
                continue
            wanted.append((typ, path.stem))
    def sort_key(item: tuple[str, str]) -> tuple[bool, bool, str]:
        return (item != ("movie", "duoplay:10647"), item[0] != "movie", item[1])

    wanted.sort(key=sort_key)
    previous = {}
    if STATE.exists():
        try:
            previous = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    last = previous.get("last")
    keys = [sort_key(item) for item in wanted]
    start = bisect_right(keys, sort_key(tuple(last))) if isinstance(last, list) and len(last) == 2 else 0
    if start >= len(wanted):
        start = 0
    tasks = (wanted[start:] + wanted[:start])[:batch]
    print(f"DuoPlay subtitles missing={len(wanted)} batch={len(tasks)} workers={workers}", flush=True)
    resolved = empty = errors = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for typ, identifier, vtt, error in executor.map(resolve, tasks):
            if error:
                errors += 1
                print(f"{identifier}: {error}", flush=True)
                continue
            if not vtt:
                empty += 1
                continue
            target = SUBTITLES / typ / (identifier + ".vtt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(vtt, encoding="utf-8")
            stream_path = STREAM / typ / (identifier + ".json")
            payload = json.loads(stream_path.read_text(encoding="utf-8"))
            url = BASE + "/" + typ + "/" + urllib.parse.quote(identifier, safe="") + ".vtt"
            for stream in payload.get("streams") or []:
                if stream.get("url"):
                    subtitles = [sub for sub in stream.get("subtitles", []) if sub.get("id") != "duoplay-et"]
                    subtitles.append({"id": "duoplay-et", "lang": "est", "url": url})
                    stream["subtitles"] = subtitles
            stream_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
            resolved += 1
    STATE.write_text(json.dumps({"last": list(tasks[-1]) if tasks else None, "missing": len(wanted),
                                 "resolved": resolved, "empty": empty, "errors": errors,
                                 "ts": int(time.time())}, indent=2) + "\n", encoding="utf-8")
    print(f"Batch done resolved={resolved} empty={empty} errors={errors}", flush=True)


if __name__ == "__main__":
    main()
