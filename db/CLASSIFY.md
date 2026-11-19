# Classification guide (for classifier agents)

Binding contract: `db/SCHEMA.md`. Codes come ONLY from `db/taxonomy.json`; never invent a code.
One taxonomy per subject is applied to every year. Legacy-only content has codes with `L` (math
`1.L1`, `4.L*`, `5.L*`, econ `2.L1`, `4.L1`), extra math topics `6`/`7`/`8`, or physics theme `X`.

## 1. Rules

1. **Classify the whole top-level question** (all parts (a), (b)(i)...). Read the question text AND
   the markscheme: the method in the markscheme decides the subtopic (e.g. "hence" solved by parts -> 5.16).
2. **`subtopics`**: every subtopic that a candidate genuinely has to *use* to earn marks in any
   part. Do not tag incidental arithmetic (e.g. using a log once to solve for n in a GP question is
   still worth `1.7` only if it carries a mark of its own). Typical counts: MCQ 1 (max 2);
   short 1–3; long 2–6; physics P2 long 2–6 across 2–4 themes; econ essay 1–3; econ data 3–6.
3. **`topics`**: the set of parents of the chosen subtopics (no topic without at least one of its
   subtopics, no subtopic without its topic). **Order**: primary first = the topic carrying the most
   marks; ties -> the topic of part (a). Order `subtopics` the same way (primary subtopic first, then
   in order of appearance).
4. **Multi-theme is the norm for long questions — include ALL.** A physics P2 question that starts
   with projectile motion, moves to energy and ends with a charged particle in a field is
   `["A","D"]`/`["A.1","A.3","D.3"]`. An econ P2 data question normally spans its main unit plus the
   policy subtopics asked in later parts and in the final 15-mark (or 4-mark/ 15-mark) part.
5. **Legacy papers**: classify by the *content*, using the mapping tables below — not by the old
   topic number printed anywhere. Legacy math P3 / pre-2006 P2 Section B options: the option fixes
   the default topic (Discrete -> 6, Sets/relations/groups -> 7, Statistics -> 4, Series & DE /
   Calculus / Analysis & approximation -> 5, Euclidean geometry & conics -> 8), but still add core
   subtopics used (e.g. induction 1.15 in a recurrence proof; matrices 1.L1; 4.8 binomial in a stats-option test).
6. **Prefer the AA / new-syllabus code** when it fits; use an `L`/`X` code only when no current
   subtopic covers the skill (e.g. hypothesis test -> 4.L7; Poisson -> 4.L1; capacitor -> X.5).
7. SL-vs-AHL duplicates in math: when the content clearly belongs to one level, choose that one;
   when both fit, tag the more advanced one (e.g. differentiating `tan x` -> 5.15 not 5.6; solving
   `sin 2x = cos x` with a double-angle identity -> 3.6 + 3.8). Inverse function finding with
   restricted domain -> 2.14 (+2.5).
8. Uncertain? Pick the best fit and add flag `"topic-uncertain"` to `flags` (SCHEMA allows free flags).

## 2. qtype

| qtype  | use for |
|--------|---------|
| `mcq`  | Multiple-choice item (physics P1 / P1A). `marks` = 1, set `mcq_answer` A–D from markscheme. |
| `short`| Short structured response: math Section A (P1/P2) and any question ≤ ~8 marks; physics P2 / P1B / old P2 Section B short questions ≤ ~8 marks; legacy P3 option questions ≤ ~8 marks. |
| `long` | Extended multi-part structured problem: math Section B, math P3 (AA and legacy options) of > ~8 marks; physics P2 questions > ~8 marks (most of them), old physics P2 Section B and P3 option questions > ~8 marks. |
| `essay`| Economics P1 (two-part extended response, typically 10 + 15 marks); any prose-only extended-response question. |
| `data` | Data-based / data-analysis question built around a provided data table, graph or text extract: economics P2 (all), physics P1B and the physics data-analysis question (legacy P2 Q1 / P3 Section A experimental question). |

Thresholds are guidance; the paper's own section structure wins (math "Section B" is always `long`).

## 3. Legacy -> new mapping tables

### 3.1 Physics (2009 syllabus: exams to 2015; 2014 syllabus: exams 2016–2024)

