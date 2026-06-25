# CLAUDE.md

Guidance for Claude Code when working in this repository. Read this fully at the
start of every session — it is the project's memory between sessions, since the
model itself remembers nothing.

---

## 1. What this project is

**label-decoder** takes unstructured building-energy measurement labels and
decodes them into a structured, machine-readable format. A "label" is a column
header or point name from a building's data system — an unstructured string
(mostly Norwegian) that encodes building, system, subsystem, component, and
measurement type.

The project is **source-agnostic and replicable**: it must handle data from many
different building systems and be reusable beyond any single customer. Do not
hardcode anything specific to one building, vendor, or municipality.

### This round's goal (narrow — stay focused)

Take the unstructured data we have now and get it into a **structured format**.
That is the only objective right now. Decoding happens by interpreting names
(both a human reading them and Claude as a machine) **plus** cross-referencing
the measurement data over time to find patterns and confirm what makes sense.

Downstream goals (Brick knowledge graph, live operation) are out of scope for
now. Do not build toward them yet unless explicitly asked.

> **Status note:** This reflects current status, which has changed several times
> (data sensitivity, whether Claude may see the data, tooling). Treat it as a
> living document. External advisers will refine our understanding of the data —
> update this file when that happens.

---

## 2. Architecture (layered, model-agnostic)

Four conceptual layers. The LLM is a **swappable component**, not a hardcoded
dependency — this keeps the system replicable to stricter environments.

1. **Extract** (`src/extract/`) — read a dataset, pull out only the unique
   labels. No measurement values needed for this step.
2. **Decode** (`src/decode/`) — turn each label into a structured object. A
   cascade, cheapest-first:
   - deterministic **rules** (catches well-formed labels)
   - **retrieval** against the knowledge base (have we seen a similar label?)
   - **LLM fallback** (the swappable engine — Claude now; could be a local model
     later). Only labels unresolved by the cheaper layers reach it.
   - **human validation** for uncertain cases.
3. **Knowledge base** (`knowledge_base/`) — grows over time: raw labels,
   normalized labels, abbreviations, synonyms, NS/Brick mappings, prior
   classifications, confidence scores, and human-validated corrections. The
   system improves by accumulating here, NOT by the LLM "learning" from prompts.
4. **Connect / operate** (downstream, later) — measurement values are joined to
   already-decoded labels by ID, locally, with no AI. The LLM never needs the
   values to do its job.

**Golden rule:** the LLM is a development and interpretation partner that sees
labels (and data *summaries*/profiles), never a hardcoded runtime dependency.
Keep its interface clean so it can be swapped out.

---

## 3. The three data universes

The same building can be described at very different levels. Always record which
one a label came from in `source_type`.

- **Kiona / Energinet (EMS)** — aggregated, building-level, already clean.
  Human-readable column names (e.g. `El Energi`, `Fjernvarme Energi`,
  `Utetemperatur`). Often includes **derived/virtual** series (e.g.
  `El Kostnad + Spotpris + ...` — a computed cost, not a physical meter). Nearly
  ready to map directly. Best fit for time-series analysis.
- **BACnet / SD-anlegg** — granular, component-level, cryptic, vendor-specific
  point paths (e.g. `AXX-PX-APPXXX:...-Location/BACnet IP1.XXXXXX.Utganger...`).
  This is the "hard" universe and the source of the rich equipment detail.
- **NS / TFM / Brick** — the *target* structured vocabulary, not a data source.
  Used to give meaning to codes found inside labels.

These differ in syntax AND in completeness — not just format. "Same info,
different format" is false; expect missing fields in older sources.

---

## 4. Domain conventions (label grammar)

### Norwegian keywords (most reliable semantic signal)
`varme` = heating · `kjøling` = cooling · `ventilasjon` = air handling ·
`lys` / `strøm` = electrical · `tappevann` / `bereder` = domestic hot water ·
`utganger` = outputs · `innganger` = inputs · `fjernvarme` = district heating ·
`børverdi` = setpoint · `alarm` = alarm.

### NS 3451:2022 system codes (4-digit)
Examples: `3100` sanitary, `3200` heating, `3600` air handling, `3700` cooling,
`4320`/`4330`/`4340` electrical distribution, `4420` lighting.
Note: Oslobygg's Merkesystem forbids the overordnede (rounded) codes such as
`3100`, `3500` — see the Merkesystem reference. Codes seen "in the wild" may be
older / non-standard and therefore need LLM interpretation.

### Pilot's 3-digit codes (truncation, with a known bug)
The pilot's `ns2bricks.json` used 3-digit codes = the **first 3 digits** of the
NS 3451 code. `320` heating, `360` air, `370` cooling, `432`/`433`/`434`
electrical. **Known mismapping:** `310` was mapped to "domestic hot water" but
NS `31xx` means **sanitary** (cold + hot + drainage). The hot-water meaning came
from the *text* ("Varmt tappevann"), not the code. Lesson: **the code alone is
insufficient — semantics often live in the text and must be confirmed by data.**

