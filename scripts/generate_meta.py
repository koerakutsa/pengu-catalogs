#!/usr/bin/env python3
"""Generate meta/{type}/{id}.json from catalog + live episode lists."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "catalog"
META = ROOT / "meta"

UA = "PenguCatalogsMeta/1.2"
ERR_API = "https://services.err.ee/api/v2/vodContent/getContentPageData"
DUO_SITE = "https://duoplay.ee"


def http_json(url: str, referer: str = "https://jupiter.err.ee/") -> dict | None:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": UA,
            "Referer": referer,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            return json.loads(res.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"  json fail {url}: {e}")
        return None


def http_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": "Mozilla/5.0 (compatible; PenguCatalogs/1.2)",
            "Referer": DUO_SITE + "/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  text fail {url}: {e}")
        return ""


def to_base_meta(item: dict, typ: str) -> dict:
    m = {
        "id": item["id"],
        "type": typ,
        "name": item.get("name") or item.get("title") or "Untitled",
    }
    for k in (
        "poster",
        "background",
        "logo",
        "description",
        "releaseInfo",
        "imdbRating",
        "runtime",
        "genres",
        "director",
        "cast",
        "country",
        "language",
    ):
        if item.get(k):
            m[k] = item[k]
    return m


def parse_prefix_id(full_id: str) -> tuple[str, str]:
    m = re.match(r"^(duoplay|err-archive|lasteekraan|err):(\d+)", full_id or "", re.I)
    if not m:
        return "", ""
    return m.group(1).lower(), m.group(2)


def err_videos(prefix: str, content_id: str) -> list[dict]:
    url = f"{ERR_API}?contentId={content_id}&rootId=3905&page=web"
    j = http_json(url)
    if not j:
        return []
    videos: list[dict] = []
    seasons = ((j.get("data") or {}).get("seasonList") or {}).get("items") or []
    season_num = 0
    for s in seasons:
        season_num += 1
        groups = s.get("items") if s.get("items") else [s]
        ep_num = 0
        for g in groups:
            for c in g.get("contents") or []:
                ep_num += 1
                cid = c.get("id")
                if not cid:
                    continue
                sid = int(c["season"]) if c.get("season") not in (None, 0, "0") else season_num
                eid = int(c["episode"]) if c.get("episode") not in (None, 0, "0") else ep_num
                released = None
                if c.get("publicStart"):
                    try:
                        released = time.strftime("%Y-%m-%d", time.gmtime(int(c["publicStart"])))
                    except Exception:
                        released = None
                v = {
                    "id": f"{prefix}:{cid}",
                    "title": c.get("heading") or c.get("name") or f"S{sid}E{eid}",
                    "season": sid,
                    "episode": eid,
                }
                if released:
                    v["released"] = released
                thumb = None
                photos = c.get("photos") or c.get("photo") or {}
                if isinstance(photos, dict):
                    thumb = photos.get("photoUrl") or photos.get("url")
                elif isinstance(photos, list) and photos:
                    thumb = photos[0].get("photoUrl") if isinstance(photos[0], dict) else None
                if thumb:
                    v["thumbnail"] = thumb if str(thumb).startswith("http") else f"https:{thumb}"
                videos.append(v)
    if not videos:
        main = (j.get("data") or {}).get("mainContent") or {}
        if main.get("medias") or main.get("heading"):
            videos.append(
                {
                    "id": f"{prefix}:{content_id}",
                    "title": main.get("heading") or "Episode 1",
                    "season": 1,
                    "episode": 1,
                }
            )
    # de-dupe by id, keep order
    seen = set()
    out = []
    for v in videos:
        if v["id"] in seen:
            continue
        seen.add(v["id"])
        out.append(v)
    return out


def duoplay_has_ep(telecast_id: str, ep: int) -> bool:
    html = http_text(f"{DUO_SITE}/{telecast_id}?ep={ep}")
    return "router.euddn.net" in html


def duoplay_max_ep(telecast_id: str) -> int:
    """Exponential + binary search for last playable ?ep=N."""
    if not duoplay_has_ep(telecast_id, 1):
        return 0
    hi = 1
    while hi < 256 and duoplay_has_ep(telecast_id, hi):
        hi *= 2
        time.sleep(0.05)
    lo = hi // 2
    best = lo
    while lo <= hi:
        mid = (lo + hi) // 2
        if mid == 0:
            break
        if duoplay_has_ep(telecast_id, mid):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
        time.sleep(0.05)
    return best


def duoplay_videos(telecast_id: str) -> list[dict]:
    n = duoplay_max_ep(telecast_id)
    if n <= 0:
        return []
    videos = []
    for ep in range(1, n + 1):
        videos.append(
            {
                "id": f"duoplay:{telecast_id}:ep:{ep}",
                "title": f"Osa {ep}",
                "season": 1,
                "episode": ep,
            }
        )
    return videos


def enrich_series(meta: dict) -> dict:
    prefix, num = parse_prefix_id(meta["id"])
    if not prefix or not num:
        return meta
    videos: list[dict] = []
    if prefix in ("err", "err-archive", "lasteekraan"):
        print(f"  ERR episodes {meta['id']}...")
        videos = err_videos(prefix, num)
        time.sleep(0.08)
    elif prefix == "duoplay":
        print(f"  DuoPlay episodes {meta['id']}...")
        videos = duoplay_videos(num)
        time.sleep(0.1)
    if videos:
        meta["videos"] = videos
        # help clients that expect behaviorHints
        meta.setdefault("behaviorHints", {})
    return meta


def main() -> None:
    n_files = 0
    n_with_videos = 0
    for typ in ("movie", "series"):
        (META / typ).mkdir(parents=True, exist_ok=True)
        for path in sorted((CAT / typ).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("metas") or []:
                mid = item.get("id")
                if not mid:
                    continue
                meta = to_base_meta(item, typ)
                if typ == "series":
                    meta = enrich_series(meta)
                    if meta.get("videos"):
                        n_with_videos += 1
                out = META / typ / f"{mid}.json"
                out.write_text(
                    json.dumps({"meta": meta}, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                n_files += 1
    print(f"Wrote {n_files} meta files ({n_with_videos} series with videos)")


if __name__ == "__main__":
    main()
