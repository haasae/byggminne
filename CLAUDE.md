# CLAUDE.md

Project memory for Claude Code — the map: what the project is, where things live,
and the rules for decoding. The full label-grammar reference (§4) is a candidate
to move into the `decode` skill once built; load it only when decoding.

---

## 1. What this project is

**label-decoder** turns unstructured building-energy measurement labels into a
structured, machine-readable format. A "label" is a column header or point name
from a building's data system — an unstructured (mostly Norwegian) string
encoding building, system, subsystem, component, and measurement type.

It is **source-agnostic**: it must handle many different building
systems. Never hardcode anything specific to one building, vendor, or municipality.

**This round's goal (stay narrow):** get the unstructured data we have now into a **structured format** — nothing more. At this time, decoding works by interpreting names (a human *and* Claude-as-machine). The goal is to include  cross-referencing of the measurement data over time to confirm what makes sense. **Update (2026-07): the first Brick slice is now in scope** (user asked): `src/brick/` emits one Turtle graph per building from decoded outputs, driven by `knowledge_base/brick_mapping.json`; the `graph_readiness` report defines "decoded well enough for the graph". Live operation stays out of scope.

---

## 2. Architecture (layered)

Five layers:
1. **Extract** (`src/extract/`) — read a dataset, pull out unique labels only. No measurement values needed.
2. **Decode** (`src/decode/`) — turn each label into a structured object,
   cheapest-first:
   - deterministic **rules** (well-formed labels) — IMPLEMENTED: `rules_engine.py`
     over `kb_lookup.py` + `knowledge_base/deterministic_rules.json`
   - **retrieval** against the knowledge base (seen a similar label?) —
     IMPLEMENTED: `retrieval.py` over `knowledge_base/validated_decodes.jsonl`
     (exact + structural-sibling inheritance; observation fields transfer only on
     exact point-name match — the RT401 trap)
   - **LLM fallback** — only labels the cheaper layers can't resolve reach it;
     `deterministic_batch.py` runs rules+retrieval and emits `residue.jsonl`
   - **LLM enrichment** — thin-but-passing decodes: `enrichment.py` selects one
     representative per structural family (gaps a graph needs), the `/enrich`
     skill decodes them cold-start, `merge_outputs.py` fills nulls only
     (deterministic non-null always wins; conflicts logged, never overwritten)
   - **human validation** for uncertain cases — `src/profile/promote.py`
     nominates data-confirmed LLM decodes; only a human `--approve` appends to
     the validated store
   - Some method for validation/confidence metric may be implemented here as well 
3. **Knowledge base** (`knowledge_base/`) — grows over time: raw/normalized
   labels, abbreviations, synonyms, NS/Brick mappings, prior classifications,
   confidence scores, human corrections. The system improves by **accumulating
   here**, NOT by the LLM "learning" from prompts.
4. **Connect / operate** (later) — values join to already-decoded labels by ID,
   locally, with no AI.
5. **Parse** (`src/PDF-parser/`) – an attempt to parse PDF's. May be developed further later. Not main focus as of now

---

## 3. Label grammar (decode reference)

> Essentials and traps below. Full code enumerations should move to the `decode`
> skill / knowledge base — keep this section lean.

**Norwegian keywords (most reliable signal):** `varme`=heating · `kjøling`=cooling
· `ventilasjon`=air handling · `lys`/`strøm`=electrical ·
`tappevann`/`bereder`=domestic hot water · `utganger`=outputs · `innganger`=inputs
· `fjernvarme`=district heating · `børverdi`=setpoint · `alarm`=alarm.

**NS 3451:2022 system codes (4-digit):** `3100` sanitary, `3200` heating, `3600`
air handling, `3700` cooling, `4320/4330/4340` electrical distribution, `4420`
lighting. Oslobygg's Merkesystem forbids rounded overordnede codes (`3100`,
`3500`, … — see the Merkesystem reference); codes seen in the wild may be older /
non-standard and need LLM interpretation.

**Pilot's 3-digit codes** (the pilot's `ns2bricks.json` used the **first 3 digits**
of the NS code): `320` heating, `360` air, `370` cooling, `432/433/434`
electrical. **Known bug:** `310` was mapped to "domestic hot water," but NS `31xx`
= **sanitary** (cold + hot + drainage); the hot-water meaning came from the *text*
("Varmt tappevann"), not the code. **Lesson: the code alone is insufficient —
semantics often live in the text and must be confirmed by data.**

