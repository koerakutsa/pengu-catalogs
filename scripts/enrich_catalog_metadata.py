#!/usr/bin/env python3
"""Fill missing catalog artwork/descriptions in bounded daily batches."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time

from generate_meta import DUO_API, DUO_SITE, ERR_API, http_json, parse_prefix_id
from metadata_fields import duo_fields, err_fields

ROOT = Path(__file__).resolve().parents[1]
CAT = ROOT / "catalog"
META = ROOT / "meta"
STATE = ROOT / "metadata-state.json"


def fetch_fields(key: str) -> dict:
    source, content_id = key.split(":", 1)
    if source == "duoplay":
        payload = http_json(f"{DUO_API}/catchup/{content_id}", referer=DUO_SITE + "/")
        return duo_fields(payload or {})
    payload = http_json(f"{ERR_API}?contentId={content_id}&rootId=3905&page=web")
    main = ((payload or {}).get("data") or {}).get("mainContent") or {}
    return err_fields(main)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=350, help="Maximum distinct upstream IDs to check")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")

    catalogs: dict[Path, dict] = {}
    entries: dict[str, list[tuple[Path, dict]]] = {}
    for path in sorted(CAT.glob("*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        catalogs[path] = payload
        for item in payload.get("metas") or []:
            prefix, content_id = parse_prefix_id(item.get("id", ""))
            if prefix and content_id:
                key = f"{'duoplay' if prefix == 'duoplay' else 'err'}:{content_id}"
                entries.setdefault(key, []).append((path, item))

    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    checked = {k: v for k, v in (state.get("checked") or {}).items() if k in entries}
    # Never-seen IDs are checked first, newest source ID first. Older IDs are
    # revisited in a round robin, so changed artwork can eventually refresh.
    selected = sorted(entries, key=lambda k: (checked.get(k, 0), -int(k.split(":", 1)[1])))[:args.limit]
    changed_catalogs: set[Path] = set()
    changed_meta = 0
    now = int(time.time())
    with ThreadPoolExecutor(max_workers=8) as executor:
        for key, fields in zip(selected, executor.map(fetch_fields, selected)):
            checked[key] = now
            if not fields:
                continue
            for path, item in entries[key]:
                missing = {name: value for name, value in fields.items() if value and not item.get(name)}
                if missing:
                    item.update(missing)
                    changed_catalogs.add(path)
                typ = item.get("type")
                meta_path = META / str(typ) / f"{item['id']}.json"
                if meta_path.exists():
                    payload = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta = payload.get("meta") or {}
                    missing = {name: value for name, value in fields.items() if value and not meta.get(name)}
                    if missing:
                        meta.update(missing)
                        payload["meta"] = meta
                        meta_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                        changed_meta += 1

    for path in changed_catalogs:
        path.write_text(json.dumps(catalogs[path], ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    STATE.write_text(json.dumps({"checked": checked}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Checked {len(selected)} source IDs; updated {len(changed_catalogs)} catalogs and {changed_meta} meta files")


if __name__ == "__main__":
    main()
