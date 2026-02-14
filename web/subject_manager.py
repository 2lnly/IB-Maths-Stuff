"""
SubjectManager: Unified interface for all three subjects (Math, Physics, Economics).

This module provides a consistent API for accessing questions across different subjects,
each of which has its own data structure and organization.
"""

import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod


class SubjectAdapter(ABC):
    """Abstract base class for subject-specific adapters."""

    def __init__(self, data: Dict, base_path: Path):
        self.data = data
        self.base_path = base_path

    @abstractmethod
    def get_topics(self, paper: Optional[str] = None) -> Dict[str, Dict[str, List[str]]]:
        """
        Returns nested structure of topics and subtopics organized by paper.
        Format: {paper: {topic: [subtopics]}}
        """
        pass

    @abstractmethod
    def filter_questions(self, filters: Dict) -> List[Dict]:
        """
        Apply filters and return matching questions.
        Filters: {paper, topics[], subtopics[], year_min, year_max, limit}
        """
        pass

    @abstractmethod
    def get_question_display_data(self, question_id: str) -> Dict:
        """
        Returns unified structure for displaying a question.
        Format: {
            mode: "image" | "text",
            question_id: str,
            metadata: {...},
            images: [...] if mode=image,
            text: {...} if mode=text,
            answer_images: [...] if mode=image,
            answer_text: str if mode=text
        }
        """
        pass

    @abstractmethod
    def browse_hierarchy(self, level: str, filters: Dict) -> List[Dict]:
        """
        Return items at a specific hierarchy level for ranger-style browsing.
        Levels: "topics" | "subtopics" | "years" | "questions"
        """
        pass


class MathAdapter(SubjectAdapter):
    """Adapter for Math practice questions."""

    def get_topics(self, paper: Optional[str] = None) -> Dict[str, Dict[str, List[str]]]:
        """Get math topics organized by paper."""
        result = {}

        for question in self.data.values():
            q_paper = question.get('paper', 'Paper1')
            topic = question.get('primary_topic', 'unknown')
            subtopic = question.get('primary_subtopic', 'unknown')

            if paper and q_paper != paper:
                continue

            if q_paper not in result:
                result[q_paper] = {}
            if topic not in result[q_paper]:
                result[q_paper][topic] = []
            if subtopic not in result[q_paper][topic]:
                result[q_paper][topic].append(subtopic)

        return result

    def filter_questions(self, filters: Dict) -> List[Dict]:
        """Filter math questions."""
        papers = filters.get('papers', [])
        topics = filters.get('topics', [])
        subtopics = filters.get('subtopics', [])
        year_min = filters.get('year_min')
        year_max = filters.get('year_max')
        limit = filters.get('limit')

        results = []

        for question_id, question in self.data.items():
            # Paper filter (support multiple papers)
            if papers and question.get('paper') not in papers:
                continue

            # Topics filter (if specified)
            if topics and question.get('primary_topic') not in topics:
                continue

            # Subtopics filter (if specified)
            if subtopics and question.get('primary_subtopic') not in subtopics:
                continue

            # Year filter - math practice has year="practice", skip year filtering
            # (In future, could parse from source_info.txt if needed)

            # Ensure question_id is in the result
            question_copy = dict(question)
            question_copy['question_id'] = question_id
            results.append(question_copy)

        # Shuffle for randomness
        random.shuffle(results)

        # Apply limit
        if limit:
            results = results[:limit]

        return results

    def get_question_display_data(self, question_id: str) -> Dict:
        """Get math question display data."""
        question = self.data.get(question_id)
        if not question:
            return None

        # JSON path already includes the base folder, so use parent directory
        question_path = self.base_path.parent / question['path']

        # Math uses images
        return {
            'mode': 'image',
            'question_id': question_id,
            'metadata': {
                'paper': question.get('paper'),
                'topic': question.get('primary_topic'),
                'subtopic': question.get('primary_subtopic'),
                'description': question.get('description'),
            },
            'question_path': str(question_path),
            'relative_path': question['path'],  # Relative path for image URLs
            'images': self._get_question_images(question_path),
            'answer_images': self._get_answer_images(question_path),
        }

    def _get_question_images(self, question_path: Path) -> List[str]:
        """Get list of question image filenames."""
        if not question_path.exists():
            return []
        images = sorted([f.name for f in question_path.glob('question_p*.png')])
        return images

    def _get_answer_images(self, question_path: Path) -> List[str]:
        """Get list of answer image filenames."""
        if not question_path.exists():
            return []
        images = sorted([f.name for f in question_path.glob('answer_p*.png')])
        return images

    def browse_hierarchy(self, level: str, filters: Dict) -> List[Dict]:
        """Browse math hierarchy."""
        if level == "topics":
            # Return all unique topics with counts
            topics = {}
            for question in self.data.values():
                topic = question.get('primary_topic', 'unknown')
                topics[topic] = topics.get(topic, 0) + 1
            return [{'name': topic, 'count': count} for topic, count in sorted(topics.items())]

        elif level == "subtopics":
            # Return subtopics for selected topic(s)
            selected_topics = filters.get('topics', [])
            subtopics = {}
            for question in self.data.values():
                topic = question.get('primary_topic')
                if not selected_topics or topic in selected_topics:
                    subtopic = question.get('primary_subtopic', 'unknown')
                    subtopics[subtopic] = subtopics.get(subtopic, 0) + 1
            return [{'name': subtopic, 'count': count} for subtopic, count in sorted(subtopics.items())]

        elif level == "years":
            # Math practice doesn't have real years, return papers instead
            papers = {}
            for question in self.data.values():
                paper = question.get('paper', 'Paper1')
                papers[paper] = papers.get(paper, 0) + 1
            return [{'name': paper, 'count': count} for paper, count in sorted(papers.items())]

        elif level == "questions":
            # Return filtered questions
            questions = self.filter_questions(filters)
            return [{'question_id': q['question_id'], 'metadata': q} for q in questions]

        return []


