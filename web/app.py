"""Flask web app for IB Math and Physics practice questions."""

import json
import os
import random
import base64
from pathlib import Path
from collections import defaultdict
from flask import Flask, jsonify, send_file, render_template, request, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from auth import create_user, check_user
from user_data import (
    track_question_view, save_question, unsave_question,
    is_question_saved, get_user_history, get_saved_questions,
    clear_all_user_data
)
from time_tracking import (
    update_question_time, get_question_time,
    update_daily_time, get_daily_time
)
from database import get_db_connection, execute_query, USE_POSTGRES

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production-12345'
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configure session to last longer and be more persistent
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)  # Sessions last 30 days
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True if using HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Load MATH classification results
RESULTS_FILE = Path(__file__).parent.parent / "data" / "practice_classification_results.json"
PRACTICE_DIR = Path(__file__).parent.parent / "practice"

with open(RESULTS_FILE, 'r') as f:
    QUESTIONS = json.load(f)

# Build topic/subtopic index for MATH
TOPICS_INDEX = {}
for q_id, data in QUESTIONS.items():
    paper = data.get('paper', 'unknown')
    topic = data.get('primary_topic', 'unknown')
    subtopic = data.get('primary_subtopic', 'unknown')

    key = f"{paper}:{topic}:{subtopic}"
    if key not in TOPICS_INDEX:
        TOPICS_INDEX[key] = []
    TOPICS_INDEX[key].append(q_id)

# Build list of all subtopics for MATH
SUBTOPICS = {}
for key in TOPICS_INDEX.keys():
    paper, topic, subtopic = key.split(':')
    if paper not in SUBTOPICS:
        SUBTOPICS[paper] = {}
    if topic not in SUBTOPICS[paper]:
        SUBTOPICS[paper][topic] = []
    if subtopic not in SUBTOPICS[paper][topic]:
        SUBTOPICS[paper][topic].append(subtopic)

# Load PHYSICS classification results
PHYSICS_RESULTS_FILE = Path(__file__).parent.parent / "data" / "physics_classification_results.json"
PHYSICS_DIR = Path(__file__).parent.parent / "Physics Flattened"

with open(PHYSICS_RESULTS_FILE, 'r') as f:
    PHYSICS_QUESTIONS = json.load(f)

# Build topic/subtopic index for PHYSICS using IB structure codes
PHYSICS_TOPICS_INDEX = {}
for q_id, data in PHYSICS_QUESTIONS.items():
    paper = data.get('paper', 'unknown')
    topic_code = data.get('topic_code', 'unknown')
    subtopic_code = data.get('subtopic_code', 'unknown')

    key = f"{paper}:{topic_code}:{subtopic_code}"
    if key not in PHYSICS_TOPICS_INDEX:
        PHYSICS_TOPICS_INDEX[key] = []
    PHYSICS_TOPICS_INDEX[key].append(q_id)

# Build list of all subtopics for PHYSICS with full names
PHYSICS_SUBTOPICS = {}
for q_id, data in PHYSICS_QUESTIONS.items():
    paper = data.get('paper', 'unknown')
    topic_code = data.get('topic_code', 'unknown')
    topic_name = data.get('primary_topic', 'unknown')
    subtopic_code = data.get('subtopic_code', 'unknown')
    subtopic_name = data.get('primary_subtopic', 'unknown')

    if paper not in PHYSICS_SUBTOPICS:
        PHYSICS_SUBTOPICS[paper] = {}

    # Use format: "A: Space, Time & Motion"
    topic_key = f"{topic_code}: {topic_name}"
    if topic_key not in PHYSICS_SUBTOPICS[paper]:
        PHYSICS_SUBTOPICS[paper][topic_key] = []

    # Use format: "A.1: Kinematics"
    subtopic_key = f"{subtopic_code}: {subtopic_name}"
    if subtopic_key not in PHYSICS_SUBTOPICS[paper][topic_key]:
        PHYSICS_SUBTOPICS[paper][topic_key].append(subtopic_key)

# Load ECONOMICS classification results
ECON_RESULTS_FILE = Path(__file__).parent.parent / "data" / "economics_classification_results.json"

with open(ECON_RESULTS_FILE, 'r') as f:
    ECON_QUESTIONS = json.load(f)

# Build index for ECONOMICS by paper and topic
ECON_BY_PAPER = defaultdict(list)
ECON_BY_PAPER_TOPIC = defaultdict(list)

for q_id, data in ECON_QUESTIONS.items():
    paper = data.get('paper', 'unknown')
    topic = data.get('topic', 'unknown')

    ECON_BY_PAPER[paper].append(q_id)

    key = f"{paper}:{topic}"
    ECON_BY_PAPER_TOPIC[key].append(q_id)


@app.route('/')
def landing():
    from flask import redirect
    return redirect('/math')


@app.route('/math')
def math_page():
    return render_template('question_bank.html')


@app.route('/documentation')
def documentation():
    """Serve the documentation page."""
    doc_file = Path(__file__).parent / 'documentation.txt'
    content = ''
    if doc_file.exists():
        with open(doc_file, 'r', encoding='utf-8') as f:
            content = f.read()
    return render_template('documentation.html', content=content)


