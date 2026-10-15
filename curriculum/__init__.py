"""Person 2: Curriculum.

    from curriculum import generate_plan, get_definition, generate_quiz, ...
    from curriculum.prompts import SETUP_QUESTIONS   # for the UI

Set CURRICULUM_FAKE=1 for a fixed fake plan (no API key needed).
"""

from .core import (edit_plan, generate_diagnostic, generate_plan, generate_practice,
                   generate_quiz, get_definition, next_new_concept)
from .validate import PlanError

__all__ = ["generate_plan", "get_definition", "generate_quiz", "generate_diagnostic",
           "edit_plan", "next_new_concept", "generate_practice", "PlanError"]