class PhysicsAdapter(SubjectAdapter):
    """Adapter for Physics questions."""

    def get_topics(self, paper: Optional[str] = None) -> Dict[str, Dict[str, List[str]]]:
        """Get physics topics organized by paper."""
        result = {}

        for question in self.data.values():
            q_paper = question.get('paper', 'Paper 1')
            topic = question.get('primary_topic', 'unknown')
            subtopic = question.get('primary_subtopic', 'unknown')

            if paper and q_paper != paper:
                continue

            if q_paper not in result:
                result[q_paper] = {}
            if topic not in result[q_paper]:
                result[q_paper][topic] = []
            if subtopic not in result[q_paper][topic]:
                result[q_paper][topic].append(subtopic)

        return result

    def filter_questions(self, filters: Dict) -> List[Dict]:
        """Filter physics questions."""
        papers = filters.get('papers', [])
        topics = filters.get('topics', [])
        subtopics = filters.get('subtopics', [])
        year_min = filters.get('year_min')
        year_max = filters.get('year_max')
        limit = filters.get('limit')

        results = []

        for question_id, question in self.data.items():
            # Paper filter (support multiple papers)
            if papers and question.get('paper') not in papers:
                continue

            # Topics filter
            if topics and question.get('primary_topic') not in topics:
                continue

            # Subtopics filter
            if subtopics and question.get('primary_subtopic') not in subtopics:
                continue

            # Year filter
            year = question.get('year')
            if year:
                try:
                    year_int = int(year)
                    if year_min and year_int < year_min:
                        continue
                    if year_max and year_int > year_max:
                        continue
                except (ValueError, TypeError):
                    pass

            # Ensure question_id is in the result
            question_copy = dict(question)
            question_copy['question_id'] = question_id
            results.append(question_copy)

        # Shuffle for randomness
        random.shuffle(results)

        # Apply limit
        if limit:
            results = results[:limit]

        return results

    def get_question_display_data(self, question_id: str) -> Dict:
        """Get physics question display data."""
        question = self.data.get(question_id)
        if not question:
            return None

        question_path = Path(question['path'])

        # Check if question has text or just images
        text_file = question_path / 'question_text.txt'
        has_text = text_file.exists()

        result = {
            'mode': 'image',  # Physics primarily uses images
            'question_id': question_id,
            'metadata': {
                'paper': question.get('paper'),
                'topic': question.get('primary_topic'),
                'subtopic': question.get('primary_subtopic'),
                'topic_code': question.get('topic_code'),
                'subtopic_code': question.get('subtopic_code'),
                'year': question.get('year'),
                'session': question.get('session'),
                'tz': question.get('tz'),
                'text_incomplete': question.get('text_incomplete', False),
            },
            'question_path': str(question_path),
            'relative_path': str(question_path).replace('/home/xiaohe/stuff/claudable/Physics Flattened/', ''),  # Relative path for image URLs
            'images': self._get_question_images(question_path),
            'answer_images': self._get_answer_images(question_path),
        }

        # Add text if available
        if has_text:
            with open(text_file, 'r', encoding='utf-8') as f:
                result['question_text'] = f.read()

        # Add answer text if available
        answer_text_file = question_path / 'answer.txt'
        if answer_text_file.exists():
            with open(answer_text_file, 'r', encoding='utf-8') as f:
                result['answer_text'] = f.read()

        return result

    def _get_question_images(self, question_path: Path) -> List[str]:
        """Get list of question image filenames."""
        if not question_path.exists():
            return []
        images = sorted([f.name for f in question_path.glob('question_p*.png')])
        return images

    def _get_answer_images(self, question_path: Path) -> List[str]:
        """Get list of answer image filenames."""
        if not question_path.exists():
            return []
        # Physics uses 'answer.png' or 'answer_p*.png'
        images = sorted([f.name for f in question_path.glob('answer*.png')])
        return images

    def browse_hierarchy(self, level: str, filters: Dict) -> List[Dict]:
        """Browse physics hierarchy."""
        if level == "topics":
            # Return all unique topics with counts
            topics = {}
            for question in self.data.values():
                topic = question.get('primary_topic', 'unknown')
                topics[topic] = topics.get(topic, 0) + 1
            return [{'name': topic, 'count': count} for topic, count in sorted(topics.items())]

        elif level == "subtopics":
            # Return subtopics for selected topic(s)
            selected_topics = filters.get('topics', [])
            subtopics = {}
            for question in self.data.values():
                topic = question.get('primary_topic')
                if not selected_topics or topic in selected_topics:
                    subtopic = question.get('primary_subtopic', 'unknown')
                    subtopic_code = question.get('subtopic_code', '')
                    key = f"{subtopic_code}: {subtopic}" if subtopic_code else subtopic
                    subtopics[key] = subtopics.get(key, 0) + 1
            return [{'name': subtopic, 'count': count} for subtopic, count in sorted(subtopics.items())]

        elif level == "years":
            # Return years for selected topics/subtopics
            selected_topics = filters.get('topics', [])
            selected_subtopics = filters.get('subtopics', [])
            years = {}
            for question in self.data.values():
                # Apply topic/subtopic filters
                if selected_topics and question.get('primary_topic') not in selected_topics:
                    continue
                if selected_subtopics and question.get('primary_subtopic') not in selected_subtopics:
                    continue

                year = question.get('year', 'unknown')
                years[year] = years.get(year, 0) + 1
            return [{'name': year, 'count': count} for year, count in sorted(years.items())]

        elif level == "questions":
            # Return filtered questions
            questions = self.filter_questions(filters)
            return [{'question_id': q['question_id'], 'metadata': q} for q in questions]

        return []


