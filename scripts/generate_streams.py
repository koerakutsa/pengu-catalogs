#!/usr/bin/env python3
"""Publish Stremio stream responses for custom IDs used by Nuvio Android TV.

Nuvio TV does not invoke local JS plugins for duoplay:/err:/lasteekraan:
IDs. These JSON files make the GitHub-hosted catalog addon a stream addon too.
"""
from __future__ import annotations

import concurrent.futures
import html
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "meta"
STREAM = ROOT / "stream"
ERR_API = "https://services.err.ee/api/v2/vodContent/getContentPageData"
DUO_SITE = "https://duoplay.ee"
UA = "Mozilla/5.0 (compatible; PenguCatalogs/2.0)"
ID_RE = re.compile(r"^(duoplay|err|err-archive|lasteekraan):(\d+)(?::(?:ep:)?(\d+))?$", re.I)


def request(url: str, referer: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept": "application/json,text/html"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def source_stream(identifier: str) -> dict | None:
    match = ID_RE.fullmatch(identifier)
    if not match:
        return None
    prefix, content_id, episode_id = match.groups()
    if prefix == "duoplay":
        path = f"/{content_id}" + (f"?ep={urllib.parse.quote(episode_id)}" if episode_id else "")
        page = html.unescape(request(DUO_SITE + path, DUO_SITE + "/")).replace("\\/", "/")
        # The site embeds its playable router URL in HTML attributes / JSON.
        pattern = r"https?://router\.euddn\.net[^\s\"'<>]+?\.m3u8(?:\?[^\s\"'<>]*)?"
        found = re.search(pattern, page)
        if not found:
            return None
        url = found.group(0)
        headers = {"Referer": DUO_SITE + "/", "Origin": DUO_SITE, "User-Agent": UA}
        return {"name": "DuoPlay", "title": "DuoPlay · HLS", "url": url,
                "behaviorHints": {"notWebReady": True, "proxyHeaders": {"request": headers}}}

    url = ERR_API + "?" + urllib.parse.urlencode({"contentId": content_id, "rootId": 3905, "page": "web"})
    payload = json.loads(request(url, "https://jupiter.err.ee/"))
    main = (payload.get("data") or {}).get("mainContent") or {}
    for media in main.get("medias") or []:
        if (media.get("restrictions") or {}).get("drm"):
            continue
        src = media.get("src") or {}
        raw = src.get("hlsNew") or src.get("hls2") or src.get("hls") or src.get("file")
        if not isinstance(raw, str) or not raw:
            continue
        playable = "https:" + raw if raw.startswith("//") else raw
        if not playable.startswith("https://"):
            continue
        headers = {"Referer": "https://jupiter.err.ee/", "Origin": "https://jupiter.err.ee"}
        return {"name": "ERR", "title": str(main.get("heading") or "ERR") + " · HLS",
                "url": playable,
                "behaviorHints": {"notWebReady": False, "proxyHeaders": {"request": headers}}}
    return None


def collect_ids() -> dict[str, set[str]]:
    ids = {"movie": set(), "series": set()}
    for typ in ids:
        for path in (META / typ).glob("*.json"):
            if path.name.startswith("."):
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            meta = payload.get("meta") or {}
            if ID_RE.fullmatch(str(meta.get("id") or "")):
                ids[typ].add(meta["id"])
            if typ == "series":
                for video in meta.get("videos") or []:
                    identifier = str(video.get("id") or "")
                    if ID_RE.fullmatch(identifier):
                        ids[typ].add(identifier)
    return ids


def render_one(task: tuple[str, str]) -> tuple[str, str, dict | None, str | None]:
    typ, identifier = task
    try:
        return typ, identifier, source_stream(identifier), None
    except Exception as exc:
        return typ, identifier, None, str(exc)


def main() -> None:
    ids = collect_ids()
    tasks = [(typ, identifier) for typ, values in ids.items() for identifier in sorted(values)]
    if not tasks:
        raise ValueError("No catalog IDs found")
    print(f"Resolving {len(tasks)} unique movie/series/episode IDs", flush=True)
    expected: dict[str, set[str]] = {typ: set() for typ in ids}
    failed: list[str] = []
    resolved = 0
    workers = min(24, max(1, int(os.environ.get("STREAM_WORKERS", "16"))))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for typ, identifier, stream, error in executor.map(render_one, tasks):
            target = STREAM / typ / f"{identifier}.json"
            if error:
                failed.append(f"{identifier}: {error}")
                if target.exists():
                    expected[typ].add(target.name)
                continue
            if stream:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({"streams": [stream]}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
                expected[typ].add(target.name)
                resolved += 1
            elif target.exists():
                # Keep the prior response if the source is temporarily empty.
                expected[typ].add(target.name)
    for typ in ids:
        for path in (STREAM / typ).glob("*.json"):
            if path.name not in expected[typ]:
                path.unlink()
    print(f"Resolved {resolved}/{len(tasks)} stream IDs; request errors={len(failed)}", flush=True)
    if failed:
        print("\n".join(failed[:20]))
    if failed or resolved < max(1, int(len(tasks) * 0.5)):
        raise RuntimeError("Stream inventory incomplete; no catalog update should be committed")


if __name__ == "__main__":
    main()
