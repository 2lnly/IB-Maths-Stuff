#!/usr/bin/env python3
"""
Classify all extracted IB Physics HL questions using Claude Haiku.

For each question, sends the image to Claude Haiku and gets:
- topic_code / topic_name
- subtopic_code / subtopic_name
- description (one line)
- difficulty (1-5)

Output: data/physics_question_bank.json
Checkpoint: data/physics_classification_checkpoint.json

Run with ANTHROPIC_API_KEY set in environment.
Checkpoints every 100 questions so it can be resumed safely.
"""

import anthropic
import base64
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
PRACTICE_DIR = BASE_DIR / "practice_physics"
OUTPUT_PATH = BASE_DIR / "data" / "physics_question_bank.json"
CHECKPOINT_PATH = BASE_DIR / "data" / "physics_classification_checkpoint.json"

# IB Physics HL taxonomy — both pre-2023 and new 2023+ curricula
TAXONOMY = """
IB Physics HL Topic Taxonomy:

=== PRE-2023 CURRICULUM (use when curriculum=pre-2023) ===

Topic 1: Measurements & Uncertainties
  1.1  Measurements in Physics
       - SI units, fundamental and derived units, scientific notation
       - Orders of magnitude, significant figures
  1.2  Uncertainties and Errors
       - Random and systematic errors
       - Absolute, fractional, percentage uncertainties
       - Propagation of uncertainties; error bars, line of best fit
  1.3  Vectors and Scalars
       - Vector addition, subtraction, components
       - Resolving vectors

Topic 2: Mechanics
  2.1  Motion
       - Displacement, velocity, acceleration
       - Uniform and non-uniform acceleration; SUVAT equations
       - Graphs of motion; projectile motion
  2.2  Forces
       - Newton's three laws
       - Free-body diagrams; normal force, friction, tension
       - Inclined planes, Atwood machine
  2.3  Work, Energy and Power
       - Work done by a constant and variable force
       - Kinetic energy, gravitational and elastic potential energy
       - Conservation of energy; power; efficiency
  2.4  Momentum and Impulse
       - Linear momentum; Newton's second law in terms of momentum
       - Impulse; conservation of momentum
       - Elastic and inelastic collisions; explosions

Topic 3: Thermal Physics
  3.1  Thermal Concepts
       - Temperature, internal energy, heat
       - Specific heat capacity; specific latent heat
       - Phase changes; heating/cooling curves
  3.2  Modelling a Gas
       - Ideal gas model; pressure, volume, temperature
       - Boyle's, Charles's, Gay-Lussac's, ideal gas laws (pV = nRT)
       - Kinetic theory of gases; mean kinetic energy

Topic 4: Waves
  4.1  Oscillations
       - Simple harmonic motion: characteristics, equations
       - Period, frequency, amplitude, phase
  4.2  Travelling Waves
       - Wave types (transverse, longitudinal); wave speed
       - Frequency, wavelength, amplitude, intensity
       - Electromagnetic spectrum
  4.3  Wave Characteristics
       - Wavefronts and rays
       - Amplitude, intensity, superposition
  4.4  Wave Behaviour
       - Reflection, refraction (Snell's law)
       - Single-slit and double-slit diffraction; diffraction gratings
       - Young's double-slit experiment; thin film interference
  4.5  Standing Waves
       - Formation of standing waves
       - Nodes and antinodes; harmonics in strings and pipes

Topic 5: Electricity and Magnetism
  5.1  Electric Fields
       - Coulomb's law; electric field strength
       - Uniform electric field; electric potential
  5.2  Heating Effect of Electric Currents
       - Current, voltage, resistance; Ohm's law
       - Resistivity; combinations of resistors (series/parallel)
       - Power dissipation; I-V characteristics
  5.3  Electric Cells
       - EMF and internal resistance
       - Terminal voltage; efficiency of cells
  5.4  Magnetic Effects of Electric Currents
       - Magnetic field due to currents (wires, solenoids)
       - Force on current-carrying conductors; F = BIL sin θ
       - Force on moving charges; F = qvB sin θ; Hall effect

Topic 6: Circular Motion and Gravitation
  6.1  Circular Motion
       - Period, frequency, angular velocity, centripetal acceleration
       - Centripetal force; examples (banked tracks, conical pendulum)
  6.2  Newton's Law of Gravitation
       - Gravitational field strength g; gravitational potential
       - Orbital motion; Kepler's third law

Topic 7: Atomic, Nuclear and Particle Physics
  7.1  Discrete Energy and Radioactivity
       - Atomic spectra; energy levels; photons
       - Types of radioactive decay (α, β, γ); nuclear equations
       - Half-life; decay constant; radioactive decay law
  7.2  Nuclear Reactions
       - Mass defect and binding energy; nuclear stability
       - Fission and fusion; energy released per nucleon
  7.3  The Structure of Matter
       - Fundamental particles: quarks, leptons, hadrons, bosons
       - Quark model; conservation laws; Feynman diagrams

Topic 8: Energy Production
  8.1  Energy Sources
       - Fossil fuels, nuclear, solar, wind, hydroelectric, biofuels
       - Energy density, capacity factor
       - Sankey diagrams; primary and secondary energy
  8.2  Thermal Energy Transfer
       - Conduction, convection, radiation
       - Black-body radiation; Stefan-Boltzmann law; Wien's law
       - Greenhouse effect; albedo; emissivity

Topic 9: Wave Phenomena (HL)
  9.1  Simple Harmonic Motion
       - SHM equations; energy in SHM
       - Damping; resonance; natural frequency
  9.2  Single-Slit Diffraction
       - Diffraction pattern; central maximum width
       - Condition for first minimum: sin θ = λ/b
  9.3  Interference
       - Young's double-slit; path difference
       - Diffraction grating; thin-film interference; multiple slits
  9.4  Resolution
       - Rayleigh criterion; resolving power of telescopes and microscopes
  9.5  Doppler Effect
       - Moving source and observer; Doppler equation
       - Applications: radar, medical ultrasound, red-shift

Topic 10: Fields (HL)
  10.1  Describing Fields
        - Gravitational and electric field lines and equipotentials
        - Field strength, potential, potential gradient
        - Analogy between gravitational and electric fields
  10.2  Fields at Work
        - Orbital motion and escape speed
        - Potential wells; work done in moving a mass/charge
        - Charged particle in combined electric and magnetic fields

Topic 11: Electromagnetic Induction (HL)
  11.1  Electromagnetic Induction
        - Magnetic flux; Faraday's and Lenz's laws
        - EMF induced by a moving conductor
  11.2  Power Generation and Transmission
        - AC generators; sinusoidal output
        - Transformers; transmission losses
        - Rectification; half-wave and full-wave
  11.3  Capacitance
        - Capacitors in series and parallel; energy stored
        - Capacitor charging and discharging; RC circuits; time constant

Topic 12: Quantum and Nuclear Physics (HL)
  12.1  The Interaction of Matter with Radiation
        - Photoelectric effect; photon model; work function
        - Compton scattering; pair production and annihilation
        - Wave-particle duality; de Broglie wavelength
        - Heisenberg uncertainty principle
  12.2  Nuclear Physics
        - Rutherford scattering; nuclear radius
        - Nuclear energy levels; gamma emission
        - Radioactive decay law; activity; binding energy per nucleon
        - Neutrinos; beta-plus and beta-minus decay

Option A: Relativity
  A.1  The Beginning of Relativity
  A.2  Lorentz Transformations
  A.3  Spacetime Diagrams
  A.4  Relativistic Mechanics (HL)
  A.5  General Relativity (HL)

Option B: Engineering Physics
  B.1  Rigid Bodies and Rotational Dynamics
  B.2  Thermodynamics
  B.3  Fluids and Fluid Dynamics (HL)
  B.4  Forced Vibrations and Resonance (HL)

Option C: Imaging
  C.1  Introduction to Imaging
  C.2  Imaging Instrumentation
  C.3  Fibre Optics
  C.4  Medical Imaging (HL)

Option D: Astrophysics
  D.1  Stellar Quantities
  D.2  Stellar Characteristics and Stellar Evolution
  D.3  Cosmology
  D.4  Stellar Processes (HL)
  D.5  Further Cosmology (HL)

=== NEW 2023+ CURRICULUM (use when curriculum=new) ===

Theme A: Space, Time and Motion
  A.1  Kinematics
       - Displacement, velocity, acceleration (average and instantaneous)
       - Uniform acceleration; SUVAT equations
       - Graphs of motion; projectile motion; relative motion
  A.2  Forces and Momentum
       - Newton's three laws; free-body diagrams
       - Friction (static and dynamic); tension; normal force
       - Linear momentum; impulse; conservation of momentum
       - Elastic and inelastic collisions
  A.3  Work, Energy and Power
       - Work done by constant and variable forces
       - Kinetic, gravitational potential, and elastic potential energy
       - Conservation of energy; power and efficiency
  A.4  Rigid Body Mechanics (HL)
       - Torque and moment of inertia
       - Rotational kinematics and dynamics
       - Angular momentum; conservation of angular momentum
       - Rolling without slipping
  A.5  Galilean and Special Relativity (HL)
       - Galilean relativity and reference frames
       - Postulates of special relativity
       - Time dilation and length contraction
       - Relativistic momentum, energy; mass-energy equivalence
       - Spacetime diagrams; simultaneity

Theme B: The Particulate Nature of Matter
  B.1  Thermal Energy Transfers
       - Temperature scales; internal energy
       - Specific heat capacity; specific latent heat; phase changes
       - Conduction, convection, radiation; black-body radiation
       - Stefan-Boltzmann law; Wien's displacement law
  B.2  Greenhouse Effect
       - Solar radiation and Earth's energy balance
       - Albedo; emissivity; greenhouse gases
       - Global warming; climate models
  B.3  Gas Laws
       - Ideal gas model; empirical gas laws
       - Ideal gas equation (pV = nRT); molar quantities
       - Kinetic theory; mean kinetic energy; root-mean-square speed
  B.4  Thermodynamics (HL)
       - First law of thermodynamics; internal energy changes
       - Isothermal, adiabatic, isobaric, isovolumetric processes
       - Second law; entropy; Carnot cycle and efficiency
  B.5  Current and Circuits
       - Electric current; drift velocity; charge carriers
       - Resistance; resistivity; Ohm's law; I-V characteristics
       - EMF and internal resistance; terminal voltage
       - Series and parallel circuits; Kirchhoff's laws
       - Power dissipation; potential dividers

Theme C: Wave Behaviour
  C.1  Simple Harmonic Motion
       - Defining SHM; restoring force; equations of motion
       - Energy in SHM; kinetic and potential energy
       - Damping; resonance; natural frequency; Q-factor (HL)
  C.2  Wave Model
       - Transverse and longitudinal waves; wave speed, frequency, wavelength
       - Intensity; superposition; standing waves
       - Nodes and antinodes; harmonics in strings and pipes
  C.3  Wave Phenomena
       - Reflection and refraction; Snell's law; total internal reflection
       - Single-slit diffraction; double-slit interference
       - Diffraction gratings; thin-film interference
       - Polarisation; Malus's law
  C.4  Standing Waves and Resonance
       - Formation of standing waves; boundary conditions
       - Resonant frequencies; harmonics and overtones
       - Applications: musical instruments, microwave cavities
  C.5  Doppler Effect
       - Doppler equation for moving source and observer
       - Applications: radar, ultrasound, red-shift of stars

Theme D: Fields
  D.1  Gravitational Fields
       - Newton's law of gravitation; gravitational field strength
       - Gravitational potential energy and potential
       - Orbital speed, period, and radius; Kepler's third law
       - Escape speed; satellites; weightlessness
  D.2  Electric and Magnetic Fields
       - Coulomb's law; electric field strength; field lines
       - Electric potential energy and potential; equipotentials
       - Magnetic field; force on current-carrying conductor (F = BIL sin θ)
       - Force on moving charge (F = qvB sin θ); Hall effect
  D.3  Motion in Electromagnetic Fields
       - Charged particle in uniform electric and magnetic fields
       - Velocity selector; mass spectrometer; cyclotron (HL)
       - Magnetic force providing centripetal acceleration
  D.4  Induction (HL)
       - Magnetic flux; Faraday's law; Lenz's law
       - EMF from moving conductor; generators
       - Transformers; AC transmission and rectification
       - Inductance; RL circuits; LC oscillations

Theme E: Nuclear and Quantum Physics
  E.1  Structure of the Atom
       - Atomic models; Rutherford scattering experiment
       - Nuclear composition; atomic number, mass number, isotopes
  E.2  Quantum Models of the Atom
       - Bohr model; energy levels; emission and absorption spectra
       - Photon energy; ionisation; excitation
       - Wave-particle duality; de Broglie wavelength
       - Heisenberg uncertainty principle (HL)
  E.3  Radioactive Decay
       - Types of decay (α, β⁻, β⁺, γ); nuclear equations
       - Decay constant; half-life; radioactive decay law; activity
       - Background radiation; uses of radioisotopes
  E.4  Fission
       - Mass defect; binding energy; binding energy per nucleon
       - Nuclear fission; chain reaction; nuclear reactors
       - Safety and waste management
  E.5  Fusion and Stars
       - Nuclear fusion; conditions for fusion
       - Stellar energy production; proton-proton chain
       - Hertzsprung-Russell diagram; stellar evolution
  E.6  Electromagnetic Radiation from Stars
       - Blackbody radiation; Wien's law; Stefan-Boltzmann law
       - Luminosity; apparent brightness; parsec; light-year
       - Stellar spectra; Hubble's law; red-shift; age of universe

Tools (Experimental and Inquiry Skills)
  Tools.1  Experimental Design
           - Variables; control of variables; hypothesis
           - Apparatus selection; risk assessment
  Tools.2  Collecting and Recording Data
           - Measurements; uncertainties; significant figures
           - Tables; graphs; error bars
  Tools.3  Processing and Analysing Data
           - Calculations; propagation of uncertainties
           - Linearisation; gradient and intercept analysis
  Tools.4  Evaluating and Improving
           - Systematic and random errors; improving experiments
           - Conclusion drawing; evaluation of method

Synoptic Assessment (multi-topic questions linking concepts across themes)
"""

