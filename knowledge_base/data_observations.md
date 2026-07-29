# Data-confirmed observations (name = hypothesis, data = test)

Facts about specific labels/patterns CONFIRMED by cross-checking against the
measurement data (`src/profile/`: series_stats, cross_check, seasonal_check) --
the accumulating feedback loop of CLAUDE.md section 4. Each entry states the
evidence so it can be trusted (and re-derived) without rerunning the analysis.
Scope so far: Tasen + Skoyen 2025 exports and the COLLECTiEF dataset (B01-B07).

## Outdoor-temperature reference (IMPORTANT decode correction)

- **`FCB ... -RT401` on the Tasen undersentraler (OU001...) is the OUTDOOR
  temperature sensor (utetemperatur), NOT a tur/tilluft sensor.** Evidence:
  full-2025 monthly profile Jan mean 0.6 C (min -13.1) .. Jul mean 22.3 C
  (max 29.9) -- an Oslo annual outdoor profile; amplitude 21.7 C. No regulated
  indoor/ventilation point behaves like this.
- Lesson for the RT4_ convention: **lopenummer conventions are hints, not
  guarantees.** RT4_ = tur/tilluft holds for e.g. RT404 (flat ~21 C year-round,
  r=+0.41 vs outdoor), but RT401 on these FCB controllers is the outdoor
  compensation sensor. Confirm against data when possible.
- **Scope of the outdoor finding: verified ONLY for `20053401-OU001` RT401.**
  Other OUs' RT401 likely follow the same site convention but are unverified --
  observations never inherit across labels (Skoyen lesson: RD503 on system
  360005 shares its name with 2-valued RD503s yet is genuinely analog).
  Verify each with `seasonal_check` before validating.
- These RT401 series can serve as the **in-data outdoor reference** for
  heating/cooling correlation checks (CLAUDE.md section 4) -- external weather
  data is not required for a first pass.

## Confirmed decodes (correlation / range evidence)

- **`N2 Trunk 1.320001.Analoge innganger.RT401`** = heating supply-water
  temperature on system 3200: 24..69 C, winter-high, **r = -0.796 vs the outdoor
  reference** (n=50734) -- the section-4 heating rule observed on real data.
- **`ModbusRTU2.320x_adr106.Effective Set point`** = a ~20 C temperature
  setpoint: the only observed values are {19.9, 20.0, 20.1} (the +- adjustment
  mechanism in the label grammar glossary). measurement_type = temperatur.
- **`ModbusRTU2.IK001_TEST.Arb_Spkt`** = working setpoint, constant 24.0 --
  consistent with a cooling-machine temperature setpoint in C.
- **`ModbusRTU.2017_adr1.Heating control ...` register #85** spans 0..100 --
  reads as a percentage (paadrag/valve position) on the heating regulator.
- **`FCB ... -RP401_SP`** = pressure setpoint, constant 90.0 all year
  (constant is expected for setpoints).
- **`ModbusRTU2.1031_adr10.Temperature`** = indoor temperature (18.1..32.1 C,
  mean 24.8); **`...CO2`** = indoor CO2 (430..1314 ppm, mean 518).

## Relationship-level findings (Phase 3, correlation across points)

- **`N2 Trunk 1.320001_bygg3 ... RT401`** = heating supply for building 3:
  r = -0.804 vs the outdoor reference -- same signature as the main 320001
  supply. The two supplies track each other at **r = +0.886**: one heating
  plant serving multiple buildings.
- **`FCB OU001 -LR401` (frekvensomformer) and `-RD401` (differansetrykkgiver)
  correlate at r = +0.988** -- drive speed up, differential pressure up: they
  almost certainly sit on the SAME fan/pump circuit (a VFD-controlled
  aggregate). LR401 runs harder in cold weather (r = -0.32 vs outdoor).
  Which system (ventilation vs heating circulation) is still unresolved.
- **`N2 ... 320001 SB41` (valve command)**: r = +0.641 vs outdoor and
  r = -0.759 vs its own supply temperature -- consistent with a
  **reverse-acting shunt/mixing valve** (opens more in warm weather to cool
  the supply). Not a decode error; a lesson: actuator command signs are
  installation-specific, so load-direction rules must not judge kommando
  points (the checker now skips them, recording r as evidence).
