"""Prompts and setup questions for the curriculum builder."""

# Phase 1: questions the app asks before building a plan.
# The website shows these and passes the answers to generate_plan.
SETUP_QUESTIONS = [
    {
        "key": "level",
        "question": "How much do you already know about this topic?",
        "options": ["Complete beginner", "I know the basics", "Intermediate", "Advanced"],
    },
    {
        "key": "goal",
        "question": "What do you want to be able to do when you're done?",
        "examples": ["Pass an exam", "Build a project", "Crack interviews", "Just understand it"],
    },
    {
        "key": "time",
        "question": "How much time do you have?",
        "examples": ["1 week", "2 weeks, 1 hour a day", "1 month"],
    },
]

PLAN_SYSTEM = """You are a curriculum designer. You break a topic into a small set of \
concepts a learner should study, in the order they should study them.
Reply with JSON only. No extra text."""

PLAN_PROMPT = """Make a learning plan.

Topic: {topic}
Learner's current level: {level}
Learner's goal: {goal}
Time available: {time}

Rules:
- Give between {min_n} and {max_n} concepts. Fit the number to the time available.
- List them in the order the learner should study them.
- Each concept is one idea that can be taught and quizzed in one short session.
- "definition" is ONE plain sentence (under 35 words) a beginner can understand.
  Say what the concept is. Don't repeat the concept's name at the start.
- "prerequisites" lists the names of other concepts FROM THIS SAME LIST that must be
  learned first. Use the exact names. Use [] if none. Never list a concept outside the plan.
- No prerequisite loops.
- Skip things the learner clearly already knows at their level.

Return exactly this shape:
{{
  "concepts": [
    {{"name": "...", "definition": "...", "prerequisites": ["..."]}}
  ]
}}"""

FIX_PROMPT = """Your last plan had these problems:
{problems}

Here is the plan you gave:
{previous}

Return a corrected plan in the same JSON shape. Fix every problem listed."""
