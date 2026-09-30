#!/usr/bin/env python3
"""Refresh the eight published catalogs from DuoPlay and ERR inventories."""
from __future__ import annotations

import json
import concurrent.futures
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
ERR = "https://services.err.ee"
DUO = "https://tigu.kanal2.ee/duoplay/ee/et"
SLUGS = ("vaata-ja-kuula", "filmid", "sarjad", "multikad", "lastesaated", "animafilmid", "lastefilmid")


def get_json(url: str, referer: str = "https://jupiter.err.ee/") -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 PenguCatalogs/2.0", "Referer": referer})
    with urllib.request.urlopen(request, timeout=35) as response:
        return json.load(response)


def pages(url: str, key: str, referer: str) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 100):
        query = urllib.parse.urlencode({"page": page, "limit": 100})
        payload = get_json(f"{url}?{query}", referer)
        batch = payload.get(key)
        if not isinstance(batch, list):
            raise ValueError(f"Invalid page response: {url} page={page}")
        rows.extend(batch)
        if page >= int(payload.get("last_page") or 1):
            return rows
    raise ValueError(f"Page limit reached: {url}")


def err_pages(kind: str) -> list[dict]:
    rows: list[dict] = []
    for page in range(1, 150):
        options = {"page": page, "limit": 100, "offset": (page - 1) * 100,
                   "category": 3905, "phrase": "", "types": ["media"],
                   "searchTypes": ["video"], "viewTypes": [kind], "now": 0, "order": 1}
        query = urllib.parse.urlencode({"type": "video", "options": json.dumps(options, separators=(",", ":"))})
        payload = get_json(f"{ERR}/api/search/getVodContents2/?{query}")
        batch = (payload.get("video") or {}).get("contents")
        if not isinstance(batch, list):
            raise ValueError(f"Invalid ERR {kind} page={page}")
        rows.extend(item for item in batch if item.get("type") == kind)
        if len(batch) < 100:
            return rows
    raise ValueError(f"ERR {kind} page limit reached")


def photo(item: dict, key: str) -> str | None:
    photos = item.get(key) or []
    if isinstance(photos, list) and photos:
        first = photos[0]
        return first.get("photoUrlOriginal") or first.get("photoUrlBase")
    return None


def err_meta(item: dict, typ: str, prefix: str) -> dict:
    poster = photo(item, "verticalPhotos") or photo(item, "photos")
    backdrop = photo(item, "horizontalPhotos") or photo(item, "photos") or poster
    meta = {"id": f"{prefix}:{item['id']}", "type": typ,
            "name": str(item.get("heading") or item.get("name") or "ERR").strip()}
    if poster:
        meta["poster"] = poster
    if backdrop:
        meta["background"] = backdrop
    if item.get("lead"):
        meta["description"] = str(item["lead"])
    category = item.get("primaryCategory") or {}
    if category.get("name"):
        meta["genres"] = [category["name"]]
    return meta


def duo_meta(item: dict, typ: str) -> dict:
    poster = item.get("image") or (item.get("images") or {}).get("510x774")
    backdrop = (item.get("images") or {}).get("1440x645") or poster
    meta = {"id": f"duoplay:{item['id']}", "type": typ,
            "name": str(item.get("title") or "DuoPlay").strip()}
    for key, value in (("poster", poster), ("background", backdrop)):
        if value:
            meta[key] = "https:" + value if str(value).startswith("//") else value
    return meta


def dedupe(rows: list[dict]) -> list[dict]:
    return list({item["id"]: item for item in rows if item.get("id")}.values())


