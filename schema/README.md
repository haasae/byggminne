# `decoded_label.schema.json` — the decoded-label output contract

This directory holds the project's **output contract**: the JSON Schema that every
decoded building-measurement label must conform to. This README is the
human-readable companion to that schema (JSON can't carry comments), so if you
change the schema, update this file too.

- **Schema file:** `decoded_label.schema.json`
- **Dialect:** JSON Schema Draft 2020-12
- **Validated by:** `src/validate/schema_validator.py`
- **Worked examples:** `examples/` (clean Kiona, derived Kiona cost, redacted BACnet)
- **Project context:** `CLAUDE.md` §5 (output contract), `docs/EVALUATION.md` (scoring)

---

## 1. What it is and why it exists

`byggminne` turns unstructured, mostly-Norwegian measurement labels (column
headers / point names from building data systems) into structured JSON. **Every
decoded label becomes exactly one instance of this schema, validated before it is
stored or used.**

The schema is the **single source of truth for the *shape* of a decoded label**.
It is deliberately source-agnostic — it must hold a clean Kiona meter reading, a
heavily-redacted BACnet point, and everything in between — so nothing here is
specific to one building, vendor, or municipality.

Because the whole pipeline reads and writes this one shape, any layer can be run
independently against any other layer's output:

- **Produced by:** the rules engine, retrieval, the deterministic batch driver,
  the `/decode` and `/enrich` skills (LLM), and the merge step.
- **Consumed by:** the schema validator, the scoring harness, the data
  cross-check layer, and the Brick graph emitter.

---

## 2. The two rules that govern the whole schema

**a. `additionalProperties: false` — no invented fields.**
The root object *and* every nested object (`primary_system`, `location`,
`data_checks`, `relationships[]`) forbid extra keys. A decoder may emit only the
keys defined here. This is the contract that lets the scorer and the graph
emitter trust the data's shape.

**b. Partial decoding is valid — only four fields are required.**
Just `raw_label`, `source_type`, `confidence`, and `validated` are mandatory.
**Everything else is nullable.** An unknown field must be `null`, never a guess.
"Fjernvarme energy, building unknown" (with appropriate confidence) is a good
answer; inventing a building to fill the slot is not. Degrade gracefully.

Two supporting conventions:

- **Enum vs. free text is deliberate.** Closed, gradeable vocabularies
  (`carrier`, `measurement_type`, `object_type`, `source_type`) are enums so the
  scorer can compare them exactly and the model can't drift. Open Norwegian
  vocabularies (`function`, `unit`, `subsystem`, `component`) are free text.
- **Cite your sources.** When a field rests on a knowledge-base / NS entry, the
  decoder names the source (file + row) in `reasoning`. Never invent a meaning
  for an unknown code.

---

## 3. Property reference

### Required — identity & trust (always present)

| Property | Type | Meaning |
|---|---|---|
| `raw_label` | string | The original label, **verbatim**. The join key across the entire pipeline (scoring, cross-checks, graph all match on it) and the traceability anchor. Never altered. |
| `source_type` | enum: `kiona`, `bacnet`, `other` | Which data universe the label came from. *Given*, not decoded; gates source-specific logic (e.g. `object_type` only applies to `bacnet`). |
| `confidence` | number, 0–1 | Calibrated overall confidence in the decode. Required because a decode you can't trust-rank is unusable — it drives human-review routing. |
| `validated` | boolean | `true` **only** after a human confirms the decode. The line between "the machine thinks so" and "we know so"; only validated rows accumulate into the knowledge base. |

### Semantic core — *what the point measures*

| Property | Type | Allowed values / notes |
|---|---|---|
| `carrier` | enum or null | `el`, `fjernvarme`, `kjoling`, `gass`, `vann`, `annet`, `null`. Energy/medium carrier, inferred from keywords or codes. |
| `function` | string or null | Free-text role: `temperatur`, `settpunkt`, `status`, `kommando`, `energimaaling`, `utgang`, `inngang`, … Open vocabulary → free text. |
| `measurement_type` | enum or null | `energi`, `effekt`, `temperatur`, `volum`, `trykk`, `kostnad`, `co2`, `status`, `kommando`, `annet`, `null`. What quantity is represented. |
| `unit` | string or null | e.g. `kWh`, `°C`, `NOK`, `kg`, `m3`. Often absent from the label; inferred from data or docs. |
| `object_type` | enum or null | BACnet object type: `AV`, `BV`, `MV`, `AI`, `AO`, `BI`, `BO`, `MI`, `MO`, `null`. **AV-as-binary trap:** verify against the value distribution, never trust the type alone. |

### Structural placement — *where the point sits in the building's systems*

| Property | Type | Notes |
|---|---|---|
| `primary_system` | object or null | NS 3451 system. Object of `{ code, description }`; `code` is **required within it** (the mappable part) and is **always the 4-digit form on output** (resolve legacy `320` → `3200`). `description` is the human-readable meaning. |
| `subsystem` | string or null | Subsystem code/description: `NNN.NNN`, or undernummer meaning (tur/retur, tilluft/avtrekk). Free text. |
| `component` | string or null | NS 3457-8 component: a 2-letter code usually with a 3-digit number (e.g. `RT401`), or a description. Its leading letters are extracted downstream for Brick equipment typing. |
| `location` | object or null | `{ building, zone }`. `null` when nothing about location is known; otherwise **both members are required** (each may itself be `null`), which forces an explicit "zone unknown" rather than a missing key — a consistent shape the graph relies on. |

### Nature

| Property | Type | Meaning |
|---|---|---|
| `is_derived` | boolean or null | `true` for a computed/virtual series (e.g. a cost built from price components), `false` for a measured quantity, `null` when undeterminable. Keeps a virtual point from being modeled as physical hardware in the graph. |

### Justification & data verification

| Property | Type | Meaning |
|---|---|---|
| `reasoning` | string or null | Short justification (with KB citations) so mistakes are traceable. Excluded from scoring — it's prose. |
| `data_checks` | object or null | Results of testing the name-hypothesis against the actual measurements (CLAUDE.md §4, "name = hypothesis, data = test"). Members: `temp_correlation` (number/null), `distinct_values` (integer/null), `monotonic` (boolean/null), `conflict` (boolean/null — `true` when the data contradicts the name). |

### Graph edges

| Property | Type | Meaning |
|---|---|---|
| `relationships` | array | Links to other points. Each item is `{ type, target_raw_label }` — e.g. `type` = `same_system` / `aggregate_of` / `feeds`, `target_raw_label` = the related point's `raw_label`. Empty until the relationship layer fills it. Becomes the **edges** of the knowledge graph. |

### Provenance (optional)

| Property | Type | Meaning |
|---|---|---|
| `decode_method` | enum or null | Which layer produced this instance: `rules`, `retrieval`, `rules+retrieval`, `llm`, `rules+llm`, `retrieval+llm`, `rules+retrieval+llm`, `human`, `null`. `+llm` = a deterministic decode whose null fields were filled by LLM enrichment. |
| `decoded_kb_version` | string or null | The context-pack hash (`kb_version`) in force when the decode was produced, so a metric change can be traced to a specific KB state. |

---

## 4. How the properties feed the Brick knowledge graph

The graph emitter (`src/brick/emit_graph.py`) never invents anything — it can
only build what these fields carry. So each property is the raw material for a
specific part of the graph, and the graph-readiness metrics
(`src/brick/readiness_report.py`) map almost 1:1 onto them:

| Graph-readiness metric | Fed by | Produces in Brick |
|---|---|---|
| **typed** (point class beyond `brick:Point`) | `measurement_type` + `function` + `component` letters | the point's Brick class (`temperatur` → `Temperature_Sensor`, `co2` → `CO2_Sensor`) |
| **system** | `primary_system.code` | a system node (`32xx` → a heating class) + `isPointOf` / `hasPoint` |
| **building** | `location.building` | which per-building graph the point lands in (no building → floats to `<site>_site.ttl`) |
| **equipment** | `component` letters + structural tokens in `raw_label` | equipment nodes + `isPointOf` anchoring |
| **unit** | `unit` | `brick:hasUnit` → a QUDT IRI |
| **edges** | `relationships[]` | `isPointOf`, `hasPart`, (later) `feeds` |

**A field left `null` is a missing node or edge — not a cosmetic gap.** This is
why "which properties we resolve" and "how complete a graph we can build" are the
same thing measured two ways.

Three property choices specifically protect graph *correctness*:

- **`object_type` + `data_checks`** guard the AV-as-binary trap — a 2-valued `AV`
  is really binary status, not an analog sensor, so `data_checks.conflict` catches
  a mistyping before it becomes a triple.
- **`is_derived`** keeps a computed cost series from being modeled as a physical
  meter.
- **`primary_system.code` forced to 4-digit** matches the Brick mapping, which
  keys on the NS prefix (`32`, `36`, `37`…) — normalizing `320` → `3200` at the
  schema boundary means the mapping never misses on a legacy 3-digit form.

Finally, the trust fields gate what is even allowed into the graph loop: the
graph-readiness definition includes a confidence floor, and only `validated`
decodes accumulate — so the schema is also the quality gate, not just a shape.

---

## 5. Validating an instance

```bash
# validate a single JSON instance
python -m src.validate.schema_validator --file path/to/instance.json

# validate every line of a JSONL file
python -m src.validate.schema_validator --jsonl runs/<id>/outputs.jsonl

# validate the worked examples in examples/
python -m src.validate.validate_examples
```

The validator uses `jsonschema` (Draft 2020-12) and reports `(location, message)`
for every violation. Decoders validate their output against this schema before
storage; the scoring harness reports a schema-validity rate.

---

## 6. Example instance

A partially-decoded BACnet temperature point (unknown fields left `null`, not
guessed):

```json
{
  "raw_label": "A1-P1-APP1:20053401-OU001/FCB.Local Application.-RT401.#1",
  "source_type": "bacnet",
  "carrier": null,
  "function": "temperatur",
  "measurement_type": "temperatur",
  "unit": null,
  "object_type": null,
  "primary_system": null,
  "subsystem": "tur",
  "component": "RT401 (RT = Temperaturgiver)",
  "location": { "building": "20053401", "zone": null },
  "is_derived": false,
  "confidence": 0.55,
  "reasoning": "component code RT = Temperaturgiver (komponentkodeliste.md); first digit 4 -> tur (side convention, data_observations.md)",
  "data_checks": null,
  "relationships": [],
  "validated": false,
  "decode_method": "rules",
  "decoded_kb_version": "88d05314a103"
}
```

Note the four required fields are all present, `location` carries both members
(with `zone` explicitly `null`), and every genuinely-unknown field is `null`
rather than invented.

---

## 7. Gotchas & conventions

- **`raw_label` is sacred.** It is the join key everywhere; the scorer flags any
  decoder that alters it ("near-miss keys").
- **`relationships` is an array, never `null`.** Use `[]` when there are no links.
- **`location` is all-or-nothing at the object level, explicit at the member
  level.** Either the whole object is `null`, or it exists with both `building`
  and `zone` present (each possibly `null`).
- **`validated: true` is a human act.** No automated step may set it.
- **Don't trust `object_type` alone.** A legacy `AV` can be semantically binary —
  confirm against the value distribution.
