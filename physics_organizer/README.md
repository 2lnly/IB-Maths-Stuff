# IB Physics HL Question Organizer

Automatically organize, extract text, and classify IB Physics HL questions by topic using local LLM (Ollama).

## What it does

1. **Flattens** the nested folder structure (Session/Question → Paper/Question_Session)
2. **Extracts text** from question images using Ollama vision model
3. **Classifies** questions into physics topics/subtopics using AI
4. **Organizes** questions into topic folders with symlinks

## Prerequisites

- Ollama running with llama3.2-vision model
- Python 3.9+
- ~2927 physics questions to process

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Make sure Ollama is running
ollama serve

# Verify model is available
curl http://localhost:11434/api/tags
```

## Usage

### Run everything at once:
```bash
python run_all.py
```

### Or run steps individually:

1. **Flatten structure**:
   ```bash
   python flatten.py
   ```

2. **Extract text** (uses Ollama, ~30 min for 2927 questions):
   ```bash
   python extract_text.py
   ```

3. **Classify topics** (uses Ollama, ~30 min for 2927 questions):
   ```bash
   python classify.py
   ```

4. **Organize by topic** (instant):
   ```bash
   python organize.py
   ```

## Output Structure

```
Physics By Topic/
├── Paper1/
│   ├── mechanics/
│   │   ├── kinematics/
│   │   │   ├── Q27_2017_May_TZ1/  (symlink)
│   │   │   └── Q34_2017_May_TZ1/  (symlink)
│   │   └── forces/
│   ├── waves/
│   └── electricity_magnetism/
├── Paper2/
└── Paper3/
```

Each question folder contains:
- `question_p*.png` - Original question images
- `question_text.txt` - Extracted text
- `answer.txt` or `answer.png` - Answer

## Configuration

Edit `config.py` to adjust:
- `num_workers` - Parallel processing (default: 4)
- `question_delay` - Delay between questions (default: 0.2s)
- `model` - Ollama model to use (default: llama3.2-vision)

## Progress Tracking

Progress is saved automatically:
- `physics_text_extraction_progress.json`
- `physics_classification_progress.json`
- `physics_classification_results.json`

If interrupted, just run again and it will resume.

## Topics Covered

- Mechanics (kinematics, forces, energy, momentum, circular motion, gravitation)
- Thermal Physics
- Waves (SHM, wave properties, standing waves, Doppler)
- Electricity & Magnetism
- Atomic, Nuclear & Particle Physics
- Relativity
- Quantum Physics
- Astrophysics (optional)
- Engineering Physics (optional)
- Imaging (optional)

## Estimated Time

- Flatten: ~1 minute
- Text extraction: ~30-40 minutes (4 workers, 2927 questions)
- Classification: ~30-40 minutes (4 workers)
- Organization: ~10 seconds

Total: ~1-1.5 hours