def load_lasteekraan() -> dict[str, list[dict]]:
    found: dict[str, dict] = {}
    valid_pages = 0
    for slug in SLUGS:
        url = f"{ERR}/api/v2/category/getByUrl?" + urllib.parse.urlencode({"url": slug, "domain": "lasteekraan.err.ee", "page": "web"})
        category = (get_json(url, "https://lasteekraan.err.ee/").get("data") or {}).get("category") or {}
        blocks = category.get("frontPage") or []
        if blocks:
            valid_pages += 1
        for block in blocks:
            for item in block.get("data") or []:
                kind = item.get("type")
                if kind not in ("movie", "series", "show", "episode"):
                    continue
                content_id = item.get("rootContentId") if kind == "episode" else item.get("id")
                if not content_id:
                    continue
                existing = found.get(str(content_id))
                if existing and existing.get("type") != "episode" and kind == "episode":
                    continue
                found[str(content_id)] = {**item, "id": content_id}
    if not valid_pages or len(found) < 100:
        raise ValueError("Lasteekraan returned an incomplete inventory")
    result = {"movie": [], "series": []}
    for item in found.values():
        typ = "movie" if item.get("type") == "movie" else "series"
        result[typ].append(err_meta(item, typ, "lasteekraan"))
    # Category front pages are a curated window, not the complete inventory.
    # Keep older entries while the ERR content API still exposes playable media.
    for typ in result:
        old_path = CATALOG / typ / "lasteekraan.json"
        if not old_path.exists():
            continue
        old = json.loads(old_path.read_text(encoding="utf-8")).get("metas") or []
        current_ids = {item["id"] for item in result[typ]}
        missing = [item for item in old if item.get("id") not in current_ids]

        def available(item: dict) -> bool:
            content_id = str(item["id"]).split(":")[-1]
            query = urllib.parse.urlencode({"contentId": content_id, "rootId": 3905, "page": "web"})
            data = (get_json(f"{ERR}/api/v2/vodContent/getContentPageData?{query}").get("data") or {})
            main = data.get("mainContent") or {}
            seasons = (data.get("seasonList") or {}).get("items") or []
            return bool(main.get("medias") or seasons)

        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
            for item, keep in zip(missing, executor.map(available, missing)):
                if keep:
                    result[typ].append(item)
    return result


def write_catalog(typ: str, source: str, metas: list[dict]) -> int:
    path = CATALOG / typ / f"{source}.json"
    previous = json.loads(path.read_text(encoding="utf-8"))["metas"] if path.exists() else []
    # A temporary API truncation must not wipe most of the published catalog.
    if len(metas) < max(1, int(len(previous) * 0.65)):
        raise ValueError(f"{source}/{typ} shrank from {len(previous)} to {len(metas)}")
    if len({item["id"] for item in metas}) != len(metas):
        raise ValueError(f"Duplicate IDs in {source}/{typ}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"metas": metas}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return len(metas)


def main() -> None:
    duo_all = dedupe(pages(f"{DUO}/telecasts", "data", "https://duoplay.ee/"))
    duo_movies = dedupe(pages(f"{DUO}/telecasts/movies", "data", "https://duoplay.ee/"))
    movie_ids = {str(item["id"]) for item in duo_movies}
    duo_series = [item for item in duo_all if str(item["id"]) not in movie_ids]
    err_movies = dedupe(err_pages("movie"))
    err_series = dedupe(err_pages("series"))
    kids = load_lasteekraan()
    results = {}
    for typ, source, metas in (
        ("movie", "duoplay", [duo_meta(x, "movie") for x in duo_movies]),
        ("series", "duoplay", [duo_meta(x, "series") for x in duo_series]),
        ("movie", "jupiter", [err_meta(x, "movie", "err") for x in err_movies]),
        ("series", "jupiter", [err_meta(x, "series", "err") for x in err_series]),
        ("movie", "err-archive", [err_meta(x, "movie", "err-archive") for x in err_movies]),
        ("series", "err-archive", [err_meta(x, "series", "err-archive") for x in err_series]),
        ("movie", "lasteekraan", kids["movie"]),
        ("series", "lasteekraan", kids["series"]),
    ):
        results[f"{typ}/{source}"] = write_catalog(typ, source, metas)
    (ROOT / "catalog-summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
