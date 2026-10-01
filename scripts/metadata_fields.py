"""Normalize artwork and descriptions returned by ERR and DuoPlay."""
from __future__ import annotations

import html
import re


def description(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()[:2000]


def image_url(value: object, sizes: tuple[str, ...] = ()) -> str:
    if isinstance(value, list):
        return image_url(value[0], sizes) if value else ""
    if isinstance(value, dict):
        types = value.get("photoTypes") or {}
        if not isinstance(types, dict):
            types = {}
        for size in sizes:
            if isinstance(types.get(size), dict) and types[size].get("url"):
                return image_url(types[size]["url"])
            if value.get(size):
                return image_url(value[size])
        for key in ("photoUrlOriginal", "photoUrlBase", "original", "url"):
            if value.get(key):
                return image_url(value[key])
        return ""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    return value if value.startswith(("https://", "http://")) else ""


def err_photo(item: dict, keys: tuple[str, ...], sizes: tuple[str, ...]) -> str:
    for key in keys:
        url = image_url(item.get(key), sizes)
        if url:
            return url
    return ""


def err_fields(item: dict) -> dict:
    poster = err_photo(item, ("verticalPhotos", "photos", "horizontalPhotos"), ("80", "47", "34"))
    background = err_photo(item, ("horizontalPhotos", "heroImage", "photos"), ("48", "2", "61", "34"))
    summary = description(item.get("lead") or item.get("body") or item.get("subHeading"))
    return {key: value for key, value in (("poster", poster), ("background", background), ("description", summary)) if value}


def err_episode_thumbnail(item: dict) -> str:
    return err_photo(item, ("horizontalPhotos", "photos", "heroImage"), ("48", "61", "34", "2"))


def duo_fields(item: dict) -> dict:
    images = item.get("images") or {}
    portrait = images.get("510x774") if isinstance(images, dict) else None
    poster = image_url(portrait) or image_url(item.get("image")) or image_url(images, ("original",))
    background = image_url(images, ("1440x645", "1200x630", "original")) or poster
    summary = description(item.get("synopsis") or item.get("description"))
    return {key: value for key, value in (("poster", poster), ("background", background), ("description", summary)) if value}