DIFFICULTY_GUIDE = """
Difficulty scale 1-5:
  1 = Routine recall or single-step calculation (typically 1-3 marks)
  2 = Standard application of a single concept (typically 3-5 marks)
  3 = Multi-step problem requiring two or more concepts (typically 5-8 marks)
  4 = Challenging synthesis, non-obvious approach, or extended working (typically 8-12 marks)
  5 = Extended investigation or very high cognitive demand (typically 12+ marks)
"""

CLASSIFICATION_PROMPT = """You are classifying an IB Physics Higher Level exam question.

{taxonomy}

{difficulty}

The question's curriculum field tells you which syllabus it belongs to:
- If curriculum=pre-2023: use the PRE-2023 CURRICULUM topics (numbered 1-12 and Options A-D)
- If curriculum=new: use the NEW 2023+ CURRICULUM themes (lettered A-E, plus Tools or Synoptic)

The curriculum for this question is: {curriculum}

Look at the question image and respond with ONLY a JSON object (no markdown, no code fences):
{{
  "topic_code": "2",
  "topic_name": "Mechanics",
  "subtopic_code": "2.1",
  "subtopic_name": "Motion",
  "description": "One-line description of what the question asks",
  "difficulty": 2,
  "marks": 4
}}

Rules:
- For pre-2023: topic_code must be "1"-"12" or "A"-"D" (for Options A=Relativity, B=Engineering, C=Imaging, D=Astrophysics)
- For new 2023+: topic_code must be "A"-"E", "Tools", or "Synoptic"
- topic_name must exactly match the topic/theme name in the taxonomy above
- subtopic_code must exactly match a code from the appropriate taxonomy (e.g. "2.1", "9.3", "A.2", "D.4", "Tools.1")
- subtopic_name must exactly match the subtopic name from the taxonomy
- marks: read from "[Maximum mark: N]" if visible, otherwise estimate from question length
- difficulty: 1=routine single-step, 2=standard application, 3=multi-step, 4=challenging, 5=extended
- Choose the PRIMARY topic/subtopic even if the question touches multiple areas
- If the question tests experimental skills or data analysis without a clear physics topic, use Tools"""


