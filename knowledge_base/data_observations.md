# Data-confirmed observations (name = hypothesis, data = test)

Facts about specific labels/patterns CONFIRMED by cross-checking against the
measurement data (`src/profile/`: series_stats, cross_check, seasonal_check) --
the accumulating feedback loop of CLAUDE.md section 4. Each entry states the
evidence so it can be trusted (and re-derived) without rerunning the analysis.
Scope so far: Tasen 2025 exports.

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