- **`ModbusRTU.2017_adr1 'Heating control' register #85`** shows NO outdoor
  correlation (r = +0.11) despite the 0..100 range -- its role stays unknown;
  keep confidence low.

## Skoyen findings (2025 exports; cross-checked 2026-07-02)

- **2-valued working setpoints are normal scheduling**, not the AV trap:
  `360001.Settpunkt.-RP401_WSP` holds exactly {50, 120} (day/night pressure
  setpoint) and `-RT503_WSP` toggles between two temperatures (nattsenking).
  The av-trap check exempts settpunkt-function points for this reason.
- **`360002.Innganger.-RD503` (4 labels across the 3600xx systems) reads only
  2 distinct values** -- letter-coded RD (Differansetrykkgiver/transmitter) but
  BEHAVES as a differential-pressure SWITCH (filtervakt; QD semantics in
  komponentkodeliste.md). Data-over-convention candidate: measurement_type is
  probably status, component probably a vakt. Human confirmation pending.
- **Binary-behaving "analog" points (the AV trap, for real):** the
  `360001.Analoge verdier.AV-0` family (14 labels) and Swegon
  `AI-13611`-family (8) + `AI-45` hold exactly 2 values -- semantically binary
  (likely presence/window contacts on WISE rooms and status flags on the
  ventilation systems). Decode as status pending confirmation.
- Skoyen structure: controller segment is `<controlnumber>-Skoyen` (a NAME,
  not OU); systems `360001/360002/360003` = luftbehandling; Swegon WISE rooms
  carry per-room comfort setpoints (H/C, Occ/Uocc, natt/morgen).

## Open flags (data raised, human answer pending)

- **`ModbusRTU2.IK001_TEST.Kjole_Drift-`** reads constant 1 ("running") from
  2025-03-03 onward -- plausibly a freezer/cooler that truly runs continuously,
  or a stuck status. Unresolved.
- **`...kj maskin bygg5etg3.BO1`** constant 0 -- an output never commanded.
- The `-TEST` suffix on IK001 points and their late start (2025-03-03) suggest
  a test/commissioning setup; treat IK001 decodes with modest confidence.

## COLLECTiEF Phase 0 ground-truthing (2026-07-23, src/heating/tz_check.py)

- **Zone timestamps are honest UTC** (the `+00:00` suffix is true). Evidence:
  B01 setpoint up-step modes shift exactly +59/+60/+60 min from CET (Jan-Mar
  2023) to CEST (Apr-Jun 2023) in three independent zones (B01-MA-A-1-19/-23/
  -25) -- the signature of a fixed local-wall-clock schedule logged in UTC.
  B07's zones were too noisy to vote either way (its only clean steppers are
  the two known dead-gain zones); no zone voted "local".
- **Weather/weather.csv is also UTC** despite naive timestamps: first hour
  with DNI > 5 in June 2023 falls at 01-02h UTC on 27 of 30 days (local CEST
  would put Aalesund first light at 03-04h). The hourly DNI "peak at 13h" that
  suggested local time is noise (flat afternoon distribution).
- **Consequence:** all occupied-hours / schedule logic in src/heating/ must
  convert UTC -> Europe/Oslo before comparing against wall-clock schedules.
- **Throughput benchmark (B07, full building):** 43.5M rows / 1.65 GB in
  305 s = 142k rows/s, 5.4 MB/s (Python-parse-bound, sequential). Fleet
  extrapolation ~2.5-3 h for all 1050 zone CSVs; scan cache makes re-runs
  file-granular. Disk OK (95 GB free; dataset already hydrated locally).
- **Smoke-pair regime validation (B07+B02) passed all channels:** B07 30
  binary + 2 dead (pins reproduce); duty-vs-outdoor-temp r=-0.57 and
  duty-vs-main-kWh r=+0.88 (n=372 heating-season days) -- the duty-cycle
  proxy tracks real electric energy. B02 15 binary + NEW findings the survey
  never sampled: B02-MA-B-2-26 and B02-MA-B-2-27 dead gain, B02-MA-A-1-5 no
  data at all; duty-vs-temp r=-0.14 (right sign, weak -- HP+radiant-floor mix
  plausibly dilutes; watch in fleet validation).
