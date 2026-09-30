# Pengu Eesti Kataloogid

GitHubis hostitud Stremio/Nuvio addon Eesti filmidele ja sarjadele. Addon annab
`catalog`, `meta` ja `stream` vastused. Nuvio Android TV ei käivita kohalikke
JavaScript-pluginaid `duoplay:`, `err:` või `lasteekraan:` ID-de jaoks, seega
annab voolingid sama addon otse.

## Install (Nuvio)

**Addons** (mitte Plugins) → lisa:

```
https://raw.githubusercontent.com/koerakutsa/pengu-catalogs/main/manifest.json
```

Kui addon oli juba paigaldatud, värskenda või paigalda see uuesti, et Nuvio
loeks manifesti uue `stream` ressursi. Mobiilse Nuvio pluginad võivad jääda
alles muude kataloogide jaoks, kuid Eesti kataloogid ei vaja neid.

## Streamid

Addon annab voolingid aadressilt `stream/{movie|series}/{id}.json`.

## Kataloogid

| ID | Sisu |
|----|------|
| duoplay | DuoPlay filmid + sarjad |
| jupiter | ERR Jupiter filmid + sarjad |
| err-archive | ERR Arhiiv (sama VOD inventuur, teine id-prefix) |
| lasteekraan | Lasteekraan filmid + sarjad |

## Uuendamine

`.github/workflows/refresh-catalogs.yml` käivitub iga päev kell 03:25 UTC ja
käsitsi GitHubi Actionsi lehel. See loeb lähte-API-de inventuuri, uuendab
episoodide metaandmed ja voolingid ning lisab või eemaldab failid vastavalt
saadaolevale sisule. Suure ootamatu kataloogikahanemise või voogude päringuvea
korral töö katkeb ega avalda poolikut uuendust.

DuoPlay HLS-aadressid võivad allika poolel päeva jooksul muutuda. GitHub
Actionsi viimase töö tulemus näitab, kas päevane värskendus õnnestus.
