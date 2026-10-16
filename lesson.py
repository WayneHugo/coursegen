"""Write one lesson (slides + narration + quiz) and record it as slides with audio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from coursegen.llm import LLM
from coursegen.models import (
    ClaimGroup,
    CoursePlanOut,
    CourseSpec,
    LessonOut,
    Note,
    StyleGuide,
)
from coursegen.player import render_player
from coursegen.voice import Voice, duration_seconds

WORDS_PER_MINUTE = 150

SYSTEM = (
    "You write and narrate lessons for an online course platform. Lessons are slides with a spoken "
    "voice-over. Narration is written for the ear: short sentences, natural spoken rhythm, no markdown, "
    "no URLs, no reading bullet points aloud word for word. On-screen text is brief; the narration "
    "carries the explanation. Only teach what the provided research supports."
)


def lesson_key(arc: int, lesson: int) -> str:
    return f"{arc}-{lesson}"


def write_lesson(llm: LLM, spec: CourseSpec, plan: CoursePlanOut, arc_no: int, lesson_no: int,
                 groups: list[ClaimGroup], notes: list[Note], style: StyleGuide,
                 fix: list[str] | None = None) -> LessonOut:
    arc = plan.arcs[arc_no - 1]
    lesson = arc.lessons[lesson_no - 1]
    gmap = {g.id: g for g in groups}
    nmap = {n.id: n for n in notes}

    research = []
    for gid in lesson.group_ids:
        g = gmap.get(gid)
        if not g:
            continue
        research.append(f"- [{g.status}] {g.merged_claim}" + (f" (disputed: {g.conflict})" if g.conflict else ""))
        research += [f"    · {nmap[x].kind}: {nmap[x].evidence}" for x in g.note_ids if x in nmap]

    earlier = [
        f"{a}.{n} {l.title}"
        for a, arc_ in enumerate(plan.arcs, 1) for n, l in enumerate(arc_.lessons, 1)
        if (a, n) < (arc_no, lesson_no)
    ]
    words = style.target_minutes * WORDS_PER_MINUTE
    prompt = f"""Course: {plan.title} — {plan.summary}
Learner level: {spec.level}. Learner goal: {spec.goal or 'general understanding'}.

Arc {arc_no}: {arc.title} — {arc.goal}
This is lesson {arc_no}.{lesson_no}: "{lesson.title}" (role: {lesson.role})
Objectives:
{chr(10).join('- ' + o for o in lesson.objectives)}
Key points:
{chr(10).join('- ' + k for k in lesson.key_points)}
Exercise: {lesson.exercise}

Lessons the learner has already taken: {', '.join(earlier) or 'none, this is the first lesson'}

Research to draw on (claims with their status, then supporting evidence):
{chr(10).join(research) or '- (none attached; stay within well-established basics)'}

Style guide:
- Tone: {style.tone}
- Pace: {style.pace}
- Depth: {style.depth}
- Examples: {style.examples}
{chr(10).join('- ' + r for r in style.extra_rules)}

Write the lesson as 8-14 slides with about {words} words of narration in total (about {style.target_minutes} minutes).
Start with a title slide whose narration hooks the learner and says what they will be able to do.
Use 'code' slides for code, with the code in the code field. Walk through the exercise on its own slide.
End with a 'summary' slide that recaps and previews the next lesson.
If a claim is contested, say so plainly rather than picking a side.
Then write 3-5 multiple-choice quiz questions (4 options each) that check the objectives, with
answer_index (0-based) and a one-sentence explanation."""
    if fix:
        prompt += "\n\nA previous draft had these problems, fix them:\n" + "\n".join("- " + p for p in fix)
    return llm.structured(SYSTEM, prompt, LessonOut, effort="high")


def check_lesson(lesson: LessonOut, style: StyleGuide) -> list[str]:
    problems = []
    if not lesson.slides:
        problems.append("lesson has no slides")
    for i, q in enumerate(lesson.quiz, 1):
        if not 0 <= q.answer_index < len(q.options):
            problems.append(f"quiz question {i} has an answer_index outside its options")
    words = sum(len(s.narration.split()) for s in lesson.slides)
    target = style.target_minutes * WORDS_PER_MINUTE
    if not 0.6 * target <= words <= 1.5 * target:
        problems.append(f"narration is {words} words; target is about {target}")
    return problems


def lesson_sources(lesson_plan_group_ids: list[str], groups: list[ClaimGroup], notes: list[Note]) -> list[str]:
    gmap = {g.id: g for g in groups}
    nmap = {n.id: n for n in notes}
    urls = []
    for gid in lesson_plan_group_ids:
        for nid in gmap[gid].note_ids if gid in gmap else []:
            url = nmap[nid].source_url if nid in nmap else ""
            if url.startswith("http") and url not in urls:
                urls.append(url)
    return urls


def record_lesson(lesson: LessonOut, voice: Voice, out_dir: Path, meta: dict,
                  log: Callable[[str], None] = print) -> Path:
    """Narrate each slide to its own audio file and write the slide player."""
    audio_dir = out_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    slides = []
    for i, slide in enumerate(lesson.slides, 1):
        log(f"[record] slide {i}/{len(lesson.slides)}: {slide.heading}")
        audio = voice.synthesize(slide.narration, audio_dir / f"slide-{i:02d}")
        slides.append({**slide.model_dump(), "audio": f"audio/{audio.name}",
                       "seconds": duration_seconds(audio)})
    data = {**meta, "title": lesson.title, "voice": voice.name, "slides": slides,
            "quiz": [q.model_dump() for q in lesson.quiz]}
    (out_dir / "lesson.json").write_text(json.dumps(data, indent=2))
    (out_dir / "transcript.md").write_text(_transcript(lesson))
    player = out_dir / "index.html"
    player.write_text(render_player(data))
    return player


def _transcript(lesson: LessonOut) -> str:
    parts = [f"# {lesson.title}", ""]
    for i, s in enumerate(lesson.slides, 1):
        parts += [f"## {i}. {s.heading}", "", s.narration, ""]
    return "\n".join(parts)

