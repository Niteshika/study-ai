"""
Checks an LLM-made plan before anything is saved.

Team rule: never save raw LLM text as a plan. Every plan passes through
`check_plan` first. If it fails, we get a list of plain-English problems
that we can send back to the LLM so it can fix them.
"""
import json

MIN_CONCEPTS = 5
MAX_CONCEPTS = 10
MAX_DEFINITION_WORDS = 35  # retrieval embeds "name: definition" to match notes


def sentence_count(text: str) -> int:
    """Rough count: sentence-ending marks followed by more text, plus one."""
    import re
    text = re.sub(r"\b(e\.g|i\.e|etc|vs)\.", "", text.strip(), flags=re.I)
    return len(re.findall(r"[.!?](?=\s+\S)", text)) + 1


class PlanError(Exception):
    """Raised when a plan can't be used. `.problems` lists what is wrong."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def parse_json(text: str) -> dict:
    """Turn LLM text into a dict. Strips ```json fences if the model added them."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise PlanError([f"Output is not valid JSON ({e.msg})."])
    if not isinstance(data, dict):
        raise PlanError(["Output must be a JSON object with a 'concepts' list."])
    return data


def check_plan(data: dict) -> list[dict]:
    """
    Make sure the plan is usable. Returns the concepts in a safe learning
    order (every concept comes after all of its prerequisites).

    Raises PlanError with every problem found, not just the first one.
    """
    concepts = data.get("concepts")
    if not isinstance(concepts, list):
        raise PlanError(["Missing a 'concepts' list."])

    problems: list[str] = []
    if not (MIN_CONCEPTS <= len(concepts) <= MAX_CONCEPTS):
        problems.append(
            f"Plan has {len(concepts)} concepts; it needs {MIN_CONCEPTS} to {MAX_CONCEPTS}."
        )

    # 1. Every concept has the fields we need, with the right types.
    clean: list[dict] = []
    for i, c in enumerate(concepts):
        if not isinstance(c, dict):
            problems.append(f"Concept #{i + 1} is not an object.")
            continue
        name = c.get("name")
        definition = c.get("definition")
        prereqs = c.get("prerequisites", [])
        if not isinstance(name, str) or not name.strip():
            problems.append(f"Concept #{i + 1} has no name.")
            continue
        if not isinstance(definition, str) or not definition.strip():
            problems.append(f"'{name}' has no definition.")
        else:
            if sentence_count(definition) > 1:
                problems.append(f"'{name}' definition must be one sentence.")
            if len(definition.split()) > MAX_DEFINITION_WORDS:
                problems.append(
                    f"'{name}' definition is too long (max {MAX_DEFINITION_WORDS} words)."
                )
        if not isinstance(prereqs, list) or not all(isinstance(p, str) for p in prereqs):
            problems.append(f"'{name}' prerequisites must be a list of concept names.")
            prereqs = []
        clean.append(
            {
                "name": name.strip(),
                "definition": (definition or "").strip(),
                "prerequisites": [p.strip() for p in prereqs],
            }
        )

    # 2. Names are unique (case doesn't matter).
    seen: dict[str, str] = {}
    for c in clean:
        key = c["name"].lower()
        if key in seen:
            problems.append(f"'{c['name']}' appears more than once.")
        seen[key] = c["name"]

    # 3. Every prerequisite is a concept in this plan, and not the concept itself.
    for c in clean:
        for p in c["prerequisites"]:
            if p.lower() not in seen:
                problems.append(f"'{c['name']}' needs '{p}', which is not in the plan.")
            elif p.lower() == c["name"].lower():
                problems.append(f"'{c['name']}' lists itself as a prerequisite.")

    if problems:
        raise PlanError(problems)

    # 4. No loops (A needs B, B needs A). Also gives us a safe order.
    return safe_order(clean)


def safe_order(concepts: list[dict]) -> list[dict]:
    """
    Put concepts in an order where prerequisites always come first.
    Keeps the LLM's order where it can (it usually knows a good teaching order).
    Raises PlanError if there is a loop.
    """
    by_key = {c["name"].lower(): c for c in concepts}
    remaining = [c["name"].lower() for c in concepts]  # LLM's order
    placed: set[str] = set()
    ordered: list[dict] = []

    while remaining:
        # Pick the earliest concept whose prerequisites are all placed.
        for key in remaining:
            needs = {p.lower() for p in by_key[key]["prerequisites"]}
            if needs <= placed:
                ordered.append(by_key[key])
                placed.add(key)
                remaining.remove(key)
                break
        else:
            stuck = ", ".join(by_key[k]["name"] for k in remaining)
            raise PlanError([f"Prerequisites form a loop among: {stuck}."])

    return ordered