| Legacy content | New code(s) |
|---|---|
| T1 Physics & physical measurement / Measurements & uncertainties (SI units, orders of magnitude, error bars, gradient uncertainty, vectors & scalars) | X.1 |
| T2 Mechanics: kinematics, projectiles, fluid resistance | A.1 |
| T2 Newton's laws, momentum, impulse, collisions; circular motion (2009 T2.4 / 2014 T6.1) | A.2 |
| T2 Work, energy, power, efficiency, Sankey diagrams | A.3 |
| T3 Thermal physics: internal energy, specific heat, latent heat, temperature | B.1 |
| T3 Kinetic model, ideal gases, pressure (pV = nRT, molecular KE) | B.3 |
| 2009 T10 / 2014 Option B.2 Thermodynamics: first law, pV diagrams, cycles, entropy, second law, heat engines | B.4 |
| 2009 T8 / 2014 T8.2 Black-body radiation, Stefan–Boltzmann, Wien, emissivity | B.1 |
| 2009 T8 / 2014 T8.2 Albedo, greenhouse effect, energy balance, global warming | B.2 |
| 2009 T8 / 2014 T8.1 Energy sources, fossil fuels, nuclear power stations (reactor design), wind, hydro, solar, energy density | X.3 (+E.4 for fission physics) |
| T4 Oscillations, SHM, energy in SHM (2009 T4, T9.1 / 2014 T4.1, T9.1) | C.1 |
| T4 Travelling waves, wave equation, EM spectrum, transverse/longitudinal | C.2 |
| Reflection, refraction, Snell's law, critical angle, diffraction, two-source interference, single slit, multiple slits / gratings (T4.4, T9.2, T9.3; 2009 T11, G) | C.3 |
| Thin-film interference, polarization & Malus's law, resolution / Rayleigh criterion, lasers (2009 G, T11; 2014 T4.3, T9.3, T9.4) | X.4 (+C.3 if two-slit/diffraction core is also used) |
| Standing waves, pipes & strings, damping, forced oscillations & resonance (T4.5; 2009 T11; 2014 Option B.4) | C.4 |
| Doppler effect (sound & light, redshift Δλ/λ ≈ v/c) | C.5 |
| T5 Electric current, drift speed, resistance, resistivity, circuits, potential dividers, internal resistance, cells, meters | B.5 |
| T5/T6 Electric field, Coulomb's law, charge | D.2 |
| T6 Magnetic fields of wires/solenoids, force on current & on moving charge; charged particles in fields (incl. mass spectrometer) | D.2 (field) / D.3 (motion of charges, force on conductor) |
| T6 Gravitational force & field; 2009 T9 / 2014 T10 gravitational potential, escape speed, orbits, satellites | D.1 |
| 2014 T10 electric potential & potential energy, equipotentials, field lines | D.2 |
| 2009 T12 / 2014 T11.1 EM induction, Faraday, Lenz, flux, generators | D.4 |
| 2009 T12 / 2014 T11.2 AC, rms, transformers, power transmission, rectification | X.6 (+D.4 if induction law used) |
| 2014 T11.3 Capacitance, RC circuits, time constant | X.5 |
| T7 Atomic structure, Rutherford, energy levels, spectra; nuclear radius (2014 T12.2) | E.1 |
| T7 Radioactivity, half-life, decay equations, mass defect, binding energy, decay constant (2009 T13.2 / 2014 T12.2) | E.3 |
| Fission (incl. chain reactions, critical mass) | E.4 |
| Fusion; stars' energy source | E.5 |
| 2009 T13.1 / 2014 T12.1 Photoelectric effect, de Broglie, matter waves, Bohr model, Schrödinger, uncertainty principle, tunnelling, pair production | E.2 (Bohr energy levels -> also E.1) |
| 2014 T7.3 / 2009 Option J Particle physics: quarks, leptons, exchange particles, Feynman diagrams, conservation laws, accelerators/detectors | X.2 |
| 2009 T14 Digital technology: analogue/digital, CDs/DVDs, CCDs | X.13 |
| 2009 Option F Communications: modulation, digital signals, channels, op-amps, mobile phones; fibre optics in F | X.14; fibre -> X.10 |
| 2009 Option G Electromagnetic waves: lenses, instruments; lasers; interference/diffraction; X-ray diffraction | X.9; X.4; C.3; X.4 |
| 2009 Option H / 2014 Option A Relativity: frames, Galilean, postulates, Lorentz, time dilation, length contraction, spacetime diagrams, simultaneity, twin paradox, muon decay | A.5 |
| Relativistic momentum & energy, mass–energy, particle acceleration (2014 A.4) ; general relativity, equivalence principle, gravitational redshift, black holes (2014 A.5, 2009 H) | X.7 |
| 2014 Option B.1 Rigid bodies & rotational dynamics (torque, moment of inertia, angular momentum) | A.4 |
| 2014 Option B.3 Fluids & fluid dynamics (buoyancy, Pascal, Bernoulli, Stokes, Reynolds) | X.8 |
| 2014 Option C.1/C.2 Imaging: lenses, mirrors, aberrations, microscopes, telescopes, radio telescopes | X.9 |
| 2014 Option C.3 Fibre optics (attenuation, dispersion, dB) | X.10 |
| 2014 Option C.4 / 2009 Option I Medical imaging & physics: X-rays, attenuation, ultrasound, MRI, CT, PET, dosimetry, hearing | X.11 |
| 2009 Option E / 2014 Option D.1–D.2, D.4 Stellar quantities (parallax, luminosity, apparent brightness), HR diagram, stellar evolution, Wien for stars, nucleosynthesis, Jeans criterion, Chandrasekhar / Oppenheimer–Volkoff | E.5 |
| 2014 Option D.3, D.5 / 2009 E Cosmology: Hubble's law, CMB, Big Bang, expansion, dark matter/energy, critical density, rotation curves | X.12 (+C.5 if redshift via Doppler formula) |

