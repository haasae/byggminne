# Tokenizer failure modes (what the parser struggles with, and why)

Produced 2026-07-21 from a systematic probe of all 1,386 batch labels (rules
layer only, no validated store) plus structural mutations, followed by a
multi-agent interpretation of every failure cluster against the knowledge
base and an adversarial review of the newest tokenizer change.

This documents failure **categories** to understand, not labels to patch.
Re-run the probe on any new dataset:

    python -m src.eval.token_probe data/eval/batches/*/input.jsonl -o runs/token_probe/report.md

Raw numbers: `runs/token_probe/report.md`. (Nit: the three batches overlap --
b001's 19 labels also appear in b_all_tasen, so unique labels are 1,367.)

---

## Category 1 -- qualifier after the component code (the dominant mode)

**The single biggest failure shape:** a valid component code followed by a
qualifier the tokenizer treats as noise, killing the whole match. 149 labels
had no component despite a code-like token; most fall here. The qualifiers
are not noise -- each carries meaning:

| Qualifier | Examples | Likely meaning (evidence-backed) | Status |
|---|---|---|---|
| trailing `%` | `-LR401%`, `-SB401%` | 0-100% command signal (paadrag): VFD speed / valve position. All sit under `Utganger`. | Undocumented; expert Q pending |
| ` SP` (space) | `-RP401 SP` | Settpunkt -- separator variant of the known `_SP`. Same system carries BOTH `RP401 SP` and `RP401_WSP` -> plausibly configured vs working setpoint. | `_SP` documented; space variant + SP-vs-WSP distinction not |
| `-WSP` / ` WSP` | `563_H26-RT601-WSP`, `320 003-RT401 WSP` | Working Set Point -- separator variants of documented `_WSP`. | Meaning documented (grammar glossary); separators not handled |
| ` +-` | `-RT404 +-` | The +/- setpoint adjustment offset (documented mechanism). | Glossary documents `+-`; no machine rule |
| `_SD` / `-SD` | `-RT901_SD` (once per system, 12+ systems) | HYPOTHESIS: value sourced from the SD-anlegg -- one shared (likely outdoor) sensor broadcast per system. NOT komponentkodeliste's SD (sprinkler valve -- impossible on a temperature point). | Unknown; expert Q + seasonal_check test pending |
| ` St` | `-JP401 St` | HYPOTHESIS: pump run status (JP=pumpe; Tasen siblings use `_Drift`). | Unknown; binary data check pending |
| ` Eff` | `-LX001 Eff` (once per air system) | LX = varmegjenvinner; Eff = efficiency (virkningsgrad) OR power (effekt) -- genuinely ambiguous in Norwegian. | Unknown; expert Q + range check pending |
| circuit words `_GULV`/`_RAD`/`_Radkurs`/`_TAK` | `-RT401_GULV`, `-SB401%_GULV` | Named heating sub-circuit (floor/radiator/ceiling loop), NOT a location: sensor + setpoint + offset + valve all share the word -- complete control loops. **Decode-changing:** these sit on 3600xx-numbered controllers but are hydronic HEATING loops -- system-from-controller-number would be wrong for them. | Undocumented; expert confirmation pending |
| room words `_HALL`/`_GARDEROBE` | `-RT601_HALL` | Room-temperature sensors named by room; RT**6**xx appears to be a room/zone series -- side-digit convention only documents 4/5. | Digit-6 convention undocumented; expert Q pending |
| `_Radon` | `-SX401_Radon` | Radon concentration on ventilation (standard in Norwegian buildings). Tension: SX = "Regulator" in NS but these are inputs (RY gas detector would fit better). Brick target exists: `Radon_Concentration_Sensor`. | Expert Q pending |
| `_Y1`/`_Y2`, with siblings `UTE_X1..X4`, `Turtemp-Y1..Y4` | Settpunkt segments | Outdoor-compensation heating-curve breakpoints (x = outdoor temp, y = supply temp) -- **parameters, not sensors.** The inverse of the RT401 trap: seeing `UTE` and emitting "outdoor sensor" would be wrong. | Undocumented pattern; expert Q pending |

**Composite shapes** also occur: `<code>_WSP_<circuit>`, `<code>_+-_<circuit>`,
`<code>%_<circuit>` -- qualifier INFIX between code and circuit word.

**Fix type when confirmed:** one generalized change (separator-insensitive
suffix matching + a curated qualifier table in `deterministic_rules.json`),
NOT per-qualifier regexes. Meanings enter the KB only after expert/data
confirmation -- every "Likely meaning" above is a hypothesis until then.

## Category 2 -- vocabulary the parser has never heard of

- `WM01_Energi_Fjernvarme.Totalisering1` / `WM02_Energi_Hovedtavle...`:
  almost certainly cumulative energy meters (district heat / main board). WM
  is NOT an NS code (W = "ikke i bruk"; NS uses OE = energimaaler) -- the
  meaning lives in the free text, the pilot lesson again. Data check:
  totalizers must be monotonic.
- `TH1/TH5/TH7/TH11` on the IK001 chiller: plausibly thermistor probe
  channels (non-contiguous numbering fits hardware channels); TH is not an
  NS code. Leave null, low confidence -- correct current behavior.
- Bus-segment values: grammar doc lists only `FCB`; observed also
  `BACnet IP1`, `ModbusRTU`, `ModbusRTU2`, `N2 Trunk 1` (all infrastructure,
  no NS meaning) and `Programming` (hypothesis: the controller's soft/computed
  points branch -- its children are all setpoints/calculated values).
- `Utgang` (singular, 8x): author inconsistency for documented `Utganger`.

## Category 3 -- structural brittleness (mutation probe)

Measured on the 1,045 labels that currently decode:

| Variation | Breaks | Reading |
|---|---|---|
| lowercase component codes | 98% | Patterns are uppercase-only BY DESIGN (keeps free text out) -- a lowercase-labeling vendor would slip almost entirely to the LLM layer. Known trade-off, not a bug. |
| code not at segment end | 47% | EMBEDDED_POINT_TAIL only looks at segment ends; mid-segment codes (rare today) escape. |
| swap `-` and `_` | 11% | Mostly survivable -- suffix regexes (`_SP`, `_WSP`) are the main casualties. |
| spaces for separators | 11% | Same profile as swap. |

## Category 4 -- what the probe itself does not cover (verified gaps)

1. **Encoding (HIGH, demonstrated):** the cp1252-mojibake form of
   `-P1_Utløst_Vern` drops FULL -> PARTIAL (keyword no longer matches).
   Norwegian data guarantees recurrence; 4/49 curated keywords are non-ASCII.
2. **Kiona / prefix-less labels (HIGH, demonstrated):** `El Kostnad +
   Spotpris + ...` decodes to tier NONE; the probe corpus is 100% BACnet.
   By design these go to the LLM layer -- but the probe measures nothing
   about them, and 2 of 3 worked examples are Kiona.
3. **16-digit meter numbers (MEDIUM):** `decode_rules.md` documents "bare
   16-digit number = main electric meter", but no rule implements it and no
   batch label exercises it -- a documented shape that decodes to nothing.
4. **Whitespace variants (MEDIUM):** 7% of real labels contain double
   spaces (currently harmless, but multi-word path-token lookups are
   exact-match and would miss internal doubling).
5. **Keyword/suffix case (MEDIUM):** keywords are casefolded (safe), but
   `_wsp` / lowercase embedded codes are invisible -- overlaps with the
   lowercase trade-off above.

## Known ceilings of the new EMBEDDED_POINT_TAIL fallback

Adversarially reviewed against all 1,386 labels: **zero false positives
today**; every extracted tail is a genuine component code (RT/SB/RY/RD/RF/LR).
Accepted residual risks, in order:

- The komponentkodeliste guard is weak: 330 letter pairs incl. collision-prone
  ones (`IP`=gas boiler, `SW`=plenum chamber, `MV`=water filter). A future
  vendor tail like `Ver_SW102` would decode as a component. Upgrade path:
  restrict fallback letters to a curated point-family allowlist.
- Embedded extraction earns the same confidence/reasoning as an exact
  point segment, and drops the uninterpreted prefix (H26/D101 -- real zone
  info) silently. Upgrade path: a discount or an extra reasoning clause.
- Scan-order shadowing: a code-like tail in a later free-text segment could
  preempt a real code earlier in the path (zero instances today).
- Pre-existing POINT_CODE-before-IO_POINT ordering means BACnet-object-shaped
  tails (`_MV12`) would decode as components; surface widened, still zero
  instances.
- `point_role()` (relationship checker) does not use the fallback -- side
  verification skips embedded points the rules engine claims sides for.

## How each category gets fixed (the policy)

- **Structural layouts** (separators, position, case): generalized tokenizer
  patterns + tests -- code, because the deterministic layer cannot read prose.
- **Semantics** (what `%`, `_SD`, `Eff`, `H26` MEAN): documentation -- grammar
  glossary + `deterministic_rules.json` entries -- added ONLY after expert or
  data confirmation (see `docs/expert_validation_sheet.md`, section C).
- **Unknown vocabulary**: stays null with low confidence and flows to the
  LLM/enrichment layer -- that path existing is itself the robustness
  mechanism for labels we have never seen.
