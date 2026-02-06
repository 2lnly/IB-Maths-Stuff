"""Configuration for Physics question organizer."""

from dataclasses import dataclass
from pathlib import Path

# IB Physics HL Topics
PHYSICS_TOPICS = {
    "mechanics": [
        "kinematics",
        "forces",
        "work_energy_power",
        "momentum_impulse",
        "circular_motion",
        "gravitation"
    ],
    "thermal_physics": [
        "temperature_heat",
        "kinetic_theory",
        "thermodynamics",
        "heat_transfer"
    ],
    "waves": [
        "simple_harmonic_motion",
        "wave_properties",
        "wave_phenomena",
        "standing_waves",
        "doppler_effect"
    ],
    "electricity_magnetism": [
        "electric_fields",
        "electric_current",
        "circuits",
        "magnetic_fields",
        "electromagnetic_induction"
    ],
    "atomic_nuclear_particle": [
        "atomic_structure",
        "nuclear_physics",
        "radioactivity",
        "particle_physics"
    ],
    "relativity": [
        "special_relativity",
        "general_relativity",
        "spacetime"
    ],
    "quantum_physics": [
        "quantum_mechanics",
        "wave_particle_duality",
        "atomic_spectra",
        "uncertainty_principle"
    ],
    "astrophysics": [
        "stellar_characteristics",
        "stellar_evolution",
        "cosmology",
        "universe"
    ],
    "engineering_physics": [
        "fluids",
        "solid_mechanics",
        "thermodynamics_applications"
    ],
    "imaging": [
        "optics",
        "medical_imaging",
        "instrumentation"
    ],
    "general": [
        "mixed_topics",
        "exam_technique",
        "other"
    ]
}

@dataclass
class Config:
    """Configuration for physics organizer."""
    base_dir: Path = Path("/home/xiaohe/stuff/claudable/Physics HL Organised")
    flattened_dir: Path = Path("/home/xiaohe/stuff/claudable/Physics Flattened")
    topics_dir: Path = Path("/home/xiaohe/stuff/claudable/Physics By Topic")
    model: str = "llama3.2-vision"
    ollama_url: str = "http://localhost:11434"
    num_workers: int = 4
    question_delay: float = 0.2
