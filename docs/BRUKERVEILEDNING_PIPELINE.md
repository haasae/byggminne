# Brukerveiledning: Fra rådata til kunnskapsgraf

*Denne brukerveiledningen er ment for deg som skal kjøre applikasjonen. Det innebærer å bygge nye grafer eller regenerere
eksisterende. Forutsetter at du kan bruke en terminal. Hvordan du LESER
grafen, står i `BRUKERVEILEDNING_GRAF.md`.*

---

## 1. Hva applikasjonen gjør

Applikasjonen tar ustrukturerte målepunkt-navn fra byggets SD-anlegg
(f.eks. `360.001-RT401`) og gjør dem om til strukturerte, maskinlesbare
fakta. Disse blir til slutt en kunnskapsgraf per bygg i grafvisualiserings-programmet Neo4j.

```mermaid
graph LR
    CSV[Rå CSV-filer] --> EX[1 Trekk ut unike navn]
    EX --> DET[2 Deterministisk dekoding: regler + gjenfinning]
    DET -- hvis deterministisk ikke holder --> LLM[3 LLM-dekoding]
    DET --> OUT[Dekodede etiketter JSON]
    LLM --> OUT
    OUT --> BRICK[4 Brick-graf ttl per bygg]
    TS[Tidsserier] --> HEAT[5 Romvarme-fakta fra data]
    BRICK --> NEO[6 Neo4j kunnskapsgraf]
    HEAT --> NEO
```

For å gjøre prosessen billigst mulig prøver Python å dekode det den klarer gjennom regler og gjenfinning. Det som er igjen går til LLM-en (Claude i mitt tilfelle). Alt systemet
lærer, lagres i `knowledge_base/`. Fordi målet er at applikasjonen skal kunne brukes av andre, uavhengig av LLM, skal det ikke være gjennom prompter at systemet lærer.

## 2. Hva du må gi den

1. **CSV-filer med etiketter** i `data/raw/`. Etiketten må stå i første
   kolonne. Tidsserieverdier trengs *ikke* for dekoding, men det trengs for
   datakryssjekker og romvarme-analysen (paragraf 4).
2. **Kildetype** per datasett: `kiona`, `bacnet` eller `other` — den styrer
   hvilken grammatikk dekoderen prøver.
3. **Referansedokumentasjon** om merkesystemet ditt (tabeller, standarder,
   leverandørdokumenter): konverter til Markdown og legg under
   `knowledge_base/<navn>_dir/<navn>.md`. LLM-en leser Markdown, ikke PDF
   (`src/PDF-parser/` kan hjelpe med konverteringen).
4. **NS-standardene** (NS 3451, NS 3457-8) er opphavsrettsbeskyttet og
   følger ikke med. Dersom du har du dem, legg dem på plassene beskrevet i
   `README.md`. Alt virker uten dem, men dekodingen kan ikke sitere dem.

> **Windows/norske tegn:** kjør alltid med `PYTHONIOENCODING=utf-8`, og les
> alle filer som UTF-8. æ/ø/å i filINNHOLD er greit; filNAVN holdes ASCII.

Ingen byggdata følger med repoet. De innsjekkede eksempelbatchene
(`data/eval/batches/`) lar deg teste hele løypa uten egne data.

## 3. Fra CSV til dekodede etiketter

```bash
# 1. Trekk ut unike etiketter fra CSV-ene dine
python -m src.extract.unique_labels "data/raw/DINE-FILER*.csv" -o labels.txt

# 2. Bygg en dekoder-batch
python -m src.extract.build_batch labels.txt --source-type bacnet \
    -o data/eval/batches/MIN_BATCH/input.jsonl

# 3. Deterministisk dekoding (null LLM-kostnad)
python -m src.decode.deterministic_batch \
    --input data/eval/batches/MIN_BATCH/input.jsonl --out-dir runs/MIN_BATCH
```

Resultatet i `runs/MIN_BATCH/`: `outputs.jsonl` (dekodede etiketter),
`residue.jsonl` (det reglene ikke klarte) og `coverage.md` (les denne
først. Sier noe om hvor bra det gikk?).

