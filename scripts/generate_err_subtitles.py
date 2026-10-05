#!/usr/bin/env python3
"""Replace duplicated ERR HLS subtitle segments with one plain WebVTT track.

ERR repeats cues at HLS segment boundaries. Some Android TV players display both
copies. Its ``hlsNoSub`` rendition has the same video without that subtitle
playlist; we attach a single, time-aligned VTT track to the stream instead.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from generate_streams import ERR_API, ROOT, STREAM, UA

SUBTITLES = ROOT / "subtitles" / "err"
STATE = ROOT / "err-subtitle-state.json"
BASE = "https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/subtitles/err/"
STREAM_ID = re.compile(r"^(?:err|err-archive|lasteekraan):(\d+)$")
TIMING = re.compile(r"^(\d{2,}:\d{2}:\d{2}\.\d{3})\s+-->\s+(\d{2,}:\d{2}:\d{2}\.\d{3})(.*)$")
URI = re.compile(r'URI="([^"]+)"')
LANGUAGE = {"ET": "est", "EN": "eng", "RU": "rus"}


def fetch_text(url: str) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    if not (host == "err.ee" or host.endswith(".err.ee")):
        raise ValueError("Unexpected ERR media host")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://jupiter.err.ee/"})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read().decode("utf-8-sig")


def absolute(url: str) -> str:
    return "https:" + url if url.startswith("//") else url


def milliseconds(timestamp: str) -> int:
    hours, minutes, seconds = timestamp.split(":")
    whole, fraction = seconds.split(".")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(whole)) * 1000 + int(fraction)


def timestamp(value: int) -> str:
    if value < 0:
        raise ValueError("Subtitle cue would start before video")
    seconds, fraction = divmod(value, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{fraction:03d}"


def cues(vtt: str) -> list[tuple[str, str, str, str, str]]:
    """Return cue id, start, end, settings, and text; skip WebVTT metadata."""
    out = []
    for block in re.split(r"\n\s*\n", vtt.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip().splitlines()
        for index, line in enumerate(lines):
            match = TIMING.match(line)
            if match and index + 1 < len(lines):
                out.append((lines[index - 1] if index else "", match[1], match[2],
                            match[3], "\n".join(lines[index + 1:]).strip()))
                break
    return out


def shift_vtt(vtt: str, offset: int) -> str:
    output = ["WEBVTT"]
    seen = set()
    for cue_id, start, end, settings, body in cues(vtt):
        shifted_start = timestamp(milliseconds(start) + offset)
        shifted_end = timestamp(milliseconds(end) + offset)
        key = (shifted_start, shifted_end, body)
        if key in seen:
            continue
        seen.add(key)
        lines = ([cue_id] if cue_id else []) + [f"{shifted_start} --> {shifted_end}{settings}", body]
        output.append("\n".join(lines))
    if len(output) == 1:
        raise ValueError("No WebVTT cues")
    return "\n\n".join(output) + "\n"


def subtitle_playlist(master_url: str, language: str) -> str:
    for line in fetch_text(master_url).splitlines():
        if not line.startswith("#EXT-X-MEDIA:") or "TYPE=SUBTITLES" not in line:
            continue
        if not re.search(r'LANGUAGE="' + re.escape(language) + r'"', line, re.I):
            continue
        match = URI.search(line)
        if match:
            return urllib.parse.urljoin(master_url, match[1])
    raise ValueError("Matching HLS subtitle rendition missing")


def subtitle_offset(master_url: str, language: str, original_vtt: str) -> int:
    original_cues = cues(original_vtt)
    if not original_cues:
        raise ValueError("Empty original subtitle track")
    first = original_cues[0]
    playlist_url = subtitle_playlist(master_url, language)
    playlist = fetch_text(playlist_url)
    segments = [urllib.parse.urljoin(playlist_url, line.strip()) for line in playlist.splitlines()
                if line.strip() and not line.startswith("#")]
    if not segments or len(segments) > 20000:
        raise ValueError("Invalid HLS subtitle playlist")
    # ERR normally adds eight seconds. Probe near the first original cue and
    # match its text, rather than assuming every title has the same offset.
    center = min(len(segments) - 1, milliseconds(first[1]) // 10000)
    indexes = sorted(range(max(0, center - 3), min(len(segments), center + 13)),
                     key=lambda i: abs(i - (center + 1)))
    for index in indexes:
        for candidate in cues(fetch_text(segments[index])):
            if candidate[4] == first[4]:
                offset = milliseconds(candidate[1]) - milliseconds(first[1])
                if abs(offset) <= 120000:
                    return offset
    raise ValueError("Could not align HLS subtitles with original WebVTT")


def stream_paths() -> dict[str, list[Path]]:
    result: dict[str, list[Path]] = {}
    for typ in ("movie", "series"):
        for path in (STREAM / typ).glob("*.json"):
            match = STREAM_ID.fullmatch(path.stem)
            if match:
                result.setdefault(match[1], []).append(path)
    return result


def needs_update(paths: list[Path]) -> bool:
    for path in paths:
        try:
            streams = json.loads(path.read_text(encoding="utf-8")).get("streams") or []
            if any("/hls/" in str(row.get("url", "")) and
                   "/nosub/" not in str(row.get("url", "")) for row in streams):
                return True
        except (OSError, ValueError, TypeError):
            pass
    return False


def source_media(content_id: str, current_url: str) -> tuple[dict, dict] | None:
    url = ERR_API + "?" + urllib.parse.urlencode({"contentId": content_id, "rootId": 3905, "page": "web"})
    payload = json.loads(fetch_text(url))
    main = (payload.get("data") or {}).get("mainContent") or {}
    for media in main.get("medias") or []:
        if (media.get("restrictions") or {}).get("drm"):
            continue
        src = media.get("src") or {}
        if current_url in [absolute(src.get(key) or "") for key in ("hlsNew", "hls2", "hls")]:
            return media, src
    return None


def normalize(content_id: str, paths: list[Path]) -> bool:
    payloads = []
    current_url = ""
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads.append((path, payload))
        if not current_url:
            current_url = next((row.get("url", "") for row in payload.get("streams") or []
                                if "/hls/" in str(row.get("url", "")) and "/nosub/" not in row.get("url", "")), "")
    if not current_url:
        return False
    source = source_media(content_id, current_url)
    if not source:
        return False
    media, src = source
    no_sub = absolute(src.get("hlsNoSub") or "")
    tracks = [track for track in media.get("subtitles") or []
              if track.get("src") and str(track.get("srclang") or "").upper()]
    if not no_sub or not tracks or "TYPE=SUBTITLES" in fetch_text(no_sub):
        return False
    primary = next((track for track in tracks if str(track["srclang"]).upper() == "ET"), tracks[0])
    original = fetch_text(primary["src"])
    offset = subtitle_offset(current_url, str(primary["srclang"]), original)
    files = []
    subtitles = []
    for track in tracks:
        code = str(track["srclang"]).upper()
        track_vtt = original if track is primary else fetch_text(track["src"])
        output = shift_vtt(track_vtt, offset)
        filename = f"{content_id}_{code}.vtt"
        files.append((SUBTITLES / filename, output))
        subtitles.append({"id": "err-" + code.lower(), "lang": LANGUAGE.get(code, code.lower()),
                          "url": BASE + filename})
    for target, output in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
    for path, payload in payloads:
        changed = False
        for row in payload.get("streams") or []:
            if row.get("url") == current_url:
                row["url"] = no_sub
                row["subtitles"] = subtitles
                changed = True
        if changed:
            path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                            encoding="utf-8")
    return True


def recent_ids(previous_revision: str | None) -> set[str]:
    try:
        revision = previous_revision or "HEAD~1"
        names = subprocess.check_output(["git", "diff", "--name-only", "--diff-filter=AM", revision,
                                         "HEAD", "--", "stream"], cwd=ROOT, text=True)
        names += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "stream"],
                                         cwd=ROOT, text=True)
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {match[1] for name in names.splitlines()
            if (match := STREAM_ID.fullmatch(Path(name).stem))}


def main() -> None:
    groups = stream_paths()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    forced = os.environ.get("ERR_SUBTITLE_CONTENT_ID", "").strip()
    batch = max(1, int(os.environ.get("ERR_SUBTITLE_BATCH_SIZE", "50")))
    pending = sorted((content_id for content_id, paths in groups.items() if needs_update(paths)), key=int)
    if forced:
        if forced not in groups:
            raise ValueError("Requested ERR content ID has no stream file")
        tasks = [forced]
    else:
        urgent = recent_ids(state.get("stream_head")) & set(pending)
        last = int(state.get("last_id") or 0)
        regular = [item for item in pending if int(item) > last] + [item for item in pending if int(item) <= last]
        tasks = list(dict.fromkeys(sorted(urgent, key=int, reverse=True) + regular))[:batch]
    print(f"ERR subtitle candidates={len(pending)} selected={len(tasks)}", flush=True)
    resolved = empty = errors = 0
    for content_id in tasks:
        try:
            if normalize(content_id, groups[content_id]):
                resolved += 1
            else:
                empty += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors += 1
            print(f"{content_id}: {exc}", flush=True)
    if not forced:
        state["last_id"] = tasks[-1] if tasks else state.get("last_id")
        state["stream_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    print(f"ERR subtitle results resolved={resolved} skipped={empty} errors={errors}", flush=True)
    if forced and not resolved:
        raise RuntimeError("Requested ERR subtitle track was not published")


if __name__ == "__main__":
    main()
