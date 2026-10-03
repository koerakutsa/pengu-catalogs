#!/usr/bin/env python3
"""Remove playback headers and HLS variants that fail on Nuvio Android TV."""
from __future__ import annotations

import json

from generate_streams import STREAM

OLD_TV_PLAYLISTS = "https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/playlists/"


def normalize(payload: dict) -> tuple[dict, bool]:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return payload, False
    changed = False
    kept = []
    for stream in streams:
        if not isinstance(stream, dict):
            kept.append(stream)
            continue
        url = stream.get("url") or ""
        if isinstance(url, str) and url.startswith(OLD_TV_PLAYLISTS):
            changed = True
            continue
        if isinstance(url, str) and url.startswith("https://router.euddn.net/"):
            request_headers = ((stream.get("behaviorHints") or {}).get("proxyHeaders") or {}).get("request")
            if isinstance(request_headers, dict):
                for key in list(request_headers):
                    if key.lower() == "origin":
                        del request_headers[key]
                        changed = True
        kept.append(stream)
    if changed:
        payload["streams"] = kept
    return payload, changed


def main() -> None:
    updated = 0
    for typ in ("movie", "series"):
        for path in (STREAM / typ).glob("duoplay:*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload, changed = normalize(payload)
                if changed:
                    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
                    updated += 1
            except (OSError, ValueError, TypeError):
                continue
    print(f"Normalized DuoPlay stream files: {updated}", flush=True)


if __name__ == "__main__":
    main()
