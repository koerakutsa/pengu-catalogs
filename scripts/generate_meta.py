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

UA = "PenguCatalogsMeta/1.3"
ERR_API = "https://services.err.ee/api/v2/vodContent/getContentPageData"
DUO_API = "https://tigu.kanal2.ee/duoplay/ee/et"
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
            "User-Agent": "Mozilla/5.0 (compatible; PenguCatalogs/1.3)",
            "Referer": DUO_SITE + "/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return res.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  text fail {url}: {e}")
        return ""


def extract_m3u(html: str) -> str:
    marker = "router.euddn.net"
    at = html.find(marker)
    if at < 0:
        return ""
    start = html.rfind("http", 0, at)
    if start < 0:
        return ""
    end = html.find(".m3u8", at)
    if end < 0:
        return ""
    return html[start : end + 5]


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
        # ERR nests months under items, or puts episodes in contents
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
    seen: set[str] = set()
    out: list[dict] = []
    for v in videos:
        if v["id"] in seen:
            continue
        seen.add(v["id"])
        out.append(v)
    return out


def duoplay_unique_max(telecast_id: str, limit: int = 50) -> int:
    """Sequential probe: stop after 3 identical m3u8 URLs in a row."""
    last_url = ""
    same = 0
    last_unique = 0
    for ep in range(1, limit + 1):
        html = http_text(f"{DUO_SITE}/{telecast_id}?ep={ep}")
        url = extract_m3u(html)
        if not url:
            break
        if url != last_url:
            last_unique = ep
            last_url = url
            same = 0
        else:
            same += 1
            if same >= 3 and last_unique > 0:
                break
        time.sleep(0.04)
    return last_unique or (1 if last_url else 0)


def duoplay_videos(telecast_id: str) -> list[dict]:
    """Prefer catchup seasons list; fall back to unique-stream probe."""
    j = http_json(f"{DUO_API}/catchup/{telecast_id}", referer=DUO_SITE + "/")
    videos: list[dict] = []
    seasons = (j or {}).get("seasons") or []
    if seasons:
        for s in seasons:
            snum = int(s.get("number") or 0)
            if snum <= 0:
                snum = 1
            ep_ord = 0
            for e in s.get("episodes") or []:
                eid = e.get("episode_id")
                if eid is None:
                    continue
                eid = int(eid)
                ep_ord += 1
                # Prefer real episode_nr when sane, else ordinal within season
                enr = e.get("episode_nr")
                try:
                    enr_i = int(enr) if enr is not None else ep_ord
                except Exception:
                    enr_i = ep_ord
                # Cap display episode to something sensible if episode_id is global counter
                if enr_i > 10000:
                    enr_i = ep_ord
                title = (
                    e.get("display_title")
                    or e.get("subtitle")
                    or (f"Osa {enr_i}" if enr_i else f"Osa {eid}")
                )
                videos.append(
                    {
                        "id": f"duoplay:{telecast_id}:ep:{eid}",
                        "title": str(title).strip() or f"Osa {eid}",
                        "season": snum,
                        "episode": enr_i if enr_i > 0 else ep_ord,
                    }
                )
        if videos:
            return videos

    # No seasons list — probe unique streams (Angry Birds etc.)
    max_ep = duoplay_unique_max(telecast_id, 60)
    if max_ep <= 0:
        max_ep = 1
    for ep in range(1, max_ep + 1):
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
        time.sleep(0.06)
    elif prefix == "duoplay":
        print(f"  DuoPlay episodes {meta['id']}...")
        videos = duoplay_videos(num)
        time.sleep(0.08)
    if videos:
        meta["videos"] = videos
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
