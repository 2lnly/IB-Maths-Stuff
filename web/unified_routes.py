"""
Unified API routes for all subjects.
Uses SubjectManager to provide a consistent interface across Math, Physics, and Economics.
"""

from flask import jsonify, request, session, send_file
from subject_manager import SubjectManager
from database import get_db_connection, execute_query
from pathlib import Path
import json


def register_unified_routes(app):
    """Register all unified routes with the Flask app."""

    @app.route('/api/subjects')
    def unified_get_subjects():
        """Get list of available subjects."""
        subjects = SubjectManager.get_available_subjects()
        return jsonify({'subjects': subjects})

    @app.route('/api/subject/<subject>/info')
    def unified_get_subject_info(subject):
        """Get metadata about a specific subject."""
        try:
            manager = SubjectManager(subject)
            info = manager.get_subject_info()

            # Add topics structure
            info['topics'] = manager.get_topics()

            return jsonify(info)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/subject/<subject>/random')
    def unified_get_random_question(subject):
        """Get a random question from a subject with optional filters."""
        try:
            manager = SubjectManager(subject)

            # Parse filters from query params
            filters = {}
            if request.args.get('paper'):
                filters['paper'] = request.args.get('paper')
            if request.args.get('topics'):
                filters['topics'] = request.args.get('topics').split(',')
            if request.args.get('subtopics'):
                filters['subtopics'] = request.args.get('subtopics').split(',')
            if request.args.get('year_min'):
                filters['year_min'] = int(request.args.get('year_min'))
            if request.args.get('year_max'):
                filters['year_max'] = int(request.args.get('year_max'))

            # Get random question
            question = manager.get_random_question(filters)

            if not question:
                return jsonify({'error': 'No questions found matching filters'}), 404

            return jsonify({'question': question})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/subject/<subject>/filter')
    def unified_filter_questions(subject):
        """Get filtered list of questions."""
        try:
            manager = SubjectManager(subject)

            # Parse filters from query params
            filters = {}
            if request.args.get('paper'):
                filters['paper'] = request.args.get('paper')
            if request.args.get('topics'):
                filters['topics'] = request.args.get('topics').split(',')
            if request.args.get('subtopics'):
                filters['subtopics'] = request.args.get('subtopics').split(',')
            if request.args.get('year_min'):
                filters['year_min'] = int(request.args.get('year_min'))
            if request.args.get('year_max'):
                filters['year_max'] = int(request.args.get('year_max'))
            if request.args.get('limit'):
                filters['limit'] = int(request.args.get('limit'))

            # Get filtered questions
            questions = manager.filter_questions(filters)

            return jsonify({
                'questions': questions,
                'count': len(questions)
            })
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/subject/<subject>/question/<question_id>')
    def unified_get_question_display_data(subject, question_id):
        """Get display data for a specific question."""
        try:
            manager = SubjectManager(subject)
            data = manager.get_question_display_data(question_id)

            if not data:
                return jsonify({'error': 'Question not found'}), 404

            return jsonify(data)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/subject/<subject>/browse')
    def unified_browse_hierarchy(subject):
        """Browse question hierarchy for ranger-style navigation."""
        try:
            manager = SubjectManager(subject)

            # Get level (topics, subtopics, years, questions)
            level = request.args.get('level', 'topics')

            # Parse filters
            filters = {}
            if request.args.get('topics'):
                filters['topics'] = request.args.get('topics').split(',')
            if request.args.get('subtopics'):
                filters['subtopics'] = request.args.get('subtopics').split(',')
            if request.args.get('year'):
                filters['year'] = request.args.get('year')

            # Browse hierarchy
            items = manager.browse_hierarchy(level, filters)

            return jsonify({
                'level': level,
                'items': items,
                'count': len(items)
            })
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/subject/<subject>/generate', methods=['POST'])
    def unified_generate_paper(subject):
        """Generate a question paper based on filters."""
        try:
            if 'username' not in session:
                return jsonify({'error': 'Not logged in'}), 401

            manager = SubjectManager(subject)

            # Parse request data
            data = request.get_json()
            filters = data.get('filters', {})
            count = data.get('count', 10)
            paper_name = data.get('paper_name', 'Untitled Paper')

            # Apply count limit
            filters['limit'] = count

            # Get questions
            questions = manager.filter_questions(filters)

            if not questions:
                return jsonify({'error': 'No questions found matching filters'}), 404

            # Get full display data for each question
            question_details = []
            question_ids = []
            for q in questions:
                display_data = manager.get_question_display_data(q['question_id'])
                if display_data:
                    question_details.append(display_data)
                    question_ids.append(q['question_id'])

            # Save to database if requested
            if data.get('save', False):
                username = session['username']
                with get_db_connection() as conn:
                    cursor = conn.cursor()

                    # Get user_id
                    execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
                    user_row = cursor.fetchone()
                    if not user_row:
                        return jsonify({'error': 'User not found'}), 404
                    user_id = user_row[0]

                    # Save generated paper
                    if app.config.get('USE_POSTGRES', False):
                        execute_query(cursor, '''
                            INSERT INTO generated_papers (user_id, paper_name, subject, filters, question_ids)
                            VALUES (%s, %s, %s, %s, %s)
                            RETURNING id
                        ''', (user_id, paper_name, subject, json.dumps(filters), question_ids))
                        paper_id = cursor.fetchone()[0]
                    else:
                        execute_query(cursor, '''
                            INSERT INTO generated_papers (user_id, paper_name, subject, filters, question_ids)
                            VALUES (%s, %s, %s, %s, %s)
                        ''', (user_id, paper_name, subject, json.dumps(filters), json.dumps(question_ids)))
                        paper_id = cursor.lastrowid

                return jsonify({
                    'questions': question_details,
                    'count': len(question_details),
                    'paper_id': paper_id,
                    'saved': True
                })

            return jsonify({
                'questions': question_details,
                'count': len(question_details),
                'saved': False
            })
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/filter-presets', methods=['GET', 'POST', 'DELETE'])
    def unified_manage_filter_presets():
        """Manage user's filter presets."""
        try:
            if 'username' not in session:
                return jsonify({'error': 'Not logged in'}), 401

            username = session['username']

            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Get user_id
                execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
                user_row = cursor.fetchone()
                if not user_row:
                    return jsonify({'error': 'User not found'}), 404
                user_id = user_row[0]

                if request.method == 'GET':
                    # Get all presets for user
                    subject = request.args.get('subject')
                    if subject:
                        execute_query(cursor, '''
                            SELECT id, preset_name, subject, filters, created_at
                            FROM user_filter_presets
                            WHERE user_id = %s AND subject = %s
                            ORDER BY created_at DESC
                        ''', (user_id, subject))
                    else:
                        execute_query(cursor, '''
                            SELECT id, preset_name, subject, filters, created_at
                            FROM user_filter_presets
                            WHERE user_id = %s
                            ORDER BY created_at DESC
                        ''', (user_id,))

                    presets = []
                    for row in cursor.fetchall():
                        preset = {
                            'id': row[0],
                            'preset_name': row[1],
                            'subject': row[2],
                            'filters': json.loads(row[3]) if isinstance(row[3], str) else row[3],
                            'created_at': str(row[4])
                        }
                        presets.append(preset)

                    return jsonify({'presets': presets})

                elif request.method == 'POST':
                    # Save new preset
                    data = request.get_json()
                    preset_name = data.get('preset_name')
                    subject = data.get('subject')
                    filters = data.get('filters', {})

                    if not preset_name or not subject:
                        return jsonify({'error': 'preset_name and subject required'}), 400

                    execute_query(cursor, '''
                        INSERT INTO user_filter_presets (user_id, preset_name, subject, filters)
                        VALUES (%s, %s, %s, %s)
                    ''', (user_id, preset_name, subject, json.dumps(filters)))

                    return jsonify({'success': True, 'message': 'Preset saved'})

                elif request.method == 'DELETE':
                    # Delete preset
                    preset_id = request.args.get('preset_id')
                    if not preset_id:
                        return jsonify({'error': 'preset_id required'}), 400

                    execute_query(cursor, '''
                        DELETE FROM user_filter_presets
                        WHERE id = %s AND user_id = %s
                    ''', (preset_id, user_id))

                    return jsonify({'success': True, 'message': 'Preset deleted'})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/generated-papers')
    def unified_get_generated_papers():
        """Get user's saved generated papers."""
        try:
            if 'username' not in session:
                return jsonify({'error': 'Not logged in'}), 401

            username = session['username']

            with get_db_connection() as conn:
                cursor = conn.cursor()

                # Get user_id
                execute_query(cursor, 'SELECT id FROM users WHERE username = %s', (username,))
                user_row = cursor.fetchone()
                if not user_row:
                    return jsonify({'error': 'User not found'}), 404
                user_id = user_row[0]

                # Get papers
                subject = request.args.get('subject')
                if subject:
                    execute_query(cursor, '''
                        SELECT id, paper_name, subject, filters, question_ids, created_at
                        FROM generated_papers
                        WHERE user_id = %s AND subject = %s
                        ORDER BY created_at DESC
                    ''', (user_id, subject))
                else:
                    execute_query(cursor, '''
                        SELECT id, paper_name, subject, filters, question_ids, created_at
                        FROM generated_papers
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                    ''', (user_id,))

                papers = []
                for row in cursor.fetchall():
                    paper = {
                        'id': row[0],
                        'paper_name': row[1],
                        'subject': row[2],
                        'filters': json.loads(row[3]) if isinstance(row[3], str) else row[3],
                        'question_ids': json.loads(row[4]) if isinstance(row[4], str) else row[4],
                        'created_at': str(row[5])
                    }
                    papers.append(paper)

                return jsonify({'papers': papers})

        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/check-auth')
    def unified_check_auth():
        """Check if user is authenticated."""
        if 'username' in session:
            return jsonify({
                'authenticated': True,
                'username': session['username']
            })
        return jsonify({'authenticated': False})

    @app.route('/api/image/<subject>/<folder>/<image>')
    def unified_serve_image(subject, folder, image):
        """Serve question images for unified interface."""
        try:
            base_dir = Path('/home/xiaohe/stuff/claudable')

            # Get subject base path
            subject_paths = {
                'math': 'practice',
                'physics': 'Physics Flattened',
                'economics': 'economics'
            }

            if subject not in subject_paths:
                return jsonify({'error': 'Invalid subject'}), 400

            # Construct image path
            # folder is like "Paper_1/Q176_TZ1_2012_sequences"
            image_path = base_dir / subject_paths[subject] / folder / image

            if not image_path.exists():
                return jsonify({'error': 'Image not found'}), 404

            return send_file(str(image_path))
        except Exception as e:
            return jsonify({'error': str(e)}), 500
