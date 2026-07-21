# Reading a decode output (cheat sheet)

Everything below is how the code actually behaves, with file references,
using this example:

```
A20-P2-APP019:NIE00108D0A91DD/N2 Trunk 1.320001_bygg5.kj maskin bygg5etg3.BO1.#85
-> Decoded by: retrieval (exact hit) · tier FULL · confidence 1.0 · validated true
```

## The three decode methods (cheapest first, `deterministic_batch.py`)

1. **`retrieval`** — the *exact* label string is already in
   `knowledge_base/validated_decodes.jsonl`. Returns the stored decode
   verbatim; nothing recomputed. Confidence/reasoning/validated all come from
   the human who approved it. **Measures KB recall, not generalization.**
2. **`rules`** — structural parse (`rules_engine.py`): system tokens, component
   codes, I/O tokens, keywords, side digits. Every field cites its KB source in
   `reasoning`; unknown fields stay null.
3. **`rules+retrieval`** — rules ran, and a *structural sibling* (same shape,
   different digits) in the store filled some still-null fields. Only STRUCTURAL
   fields inherit (primary_system, carrier, component, is_derived, object_type);
   observation-prone fields (function, unit, subsystem, measurement_type) never
   inherit -- the RT401 trap.

## Confidence -- three regimes

- **Exact retrieval:** copied from the validated store (human-set; often 1.0).
  1.0 = "a human confirmed this", NOT "the algorithm was sure".
- **Rules:** additive policy, base **0.30**, capped **0.90**:
  +0.20 component from a code · +0.20 system from a code token (+0.10 if only a
  text keyword) · +0.10 object_type · +0.10 function/measurement_type ·
  +0.05 building. Capped at 0.90 on purpose: *conventions can lie* (RT401).
- **Sibling:** `min(0.9, max(rules_conf, sibling_conf - 0.1))`.

Confidence is a transparent sum of lined-up signals, not a model probability.

## Tier (completeness, separate from confidence)

Count non-null of the 4 key fields {primary_system, component, function,
measurement_type}: **>=3 FULL · >=1 PARTIAL · 0 NONE**. It measures how much got
filled in, not how sure we are.

## Does it go to the LLM? (`needs_llm` / residue bar)

Sent to the LLM layer if: **tier == NONE, OR confidence < 0.4, OR schema
invalid.** Otherwise deterministic is good enough. (`MIN_CONFIDENCE = 0.4`.)

## The fields (schema/decoded_label.schema.json)

- **raw_label, source_type, confidence, validated** -- the only REQUIRED fields.
- **primary_system** -- NS 3451 4-digit code + description (legacy 320 -> 3200).
- **subsystem** -- lopenummer / undernummer (tur/retur, tilluft/avtrekk).
- **component** -- NS 3457-8 code (RT401 = Temperaturgiver). Null if none present.
- **object_type** -- BACnet (AV/BV/MV/AI/AO/BI/BO...). *AV-as-binary trap:
  always check value distribution.*
- **function** -- free-text role; **measurement_type** -- constrained enum.
- **carrier** -- el/fjernvarme/kjoling/gass/vann/annet. Left null when unsure.
- **location** -- building + zone. **is_derived** -- computed vs measured series.
- **reasoning** -- the audit trail; rules decodes cite file+line, retrieval
  decodes carry the human's note.
- **data_checks** -- null here; filled by the separate `src/profile/` layer, not
  by `try_label`.
- **relationships** -- empty until the relationship layer runs.
- **decode_method / decoded_kb_version** -- which layer + which KB hash produced it.

## The story hiding in the example

Label says "kj maskin" (COOLING machine) but system 320001 = Varmeanlegg
(HEATING) -- a real contradiction. The human decode flagged it and left
`carrier` null instead of guessing ("never invent"). And `data_observations.md`
records this exact BO1 as **constant 0 all year -- an output never commanded**.
Name = hypothesis, data = test.