def load_question_image(question_dir):
    """Load the question image as base64, resizing if any dimension exceeds 7900px."""
    from PIL import Image
    import io
    img_path = question_dir / "question_p1.png"
    if not img_path.exists():
        return None
    img = Image.open(img_path)
    w, h = img.size
    max_dim = 7900
    if w > max_dim or h > max_dim:
        scale = max_dim / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def load_source_info(question_dir):
    """Load source_info.txt as a dict."""
    src_path = question_dir / "source_info.txt"
    info = {}
    if src_path.exists():
        with open(src_path) as f:
            for line in f:
                if ":" in line:
                    key, _, val = line.partition(":")
                    info[key.strip().lower().replace(" ", "_")] = val.strip()
    return info


def classify_question(client, question_dir, curriculum):
    """Classify a single question using Claude Haiku. Returns classification dict or None."""
    img_b64 = load_question_image(question_dir)
    if img_b64 is None:
        return None

    prompt = CLASSIFICATION_PROMPT.format(
        taxonomy=TAXONOMY,
        difficulty=DIFFICULTY_GUIDE,
        curriculum=curriculum,
    )

    import time
    for attempt in range(5):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": img_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )

            text = response.content[0].text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            result = json.loads(text)
            return result

        except json.JSONDecodeError as e:
            print(f"    JSON parse error: {e}, response: {text[:100]}")
            return None
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                wait = 10 * (2 ** attempt)
                print(f"    Rate limit hit (attempt {attempt+1}/5), waiting {wait}s...")
                time.sleep(wait)
                continue
            # Non-retriable error (e.g. 400 image too large — shouldn't happen after resize)
            print(f"    API error: {e}")
            return None
    print(f"    Gave up after 5 attempts")
    return None


