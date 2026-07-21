# BACnet/SD-anlegg Label Grammar (Tasen source)

Source: field feedback from Hakon, 2026-07-02, clarified 2026-07-02.
Status: mostly confirmed for structure; two fields remain genuinely
open-ended by design (see "Known unresolved fields"). Confidence per field
is marked: CONFIRMED / HYPOTHESIS / UNCLEAR / OPEN-BY-DESIGN.

## Worked example

```
A20-P2-APP019:20053401-OU001/FCB.Local Application.-RT401.#85
```

## Field breakdown

| # | Segment | Example value | Meaning | Confidence |
|---|---------|---------------|---------|------------|
| 1 | Main node | `A20-P2-APP019` | Identifies the main node. Recurs identically across all labels in a batch. Internal sub-structure (A20 / P2 / APP019) not yet decoded -- likely not semantically important for decoding purposes. | HYPOTHESIS (low priority to decode further) |
| 2 | Controller name | `20053401-OU001` | Everything between `:` and `/`. Two sub-parts (see below). | CONFIRMED |
| 2a | Control number | `20053401` | "Controllnummer" / building number, scoped to a physical area. Sibling values `20053402`, `20053404`, etc. exist across other datasets and are all part of the same Tåsen area -- a per-building ID within a known area, not a one-off. | CONFIRMED |
| 2b | Undersentral | `OU001` | "Undersentral" (sub-central unit) -- specifies more precisely where the data point is physically gathered from. | HYPOTHESIS (structure confirmed, not independently re-verified) |
| 3 | Bus segment | `FCB` | "Feltkontrollbuss" (field control bus) -- the sub-part of the control the point sits on. | CONFIRMED |
| 4 | Application field | `Local Application` | Not a constant. In some datasets it is literally "Local Application" for every label; in others it holds substantive point/equipment text, e.g. `IK001_TEST.Modus_MI`, `320001_bygg5.kj maskin bygg5etg3.BO1`, `IK001_TEST.Komp_Drift`. Always sits directly after the bus segment. See "Data quality caveat" below. | CONFIRMED (as variable, dataset-dependent) |
| 5 | Component code | `-RT401` | Component identifier, see breakdown below. | CONFIRMED (general pattern) |
| 6 | Tag number | `#85` | Constant across all labels and across several Tåsen datasets. Meaning unknown -- likely a deployment/version/area-level constant rather than a per-point identifier, since it does not vary. Low priority. | OPEN-BY-DESIGN |

## Component code sub-structure -- general rule (not just RT)

This generalizes to any two-letter component code followed by 3 digits
(e.g. RT, LR, etc.), not just temperature points.

| Part | Value | Meaning | Confidence |
|------|-------|---------|------------|
| Letters | `RT` (example) | Two-letter component type code. R = analog value, T = temperature, so RT = analog temperature point. Same letter-code logic applies to other two-letter prefixes (e.g. LR). | HYPOTHESIS |
| 1st of the 3 digits | `4` (in RT4-01) | Indicates supply side ("til-siden") vs. return side ("fra-siden"/retur-siden). Confirmed to apply generally: whenever a two-letter code is followed by three digits, the first digit carries this til/fra meaning, regardless of component type. Exact numeric mapping (whether 4=supply always, possibly mirroring the .04=tur / .05=retur convention in NS 3457-7/G1, Merkesystem_Oslobygg.pdf section 2.2.1.3) is a plausible cross-reference but not independently re-confirmed. | CONFIRMED (that this digit carries til/fra meaning generally) |
| Last 2 digits | `01` (in RT4-01) | Løpenummer (running/sequence number). Confirmed by observed data: RT401, RT403, RT404 all exist, but RT402 does not -- a gap is expected/normal in a løpenummer sequence, not evidence of hidden meaning. | CONFIRMED |

## Glossary

| Term | Meaning |
|------|---------|
| `+-` | Indicates a setpoint can be adjusted by +/- N degrees |
| `WSP` | Working Set Point -- the current setpoint value in degrees; adjustable via the +- mechanism |
| `IK` | Kjølemaskin (cooling machine) -- confirmed spelling |
| `320001` (seen inside Application-field free text, e.g. `320001_bygg5...`) | Combines a 3-digit legacy system code (320 = varmesystem/heating) with a løpenummer (001). This is raw/legacy free text, not a governed Merkesystem TFM code -- see "3-digit vs 4-digit codes" below. |

## Observed point-segment layouts and qualifiers (Skoyen batch, added 2026-07-21)

Layouts observed in `data/eval/batches/b_all_skoyen/input.jsonl` beyond the
Tasen worked example. Structure is CONFIRMED (present in data); meanings are
marked per qualifier. Full failure analysis: `docs/tokenizer_failure_modes.md`.

Point-segment layouts (component code embedded in a larger segment):

| Layout | Example | Status |
|---|---|---|
| `<sys3>_<ref>-<code>` | `563_H26-SB602` | CONFIRMED structure; `H26`/`D101` ref meaning UNKNOWN (room? circuit?) |
| `<sys3> <lopenr>-<code>` | `320 001-RT401` | CONFIRMED structure (space-separated subsystem + component) |
| `<sysNNNNNN>_<code>_SP` | `360001_RF401_SP` | CONFIRMED structure (under `Programming`) |

Qualifiers observed AFTER a component code (separator varies: `_`, `-`, space):

