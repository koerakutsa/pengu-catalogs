# Pengu Eesti Kataloogid

Staatiline Stremio/Nuvio **catalog-only** addon. Ei vaja Vercelit ega serverit.

## Install (Nuvio)

**Addons** (mitte Plugins) → lisa:

```
https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/manifest.json
```

või jsDelivr:

```
https://cdn.jsdelivr.net/gh/koerakutsa/pengu-catalogs@main/manifest.json
```

## Streamid

Kataloogid annavad ainult nimekirjad. Streamid tulevad **Nuvio pluginatest**:

```
https://raw.githubusercontent.com/koerakutsa/pengu-nuvio-plugins/main/manifest.json
```

## Kataloogid

| ID | Sisu |
|----|------|
| duoplay | DuoPlay filmid + sarjad |
| jupiter | ERR Jupiter filmid + sarjad |
| err-archive | ERR Arhiiv (sama VOD inventuur, teine id-prefix) |
| lasteekraan | Lasteekraan filmid + sarjad |

## Uuendamine

Kataloogifailid genereeritakse API dumpist. Esimene dump: vaata `catalog-summary.json`.
