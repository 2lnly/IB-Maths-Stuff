"""Test with a real question."""
import sys
sys.path.insert(0, '/home/xiaohe/stuff/claudable/physics_organizer')

from classify import FastClassifier
from config import Config

config = Config()
classifier = FastClassifier(config, model="llama3.2:3b")

# Real question text
question_text = """35
M13/4/PHYSIHPZIENGITZIXX
B4: This question is in two parts. Part I is about gravitational force fields. Part 2 is about properties of a gas:
Part 1
Gravitational force fields
State Newton 's universal law of gravitation:
[2]
A satellite of mass m orbits a planet of mass M. Derive the following relationship between the period of the satellite T and the radius of its orbit R (Kepler's third law) [3]
4w? R3 T2 = GM"""

print("Testing with real question...")
print()

result = classifier.classify(question_text)

print(f"Result: {result}")

if result:
    print(f"Topic: {result.get('primary_topic')}")
    print(f"Subtopic: {result.get('primary_subtopic')}")