**Sub-codes / components:** `NNN.NNN` (e.g. `434.003`) = subsystem.
Heating/cooling undernummer: `.04`=tur (supply), `.05`=retur (return). Air
handling (36) undernummer: `.01` inntak, `.02` avkast, `.03` by-pass, `.04`
tilluft, `.05` fraluft/avtrekk, `.06` omluft, `.07` overstrømning, `.08`
spesialavtrekk. NS 3457-8 **component codes** = a **2-letter** function code
(`RT`, `RD`, `SB`, `LR`, `OU`, `IK`, …), usually with a 3-digit number (`RT401`);
look them up in `komponentkodeliste.md` — they are lookup codes, not
letter-by-letter. In that number the **first digit encodes side** (`4`=tur/
tilluft supply, `5`=retur/fraluft return; documented across the R/S/M/J families).
A **16-digit number** = a main electric meter. Full BACnet/SD path grammar and
the legacy 3-digit→4-digit output rule live in `knowledge_base/decode_rules.md`
and `knowledge_base/bacnet_sd_label_grammar.md`.

**BACnet object types:** `AV`→sensor/setpoint, `BV`→status/command, `MV`→enumerated
state (1-based); plus `AI/AO/BI/BO` (physical I/O) and `MI/MO`. **AV-as-binary
trap:** some legacy AV objects only ever hold `0`/`1` — semantically binary,
mislabeled analog. **Always check the value distribution; never trust the object
type alone.** Path syntax is vendor-specific, not NS-standardized — split on
`: / . - _`, and apply NS codes/components only to fragments that actually match
the standard.

---

## 4. Cross-check rules (name = hypothesis, data = test)

> Implemented in `src/profile/`: `series_stats.py` (streaming per-label
> statistics), `cross_check.py` (binary/range/dead-point/monotonic/file-kind
> checks), `seasonal_check.py` (monthly profiles + Pearson vs a reference; found
> the in-data outdoor sensor), `relationship_check.py` (same_system/controller/
> equipment groups + directional and tur/retur and co-behavior verification).
> Confirmed findings accumulate in `knowledge_base/data_observations.md`.

Every name-based guess makes a testable prediction. Use these to auto-flag guesses
the data contradicts — this catches confident mistakes, the model's *and* the
human's:

- **Heating** → correlates **negatively** with outdoor temperature.
- **Cooling** → correlates **positively** with outdoor temperature.
- **Binary / status** → exactly **2** distinct values (many values ⇒ analog; see
  the AV trap).
- **Energy (cumulative meter)** → monotonically increasing / always positive.
- **Hot water (`tappevann`)** → morning/evening peaks; a different daily/weekly
  signature from temperature-driven space heating.
- **Data contradicts the name** → flag it; don't silently trust the name.

A guess that survives both the name reading and the data cross-check earns high
confidence; a guess in conflict goes to human validation.

---

## 5. Output contract

Every decoded label → one instance of `schema/decoded_label.schema.json`,
validated before storage:

- Always include `raw_label` and `source_type` — traceability is mandatory.
- Always include a **calibrated `confidence`** and a short **`reasoning`** string.
- **Partial decoding is valid.** Unknown fields are `null`; degrade gracefully
  rather than guess. "Fjernvarme energy, building unknown" with appropriate
  confidence is a good answer.
- When a field rests on a knowledge-base / NS entry, **cite the source** (file +
  row) in `reasoning`. **Never invent a meaning for an unknown code** — leave it
  `null` with low confidence and flag it.

See `examples/` for three worked instances (clean Kiona, derived Kiona cost,
heavily redacted BACnet point).

---

## 6. Lessons from the pilot (do not repeat)

- No regex-only fragility — always combine rules + retrieval + LLM + validation
  (§2).
- Persist validation data and corrections; build the feedback loop so the
  knowledge base actually accumulates.

> Global working rules (ASCII identifiers, UTF-8 / Windows encoding, no hardcoded
> paths, keep tests, real third-party deps only) live in `~/.claude/CLAUDE.md`.
> Labels and CSVs are Norwegian (æ/ø/å), so UTF-8 reading matters everywhere here.

---

## 7. Running

```bash
python -m venv .venv && source .venv/bin/activate    # optional
pip install -r requirements.txt
```

Real deps (pinned in `requirements.txt`): jsonschema, pytest, rdflib (Brick
graphs); pymupdf only for `src/PDF-parser/`. pandas/numpy/statsmodels et al.
get added only if the cross-check layer ever needs them (it streams with the
stdlib today).

