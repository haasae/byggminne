# Rådata fra bygg legges her

Denne mappen er for rå kildemateriale fra byggene: skjermbilder fra
SD-anlegget, eksportfiler, crawl-data. **Alt innhold holdes automatisk
utenfor git** — byggdata skal aldri inn i det offentlige repoet; kun denne
README-en er delt.

Struktur: først SD-system, så én mappe per bygg:

```
knowledge_base/incoming/
├── <sd-system>/            f.eks. metasys/, piscada/
│   └── pics/
│       ├── <bygg1>/        f.eks. skoyen/
│       └── <bygg2>/
```

Regler (fra kartleggingsveiledningen — se rot-README, avsnittet «Surveying
the building», og `docs/OPPLAERING_NYTT_BYGG.md` kap. 4.2):

- Gi filene navn etter faktumet de beviser (`varmeanlegg-320007-zoom1.png`,
  `rom-D101-trippel.png`) — ikke `skjermbilde-14.png`.
- Bruk små bokstaver uten æ/ø/å i mappe- og filnavn (`skoyen`, ikke `Skøyen`).
- Et zoomet, lesbart navn slår pen innramming.

*Raw building material (BMS screenshots, exports, crawl data) goes here,
grouped `<bms>/pics/<building>/`. Everything in this folder is gitignored —
only this README is shared.*