### 3.2 Economics (legacy 2011 syllabus: exams to Nov 2021; 2010 papers likewise)

| Legacy section | New code(s) |
|---|---|
| Micro 1.1 Competitive markets: demand | 2.1 |
| Micro 1.1 supply | 2.2 |
| Micro 1.1 market equilibrium, price mechanism, consumer/producer surplus, allocative efficiency | 2.3 |
| Micro 1.2 PED, XED, YED | 2.5 |
| Micro 1.2 PES | 2.6 |
| Micro 1.3 Government intervention: indirect taxes, subsidies, price ceilings/floors | 2.7 |
| Micro 1.4 Market failure: externalities, merit/demerit goods, common access resources, sustainability | 2.8 |
| Micro 1.4 public goods | 2.9 |
| Micro 1.4 asymmetric information | 2.10 |
| Micro 1.4 abuse of monopoly power; 1.5 market structures (monopoly, oligopoly, monopolistic competition) | 2.11 |
| Micro 1.5 HL theory of the firm: costs, revenues, profit maximisation, perfect competition, efficiency, price discrimination | 2.L1 (+2.11 for market-power/structure parts) |
| Scarcity, choice, opportunity cost, PPC, economic systems, (2010) central themes | 1.1 / 1.2 |
| Macro 2.1 Overall economic activity: circular flow, GDP/GNI measurement, business cycle | 3.1 |
| Macro 2.2 Aggregate demand and aggregate supply, multiplier | 3.2 |
| Macro 2.3 Low unemployment, low and stable inflation, economic growth | 3.3 |
| Macro 2.3 Equity in income distribution, taxation, Lorenz/Gini, poverty, transfer payments | 3.4 |
| Macro 2.4 Fiscal policy | 3.6 |
| Macro 2.5 Monetary policy, central banks, interest rates | 3.5 |
| Macro 2.6 Supply-side policies | 3.7 |
| International 3.1 Free trade, comparative/absolute advantage, WTO | 4.1 |
| International 3.1 tariffs, quotas, subsidies, administrative barriers | 4.2 |
| International 3.1 arguments for/against protection | 4.3 |
| International 3.2 Exchange rates (floating/fixed/managed, appreciation, depreciation) | 4.5 |
| International 3.3 Balance of payments (current/capital/financial account, deficits, Marshall–Lerner, J-curve) | 4.6 |
| International 3.4 Economic integration (FTAs, customs unions, common markets, monetary union) | 4.4 |
| International 3.5 Terms of trade (HL) | 4.L1 |
| Development 4.1 Economic growth vs development, sustainable development | 4.7 (growth only -> 3.3) |
| Development 4.2 Measuring development (GDP per capita PPP, HDI, composite indicators) | 4.8 |
| Development 4.3 Domestic factors (education, health, infrastructure, credit, gender, institutions) | 4.9 (+4.10 when asked as strategies) |
| Development 4.4 International trade & development (diversification, primary commodities, trade strategies) | 4.10 (+4.9 for barriers) |
| Development 4.5 FDI and MNCs; 4.6 Foreign aid & multilateral assistance; 4.7 International debt | 4.10 (debt as barrier -> 4.9) |
| Development 4.8 Balance between markets and intervention | 4.10 |

Econ P1 (essay) usually = one unit, 1–3 subtopics. Econ P2 data questions: always tag the definition/
diagram parts (e.g. 2.3, 2.5) and the evaluation part (e.g. 4.2 + 4.3), so 3–6 subtopics is normal.

### 3.3 Mathematics HL legacy (1995–2020)

