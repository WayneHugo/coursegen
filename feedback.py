"""Turn the learner's reaction to the sample lesson into an updated style guide."""

from __future__ import annotations

import json

from coursegen.llm import LLM
from coursegen.models import FeedbackStyleOut, StyleGuide

QUESTIONS = [
    ("pace", "Pace", ["too slow", "just right", "too fast"]),
    ("depth", "Depth", ["too basic", "just right", "too advanced"]),
    ("examples", "Examples", ["need more", "just right", "too many"]),
    ("length", "Length", ["too short", "just right", "too long"]),
    ("voice", "Voice", ["good", "okay", "change it"]),
    ("slides", "Slides", ["too much text", "just right", "too sparse"]),
]

SYSTEM = (
    "You maintain the style guide for an online course. Given a learner's reaction to a sample lesson, "
    "you update the guide so the remaining lessons suit them better. Change only what the feedback "
    "supports; keep everything else as it is."
)


def ask_interactively(lesson_number: str) -> dict:
    print(f"Feedback on sample lesson {lesson_number}. Press Enter to skip a question.\n")
    out: dict = {"lesson": lesson_number}
    for key, label, options in QUESTIONS:
        menu = "  ".join(f"[{i}] {o}" for i, o in enumerate(options, 1))
        raw = input(f"{label}: {menu}\n> ").strip()
        out[key] = options[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(options) else ""
    out["comments"] = input("Anything else?\n> ").strip()
    return out


def update_style(llm: LLM, style: StyleGuide, feedback: dict, transcript: str) -> FeedbackStyleOut:
    prompt = (
        f"Current style guide:\n{style.model_dump_json(indent=2)}\n\n"
        f"Learner feedback on the sample lesson:\n{json.dumps(feedback, indent=2)}\n\n"
        f"The sample lesson's narration, for reference:\n{transcript}\n\n"
        "Return the updated style guide. Map the feedback to concrete changes: pace and length change "
        "target_minutes and the pace description; 'too fast'/'too slow' for pace may also adjust "
        "voice_speed slightly (0.85-1.15). 'Change it' for voice means pick a different voice_name for the "
        "same voice_backend (piper voices look like en_US-amy-medium or en_GB-alan-medium; edge voices like "
        "en-US-GuyNeural); leave voice_name empty to keep the default. Put any specific requests from the "
        "comments in extra_rules. List each change in plain words. Set replan to true only if the feedback "
        "means the course plan itself is wrong (for example, the whole course is pitched at the wrong level)."
    )
    return llm.structured(SYSTEM, prompt, FeedbackStyleOut, effort="medium")