class EconomicsAdapter(SubjectAdapter):
    """Adapter for Economics questions."""

    def get_topics(self, paper: Optional[str] = None) -> Dict[str, Dict[str, List[str]]]:
        """Get economics topics organized by paper."""
        result = {}

        for question in self.data.values():
            q_paper = question.get('paper', 'Paper 1')
            topic = question.get('primary_topic', question.get('topic', 'unknown'))

            if paper and q_paper != paper:
                continue

            if q_paper not in result:
                result[q_paper] = {}
            if topic not in result[q_paper]:
                # Economics doesn't have subtopics, use empty list
                result[q_paper][topic] = []

        return result

    def filter_questions(self, filters: Dict) -> List[Dict]:
        """Filter economics questions."""
        papers = filters.get('papers', [])
        topics = filters.get('topics', [])
        year_min = filters.get('year_min')
        year_max = filters.get('year_max')
        limit = filters.get('limit')

        results = []

        for question_id, question in self.data.items():
            # Paper filter (support multiple papers)
            if papers and question.get('paper') not in papers:
                continue

            # Topics filter
            q_topic = question.get('primary_topic', question.get('topic'))
            if topics and q_topic not in topics:
                continue

            # Year filter
            year = question.get('year')
            if year:
                try:
                    year_int = int(year)
                    if year_min and year_int < year_min:
                        continue
                    if year_max and year_int > year_max:
                        continue
                except (ValueError, TypeError):
                    pass

            # Ensure question_id is in the result
            question_copy = dict(question)
            question_copy['question_id'] = question_id
            results.append(question_copy)

        # Shuffle for randomness
        random.shuffle(results)

        # Apply limit
        if limit:
            results = results[:limit]

        return results

    def get_question_display_data(self, question_id: str) -> Dict:
        """Get economics question display data."""
        question = self.data.get(question_id)
        if not question:
            return None

        # Economics uses text display
        return {
            'mode': 'text',
            'question_id': question_id,
            'metadata': {
                'paper': question.get('paper'),
                'topic': question.get('primary_topic', question.get('topic')),
                'year': question.get('year'),
                'session': question.get('session'),
                'tz': question.get('tz'),
                'question_num': question.get('question_num'),
                'is_15_marker': question.get('is_15_marker', False),
            },
            'text': {
                'part_a': question.get('part_a', ''),
                'part_b': question.get('part_b', ''),
                'full_text': question.get('full_text', ''),
            },
            'answer_text': question.get('markscheme', ''),
        }

    def browse_hierarchy(self, level: str, filters: Dict) -> List[Dict]:
        """Browse economics hierarchy."""
        if level == "topics":
            # Return all unique topics with counts
            topics = {}
            for question in self.data.values():
                topic = question.get('primary_topic', question.get('topic', 'unknown'))
                topics[topic] = topics.get(topic, 0) + 1
            return [{'name': topic, 'count': count} for topic, count in sorted(topics.items())]

        elif level == "subtopics":
            # Economics doesn't have subtopics, return empty
            return []

        elif level == "years":
            # Return years for selected topics
            selected_topics = filters.get('topics', [])
            years = {}
            for question in self.data.values():
                # Apply topic filter
                q_topic = question.get('primary_topic', question.get('topic'))
                if selected_topics and q_topic not in selected_topics:
                    continue

                year = question.get('year', 'unknown')
                years[year] = years.get(year, 0) + 1
            return [{'name': year, 'count': count} for year, count in sorted(years.items())]

        elif level == "questions":
            # Return filtered questions
            questions = self.filter_questions(filters)
            return [{'question_id': q['question_id'], 'metadata': q} for q in questions]

        return []


