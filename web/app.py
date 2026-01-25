"""Flask web app for IB Math practice questions."""

import json
import random
from pathlib import Path
from flask import Flask, jsonify, send_file, render_template
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Load classification results
RESULTS_FILE = Path(__file__).parent.parent / "practice_classification_results.json"
PRACTICE_DIR = Path(__file__).parent.parent / "practice"

with open(RESULTS_FILE, 'r') as f:
    QUESTIONS = json.load(f)

# Build topic/subtopic index
TOPICS_INDEX = {}
for q_id, data in QUESTIONS.items():
    paper = data.get('paper', 'unknown')
    topic = data.get('primary_topic', 'unknown')
    subtopic = data.get('primary_subtopic', 'unknown')

    key = f"{paper}:{topic}:{subtopic}"
    if key not in TOPICS_INDEX:
        TOPICS_INDEX[key] = []
    TOPICS_INDEX[key].append(q_id)

# Build list of all subtopics
SUBTOPICS = {}
for key in TOPICS_INDEX.keys():
    paper, topic, subtopic = key.split(':')
    if paper not in SUBTOPICS:
        SUBTOPICS[paper] = {}
    if topic not in SUBTOPICS[paper]:
        SUBTOPICS[paper][topic] = []
    if subtopic not in SUBTOPICS[paper][topic]:
        SUBTOPICS[paper][topic].append(subtopic)


@app.route('/')
def index():
    """Serve the main page."""
    return render_template('index.html')


@app.route('/api/topics')
def get_topics():
    """Get all available topics and subtopics."""
    return jsonify(SUBTOPICS)


@app.route('/api/random')
def get_random_question():
    """Get a random question from any subtopic."""
    q_id = random.choice(list(QUESTIONS.keys()))
    return jsonify({
        'question_id': q_id,
        **QUESTIONS[q_id]
    })


@app.route('/api/question/<paper>/<topic>/<subtopic>/random')
def get_random_from_subtopic(paper, topic, subtopic):
    """Get a random question from a specific subtopic."""
    key = f"{paper}:{topic}:{subtopic}"
    if key not in TOPICS_INDEX:
        return jsonify({'error': 'Subtopic not found'}), 404

    q_id = random.choice(TOPICS_INDEX[key])
    return jsonify({
        'question_id': q_id,
        **QUESTIONS[q_id]
    })


@app.route('/api/image/<paper>/<question_num>/<image_name>')
def get_image(paper, question_num, image_name):
    """Serve a question or answer image."""
    # Normalize paper name: Paper1 -> paper 1, Paper2 -> paper 2, etc.
    paper_normalized = paper.lower().replace('paper', 'paper ')
    paper_dir = PRACTICE_DIR / paper_normalized
    image_path = paper_dir / question_num / image_name

    if not image_path.exists():
        return jsonify({'error': f'Image not found: {image_path}'}), 404

    return send_file(image_path, mimetype='image/png')


@app.route('/api/text/<paper>/<question_num>')
def get_question_text(paper, question_num):
    """Get the extracted question text."""
    # Normalize paper name: Paper1 -> paper 1, Paper2 -> paper 2, etc.
    paper_normalized = paper.lower().replace('paper', 'paper ')
    paper_dir = PRACTICE_DIR / paper_normalized
    text_path = paper_dir / question_num / 'question_text.txt'

    if not text_path.exists():
        return jsonify({'error': 'Question text not found'}), 404

    with open(text_path, 'r') as f:
        text = f.read()

    return jsonify({'text': text})


if __name__ == '__main__':
    import os
    # Check if running in production (Render sets PORT env variable)
    is_production = 'PORT' in os.environ
    port = int(os.environ.get('PORT', 5000))

    app.run(
        host='0.0.0.0' if is_production else '127.0.0.1',
        port=port,
        debug=not is_production
    )