| Qualifier | Example | Meaning | Status |
|---|---|---|---|
| `%` | `-LR401%`, `-SB401%` | 0-100% command signal (paadrag) -- all under Utganger | HYPOTHESIS |
| `SP` | `-RP401 SP` | settpunkt (space variant of `_SP`); coexists with `_WSP` on the same system -- configured vs working setpoint? | HYPOTHESIS |
| `WSP` | `563_H26-RT601-WSP`, `320 003-RT401 WSP` | Working Set Point (glossary above); only the separators are new | CONFIRMED meaning |
| `SD` | `-RT901_SD`, once per system across 12+ systems | shared sensor sourced from the SD-anlegg, likely outdoor? NOT komponentkodeliste's SD (sprinkler valve) | HYPOTHESIS |
| `St` | `-JP401 St` | pump run status? | HYPOTHESIS |
| `Eff` | `-LX001 Eff` | heat-recovery efficiency (virkningsgrad) OR power (effekt) | UNCLEAR |
| `GULV`/`RAD`/`Radkurs`/`TAK` | `-RT401_GULV`, `-SB401%_GULV` | named heating sub-circuit (complete control loop shares the word); NOT a location | HYPOTHESIS |
| `HALL`/`GARDEROBE` | `-RT601_HALL` | room name on RT6xx room sensors; digit 6 = room/zone series? | HYPOTHESIS |
| `Radon` | `-SX401_Radon` | radon concentration (ventilation-controlled) | HYPOTHESIS |
| `Y1..Y4` + sibling `UTE_X1..X4` / `Turtemp-Y1..Y4` | Settpunkt segments | outdoor-compensation curve breakpoints -- parameters, NOT sensors (do not decode `UTE` as an outdoor sensor) | HYPOTHESIS |

Composite shapes: `<code>_WSP_<circuit>`, `<code>_+-_<circuit>`,
`<code>%_<circuit>` -- the WSP/+-/% qualifier sits INFIX before the circuit word.

Bus-segment (field 3) values observed beyond `FCB`: `BACnet IP1`,
`ModbusRTU`, `ModbusRTU2`, `N2 Trunk 1` (infrastructure, no NS meaning --
CONFIRMED positionally) and `Programming` (children are all soft/computed
points -- controller program branch? HYPOTHESIS). Path token `Utgang`
(singular) observed as author-inconsistent variant of `Utganger`.

Vendor vocabulary with no NS reading (leave component null): `WM01`/`WM02`
(energy-meter prefix; W = "ikke i bruk" in NS 3457-8 -- meaning carried by the
free text `Energi_Fjernvarme`/`Energi_Hovedtavle` + `Totalisering`),
`TH1/TH5/TH7/TH11` (IK chiller register names, thermistor channels? UNKNOWN).

## 3-digit vs. 4-digit codes -- how this project resolves it

Hakon's answer: label naming in the raw BACnet/SD and legacy sources is
unpredictable, with no guarantee of consistency, and must be learned
empirically from the data rather than assumed from documentation alone.

Practical resolution for the decoder pipeline:
- Input labels may legitimately contain 3-digit (or otherwise non-standard)
  legacy codes. This is expected, not an error to "fix" at ingestion -- it
  is a property of the raw source data (SD-anlegg / Kiona legacy naming),
  consistent with the project's existing understanding that data sources are
  inconsistent and information-incomplete by nature.
- Output must still conform to the schema contract: decoded records always
  resolve to the 4-digit NS 3451 system code (schema/decoded_label.schema.json),
  regardless of whether the input label used a 3-digit shorthand. The
  3-digit-to-4-digit mapping (e.g. 320 -> 3200) happens during decoding, not
  by rejecting or "correcting" the input label itself.
- This does not reopen the OsloFlex pilot error (hardcoding 3-digit codes as
  the system's own output/target format). The distinction: 3-digit codes are
  an accepted, expected input pattern from messy legacy labels; 4-digit
  codes remain the only correct output convention.

## Data quality caveat

Label authors are inconsistent: variable/free-text names are frequently just
copy-pasted from other instances and are therefore semantically unreliable.
This unreliable free text tends to appear after the bus field (i.e. in the
Application field, after the FCB/bus segment) -- confirmed by the examples
above, where the same field ranges from a meaningless constant ("Local
Application") to genuinely useful equipment references
(320001_bygg5.kj maskin bygg5etg3.BO1). Practical implication: weight the
structural/coded fields (node, controller, bus, component code) much more
heavily than the Application-field free text when decoding BACnet/SD labels
-- treat that free text as supplementary/low-confidence evidence, useful for
LLM-fallback reasoning but not as a primary deterministic signal.

## Design note: controller-number-to-area mapping

Per Hakon: "Claude Code should know this considering it has access to all
files." Rather than hardcoding a static list of control numbers (20053401,
20053402, 20053404, ...) into CLAUDE.md, the decoder should derive the
control-number-to-area mapping empirically by scanning all available label
files and accumulating observed control numbers into a knowledge_base/
lookup table as they are encountered -- consistent with the project's Layer
3 principle (accumulate validated mappings in the knowledge base rather than
relying on in-session LLM learning or exhaustive manual documentation).

## Known unresolved fields (accepted as open, not blocking)

These do not currently block decoding and are being consciously left open
rather than chased further right now:

- Field 1 (main node internal structure, A20-P2-APP019) -- low decoding value.
- Field 6 (#85 tag) -- appears to be a constant, meaning unknown.
- Full component-letter glossary (R=analog value, T=temperature, L=?, etc.)
  -- only R/T confirmed so far; build incrementally as more codes are
  observed, per the "learn empirically" principle above.