**Resten til LLM-en:** *(Denne delen er per (31.07.26) bare testet med Claude. Forhåpentligvis kan man få til gode resultater med andre LLM'er også.)* 

Åpne prosjektet i Claude Code og kjør
`/decode`-ferdigheten på batchen. Den dekoder hver rest-etikett i en ny
agent (Dette sørger for at det ikke er noen "smitte" mellom etiketter) og legger resultatene til
`outputs.jsonl`. Tynne-men-gyldige dekoder kan berikes tilsvarende:

```bash
python -m src.decode.enrichment --outputs runs/MIN_BATCH/outputs.jsonl \
    --out-dir runs/MIN_BATCH_enrich          # velger kandidater
# ... kjør /enrich i Claude Code ...
python -m src.decode.merge_outputs \
    --deterministic runs/MIN_BATCH/outputs.jsonl \
    --llm runs/MIN_BATCH_enrich/outputs_llm.jsonl \
    --out runs/MIN_BATCH_enrich/outputs_enriched.jsonl
```

(Deterministiske ikke-null-felter vinner alltid ved fletting.)

**Feilsøke én etikett:**

```bash
python -m src.decode.try_label "360.001-RT401" --source-type bacnet
```

**Slik leser du en dekodet etikett:** hvert JSON-objekt har `confidence`
(0–1), `tier` (FULL/PARTIAL/NONE — hvor mye som ble fylt ut) og `reasoning`
(hvorfor, med kildehenvisninger til kunnskapsbasen). Ukjente felter er
`null`. Altså vil systemet aldri gjette. Detaljer: `docs/output_explainer.md` og
`schema/README.md` (tre gjennomarbeidede eksempler i `examples/`).

Har du et fasitsett (`tests/gold/<id>/gold.jsonl`), kjører én kommando hele
løypa med scoring: `python -m src.eval.run_eval --batch MIN_BATCH` — les
`summary.md` i run-mappa. Målemetodikken: `docs/EVALUATION.md`.

## 4. Fra dekodede etiketter til kunnskapsgraf

**Brick-graf** (én Turtle-fil per bygg):

```bash
python -m src.brick.emit_graph --outputs runs/MIN_BATCH/outputs.jsonl \
    --site mittbygg --out-dir runs/MIN_BATCH/graphs

# Rask visuell sjekk (Mermaid-diagram i Markdown):
python -m src.brick.graph_viz runs/MIN_BATCH/graphs/BYGG.ttl -o graf.md
```

**Romvarme-fakta fra tidsserier** (valgfritt, men det er dette som gir
energifleksibilitet): krever én CSV per sone/rom med kolonnene
`Timestamp,T_Actualvalue,T_Setvalue,T_Gain` under
`<rot>/Buildings/<BYGG>/Thermal zone/`. Kjeden:

```bash
python -m src.heating.build_zone_table --root <rot> --buildings <BYGG> \
    -o runs/heating/zone_table.jsonl --cache runs/heating/scan_cache.jsonl
python -m src.heating.gain_regime runs/heating/zone_table.jsonl \
    -o runs/heating/regimes.jsonl
python -m src.heating.step_response --root <rot> --buildings <BYGG>
python -m src.heating.heating_type runs/heating/regimes.jsonl \
    runs/heating/step_summary.jsonl -o runs/heating/heating_types.jsonl
```

Design og metodikk: `docs/ROOM_HEATING_PLAN.md`. Terskler kan justeres i
`knowledge_base/heating_rules.json`.

**Inn i Neo4j:**

```bash
python -m src.heating.neo4j_export --index-dir <indeksmappe> \
    --runs-dir <run-mappe> -o runs/heating/import.cypher
python -m src.heating.neo4j_import --cypher runs/heating/import.cypher
```

Import krever at Neo4j kjører lokalt (`bolt://127.0.0.1:7687`) og at
passordet ligger i miljøvariabelen `NEO4J_PASSWORD` eller i en `.env`-fil.
Indeksmappa inneholder én JSON per bygg med den håndkuraterte
strukturen (bygg, etasjer, rom, systemer, proveniens). Formatet er
dokumentert i docstringen til `src/heating/neo4j_export.py`, og
`knowledge_base/school_index/` (lokal) er malen.

## 5. Vedlikehold og læring

Systemet blir bedre ved å **samle kunnskap i `knowledge_base/`**, aldri
ved at LLM-en «husker» fra tidligere sessions. Validerte dekoder legges i
`validated_decodes.jsonl` (kun etter menneskelig godkjenning via
`python -m src.profile.promote --approve`), nye regler i
`deterministic_rules.json`. Nye runs beviser at forbedringene
generaliserer — regelen og begrunnelsen står i `docs/EVALUATION.md`.

## 6. Feilsøking

| Symptom | Se |
|---|---|
| Stor `residue.jsonl` (reglene klarer lite) | `docs/tokenizer_failure_modes.md` — kjente hull og policy |
| æ/ø/å blir til rare tegn | UTF-8: `PYTHONIOENCODING=utf-8`, les filer som UTF-8 |
| `neo4j_import` får «connection refused» | Start Neo4j Desktop først |
| Dekoderen setter `null` der du vet svaret | Riktig oppførsel: aldri gjette. Legg kunnskapen i `knowledge_base/`, kjør på nytt |
| Alt annet | `python -m pytest -q` skal være grønn. Er den ikke det, er noe galt lokalt |