| Legacy content / option | Code(s) |
|---|---|
| Core algebra, functions, circular functions & trig, vectors, statistics & probability, calculus | matching 1.x / 2.x / 3.x / 4.x / 5.x |
| Matrices: algebra, determinants, inverses, matrix transformations (core pre-2014) | 1.L1 (+1.16 if solving a system) |
| Poisson distribution (core 2006–2014, stats option) | 4.L1 |
| Stats option: geometric/negative binomial -> 4.L2 ; cdf, pgf -> 4.L3 ; linear combinations of RVs -> 4.L4 ; CLT, unbiased estimators, sampling distributions -> 4.L5 ; confidence intervals (z, t) -> 4.L6 ; hypothesis tests, critical regions, type I/II errors -> 4.L7 ; bivariate normal, test for rho, regression inference -> 4.L8 ; chi-squared GOF/contingency -> 4.L9 ; Bayes -> 4.13 ; continuous RVs -> 4.14 | see left |
| Series & differential equations / Calculus option (2006–2020) & Analysis and approximation (pre-2006): limits & L'Hopital -> 5.13 ; continuity/differentiability -> 5.12 ; Rolle, MVT, FTC -> 5.L4 ; Riemann sums, improper integrals, integral bounds on sums -> 5.L5 ; series convergence tests (comparison, limit comparison, ratio, integral, alternating, p-series) -> 5.L1 ; power series, radius/interval of convergence -> 5.L2 ; Taylor series & Lagrange error -> 5.L3 ; Maclaurin -> 5.19 ; DEs (separable, homogeneous, integrating factor, Euler) -> 5.18 ; Newton–Raphson, fixed-point iteration, trapezium/Simpson -> 5.L6 ; limits of sequences, epsilon-delta -> 5.L7 | see left |
| Discrete mathematics option | 6.1–6.12 (+1.15 induction, 1.L1 matrices for adjacency powers -> 6.11) |
| Sets, relations and groups option | 7.1–7.9 |
| Euclidean geometry and conic sections (pre-2006 P2 Section B) | 8.1 / 8.2 / 8.3 |
| Pre-2006 P2 Section B "Statistics" option | 4.x / 4.L* as above |

AA HL P3 (2021+) is not an option paper: classify it like any long question (usually 3–5 subtopics).

## 4. Worked examples

### Math
1. *2015 M P1 TZ1, Section A, 6 marks*: "Find the term independent of x in (2x − 1/x²)⁹" ->
   qtype `short`, topics `["1"]`, subtopics `["1.9"]`.
2. *2017 M P2, Section B, 16 marks*: (a) find intersection of line L and plane Π; (b) angle between L
   and Π; (c) find the plane containing L perpendicular to Π using a cross product ->
   `long`, topics `["3"]`, subtopics `["3.18","3.14","3.17","3.16"]`.
3. *2012 M P3 Series & DE, 11 marks*: solve dy/dx + y tan x = cos x by integrating factor, then
   find Maclaurin series of the solution up to x³ -> `long`, topics `["5"]`,
   subtopics `["5.18","5.19","5.15"]`. *(Discrete option, 9 marks: show 7ⁿ ≡ 1 (mod 3) by
   induction and solve 4x ≡ 5 (mod 9))* -> topics `["6","1"]`, subtopics `["6.4","1.15"]`.

### Physics
1. *2018 M P1 TZ1 Q12 (MCQ)*: "A gas at constant volume is heated; which graph shows p vs T?" ->
   `mcq`, marks 1, topics `["B"]`, subtopics `["B.3"]`, `mcq_answer` from markscheme.
2. *2019 N P2 Q3, 14 marks*: (a) ball projected horizontally from a cliff — time of flight and
   range; (b) kinetic energy at impact and energy lost to air resistance; (c) the ball is charged and
   enters a uniform magnetic field — radius of circular path ->
   `long`, topics `["A","D"]`, subtopics `["A.1","A.3","D.3"]`.
3. *2016 M P2 TZ2, 12 marks*: (a) uranium-235 fission equation & energy released from mass defect;
   (b) Sankey diagram / efficiency of a nuclear power station; (c) half-life of a waste product;
   (d) uncertainty in the measured activity ->
   `long`, topics `["E","X","A"]`, subtopics `["E.4","E.3","X.3","A.3","X.1"]`
   (E carries most marks, so it is primary).

### Economics
1. *2017 M P1 (essay)*: (a) "Explain why the price elasticity of demand for agricultural products
   is low" [10]; (b) "Evaluate the use of price floors to support farmers' incomes" [15] ->
   `essay`, topics `["2"]`, subtopics `["2.5","2.7"]`.
2. *2019 N P2 (data, legacy International)*: text on a country raising tariffs on steel; (a)(i)
   define *depreciation*, (a)(ii) define *tariff*; (b) diagram of tariff effect; (c) exchange-rate
   diagram; (d) "evaluate the impact of the tariffs on the economy" [8] ->
   `data`, topics `["4"]`, subtopics `["4.2","4.5","4.3"]`.
3. *2023 M P2 (data, 2020 syllabus)*: extract on rising inflation and unemployment in a country;
   define *GDP*; AD/AS diagram; calculate real GDP growth; (g) evaluate the use of
   contractionary monetary policy [15] ->
   `data`, topics `["3"]`, subtopics `["3.2","3.1","3.3","3.5"]`; if an extract part asks about
   income inequality, add `3.4`; if about exports/exchange rate, add topic `4` + `4.5`.

(Exam IDs in examples are illustrative of the question style; do not copy their codes blindly.)
