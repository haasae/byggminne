# S01 "Granlia sykehjem" — synthetic batch answer key (b_synth_s01)

Invented 2026-07-31 for the ChatGPT-as-LLM-leg test. Structure-true per
`knowledge_base/bacnet_sd_label_grammar.md` (worked example + Skøyen layouts),
the Piscada/Bislett `+<loc>_563_<rom>_<komp>_<PV|C>` grammar
(bislett_building_survey.md), and the Kiona examples in `examples/`.
Fictional building: Granlia sykehjem, controller 20099101, gateway
NIE00307F2B44CC, Piscada location tag +3G100077. NOT a real site.

Intended meaning per label (for eyeball scoring — no formal gold):

| # | Label (short) | Intended truth |
|---|---|---|
| 1 | OU001 -RT401 | AHU 1: tilluft/supply temperature (RT, side digit 4) |
| 2 | OU001 -RT501 | AHU 1: avtrekk/return temperature (side digit 5) |
| 3 | OU001 -RD401 | AHU 1: differansetrykk, supply side |
| 4 | OU001 -LR401 | AHU 1: regulator (LR), supply side |
| 5 | OU002 -RT404_WSP | AHU 2: working setpoint on supply temp (WSP glossary) |
| 6 | OU002 360 002-Sch | AHU 2 = system 360.002, schedule point |
| 7 | N2 320001 RT401 | heating system 320.001: tur temp (Analoge innganger) |
| 8 | N2 320001 RT501 | heating 320.001: retur temp |
| 9 | N2 320001 SB42 | heating valve output; 2-digit SB — side-digit rule NOT applicable |
| 10 | N2 320001_bygg2 RT401 | heating branch serving bygg 2, tur temp |
| 11 | ModbusRTU 1204_adr31 Heating control  connector A2 | room 1204 (bygg 1, etg 2) heating actuator 0-100 % (double space verbatim) |
| 12 | 1204_adr31 Temperature | room 1204 temperature |
| 13 | 1204_adr31 CO2 | room 1204 CO2 |
| 14 | 12xx_adr35 Heating control | masked room (bygg 1, etg 2), heating actuator |
| 15 | 140x_adr52 Set point by Modbus | room 140x commanded setpoint |
| 16 | 140x_adr52 Effective Set point | room 140x working setpoint |
| 17 | +3G100077_563_214_RT601_PV | Piscada room control (563): room 214 temperature, present value |
| 18 | +3G100077_563_214_SB601_C | room 214 heating valve, command |
| 19 | +3G100077_563_214_KMD_MSV | room 214 tidsprogram (multi-state), KMD grammar from Bislett |
| 20 | Schedule_GS_320_014_RT630_SPN | Piscada schedule object: night setpoint for room/zone 014 (SPN); heating 320 |
| 21 | Fjernvarme Energi | district heating energy (exact match should hit validated store) |
| 22 | Fjernvarme Volum | district heating volume |
| 23 | 310.001 Varmt tappevann Volum | THE PILOT TRAP: code 310 = sanitary; DHW meaning comes from the TEXT |
| 24 | 432.003 Energi | electrical distribution subsystem energy |
| 25 | 7020099101000021 | 16 digits = main electric meter |
| 26 | OU001 -XZ401 | XZ is NOT a known component code → must stay null, low confidence |
| 27 | OU002 IK001_TEST.Komp_Drift | cooling machine (IK) compressor running status |
| 28 | 313.01 Varmt tappevann Temperatur tur | DHW proper code (313), supply temperature |
| 29 | BACnet IP1 Utganger 563_B214-SB602 | room-control valve output, room B214 (Skøyen layout `<sys3>_<ref>-<code>`) |
| 30 | Ukjent maaler 55882 Granlia paviljong | junk: some meter, pavilion; mostly undecodable → nulls + low confidence |

Traps deliberately planted: #23 (310 ≠ DHW by code), #26 (unknown code —
never invent), #9 (2-digit SB — no side digit), #14/15 (masked rooms), #11
(double space), #30 (graceful degradation).