- **Fleet regime classification (all 784 T-triple zones, 2026-07-23):** every
  building matches its physical character from signal shape alone -- B01 the
  only modulating-majority building (150 mod / 37 bin / 11 mixed of 198 live),
  B02/B03/B05/B06/B07 overwhelmingly binary, B04 genuinely mixed (116 mod /
  88 bin). Survey check on the full zone table: OK (counts, dead pins, orphan).
- **NEW: B01 has 44 dead heating zones (~18% of its T-triples)** -- gain
  constant 0 for the whole 2.5-year period. NOT random: 43/44 cluster in
  wings A and C, floors 2-4 (C-4:10, C-2:7, A-3:6, A-4:6, C-3:6, A-2:5,
  C-1:3, B-4:1). Systematic -- plausibly a disabled control group or rooms
  heated by another system (B01 zones are also fed by VAVs). Flexibility
  analysis must exclude them; worth asking the advisor/municipality about.
- **MAJOR: B04's T_Gain is a COOLING actuator in most zones.** Fleet physics
  gate initially failed on B04 (duty vs outdoor temp r=+0.19); per-zone
  diagnosis: 126/209 zones are summer-dominant (e.g. B04-MA-C-2-165 winter
  duty 7.9% vs summer 97.8%). The T-triple header lies for over half the
  fan-coil building. Fix: per-zone thermal orientation from seasonal duty
  dominance (heating/cooling/dual/idle; Aalesund's cold summer nights mean
  mere summer activity is NOT suspicious -- dominance is), persisted in
  runs/heating/orientation.jsonl; heating analyses use heating-oriented
  zones only.
- **Fleet validation (2026-07-23): OK, 0 hard failures.** Heating-oriented
  duty vs outdoor temp negative in ALL 7 buildings (B01 -0.68, B03 -0.47,
  B05 -0.47, B07 -0.57; weak-but-right-sign B02 -0.14, B04 -0.06, B06 -0.09).
  Meter cross-check, all three all-electric buildings: duty tracks main kWh
  at r=+0.84 (B03), +0.79 (B05), +0.88 (B07). The duty-cycle proxy measures
  real energy.
- Orientation side-findings: B01 has 95 idle + 15 cooling + 16 dual T_Gain
  zones (only 116 of 242 heat); B06 has 42 idle. Idle = <2% duty in both
  Dec-Feb and Jun-Aug -- candidates for "heating never used" rooms; keep
  excluded from flexibility, list in the graph with quality flags.
- **Phase 3 step-response fleet (2026-07-23): pre-registered prediction CONFIRMED.**
  Electric buildings (B05/B07) cool faster than hydronic (B01/B02): median
  minutes-to-1K 116 vs 135 (n=105 vs 147 zones with measurable tau).
  Per-building medians: B07=109, B05=120, B01=132, B03=173, B04=206, B02=266,
  B06=274. B06 (district heat, 274 min/K) is the slowest -- mass + slow
  supply temp is the likely driver. B02 (heat-pump+radiant-floor) very slow
  (266), only 2 zones with tau (highly ambiguous dataset).
- **Heating-type verdicts (2026-07-23):** floor-slow dominates B01 (131/244),
  B04 (70/214), B06 (112/133) -- all buildings with slow-responding radiant
  or hydronic systems. Electric-fast zones found in B05 (24), B06 (11), B07
  (11), B03 (6) -- likely panel radiators or electric underfloor. B01 has only
  2 electric-fast zones (confirms primarily hydronic/floor). Ambiguous zones
  (insufficient events or borderline tau) are a significant fraction in B02/B04
  -- shallow event counts in those buildings.
- **Consequence for flexibility ranking:** B07 and B05 have the fastest and most
  data-rich electric zones; B01/B06 have the largest floor-heated mass (best
  pre-heating candidates). B04 remains ambiguous on heating type due to the
  mixed cooling/heating actuator population.
