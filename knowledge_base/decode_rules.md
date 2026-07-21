# Decode rules (label grammar)

Reference rules for turning one building-energy label into the decoded-label
schema. This file is part of the frozen decode context pack. It contains **rules
and code enumerations only — no worked label->JSON examples** (the cold-start
rule forbids accumulating examples in the prompt; corrections accumulate in the
knowledge base instead). Cite this file or the NS/TFM/component files when a
field rests on one of their entries.

## Norwegian keywords (often the most reliable signal)
- `varme` = heating · `kjoling`/`kjoeling` (Kjoling) = cooling · `ventilasjon` = air handling
- `lys` / `strom` (strom) = electrical · `tappevann` / `bereder` = domestic hot water
- `fjernvarme` = district heating (carrier `fjernvarme`)
- `utganger` = outputs · `innganger` = inputs
- `borverdi` (boerverdi) / `settpunkt` = setpoint · `alarm` = alarm
- `drift` = operation/running · `feil` = fault/error · `modus` = mode
- `tur` = supply · `retur` = return · `tilluft` = supply air · `fraluft`/`avtrekk` = extract air

## NS 3451:2022 system codes (4-digit) -> primary_system.code
- `3100` sanitary · `3200` heating · `3600` air handling · `3700` cooling
- `4320` / `4330` / `4340` electrical distribution · `4420` lighting
Rounded "overordnede" codes (`3100`, `3500`, ...) are forbidden by some merke-
systems; codes seen in the wild may be older or non-standard. Look up codes in
`TFM_systemkodeliste.md` and `NS-3451.md` and cite the row used.

**The code alone is insufficient — semantics often live in the text.** Pilot bug:
`310`/`31xx` is **sanitary** (cold + hot + drainage), NOT "domestic hot water";
the hot-water meaning came from the text ("Varmt tappevann"). Confirm meaning
from the label text, and leave uncertain meanings null.

**Legacy 3-digit input -> 4-digit output.** Raw SD/legacy labels may carry a
3-digit (or otherwise non-standard) system code, often glued to a running number,
e.g. `320001` = legacy `320` + løpenummer `001`. This is an expected property of
messy source data, not an error to "fix" at ingestion. But `primary_system.code`
**must always be the 4-digit NS 3451 code**: resolve the shorthand to its 4-digit
form (`320` -> `3200`, `310` -> `3100`, `360` -> `3600`, `370` -> `3700`) and cite
the row in `TFM_systemkodeliste.md` / `NS-3451.md`. This does NOT reintroduce the
pilot bug: 3-digit codes are an accepted *input* pattern; 4-digit is the only
correct *output*. If the shorthand cannot be mapped, leave the code null.

## Sub-codes / components
- `NNN.NNN` (e.g. `434.003`) = subsystem code -> `subsystem`.
- Heating/cooling undernummer: `.04` = tur (supply), `.05` = retur (return).
- Air-handling (36) undernummer: `.01` inntak, `.02` avkast, `.03` by-pass,
  `.04` tilluft, `.05` fraluft/avtrekk, `.06` omluft, `.07` overstromning,
  `.08` spesialavtrekk.
- NS 3457-8 **component codes** = a **2-letter function code**, usually followed by
  a 3-digit number (e.g. `RT401`, `RD401`, `SB41`) -> `component`. Look the 2-letter
  code up in `komponentkodeliste.md` and cite the row; common ones: `RT` Temperatur-
  giver, `RD` Differansetrykkgiver, `RP` Trykkgiver, `RY` gass-/CO2-detektor, `SB`
  Reguleringsventil (motorstyrt), `LR` Frekvensomformer, `OU` Undersentral (the host
  controller, not the measured thing), `IK` Kuldeaggregat (kjølemaskin), `JP` Pumpe.
  These are **lookup codes, not letter-by-letter** — do not decompose them (`LR` =
  Frekvensomformer, not L+R).
- **First digit of the 3-digit number encodes side:** `4` = tur/tilluft (supply),
  `5` = retur/fraluft (return); the last two digits are a løpenummer (gaps are
  normal). Documented across the R/S/M/J families in `komponentkodeliste.md` (e.g.
  the RT row: "RT4_ ... tilluft/tur og RT5_ ... fraluft/retur"). Record it in
  `subsystem` (e.g. "tur/tilluft (supply)") and cite the row.
  **Caveat: the convention is a hint, not a guarantee** — at Tåsen, `FCB -RT401`
  is the OUTDOOR temperature sensor, not tur/tilluft (confirmed by its annual
  profile; see `data_observations.md`). When data contradicts the convention,
  the data wins.
- A bare **16-digit number** = a main electric meter.
- **BACnet/SD path grammar and unreliable free text:** for these vendor labels,
  see `bacnet_sd_label_grammar.md` for the positional breakdown (main node /
  controller number / undersentral / bus / application field / component code / tag)
  and `control_number_area_map.md` to resolve the controller number to an area.
  Weight the structural/coded fields (controller number, bus, component code) far
  more heavily than the free text in the Application field, which is often
  copy-pasted and semantically unreliable.

## BACnet object types -> object_type (when source_type is bacnet)
- `AV` -> sensor/setpoint · `BV` -> status/command · `MV` -> enumerated state (1-based)
- plus `AI` / `AO` / `BI` / `BO` (physical I/O) and `MI` / `MO`.
- **AV-as-binary trap:** some legacy AV objects only ever hold 0/1 — semantically
  binary, mislabeled analog. This round is name-only (no value data), so set
  object_type from the path token and keep confidence modest when unsure.
- Path syntax is vendor-specific, NOT NS-standardized. Split on `: / . - _` and
  apply NS codes / component codes only to fragments that actually match the
  standard. Common path tokens: `Innganger` (inputs), `Utganger` (outputs),
  `Analoge verdier` (analog values), `Settpunkt` (setpoint).

## Output contract (see the schema for exact types and enums)
- Echo `raw_label` verbatim; copy `source_type` exactly as given.
- **Partial decoding is valid.** Unknown fields are null; degrade gracefully
  rather than guess. Never invent a meaning for an unknown code — leave it null
  and lower `confidence`.
- Give a **calibrated** `confidence` in [0, 1] and a short `reasoning` that cites
  the knowledge-base file (and row, when applicable) behind each resolved field.
- Set `validated` to false. This is a name-only round: set `data_checks` to null
  and `relationships` to an empty array [] (never null).
