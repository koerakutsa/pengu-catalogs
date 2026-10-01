#!/usr/bin/env python3
"""Publish static Stremio stream JSON for Nuvio Android TV (custom IDs).

Batch + resume: only missing IDs, STREAM_BATCH_SIZE per run, no hard fail.
"""
from __future__ import annotations

import concurrent.futures
from bisect import bisect_right
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "meta"
STREAM = ROOT / "stream"
STATE = ROOT / "stream-state.json"

ERR_API = "https://services.err.ee/api/v2/vodContent/getContentPageData"
DUO_SITE = "https://duoplay.ee"
UA = "Mozilla/5.0 (compatible; PenguCatalogs/2.0)"
ID_RE = re.compile(r"^(duoplay|err|err-archive|lasteekraan):(\d+)(?::(?:ep:)?(\d+))?$", re.I)
M3U_RE = re.compile(r"https?://router\.euddn\.net[^\s\"'<>]+?\.m3u8(?:\?[^\s\"'<>]*)?")


def request(url: str, referer: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": referer,
            "Accept": "application/json,text/html,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


@lru_cache(maxsize=50000)
def err_stream(content_id: str) -> dict | None:
    url = ERR_API + "?" + urllib.parse.urlencode(
        {"contentId": content_id, "rootId": 3905, "page": "web"}
    )
    payload = json.loads(request(url, "https://jupiter.err.ee/"))
    main = (payload.get("data") or {}).get("mainContent") or {}
    for media in main.get("medias") or []:
        if (media.get("restrictions") or {}).get("drm"):
            continue
        src = media.get("src") or {}
        raw = src.get("hlsNew") or src.get("hls2") or src.get("hls") or src.get("file")
        if not isinstance(raw, str) or not raw:
            continue
        playable = ("https:" + raw) if raw.startswith("//") else raw
        if not playable.startswith("https://"):
            continue
        return {
            "name": "ERR",
            "title": str(main.get("heading") or "ERR") + " · HLS",
            "url": playable,
            "behaviorHints": {
                "notWebReady": False,
                "proxyHeaders": {
                    "request": {
                        "Referer": "https://jupiter.err.ee/",
                        "Origin": "https://jupiter.err.ee",
                    }
                },
            },
        }
    return None


def duo_stream(content_id: str, episode_id: str | None) -> dict | None:
    path = f"/{content_id}"
    if episode_id:
        path += f"?ep={urllib.parse.quote(episode_id)}"
    page = html.unescape(request(DUO_SITE + path, DUO_SITE + "/")).replace("\\/", "/")
    found = M3U_RE.search(page)
    if not found:
        return None
    return {
        "name": "DuoPlay",
        "title": "DuoPlay · HLS",
        "url": found.group(0),
        "behaviorHints": {
            "notWebReady": True,
            "proxyHeaders": {
                "request": {
                    "Referer": DUO_SITE + "/",
                    "Origin": DUO_SITE,
                    "User-Agent": UA,
                }
            },
        },
    }


def source_stream(identifier: str) -> dict | None:
    match = ID_RE.fullmatch(identifier)
    if not match:
        return None
    prefix, content_id, episode_id = match.groups()
    if prefix.lower() == "duoplay":
        return duo_stream(content_id, episode_id)
    return err_stream(content_id)


def collect_ids() -> dict[str, set[str]]:
    ids: dict[str, set[str]] = {"movie": set(), "series": set()}
    for typ in ids:
        folder = META / typ
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            if path.name.startswith("."):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            meta = payload.get("meta") or {}
            mid = str(meta.get("id") or "")
            if ID_RE.fullmatch(mid):
                ids[typ].add(mid)
            if typ == "series":
                for video in meta.get("videos") or []:
                    identifier = str(video.get("id") or "")
                    if ID_RE.fullmatch(identifier):
                        ids[typ].add(identifier)
    return ids


def existing_streams() -> tuple[set[tuple[str, str]], dict[str, dict]]:
    """Keep published streams untouched and reuse ERR aliases."""
    out: set[tuple[str, str]] = set()
    err_by_content: dict[str, dict] = {}
    for typ in ("movie", "series"):
        folder = STREAM / typ
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            identifier = path.stem
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                streams = payload.get("streams") or []
                if not streams or not isinstance(streams[0].get("url"), str):
                    continue
                out.add((typ, identifier))
                match = ID_RE.fullmatch(identifier)
                if match and match.group(1).lower() != "duoplay":
                    err_by_content.setdefault(match.group(2), payload)
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    return out, err_by_content


def render_one(task: tuple[str, str]) -> tuple[str, str, dict | None, str | None]:
    typ, identifier = task
    try:
        return typ, identifier, source_stream(identifier), None
    except Exception as exc:
        return typ, identifier, None, str(exc)


def main() -> None:
    batch = max(1, int(os.environ.get("STREAM_BATCH_SIZE", "4000")))
    workers = min(12, max(1, int(os.environ.get("STREAM_WORKERS", "6"))))
    prefer = os.environ.get("STREAM_PREFER", "duoplay,err")
    priorities = [part.strip() for part in prefer.split(",") if part.strip()]

    ids = collect_ids()
    wanted = {(typ, identifier) for typ, values in ids.items() for identifier in values}
    if not wanted:
        raise ValueError("No catalog stream IDs found")
    have, err_by_content = existing_streams()
    # A content ID is shared by Jupiter, ERR Arhiiv and sometimes Lasteekraan.
    # Copy the already resolved response instead of querying ERR once per alias.
    reused = 0
    for typ, identifier in sorted(wanted - have):
        match = ID_RE.fullmatch(identifier)
        if not match or match.group(1).lower() == "duoplay":
            continue
        payload = err_by_content.get(match.group(2))
        if payload is None:
            continue
        target = STREAM / typ / f"{identifier}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        have.add((typ, identifier))
        reused += 1
    # Removed catalog entries disappear from catalog/meta, while previously
    # published playable links remain available by their direct stream IDs.
    have &= wanted
    all_tasks: list[tuple[str, str]] = []
    for typ, values in ids.items():
        for identifier in values:
            if (typ, identifier) not in have:
                all_tasks.append((typ, identifier))

    def sort_key(item: tuple[str, str]) -> tuple[int, str, str]:
        typ, ident = item
        rank = 99
        for i, p in enumerate(priorities):
            if ident.startswith(p) or (
                p == "err" and ident.startswith(("err:", "err-archive:", "lasteekraan:"))
            ):
                rank = i
                break
        return (rank, ident, typ)

    all_tasks.sort(key=sort_key)
    total_missing = len(all_tasks)
    previous = {}
    if STATE.exists():
        try:
            previous = json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    last_key = previous.get("last_key") if previous.get("prefer") == prefer else None
    keys = [sort_key(task) for task in all_tasks]
    start = bisect_right(keys, tuple(last_key)) if isinstance(last_key, list) and len(last_key) == 3 else 0
    if start >= total_missing:
        start = 0
    tasks = (all_tasks[start:] + all_tasks[:start])[:batch]
    print(
        f"Stream IDs total targets={sum(len(v) for v in ids.values())} "
        f"existing={len(have)} aliases_reused={reused} missing={total_missing} "
        f"this_batch={len(tasks)} workers={workers} offset={start}",
        flush=True,
    )
    if not tasks:
        print("Nothing missing — streams complete", flush=True)
        STATE.write_text(
            json.dumps(
                {
                    "complete": True,
                    "existing": len(have),
                    "missing": 0,
                    "prefer": prefer,
                    "ts": int(time.time()),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return

    (STREAM / "movie").mkdir(parents=True, exist_ok=True)
    (STREAM / "series").mkdir(parents=True, exist_ok=True)

    resolved = 0
    empty = 0
    failed: list[str] = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for typ, identifier, stream, error in executor.map(render_one, tasks):
            target = STREAM / typ / f"{identifier}.json"
            if error:
                failed.append(f"{identifier}: {error}")
                continue
            if stream:
                target.write_text(
                    json.dumps({"streams": [stream]}, ensure_ascii=False, separators=(",", ":"))
                    + "\n",
                    encoding="utf-8",
                )
                resolved += 1
            else:
                empty += 1
                if os.environ.get("STREAM_MARK_EMPTY", "0") == "1":
                    target.write_text(
                        json.dumps({"streams": []}, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )

    elapsed = time.time() - t0
    still_missing = total_missing - resolved
    print(
        f"Batch done resolved={resolved} empty={empty} errors={len(failed)} "
        f"in {elapsed:.1f}s rate={resolved / max(elapsed, 0.1):.1f}/s "
        f"remaining≈{still_missing}",
        flush=True,
    )
    if failed:
        print("Sample errors:", flush=True)
        print("\n".join(failed[:15]), flush=True)

    STATE.write_text(
        json.dumps(
            {
                "complete": still_missing <= 0 and empty == 0,
                "existing": len(have) + resolved,
                "missing": max(0, still_missing),
                "batch_resolved": resolved,
                "batch_empty": empty,
                "batch_errors": len(failed),
                "last_key": list(sort_key(tasks[-1])),
                "prefer": prefer,
                "ts": int(time.time()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("OK (partial progress is fine; re-run to continue)", flush=True)


if __name__ == "__main__":
    main()
