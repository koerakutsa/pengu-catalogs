# Meta failide üleslaadimine

Manifest v1.1.0 juba kuulutab `meta` resource'i.

## Kiirtest

Juba üles: `meta/movie/duoplay:8577.json` (Beirut).

1. Nuvio → eemalda kataloogi addon → installi uuesti:
   `https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/manifest.json`
2. Ava **DuoPlay Filmid → Beirut** — peab avanema detail (mitte "no addon provides meta").
3. Streamid tulevad pluginatest (DuoPlay / ERR / DebugPing).

## Kõik ~7700 meta faili

Projektis: `pengu-catalogs-with-meta.zip` (~3.3 MB)

### Desktop / laptop (soovitatav)
```bash
git clone https://github.com/koerakutsa/pengu-catalogs.git
cd pengu-catalogs
unzip -o /path/to/pengu-catalogs-with-meta.zip
git add meta catalog manifest.json
git commit -m "feat: full static meta dump"
git push
```

### Mobiil
Ava `meta/movie/` või `meta/series/` → **Upload files** → vali zipist vastavad `.json` failid (nimed peavad olema täpselt `duoplay:123.json` jne).

Kaustad `meta/movie/` ja `meta/series/` on juba olemas.
