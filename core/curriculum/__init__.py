"""Curriculum: plans and concepts.

    from core.curriculum import generate_plan, save_plan, list_plans, get_plan, ...
    from core.curriculum.prompts import SETUP_QUESTIONS   # for the UI

Set CURRICULUM_FAKE=1 for a fixed fake plan (no API key needed).
"""

from .service import (delete_plan, edit_plan, generate_diagnostic, generate_plan,
                      generate_practice, generate_quiz, get_definition, get_plan, list_plans,
                      next_new_concept, save_plan)
from .validate import PlanError

__all__ = ["generate_plan", "save_plan", "list_plans", "get_plan", "delete_plan",
           "get_definition", "generate_quiz", "generate_diagnostic", "edit_plan",
           "next_new_concept", "generate_practice", "PlanError"]