def parse_question_id(question_id):
    """Parse PHY_P{N}_{year}_{session}_{tz}_Q{nn} into components.

    Returns dict with paper_num, year, session, tz.
    """
    # Format: PHY_P1_2023_May_TZ1_Q01 or PHY_P1_2023_November_Q01
    match = re.match(
        r'^PHY_P(\d+)_(\d{4})_(May|November)(?:_(TZ\d))?_Q(\d+)$',
        question_id
    )
    if match:
        return {
            "paper_num": int(match.group(1)),
            "year": int(match.group(2)),
            "session": match.group(3),
            "tz": match.group(4),
            "question_num": int(match.group(5)),
        }
    return {}


import re


def build_question_entry(question_id, question_dir, source_info, classification):
    """Build the final question bank entry."""
    # Parse paper num from question_id (PHY_P{N}_...)
    parsed_id = parse_question_id(question_id)
    paper_num = parsed_id.get("paper_num")
    if paper_num is None:
        # Fallback: parse from directory parent name
        paper_folder = question_dir.parent.name  # "paper 1"
        try:
            paper_num = int(paper_folder.split()[-1])
        except (ValueError, IndexError):
            paper_num = None

    # Parse session from source_info
    session_raw = source_info.get("session", "")
    if "_" in session_raw:
        parts = session_raw.split("_")
        session = parts[0]
        tz = parts[1] if len(parts) > 1 else None
    else:
        session = session_raw
        tz = None

    year = int(source_info.get("year", 0))
    original_q = source_info.get("original_question", "Q?").lstrip("Q")
    try:
        original_q_num = int(original_q)
    except ValueError:
        original_q_num = None

    marks_from_source = source_info.get("marks")
    marks_from_classification = classification.get("marks") if classification else None

    # Prefer source-extracted marks (from [Maximum mark: N]) over AI estimate
    marks = None
    if marks_from_source:
        try:
            marks = int(marks_from_source)
        except ValueError:
            pass
    if marks is None and marks_from_classification:
        try:
            marks = int(marks_from_classification)
        except (ValueError, TypeError):
            pass

    has_answer = (question_dir / "answer_p1.png").exists()

    # Determine section (A = short, B = long) for Paper 1 and 2
    section = None
    if paper_num in [1, 2] and original_q_num:
        if marks and marks <= 8:
            section = "A"
        elif marks and marks > 8:
            section = "B"

    curriculum = source_info.get("curriculum", "pre-2023")
    is_scan = source_info.get("is_scan", "false").lower() == "true"

    entry = {
        "question_id": question_id,
        "paper": f"Paper{paper_num}" if paper_num else "Unknown",
        "paper_num": paper_num,
        "year": year,
        "session": session,
        "tz": tz,
        "curriculum": curriculum,
        "original_question_num": original_q_num,
        "section": section,
        "marks": marks,
        "has_answer": has_answer,
        "is_scan": is_scan,
        "display_mode": "image",
        "path": str(question_dir.relative_to(BASE_DIR)),
    }

    if classification:
        entry.update({
            "topic_code": classification.get("topic_code"),
            "topic_name": classification.get("topic_name"),
            "subtopic_code": classification.get("subtopic_code"),
            "subtopic_name": classification.get("subtopic_name"),
            "description": classification.get("description"),
            "difficulty": classification.get("difficulty"),
        })
    else:
        entry.update({
            "topic_code": None,
            "topic_name": None,
            "subtopic_code": None,
            "subtopic_name": None,
            "description": None,
            "difficulty": None,
        })

    return entry


