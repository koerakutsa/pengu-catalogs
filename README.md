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
ERR-i DRM-kaitsega kirjetele annab addon valiku **„ava ERR-is (DRM)”**.
Nuvio Android TV avab selle ERR-i ametlikul lehel välises brauseris; see ei ole
Nuvio mängijas esitatav voog. Vaatamine sõltub ERR-i õigustest, asukohast ja
seadme brauseri toest. Kirjed, millele ERR ei anna üldse meediat, võivad jääda
voovalikuta. Olemasolevaid mängitavaid voofaile uuendused ei kustuta.

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
katalooge ja episoodide metaandmeid. Kataloogist kadunud kirjed eemaldatakse;
suure ootamatu kahanemise korral töö katkeb ega avalda poolikut kataloogi.

`.github/workflows/generate-streams.yml` käivitub iga päev kell 05:15 UTC ja
ka käsitsi. See lisab ainult puuduvad otse mängitavad vood ja ERR-i ametlikud
DRM-lehe lingid. Päringuvead ei kustuta juba avaldatud vastuseid.

DuoPlay HLS-aadressid võivad allika poolel muutuda. GitHub Actionsi viimase
töö tulemus näitab, kas päevane värskendus õnnestus.