---

## 8. Repository layout & where to find things

```
label-decoder/
├── CLAUDE.md                      # this file (the map)
├── README.md
├── requirements.txt
├── .gitignore
├── schema/
│   └── decoded_label.schema.json  # the output contract
├── data/
│   ├── raw/                       # real building CSVs (non-confidential)
│   ├── synthetic/                 # structure-true invented examples
│   └── training/                  # excerpts from real data meant for training
├── knowledge_base/                # validated mappings + NS/TFM reference (below)
├── src/
│   ├── extract/                   # Layer 1: pull labels out of a dataset
│   ├── decode/                    # Layer 2: rules + retrieval + enrichment + LLM merge
│   ├── profile/                   # data profiling + cross-checks + promote (store nomination)
│   ├── brick/                     # Brick mapping lookups, graph emitter, readiness report
│   ├── eval/                      # one-command decode->score->summary driver
│   └── validate/                  # schema validation
└── examples/                      # worked schema instances
(later)
```

## 9. Procedure once you have labels to decode

**Access `knowledge_base`. Here are several folders that contain markdown-files, and sometimes pictures, with info that may help you decode the label. When resolving code, cite the file + row you use! The markdown-files are created from the PDFs in `docs/`. You should never read the PDFs – unless I specifically ask you to – as this takes too much time and resources!**
- `knowledge_base/komponentkodeliste_dir/komponentkodeliste.md` — NS 3457-8 component letters/codes → meaning. 
- `knowledge_base/bacnet_sd_label_grammar.md` — positional grammar for BACnet/SD labels (main node / controller number / undersentral / bus / application field / component code / tag) + glossary (WSP, IK, `+-`).
- `knowledge_base/control_number_area_map.md` — auto-generated controller-number → area lookup (regenerate with `python -m src.extract.control_number_map`).
- `knowledge_base/data_observations.md` — data-confirmed label facts from the §4 cross-checks (outdoor-temp reference, confirmed decodes, open flags).
- `knowledge_base/deterministic_rules.json` — curated machine rules (keywords, suffixes, component-letter→measurement, side digits) for the rules engine.
- `knowledge_base/validated_decodes.jsonl` — accumulating store of validated decodings; the retrieval layer inherits from it (exact > sibling).
- `knowledge_base/brick_mapping.json` — NS codes / decoded fields → Brick classes (cited per entry; unknown → generic class, never invent).
- `knowledge_base/brick_dir/brick_classes.txt` — official Brick 1.4 class list (test-enforced against the mapping; regenerate with `python -m src.brick.build_class_list`).
(add abbreviations / synonyms files as they are built)
- `knowledge_base/NS-3451_dir/NS-3451.md` – National Standard 3451 (**local only** — copyrighted, gitignored; the context pack degrades to a stub without it)
- `knowledge_base/NS-3457_dir/NS-3457.md` – National Standard 3457 (**local only** — copyrighted, gitignored; same degradation)
- `knowledge_base/TFM_systemkodeliste_dir/TFM_systemkodeliste.md` — NS 3451 system codes → meaning.

## 10. Future goals

The project is ever-developing, so details can change underways. However, the main goals is and will always be the follwing:

**The goal is to make an application that can take in unstructured building data in .csv-files and structure the data to make sense to both humans and machines. The data we will work with is in `data/raw`. From earlier pilots, we have discovered that this is only possible with LLMs. For this reason, the first part of the pipeline will look like this:**

1. Input = Unstructured data
2. Deterministic parsing does its best to structure the label based on some database of known label format
3. If the deterministic parsing did not do good enough, we use an LLM to decode what the deterministic parsing did not manage to decode alone. LLM uses mainly the knowledge base to do this
4. Now that our labels are decoded, we translate them into Brick Schema, which is further used to create a knowledge graph. There should be one knowledge graph for each area (either each building, room, or something else). The knowledge graph will identify relationships between sensors, meters and systems in the building/area. 
5. The knowledge graphs will be used in a dashboard for operating personnel to use on a daily basis. Note that integrating this application with the dashboard is not my task, and I should not worry about it. I also do not need to worry about integrating live-data input. Only the .csv-files already in the project are used.


## 11. Reporting back

After completing any task, give a plain-language summary (no code, no jargon)
covering:
- What now works, in simple terms
- What I must do manually to finish it (config, keys, file moves, decisions)
- What remains undone from the plan, if anything