@app.route('/health')
def health_check():
    """Health check endpoint with memory stats."""
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024

        # Test database connection
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT 1')

        return jsonify({
            'status': 'healthy',
            'memory_mb': round(memory_mb, 2),
            'database': 'connected'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


@app.route('/api/register', methods=['POST'])
def register():
    """Register a new user."""
    data = request.json
    username = data.get('username', '')
    password = data.get('password', '')

    success, message = create_user(username, password)

    if success:
        session.permanent = True  # Make session last for PERMANENT_SESSION_LIFETIME
        session['username'] = username.strip().lower()
        return jsonify({'success': True, 'message': message, 'username': session['username']})
    else:
        return jsonify({'success': False, 'message': message}), 400


@app.route('/api/login', methods=['POST'])
def login():
    """Login an existing user."""
    data = request.json
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if check_user(username, password):
        session.permanent = True  # Make session last for PERMANENT_SESSION_LIFETIME
        session['username'] = username
        return jsonify({'success': True, 'message': 'Logged in successfully', 'username': username})
    else:
        return jsonify({'success': False, 'message': 'Invalid username or password'}), 404


@app.route('/api/logout', methods=['POST'])
def logout():
    """Logout the current user."""
    session.pop('username', None)
    return jsonify({'success': True, 'message': 'Logged out successfully'})


@app.route('/api/current-user')
def current_user():
    """Get the current logged-in user."""
    username = session.get('username')
    if username:
        return jsonify({'logged_in': True, 'username': username})
    else:
        return jsonify({'logged_in': False})


# ============ USER DATA ROUTES (History & Saved Questions) ============

@app.route('/api/track-view', methods=['POST'])
def track_view():
    """Track that a user viewed a question."""
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.json
    question_id = data.get('question_id')
    subject = data.get('subject')

    if not question_id or not subject:
        return jsonify({'success': False, 'message': 'Missing question_id or subject'}), 400

    success, message = track_question_view(username, question_id, subject)
    return jsonify({'success': success, 'message': message})


@app.route('/api/save-question', methods=['POST'])
def save_question_route():
    """Save a question for the user."""
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.json
    question_id = data.get('question_id')
    subject = data.get('subject')
    notes = data.get('notes')

    if not question_id or not subject:
        return jsonify({'success': False, 'message': 'Missing question_id or subject'}), 400

    success, message = save_question(username, question_id, subject, notes)
    return jsonify({'success': success, 'message': message})


@app.route('/api/save-question', methods=['DELETE'])
def unsave_question_route():
    """Remove a saved question."""
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.json
    question_id = data.get('question_id')
    subject = data.get('subject')

    if not question_id or not subject:
        return jsonify({'success': False, 'message': 'Missing question_id or subject'}), 400

    success, message = unsave_question(username, question_id, subject)
    return jsonify({'success': success, 'message': message})


@app.route('/api/is-saved', methods=['GET'])
def check_is_saved():
    """Check if a question is saved by the user."""
    username = session.get('username')
    if not username:
        return jsonify({'saved': False})

    question_id = request.args.get('question_id')
    subject = request.args.get('subject')

    if not question_id or not subject:
        return jsonify({'saved': False})

    saved = is_question_saved(username, question_id, subject)
    return jsonify({'saved': saved})


@app.route('/api/history')
def get_history():
    """Get user's question history."""
    username = session.get('username')
    if not username:
        return jsonify({'history': []})

    subject = request.args.get('subject')
    limit = int(request.args.get('limit', 50))

    history = get_user_history(username, subject, limit)
    return jsonify({'history': history})


@app.route('/api/saved')
def get_saved():
    """Get user's saved questions."""
    username = session.get('username')
    if not username:
        return jsonify({'saved': []})

    subject = request.args.get('subject')
    saved = get_saved_questions(username, subject)
    return jsonify({'saved': saved})


@app.route('/api/clear-all', methods=['POST'])
def clear_all():
    """Clear all history and saved questions for the user."""
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.json or {}
    subject = data.get('subject')

    success, message = clear_all_user_data(username, subject)
    return jsonify({'success': success, 'message': message})


# ============ TIME TRACKING ROUTES ============

@app.route('/api/time/update-question', methods=['POST'])
def update_question_time_route():
    """Update time spent on a question."""
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.json
    question_id = data.get('question_id')
    subject = data.get('subject')
    seconds = data.get('seconds', 0)

    if not question_id or not subject:
        return jsonify({'success': False, 'message': 'Missing question_id or subject'}), 400

    success, message = update_question_time(username, question_id, subject, seconds)
    return jsonify({'success': success, 'message': message})


@app.route('/api/time/question/<question_id>')
def get_question_time_route(question_id):
    """Get time spent on a question."""
    username = session.get('username')
    if not username:
        return jsonify({'time': 0})

    subject = request.args.get('subject')
    if not subject:
        return jsonify({'time': 0})

    time = get_question_time(username, question_id, subject)
    return jsonify({'time': time})


@app.route('/api/time/update-daily', methods=['POST'])
def update_daily_time_route():
    """Update daily time spent."""
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.json
    seconds = data.get('seconds', 0)

    success, message = update_daily_time(username, seconds)
    return jsonify({'success': success, 'message': message})


@app.route('/api/time/daily')
def get_daily_time_route():
    """Get today's total time."""
    username = session.get('username')
    if not username:
        return jsonify({'time': 0})

    time = get_daily_time(username)
    return jsonify({'time': time})


# ============ QUESTION NOTES ROUTES ============

@app.route('/api/notes/<subject>/<question_id>')
def get_notes(subject, question_id):
    """Get all notes for a question."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execute_query(cursor, '''
                SELECT username, note, created_at
                FROM question_notes
                WHERE question_id = %s AND subject = %s
                ORDER BY created_at DESC
            ''', (question_id, subject))

            notes = []
            for row in cursor.fetchall():
                notes.append({
                    'username': row[0],
                    'note': row[1],
                    'created_at': str(row[2])
                })

            return jsonify({'notes': notes})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/notes/add', methods=['POST'])
def add_note():
    """Add a note to a question."""
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'message': 'Not logged in'}), 401

    data = request.json
    question_id = data.get('question_id')
    subject = data.get('subject')
    note = data.get('note', '').strip()

    if not question_id or not subject or not note:
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Get user_id
            execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                return jsonify({'success': False, 'message': 'User not found'}), 404

            user_id = result[0]

            # Insert note
            execute_query(cursor, '''
                INSERT INTO question_notes (user_id, username, question_id, subject, note)
                VALUES (%s, %s, %s, %s, %s)
            ''', (user_id, username, question_id, subject, note))

            conn.commit()
            return jsonify({'success': True, 'message': 'Note added'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ============ GLOBAL CHAT ROUTES ============

@app.route('/api/chat/messages')
def get_chat_messages():
    """Get last 100 chat messages from the last 30 days."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            execute_query(cursor, '''
                SELECT gc.username, gc.message, gc.created_at, u.is_owner
                FROM global_chat gc
                LEFT JOIN users u ON gc.user_id = u.id
                WHERE gc.created_at >= NOW() - INTERVAL '30 days'
                ORDER BY gc.created_at DESC
                LIMIT 100
            ''' if USE_POSTGRES else '''
                SELECT gc.username, gc.message, gc.created_at, u.is_owner
                FROM global_chat gc
                LEFT JOIN users u ON gc.user_id = u.id
                WHERE gc.created_at >= datetime('now', '-30 days')
                ORDER BY gc.created_at DESC
                LIMIT 100
            ''', None)

            messages = []
            for row in cursor.fetchall():
                messages.append({
                    'username': row[0],
                    'message': row[1],
                    'created_at': str(row[2]),
                    'is_owner': bool(row[3]) if row[3] is not None else False
                })

            # Reverse to show oldest first
            messages.reverse()
            return jsonify({'messages': messages})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@socketio.on('send_message')
def handle_send_message(data):
    """Handle new chat message via WebSocket."""
    username = session.get('username')
    if not username:
        emit('error', {'message': 'Not logged in'})
        return

    message = data.get('message', '').strip()
    if not message:
        emit('error', {'message': 'Message cannot be empty'})
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Get user_id and is_owner status
            execute_query(cursor, 'SELECT id, is_owner FROM users WHERE username = %s', (username,))
            result = cursor.fetchone()
            if not result:
                emit('error', {'message': 'User not found'})
                return

            user_id = result[0]
            is_owner = bool(result[1]) if result[1] is not None else False

            # Insert message
            execute_query(cursor, '''
                INSERT INTO global_chat (user_id, username, message)
                VALUES (%s, %s, %s)
                RETURNING created_at
            ''' if USE_POSTGRES else '''
                INSERT INTO global_chat (user_id, username, message)
                VALUES (%s, %s, %s)
            ''', (user_id, username, message))

            if USE_POSTGRES:
                created_at = cursor.fetchone()[0]
            else:
                # For SQLite, get the timestamp
                execute_query(cursor, 'SELECT created_at FROM global_chat WHERE id = last_insert_rowid()', None)
                created_at = cursor.fetchone()[0]

            conn.commit()

            # Broadcast to all connected clients
            socketio.emit('new_message', {
                'username': username,
                'message': message,
                'created_at': str(created_at),
                'is_owner': is_owner
            }, broadcast=True)

    except Exception as e:
        emit('error', {'message': str(e)})


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


@app.route('/api/question/<question_id>')
def get_question_by_id(question_id):
    """Get a specific question by ID."""
    if question_id in QUESTIONS:
        return jsonify({
            'question_id': question_id,
            **QUESTIONS[question_id]
        })
    return jsonify({'error': 'Question not found'}), 404


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


@app.route('/api/question/filter', methods=['GET'])
def get_filtered_question():
    """Get a random question filtered by paper, topic, and/or subtopic."""
    paper = request.args.get('paper')
    topic = request.args.get('topic')
    subtopic = request.args.get('subtopic')

    # Filter questions based on provided parameters
    filtered_questions = []

    for q_id, data in QUESTIONS.items():
        matches = True

        if paper and data.get('paper') != paper:
            matches = False
        if topic and data.get('primary_topic') != topic:
            matches = False
        if subtopic and data.get('primary_subtopic') != subtopic:
            matches = False

        if matches:
            filtered_questions.append(q_id)

    if not filtered_questions:
        return jsonify({'error': 'No questions found matching the criteria'}), 404

    q_id = random.choice(filtered_questions)
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


# ============ PHYSICS ROUTES ============

@app.route('/physics')
def physics_index():
    return render_template('physics_question_bank.html')


@app.route('/api/physics/topics-old')
def get_physics_topics():
    """Get all available physics topics and subtopics."""
    return jsonify(PHYSICS_SUBTOPICS)


@app.route('/api/physics/random-old')
def get_random_physics_question():
    """Get a random physics question from any subtopic."""
    q_id = random.choice(list(PHYSICS_QUESTIONS.keys()))
    return jsonify({
        'question_id': q_id,
        **PHYSICS_QUESTIONS[q_id]
    })


@app.route('/api/physics/question-old/<question_id>')
def get_physics_question_by_id(question_id):
    """Get a specific physics question by ID."""
    if question_id in PHYSICS_QUESTIONS:
        return jsonify({
            'question_id': question_id,
            **PHYSICS_QUESTIONS[question_id]
        })
    return jsonify({'error': 'Question not found'}), 404


@app.route('/api/physics/question/<paper>/<topic>/<subtopic>/random')
def get_random_physics_from_subtopic(paper, topic, subtopic):
    """Get a random physics question from a specific subtopic."""
    key = f"{paper}:{topic}:{subtopic}"
    if key not in PHYSICS_TOPICS_INDEX:
        return jsonify({'error': 'Subtopic not found'}), 404

    q_id = random.choice(PHYSICS_TOPICS_INDEX[key])
    return jsonify({
        'question_id': q_id,
        **PHYSICS_QUESTIONS[q_id]
    })


@app.route('/api/physics/question/filter', methods=['GET'])
def get_filtered_physics_question():
    """Get a random physics question filtered by paper, topic, and/or subtopic."""
    paper = request.args.get('paper')
    topic = request.args.get('topic')  # Format: "A: Space, Time & Motion" or "A"
    subtopic = request.args.get('subtopic')  # Format: "A.1: Kinematics" or "A.1"

    # Extract codes from formatted strings
    topic_code = None
    subtopic_code = None

    if topic:
        # Extract code (e.g., "A" from "A: Space, Time & Motion")
        topic_code = topic.split(':')[0].strip() if ':' in topic else topic.strip()

    if subtopic:
        # Extract code (e.g., "A.1" from "A.1: Kinematics")
        subtopic_code = subtopic.split(':')[0].strip() if ':' in subtopic else subtopic.strip()

    # Filter questions based on provided parameters
    filtered_questions = []

    for q_id, data in PHYSICS_QUESTIONS.items():
        matches = True

        if paper and data.get('paper') != paper:
            matches = False
        if topic_code and data.get('topic_code') != topic_code:
            matches = False
        if subtopic_code and data.get('subtopic_code') != subtopic_code:
            matches = False

        if matches:
            filtered_questions.append(q_id)

    if not filtered_questions:
        return jsonify({'error': 'No questions found matching the criteria'}), 404

    q_id = random.choice(filtered_questions)
    return jsonify({
        'question_id': q_id,
        **PHYSICS_QUESTIONS[q_id]
    })


@app.route('/api/physics/image/<paper>/<question_num>/<image_name>')
def get_physics_image(paper, question_num, image_name):
    """Serve a physics question or answer image."""
    # Normalize paper name: Paper1 -> Paper 1, "Paper 1" -> Paper 1
    # Handle both "Paper1" and "Paper 1" formats
    if ' ' not in paper:
        # Convert Paper1 to Paper 1
        paper_normalized = paper.replace('Paper', 'Paper ')
    else:
        # Already has space
        paper_normalized = paper

    paper_dir = PHYSICS_DIR / paper_normalized
    image_path = paper_dir / question_num / image_name

    if not image_path.exists():
        return jsonify({'error': f'Image not found: {image_path}'}), 404

    return send_file(image_path, mimetype='image/png')


@app.route('/api/physics/text/<paper>/<question_num>')
def get_physics_question_text(paper, question_num):
    """Get the extracted physics question text."""
    # Normalize paper name: Paper1 -> Paper 1, "Paper 1" -> Paper 1
    # Handle both "Paper1" and "Paper 1" formats
    if ' ' not in paper:
        # Convert Paper1 to Paper 1
        paper_normalized = paper.replace('Paper', 'Paper ')
    else:
        # Already has space
        paper_normalized = paper

    paper_dir = PHYSICS_DIR / paper_normalized
    text_path = paper_dir / question_num / 'question_text.txt'

    if not text_path.exists():
        return jsonify({'error': 'Question text not found'}), 404

    with open(text_path, 'r') as f:
        text = f.read()

    return jsonify({'text': text})


@app.route('/api/physics/answer-text/<paper>/<question_num>')
def get_physics_answer_text(paper, question_num):
    """Get the physics answer text (for Paper 1 which has text answers)."""
    # Normalize paper name
    if ' ' not in paper:
        paper_normalized = paper.replace('Paper', 'Paper ')
    else:
        paper_normalized = paper

    paper_dir = PHYSICS_DIR / paper_normalized
    answer_path = paper_dir / question_num / 'answer.txt'

    if not answer_path.exists():
        return jsonify({'error': 'Answer text not found', 'hasAnswer': False}), 404

    with open(answer_path, 'r') as f:
        text = f.read()

    return jsonify({'answer': text, 'hasAnswer': True})


# ============ ECONOMICS ROUTES ============

@app.route('/economics')
def economics_index():
    """Serve the economics page."""
    return render_template('economics.html')


@app.route('/api/economics/info')
def get_economics_info():
    """Get available papers and topics for economics."""
    return jsonify({
        'papers': ['Paper 1', 'Paper 2'],
        'topics': {
            'Paper 1': ['Microeconomics', 'Macroeconomics'],
            'Paper 2': ['Case Study']
        },
        'counts': {
            'Paper 1': len(ECON_BY_PAPER['Paper 1']),
            'Paper 2': len(ECON_BY_PAPER['Paper 2'])
        }
    })


@app.route('/api/economics/random')
def get_random_economics_question():
    """Get a random economics question from any type."""
    q_id = random.choice(list(ECON_QUESTIONS.keys()))
    return jsonify({
        'question_id': q_id,
        **ECON_QUESTIONS[q_id]
    })


@app.route('/api/economics/question/<question_id>')
def get_economics_question_by_id(question_id):
    """Get a specific economics question by ID."""
    if question_id in ECON_QUESTIONS:
        return jsonify({
            'question_id': question_id,
            **ECON_QUESTIONS[question_id]
        })
    return jsonify({'error': 'Question not found'}), 404


@app.route('/api/economics/question/filter', methods=['GET'])
def get_filtered_economics_question():
    """Get a random economics question filtered by paper and/or topic."""
    paper = request.args.get('paper')
    topic = request.args.get('topic')

    # Filter by both paper and topic if provided
    if paper and topic:
        key = f"{paper}:{topic}"
        if key in ECON_BY_PAPER_TOPIC and ECON_BY_PAPER_TOPIC[key]:
            q_id = random.choice(ECON_BY_PAPER_TOPIC[key])
        else:
            return jsonify({'error': 'No questions found for this paper and topic combination'}), 404
    elif paper and paper in ECON_BY_PAPER:
        if not ECON_BY_PAPER[paper]:
            return jsonify({'error': 'No questions found for this paper'}), 404
        q_id = random.choice(ECON_BY_PAPER[paper])
    elif topic:
        # Filter by topic only
        matching = [q_id for q_id, q in ECON_QUESTIONS.items() if q.get('topic') == topic]
        if not matching:
            return jsonify({'error': 'No questions found for this topic'}), 404
        q_id = random.choice(matching)
    else:
        q_id = random.choice(list(ECON_QUESTIONS.keys()))

    return jsonify({
        'question_id': q_id,
        **ECON_QUESTIONS[q_id]
    })


# Economics now uses text display, no image endpoint needed

# ============ NEW MATH QUESTION BANK ROUTES ============

# Load new question bank (question_bank.json from extraction + classification pipeline)
QUESTION_BANK_FILE = Path(__file__).parent.parent / "data" / "question_bank.json"
PRACTICE_NEW_DIR = Path(__file__).parent.parent / "practice_new"

QUESTION_BANK = {}
if QUESTION_BANK_FILE.exists():
    with open(QUESTION_BANK_FILE) as f:
        QUESTION_BANK = json.load(f)


def _build_bank_index():
    """Build in-memory indexes for fast filtering of the new question bank."""
    index = {
        'by_topic': defaultdict(list),
        'by_subtopic': defaultdict(list),
        'by_paper': defaultdict(list),
        'by_year': defaultdict(list),
        'by_difficulty': defaultdict(list),
        'topics': {},  # topic_code -> {topic_name, subtopics: {code -> name}}
    }
    for q_id, q in QUESTION_BANK.items():
        if not q.get('year'):
            continue
        paper = q.get('paper', '')
        topic = q.get('topic_code')
        subtopic = q.get('subtopic_code')
        year = str(q.get('year', ''))
        diff = str(q.get('difficulty', ''))

        index['by_paper'][paper].append(q_id)
        if year:
            index['by_year'][year].append(q_id)
        if topic:
            index['by_topic'][topic].append(q_id)
        if subtopic:
            index['by_subtopic'][subtopic].append(q_id)
        if diff:
            index['by_difficulty'][diff].append(q_id)

        # Build topic/subtopic tree
        if topic and q.get('topic_name'):
            if topic not in index['topics']:
                index['topics'][topic] = {'name': q['topic_name'], 'subtopics': {}}
            if subtopic and q.get('subtopic_name'):
                index['topics'][topic]['subtopics'][subtopic] = q['subtopic_name']

    return index


BANK_INDEX = _build_bank_index()


@app.route('/math2')
def math_bank():
    """New math question bank with dashboard UI."""
    return render_template('question_bank.html')


@app.route('/api/bank/topics')
def bank_topics():
    """Get the full IB topic taxonomy with question counts."""
    result = {}
    for topic_code, topic_data in sorted(BANK_INDEX['topics'].items()):
        result[topic_code] = {
            'name': topic_data['name'],
            'count': len(BANK_INDEX['by_topic'].get(topic_code, [])),
            'subtopics': {
                code: {
                    'name': name,
                    'count': len(BANK_INDEX['by_subtopic'].get(code, [])),
                }
                for code, name in sorted(topic_data['subtopics'].items())
            }
        }
    return jsonify(result)


@app.route('/api/bank/stats')
def bank_stats():
    """Get summary stats for the dashboard."""
    username = session.get('username')

    total = len(QUESTION_BANK)
    classified = sum(1 for q in QUESTION_BANK.values() if q.get('topic_code'))
    has_answer = sum(1 for q in QUESTION_BANK.values() if q.get('has_answer'))

    # Topic breakdown
    from collections import Counter
    topic_counts = Counter(
        q.get('topic_name') for q in QUESTION_BANK.values()
        if q.get('topic_name')
    )
    difficulty_counts = Counter(
        q.get('difficulty') for q in QUESTION_BANK.values()
        if q.get('difficulty')
    )
    year_counts = Counter(
        q.get('year') for q in QUESTION_BANK.values()
        if q.get('year')
    )
    paper_counts = Counter(
        q.get('paper') for q in QUESTION_BANK.values()
        if q.get('paper')
    )

    # User-specific stats
    user_done = 0
    user_by_topic = {}
    if username:
        history = get_user_history(username, 'math2', 10000)
        user_done = len(history)
        done_ids = {h['question_id'] for h in history}
        # Count done per topic
        for q_id in done_ids:
            q = QUESTION_BANK.get(q_id, {})
            topic = q.get('topic_name')
            if topic:
                user_by_topic[topic] = user_by_topic.get(topic, 0) + 1

    return jsonify({
        'total': total,
        'classified': classified,
        'has_answer': has_answer,
        'topics': dict(topic_counts.most_common()),
        'difficulty': {str(k): v for k, v in sorted(difficulty_counts.items()) if k},
        'years': {str(k): v for k, v in sorted(year_counts.items()) if k},
        'papers': dict(paper_counts),
        'user_done': user_done,
        'user_by_topic': user_by_topic,
    })


@app.route('/api/bank/questions')
def bank_questions():
    """Get filtered list of questions (for the question list view)."""
    paper = request.args.get('paper')          # "Paper1", "Paper2", "Paper3"
    topic = request.args.get('topic')          # topic_code e.g. "1"
    subtopic = request.args.get('subtopic')    # subtopic_code e.g. "1.4"
    year_min = request.args.get('year_min', type=int)
    year_max = request.args.get('year_max', type=int)
    diff_min = request.args.get('diff_min', type=int)
    diff_max = request.args.get('diff_max', type=int)
    marks_min = request.args.get('marks_min', type=int)
    marks_max = request.args.get('marks_max', type=int)
    curriculum = request.args.get('curriculum')  # "AA" or "pre-2021"
    paper3_option = request.args.get('paper3_option')
    limit = request.args.get('limit', 200, type=int)
    offset = request.args.get('offset', 0, type=int)

    results = []
    for q_id, q in QUESTION_BANK.items():
        if paper and q.get('paper') != paper:
            continue
        if topic and q.get('topic_code') != topic:
            continue
        if subtopic and q.get('subtopic_code') != subtopic:
            continue
        if year_min and (not q.get('year') or q['year'] < year_min):
            continue
        if year_max and (not q.get('year') or q['year'] > year_max):
            continue
        if diff_min and (not q.get('difficulty') or q['difficulty'] < diff_min):
            continue
        if diff_max and (not q.get('difficulty') or q['difficulty'] > diff_max):
            continue
        if marks_min and (not q.get('marks') or q['marks'] < marks_min):
            continue
        if marks_max and (not q.get('marks') or q['marks'] > marks_max):
            continue
        if curriculum and q.get('curriculum') != curriculum:
            continue
        if paper3_option and q.get('paper3_option') != paper3_option:
            continue
        results.append(q_id)

    total_count = len(results)
    # Sort by year desc, then question num
    results.sort(key=lambda qid: (
        -(QUESTION_BANK[qid].get('year') or 0),
        QUESTION_BANK[qid].get('original_question_num') or 0
    ))
    page = results[offset:offset + limit]

    return jsonify({
        'total': total_count,
        'questions': [
            {
                'question_id': qid,
                'year': QUESTION_BANK[qid].get('year'),
                'session': QUESTION_BANK[qid].get('session'),
                'tz': QUESTION_BANK[qid].get('tz'),
                'paper': QUESTION_BANK[qid].get('paper'),
                'original_question_num': QUESTION_BANK[qid].get('original_question_num'),
                'topic_code': QUESTION_BANK[qid].get('topic_code'),
                'topic_name': QUESTION_BANK[qid].get('topic_name'),
                'subtopic_code': QUESTION_BANK[qid].get('subtopic_code'),
                'subtopic_name': QUESTION_BANK[qid].get('subtopic_name'),
                'description': QUESTION_BANK[qid].get('description'),
                'marks': QUESTION_BANK[qid].get('marks'),
                'difficulty': QUESTION_BANK[qid].get('difficulty'),
                'has_answer': QUESTION_BANK[qid].get('has_answer'),
                'paper3_option': QUESTION_BANK[qid].get('paper3_option'),
            }
            for qid in page
        ]
    })


@app.route('/api/bank/question/<question_id>')
def bank_get_question(question_id):
    """Get full data for a single question, including page counts."""
    if question_id not in QUESTION_BANK:
        return jsonify({'error': 'Question not found'}), 404
    q = QUESTION_BANK[question_id]
    q_dir = Path(__file__).parent.parent / q['path']
    # Count question and answer image pages
    question_pages = sum(1 for i in range(1, 20) if (q_dir / f'question_p{i}.png').exists())
    answer_pages = sum(1 for i in range(1, 20) if (q_dir / f'answer_p{i}.png').exists())
    return jsonify({'question_id': question_id, **q,
                    'question_pages': question_pages,
                    'answer_pages': answer_pages})


@app.route('/api/bank/random')
def bank_random():
    """Get a random question matching filters."""
    # Reuse filter logic from bank_questions but return single random result
    paper = request.args.get('paper')
    topic = request.args.get('topic')
    subtopic = request.args.get('subtopic')
    year_min = request.args.get('year_min', type=int)
    year_max = request.args.get('year_max', type=int)
    diff_min = request.args.get('diff_min', type=int)
    diff_max = request.args.get('diff_max', type=int)

    candidates = []
    for q_id, q in QUESTION_BANK.items():
        if not q.get('topic_code') or q.get('is_scan'):
            continue
        if paper and q.get('paper') != paper:
            continue
        if topic and q.get('topic_code') != topic:
            continue
        if subtopic and q.get('subtopic_code') != subtopic:
            continue
        if year_min and (not q.get('year') or q['year'] < year_min):
            continue
        if year_max and (not q.get('year') or q['year'] > year_max):
            continue
        if diff_min and (not q.get('difficulty') or q['difficulty'] < diff_min):
            continue
        if diff_max and (not q.get('difficulty') or q['difficulty'] > diff_max):
            continue
        candidates.append(q_id)

    if not candidates:
        return jsonify({'error': 'No questions match filters'}), 404

    q_id = random.choice(candidates)
    return jsonify({'question_id': q_id, **QUESTION_BANK[q_id]})


@app.route('/api/bank/image/<question_id>/<image_name>')
def bank_image(question_id, image_name):
    """Serve a question or answer image from the new practice_new directory."""
    if question_id not in QUESTION_BANK:
        return jsonify({'error': 'Question not found'}), 404
    q = QUESTION_BANK[question_id]
    img_path = Path(__file__).parent.parent / q['path'] / image_name
    if not img_path.exists():
        return jsonify({'error': f'Image not found'}), 404
    return send_file(img_path, mimetype='image/png')


# ── Physics HL Question Bank ──
PHYSICS_BANK_FILE = Path(__file__).parent.parent / "data" / "physics_question_bank.json"
PHYSICS_PRACTICE_DIR = Path(__file__).parent.parent / "practice_physics"

PHYSICS_BANK = {}
if PHYSICS_BANK_FILE.exists():
    with open(PHYSICS_BANK_FILE) as f:
        PHYSICS_BANK = json.load(f)


def _build_physics_index():
    index = {
        'by_topic': defaultdict(list),
        'by_subtopic': defaultdict(list),
        'by_paper': defaultdict(list),
        'by_year': defaultdict(list),
        'by_difficulty': defaultdict(list),
        'topics': {},
    }
    for q_id, q in PHYSICS_BANK.items():
        if not q.get('year'):
            continue
        paper = q.get('paper', '')
        topic = q.get('topic_code')
        subtopic = q.get('subtopic_code')
        year = str(q.get('year', ''))
        diff = str(q.get('difficulty', ''))
        index['by_paper'][paper].append(q_id)
        if year: index['by_year'][year].append(q_id)
        if topic: index['by_topic'][topic].append(q_id)
        if subtopic: index['by_subtopic'][subtopic].append(q_id)
        if diff: index['by_difficulty'][diff].append(q_id)
        if topic and q.get('topic_name'):
            if topic not in index['topics']:
                index['topics'][topic] = {'name': q['topic_name'], 'subtopics': {}}
            if subtopic and q.get('subtopic_name'):
                index['topics'][topic]['subtopics'][subtopic] = q['subtopic_name']
    return index


PHYSICS_INDEX = _build_physics_index()


@app.route('/physics2')
def physics_bank():
    return render_template('physics_question_bank.html')


@app.route('/api/physics/topics')
def physics_topics():
    result = {}
    for topic_code, topic_data in sorted(PHYSICS_INDEX['topics'].items()):
        result[topic_code] = {
            'name': topic_data['name'],
            'count': len(PHYSICS_INDEX['by_topic'].get(topic_code, [])),
            'subtopics': {
                code: {'name': name, 'count': len(PHYSICS_INDEX['by_subtopic'].get(code, []))}
                for code, name in sorted(topic_data['subtopics'].items())
            }
        }
    return jsonify(result)


@app.route('/api/physics/stats')
def physics_stats():
    from collections import Counter
    total = len(PHYSICS_BANK)
    classified = sum(1 for q in PHYSICS_BANK.values() if q.get('topic_code'))
    has_answer = sum(1 for q in PHYSICS_BANK.values() if q.get('has_answer'))
    topic_counts = Counter(q.get('topic_name') for q in PHYSICS_BANK.values() if q.get('topic_name'))
    difficulty_counts = Counter(q.get('difficulty') for q in PHYSICS_BANK.values() if q.get('difficulty'))
    year_counts = Counter(q.get('year') for q in PHYSICS_BANK.values() if q.get('year'))
    paper_counts = Counter(q.get('paper') for q in PHYSICS_BANK.values() if q.get('paper'))
    return jsonify({
        'total': total, 'classified': classified, 'has_answer': has_answer,
        'topics': dict(topic_counts.most_common()),
        'difficulty': {str(k): v for k, v in sorted(difficulty_counts.items()) if k},
        'years': {str(k): v for k, v in sorted(year_counts.items()) if k},
        'papers': dict(paper_counts),
        'user_done': 0, 'user_by_topic': {},
    })


@app.route('/api/physics/questions')
def physics_questions():
    paper = request.args.get('paper')
    topic = request.args.get('topic')
    subtopic = request.args.get('subtopic')
    year_min = request.args.get('year_min', type=int)
    year_max = request.args.get('year_max', type=int)
    diff_min = request.args.get('diff_min', type=int)
    diff_max = request.args.get('diff_max', type=int)
    curriculum = request.args.get('curriculum')
    limit = request.args.get('limit', 200, type=int)
    offset = request.args.get('offset', 0, type=int)

    results = []
    for q_id, q in PHYSICS_BANK.items():
        if paper and q.get('paper') != paper: continue
        if topic and q.get('topic_code') != topic: continue
        if subtopic and q.get('subtopic_code') != subtopic: continue
        if year_min and (not q.get('year') or q['year'] < year_min): continue
        if year_max and (not q.get('year') or q['year'] > year_max): continue
        if diff_min and (not q.get('difficulty') or q['difficulty'] < diff_min): continue
        if diff_max and (not q.get('difficulty') or q['difficulty'] > diff_max): continue
        if curriculum and q.get('curriculum') != curriculum: continue
        results.append(q_id)

    total_count = len(results)
    results.sort(key=lambda qid: (-(PHYSICS_BANK[qid].get('year') or 0), PHYSICS_BANK[qid].get('original_question_num') or 0))
    page = results[offset:offset + limit]

    return jsonify({
        'total': total_count,
        'questions': [{
            'question_id': qid,
            'year': PHYSICS_BANK[qid].get('year'),
            'session': PHYSICS_BANK[qid].get('session'),
            'tz': PHYSICS_BANK[qid].get('tz'),
            'paper': PHYSICS_BANK[qid].get('paper'),
            'original_question_num': PHYSICS_BANK[qid].get('original_question_num'),
            'topic_code': PHYSICS_BANK[qid].get('topic_code'),
            'topic_name': PHYSICS_BANK[qid].get('topic_name'),
            'subtopic_code': PHYSICS_BANK[qid].get('subtopic_code'),
            'subtopic_name': PHYSICS_BANK[qid].get('subtopic_name'),
            'description': PHYSICS_BANK[qid].get('description'),
            'marks': PHYSICS_BANK[qid].get('marks'),
            'difficulty': PHYSICS_BANK[qid].get('difficulty'),
            'has_answer': PHYSICS_BANK[qid].get('has_answer'),
            'is_scan': PHYSICS_BANK[qid].get('is_scan'),
            'curriculum': PHYSICS_BANK[qid].get('curriculum'),
        } for qid in page]
    })


@app.route('/api/physics/question/<question_id>')
def physics_get_question(question_id):
    if question_id not in PHYSICS_BANK:
        return jsonify({'error': 'Question not found'}), 404
    q = PHYSICS_BANK[question_id]
    q_dir = Path(__file__).parent.parent / q['path']
    question_pages = sum(1 for i in range(1, 20) if (q_dir / f'question_p{i}.png').exists())
    answer_pages = sum(1 for i in range(1, 20) if (q_dir / f'answer_p{i}.png').exists())
    return jsonify({'question_id': question_id, **q, 'question_pages': question_pages, 'answer_pages': answer_pages})


@app.route('/api/physics/random')
def physics_random():
    paper = request.args.get('paper')
    topic = request.args.get('topic')
    subtopic = request.args.get('subtopic')
    year_min = request.args.get('year_min', type=int)
    year_max = request.args.get('year_max', type=int)
    diff_min = request.args.get('diff_min', type=int)
    diff_max = request.args.get('diff_max', type=int)
    curriculum = request.args.get('curriculum')

    candidates = []
    for q_id, q in PHYSICS_BANK.items():
        if not q.get('topic_code') or q.get('is_scan'): continue
        if paper and q.get('paper') != paper: continue
        if topic and q.get('topic_code') != topic: continue
        if subtopic and q.get('subtopic_code') != subtopic: continue
        if year_min and (not q.get('year') or q['year'] < year_min): continue
        if year_max and (not q.get('year') or q['year'] > year_max): continue
        if diff_min and (not q.get('difficulty') or q['difficulty'] < diff_min): continue
        if diff_max and (not q.get('difficulty') or q['difficulty'] > diff_max): continue
        if curriculum and q.get('curriculum') != curriculum: continue
        candidates.append(q_id)

    if not candidates:
        return jsonify({'error': 'No questions match filters'}), 404
    q_id = random.choice(candidates)
    return jsonify({'question_id': q_id, **PHYSICS_BANK[q_id]})


@app.route('/api/physics/image/<question_id>/<image_name>')
def physics_image(question_id, image_name):
    if question_id not in PHYSICS_BANK:
        return jsonify({'error': 'Question not found'}), 404
    q = PHYSICS_BANK[question_id]
    img_path = Path(__file__).parent.parent / q['path'] / image_name
    if not img_path.exists():
        return jsonify({'error': 'Image not found'}), 404
    return send_file(img_path, mimetype='image/png')


# ── Built-in AI Chat ──
import secrets
import time
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

CHAT_PASSWORD = os.environ.get('CHAT_PASSWORD', 'xht3i')
_ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
_CHAT_SIGNER = URLSafeTimedSerializer(app.secret_key, salt='chat-token-v1')
_CHAT_TOKEN_MAX_AGE = 7 * 24 * 3600  # 7 days

# Brute-force protection: track failed attempts per IP
_auth_attempts = {}  # ip -> [timestamp, ...]
_AUTH_MAX_ATTEMPTS = 5
_AUTH_LOCKOUT_SECONDS = 15 * 60  # 15 minutes

def _check_rate_limit(ip):
    """Return (allowed, seconds_remaining). Cleans up old entries."""
    now = time.time()
    attempts = [t for t in _auth_attempts.get(ip, []) if now - t < _AUTH_LOCKOUT_SECONDS]
    _auth_attempts[ip] = attempts
    if len(attempts) >= _AUTH_MAX_ATTEMPTS:
        remaining = int(_AUTH_LOCKOUT_SECONDS - (now - attempts[0]))
        return False, remaining
    return True, 0

def _record_failed_attempt(ip):
    _auth_attempts.setdefault(ip, []).append(time.time())

def _clear_attempts(ip):
    _auth_attempts.pop(ip, None)

def _verify_chat_token(token):
    """Returns True if token is valid and not expired."""
    try:
        _CHAT_SIGNER.loads(token, max_age=_CHAT_TOKEN_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False

@app.route('/api/chat/auth', methods=['POST'])
def chat_auth():
    """Exchange password for a signed token. Rate-limited."""
    if not CHAT_PASSWORD:
        return jsonify({'error': 'Chat not configured'}), 503
    ip = request.remote_addr
    allowed, remaining = _check_rate_limit(ip)
    if not allowed:
        return jsonify({'error': f'Too many attempts. Try again in {remaining//60+1} min.'}), 429
    data = request.get_json() or {}
    # Timing-safe comparison prevents timing attacks
    if not secrets.compare_digest(data.get('password', ''), CHAT_PASSWORD):
        _record_failed_attempt(ip)
        allowed2, _ = _check_rate_limit(ip)
        remaining_attempts = _AUTH_MAX_ATTEMPTS - len(_auth_attempts.get(ip, []))
        if not allowed2:
            return jsonify({'error': 'Too many wrong attempts. Locked out for 15 minutes.'}), 429
        return jsonify({'error': f'Wrong password ({max(0,remaining_attempts)} attempts left)'}), 401
    _clear_attempts(ip)
    token = _CHAT_SIGNER.dumps({'v': 1})
    return jsonify({'token': token})

@app.route('/api/chat', methods=['POST'])
def ai_chat():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid request'}), 400

    # Token auth (never touches the raw password after initial login)
    token = data.get('token', '')
    if not token or not _verify_chat_token(token):
        return jsonify({'error': 'Unauthorized'}), 401

    if not _ANTHROPIC_API_KEY:
        return jsonify({'error': 'ANTHROPIC_API_KEY not set on server'}), 503

    messages = data.get('messages', [])
    question_id = data.get('question_id')
    subject = data.get('subject', 'math')

    if not messages:
        return jsonify({'error': 'No messages'}), 400

    # Load question image once (attached to first user message)
    img_b64 = None
    if question_id:
        bank = PHYSICS_BANK if subject == 'physics' else QUESTION_BANK
        q = bank.get(question_id)
        if q:
            img_path = Path(__file__).parent.parent / q['path'] / 'question_p1.png'
            if img_path.exists():
                with open(img_path, 'rb') as f:
                    img_b64 = base64.b64encode(f.read()).decode()

    anthropic_messages = []
    for i, msg in enumerate(messages):
        role = msg.get('role')
        content = msg.get('content', '')
        if role == 'user' and i == 0 and img_b64:
            anthropic_messages.append({
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': img_b64}},
                    {'type': 'text', 'text': content},
                ]
            })
        else:
            anthropic_messages.append({'role': role, 'content': content})

    try:
        import anthropic as _anthropic
        client = _anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
        response = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=1024,
            system=(
                'You are a helpful IB Physics/Math HL tutor. '
                'The student has shared an exam question image. '
                'Give clear, step-by-step explanations. '
                'Be concise but thorough.'
            ),
            messages=anthropic_messages,
        )
        reply = response.content[0].text
        return jsonify({'reply': reply})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# Register unified routes for new interface
from unified_routes import register_unified_routes
register_unified_routes(app)

# Unified practice page route
@app.route('/unified')
def unified_practice():
    """New unified practice interface."""
    return render_template('unified_practice.html')


if __name__ == '__main__':
    import os
    # Check if running in production (Render sets PORT env variable)
    is_production = 'PORT' in os.environ
    port = int(os.environ.get('PORT', 5000))

    socketio.run(
        app,
        host='0.0.0.0' if is_production else '127.0.0.1',
        port=port,
        debug=not is_production,
        allow_unsafe_werkzeug=True
    )