class SubjectManager:
    """
    Unified interface for accessing questions across all subjects.
    Routes should use this class to interact with subject data.
    """

    SUBJECTS = {
        'math': {
            'name': 'Mathematics AA HL',
            'json_file': 'practice_classification_results.json',
            'base_path': 'practice',
            'adapter_class': MathAdapter,
        },
        'physics': {
            'name': 'Physics HL',
            'json_file': 'physics_classification_results.json',
            'base_path': 'Physics Flattened',
            'adapter_class': PhysicsAdapter,
        },
        'economics': {
            'name': 'Economics SL',
            'json_file': 'economics_classification_results.json',
            'base_path': 'economics',
            'adapter_class': EconomicsAdapter,
        },
    }

    def __init__(self, subject: str, base_dir: str = None):
        if subject not in self.SUBJECTS:
            raise ValueError(f"Unknown subject: {subject}. Must be one of {list(self.SUBJECTS.keys())}")

        self.subject = subject
        # Default base_dir is parent of web/ directory
        if base_dir is None:
            base_dir = Path(__file__).parent.parent
        self.base_dir = Path(base_dir)
        self.config = self.SUBJECTS[subject]

        # Load JSON data
        json_path = self.base_dir / 'data' / self.config['json_file']
        with open(json_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

        # Create adapter
        subject_base_path = self.base_dir / self.config['base_path']
        adapter_class = self.config['adapter_class']
        self.adapter = adapter_class(self.data, subject_base_path)

    @classmethod
    def get_available_subjects(cls) -> List[Dict[str, str]]:
        """Get list of available subjects."""
        return [
            {'id': subject_id, 'name': config['name']}
            for subject_id, config in cls.SUBJECTS.items()
        ]

    def get_topics(self, paper: Optional[str] = None) -> Dict:
        """Get topics and subtopics for this subject."""
        return self.adapter.get_topics(paper)

    def filter_questions(self, filters: Dict) -> List[Dict]:
        """Filter questions based on criteria."""
        return self.adapter.filter_questions(filters)

    def get_random_question(self, filters: Optional[Dict] = None) -> Optional[Dict]:
        """Get a single random question matching filters."""
        questions = self.filter_questions(filters or {})
        return questions[0] if questions else None

    def get_question_display_data(self, question_id: str) -> Optional[Dict]:
        """Get display data for a specific question."""
        return self.adapter.get_question_display_data(question_id)

    def browse_hierarchy(self, level: str, filters: Optional[Dict] = None) -> List[Dict]:
        """Browse question hierarchy at a specific level."""
        return self.adapter.browse_hierarchy(level, filters or {})

    def get_subject_info(self) -> Dict:
        """Get metadata about this subject."""
        return {
            'subject_id': self.subject,
            'name': self.config['name'],
            'total_questions': len(self.data),
            'papers': list(self.get_topics().keys()),
        }