def load_checkpoint():
    """Load checkpoint of already-classified question IDs."""
    if CHECKPOINT_PATH.exists():
        with open(CHECKPOINT_PATH) as f:
            return json.load(f)
    return {}


def save_checkpoint(question_bank):
    """Save current progress."""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_PATH, "w") as f:
        json.dump(question_bank, f)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Classify IB Physics HL questions with Claude Haiku")
    parser.add_argument("--paper", type=int, choices=[1, 2, 3], help="Only process this paper")
    parser.add_argument("--year", type=int, help="Only process this year")
    parser.add_argument("--limit", type=int, help="Process only N questions (for testing)")
    parser.add_argument("--force", action="store_true", help="Re-classify already done questions")
    parser.add_argument("--no-api", action="store_true", help="Skip API calls, just build metadata (for testing)")
    args = parser.parse_args()

    if not PRACTICE_DIR.exists():
        print(f"ERROR: Practice directory not found: {PRACTICE_DIR}")
        print("Run scripts/extract_physics_questions.py first.")
        sys.exit(1)

    # Load existing progress
    question_bank = load_checkpoint()
    print(f"Loaded {len(question_bank)} previously classified questions")

    # Discover all question directories
    all_dirs = []
    for paper_num in [1, 2, 3]:
        if args.paper and paper_num != args.paper:
            continue
        paper_dir = PRACTICE_DIR / f"paper {paper_num}"
        if not paper_dir.exists():
            continue
        for q_dir in sorted(paper_dir.iterdir()):
            if not q_dir.is_dir():
                continue
            src = load_source_info(q_dir)
            if args.year and src.get("year") != str(args.year):
                continue
            all_dirs.append(q_dir)

    print(f"Found {len(all_dirs)} question directories")

    # Filter out already classified (unless --force)
    to_classify = []
    for q_dir in all_dirs:
        q_id = q_dir.name
        already_done = q_id in question_bank and question_bank[q_id].get("topic_code") is not None
        if not already_done or args.force:
            to_classify.append(q_dir)

    print(f"{len(to_classify)} need classification")

    if args.limit:
        to_classify = to_classify[:args.limit]
        print(f"Limited to {len(to_classify)} questions")

    if not args.no_api and to_classify:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
            print("Set it with: export ANTHROPIC_API_KEY='your-key-here'")
            sys.exit(1)
        client = anthropic.Anthropic(api_key=api_key)
    else:
        client = None

    WORKERS = 25
    lock = threading.Lock()
    errors = 0
    completed = 0

    def process_one(q_dir):
        q_id = q_dir.name
        src = load_source_info(q_dir)
        is_scan = src.get("is_scan", "false").lower() == "true"
        curriculum = src.get("curriculum", "pre-2023")

        classification = None
        if client and not is_scan and not args.no_api:
            classification = classify_question(client, q_dir, curriculum)
        entry = build_question_entry(q_id, q_dir, src, classification)
        return q_id, entry, classification, is_scan

    futures = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        for q_dir in to_classify:
            futures[executor.submit(process_one, q_dir)] = q_dir

        for future in as_completed(futures):
            try:
                q_id, entry, classification, is_scan = future.result()
                with lock:
                    question_bank[q_id] = entry
                    completed += 1
                    if classification is None and not is_scan:
                        errors += 1
                    subtopic = (
                        classification.get("subtopic_name", "?") if classification
                        else ("scan" if is_scan else "FAILED")
                    )
                    diff = classification.get("difficulty", "?") if classification else ""
                    diff_str = f" (diff={diff})" if diff else ""
                    print(f"[{completed}/{len(to_classify)}] {q_id}: {subtopic}{diff_str}")
                    if completed % 100 == 0:
                        save_checkpoint(question_bank)
                        print(f"  --- Checkpoint saved ({completed} done) ---")
            except Exception as e:
                with lock:
                    errors += 1
                    completed += 1
                    print(f"ERROR {futures[future].name}: {e}")

    # Final checkpoint save
    save_checkpoint(question_bank)

    # Also include already-classified questions not in to_classify
    for q_dir in all_dirs:
        q_id = q_dir.name
        if q_id not in question_bank:
            src = load_source_info(q_dir)
            entry = build_question_entry(q_id, q_dir, src, None)
            question_bank[q_id] = entry

    # Write final sorted question bank
    sorted_bank = dict(sorted(question_bank.items()))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(sorted_bank, f, indent=2)

    print(f"\n=== Physics Classification Summary ===")
    print(f"Total questions: {len(question_bank)}")
    print(f"Classified: {sum(1 for e in question_bank.values() if e.get('topic_code'))}")
    print(f"Unclassified (scans): {sum(1 for e in question_bank.values() if e.get('is_scan'))}")
    print(f"Errors: {errors}")
    print(f"Saved to {OUTPUT_PATH}")

    # Topic breakdown
    from collections import Counter
    topics = Counter(e.get("topic_name") for e in question_bank.values() if e.get("topic_name"))
    if topics:
        print("\nTopic distribution:")
        for topic, count in sorted(topics.items(), key=lambda x: -x[1]):
            print(f"  {topic}: {count}")


if __name__ == "__main__":
    main()
