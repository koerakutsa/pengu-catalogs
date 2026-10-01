#!/usr/bin/env python3
"""Build four-character, search-only catalog responses in resumable batches.

GitHub Raw cannot answer arbitrary searches. Nuvio requests the literal path
catalog/{type}/eesti-otsing/search={query}.json, so only the generated four
character keys have results. Normal catalog files remain unchanged.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
STATE = ROOT / "search-index-state.json"
SEARCH_ID = "eesti-otsing"
SOURCES = ("duoplay", "jupiter", "lasteekraan")
TYPES = ("movie", "series")


def search_keys(title: str) -> set[str]:
    # Count letters and digits, not spaces or punctuation in a title.
    first = "".join(char for char in title.strip() if char.isalnum())[:4]
    if len(first) != 4:
        return set()
    lower = first.lower()
    candidates = {first, lower, lower[:1].upper() + lower[1:], first.upper()}
    return {candidate for candidate in candidates if len(candidate) == 4}


def preview(item: dict, typ: str) -> dict:
    result = {"id": str(item["id"]), "type": typ, "name": str(item["name"])}
    for key in ("poster", "background", "releaseInfo"):
        if item.get(key):
            result[key] = item[key]
    return result


def desired_files() -> dict[str, bytes]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    for typ in TYPES:
        for source in SOURCES:
            path = CATALOG / typ / f"{source}.json"
            metas = json.loads(path.read_text(encoding="utf-8")).get("metas")
            if not isinstance(metas, list):
                raise ValueError(f"Invalid catalog: {path}")
            for item in metas:
                if not item.get("id") or not item.get("name"):
                    continue
                row = preview(item, typ)
                for query in search_keys(row["name"]):
                    key = (typ, query)
                    if row["id"] not in seen[key]:
                        grouped[key].append(row)
                        seen[key].add(row["id"])
    if len(grouped) < 500:
        raise ValueError("Search index unexpectedly small; refusing to delete files")
    output = {}
    for (typ, query), rows in grouped.items():
        rows.sort(key=lambda row: (row["name"].casefold(), row["id"]))
        path = f"catalog/{typ}/{SEARCH_ID}/search={query}.json"
        output[path] = (json.dumps({"metas": rows}, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    return output


def main() -> None:
    if os.name == "nt":
        raise RuntimeError("Case-sensitive search files must be written on Linux")
    batch_size = max(1, int(os.environ.get("SEARCH_BATCH_SIZE", "2000")))
    wanted = desired_files()
    existing = {
        path.relative_to(ROOT).as_posix()
        for typ in TYPES
        for path in (CATALOG / typ / SEARCH_ID).glob("search=*.json")
    }
    changes = sorted(
        path for path, data in wanted.items() if not (ROOT / path).exists() or (ROOT / path).read_bytes() != data
    )
    stale = sorted(existing - wanted.keys())
    tasks = [(path, wanted[path]) for path in changes] + [(path, None) for path in stale]
    tasks.sort(key=lambda task: task[0])
    selected = tasks[:batch_size]
    written = removed = 0
    for relative_path, data in selected:
        path = ROOT / relative_path
        if data is None:
            path.unlink()
            removed += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            written += 1
    state = {
        "complete": len(selected) == len(tasks),
        "wanted": len(wanted),
        "pending": len(tasks) - len(selected),
        "batch_written": written,
        "batch_removed": removed,
        "last_key": selected[-1][0] if selected else None,
        "ts": int(time.time()),
    }
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