### Sub-codes and components
- `NNN.NNN` (e.g. `434.003`) = subsystem.
- Undernummer for heating/cooling: `.04` = tur (supply), `.05` = retur (return).
- Undernummer for air handling (36): `.01` inntak, `.02` avkast, `.03` by-pass,
  `.04` tilluft, `.05` fraluft/avtrekk, `.06` omluft, `.07` overstrømning,
  `.08` spesialavtrekk.
- NS 3457-8 **component codes** = 3 letters (e.g. `RTA`, `SMA`, `CTD`, `UEA`).
- A **16-digit number** marks a main electric meter.

### BACnet object types
`AV` Analog Value · `BV` Binary Value · `MV` Multistate Value · plus
`AI`/`AO`/`BI`/`BO` (physical in/out) and `MI`/`MO`. Rough mapping:
AV -> sensor/setpoint, BV -> status/command, MV -> enumerated state.

**The AV-as-binary trap:** some legacy integrations expose AV objects that only
ever hold `0`/`1` — semantically binary, mislabeled as analog. **Always verify
the value distribution; never trust the object type alone.** Multistate values
are 1-based (state 1 is the first state, not 0).

BACnet path syntax is **vendor-specific, not NS-standardized.** Split on
`:` `/` `.` `-` `_`. Use NS codes/components only for fragments that actually
match the standard.

---

## 5. Cross-check rules (name = hypothesis, data = test)

Every name-based guess makes a testable prediction in the data. Use these to
automatically flag guesses the data contradicts — this catches confident
mistakes (the model's and the human's).

- **Heating** -> should correlate **negatively** with outdoor temperature.
- **Cooling** -> should correlate **positively** with outdoor temperature.
- **Binary / status** -> exactly **2** distinct values. (If many distinct
  values, it is analog — see the AV-as-binary trap.)
- **Energy (cumulative meter)** -> monotonically increasing, or always positive.
- **Hot water (`tappevann`)** -> morning/evening usage peaks; a different
  daily/weekly signature from temperature-driven space heating.
- If the data **contradicts** the name -> flag it; the label is likely
  mislabeled or the guess is wrong. Do not silently trust the name.

A guess that survives both the name reading and the data cross-check earns high
confidence. A guess in conflict goes to human validation.

---

## 6. Output contract

Every decoded label becomes one instance of `schema/decoded_label.schema.json`,
validated before it is stored. Requirements:

- Always include `raw_label` and `source_type` — traceability is mandatory.
- Always include a calibrated `confidence` and a short `reasoning` string so
  mistakes are traceable.
- **Partial decoding is valid output.** Unknown fields are `null`; degrade
  gracefully rather than guessing. "Fjernvarme energy, building unknown" with
  appropriate confidence is a good answer.

See `examples/` for three worked instances (clean Kiona, derived Kiona cost,
heavily redacted BACnet point).

---

## 7. Lessons to carry forward / weaknesses to avoid

From the pilot (do NOT repeat these):
- No regex-only fragility — combine rules + retrieval + LLM + validation.
- Persist validation data and corrections; build the feedback loop.

Worth preserving conceptually: the raw-label grammar, NS-to-Brick mapping idea,
the split between deterministic parsing and LLM interpretation, and a
Brick-compatible target (later).

> General working rules — ASCII identifiers, UTF-8 / Windows encoding, no
> hardcoded paths, keep tests, real third-party deps only — live in
> `~/.claude/CLAUDE.md`.

---

## 8. Running

```bash
python -m venv .venv && source .venv/bin/activate    # optional
pip install -r requirements.txt
```

Real deps: pandas, numpy, scikit-learn (`sklearn`), statsmodels, jsonschema,
matplotlib.

Labels and CSVs are Norwegian (æ/ø/å), so UTF-8 reading matters here — see the
global working rules for the ASCII / UTF-8 / Windows encoding conventions.

---

## 9. Repository layout

```
label-decoder/
├── CLAUDE.md                      # this file
├── README.md
├── requirements.txt
├── .gitignore
├── schema/
│   └── decoded_label.schema.json  # the output contract
├── data/
│   ├── raw/                       # real building CSVs (non-confidential)
│   └── synthetic/                 # structure-true invented examples
├── knowledge_base/                # validated mappings, abbreviations, NS/Brick lookups
├── src/
│   ├── extract/                   # Layer 1: pull labels out of a dataset
│   ├── decode/                    # Layer 2: rules + retrieval + swappable LLM
│   ├── profile/                   # data profiling + cross-checks
│   └── validate/                  # schema validation
├── examples/                      # worked schema instances
└── review/                        # local human-in-the-loop review tool (later)
```

You already have two folders of CSV data in this project. Move them into
`data/raw/` (or point the extract step at their current location) so the layout
above holds.

---

## 10. Data handling

The data is **non-confidential** (already shared with others), so Claude and
Claude Code may read it directly. Still, keep the LLM as a *swappable* component
(section 2) so the system can be replicated to environments with stricter rules
without rearchitecting.
