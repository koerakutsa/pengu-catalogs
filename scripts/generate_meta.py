#!/usr/bin/env python3
"""Generate meta/{type}/{id}.json from catalog/{type}/*.json"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "catalog"
META = ROOT / "meta"


def to_meta(item, typ):
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
        "videos",
    ):
        if item.get(k):
            m[k] = item[k]
    return {"meta": m}


def main():
    n = 0
    for typ in ("movie", "series"):
        (META / typ).mkdir(parents=True, exist_ok=True)
        for path in sorted((CAT / typ).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("metas") or []:
                mid = item.get("id")
                if not mid:
                    continue
                out = META / typ / f"{mid}.json"
                out.write_text(
                    json.dumps(to_meta(item, typ), ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
                n += 1
    print(f"Wrote {n} meta files")


if __name__ == "__main__":
    main()
