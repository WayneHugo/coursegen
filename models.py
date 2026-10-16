"""Data shapes for every pipeline stage.

Classes ending in `Out` are what the model returns (used as structured-output
schemas). The others are what the pipeline stores on disk.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


# ---------- Stage 1: scope ----------

class CourseSpec(BaseModel):
    topic: str
    level: str = "beginner"
    goal: str = ""
    num_arcs: int = 3


class SearchAngle(BaseModel):
    angle: str  # e.g. "core concepts", "common mistakes"
    query: str  # the search query to run
    why: str


class ResearchPlanOut(BaseModel):
    angles: list[SearchAngle]


# ---------- Stage 2: research ----------

class Source(BaseModel):
    url: str
    title: str = ""


class Dossier(BaseModel):
    angle: str
    query: str
    text: str
    sources: list[Source]


# ---------- Stage 3: read / notes ----------

NoteKind = Literal["definition", "explanation", "example", "pitfall", "practice", "fact", "opinion"]


class NoteOut(BaseModel):
    claim: str
    evidence: str  # short supporting detail or paraphrase from the source
    source_url: str
    concepts: list[str]
    kind: NoteKind


class NoteSetOut(BaseModel):
    notes: list[NoteOut]


class Note(NoteOut):
    id: str
    angle: str
    from_memory: bool = False


# ---------- Stage 4: compare ----------

class ClaimGroupOut(BaseModel):
    merged_claim: str
    note_ids: list[str]
    status: Literal["consensus", "contested", "single_source"]
    conflict: str  # what the sources disagree on; empty unless contested


class ComparisonOut(BaseModel):
    groups: list[ClaimGroupOut]


class ClaimGroup(ClaimGroupOut):
    id: str


# ---------- Stage 5: themes ----------

class ThemeOut(BaseModel):
    id: str  # short slug, e.g. "t-variables"
    name: str
    summary: str
    group_ids: list[str]
    prerequisites: list[str]  # ids of themes that must be taught first


class ThemesOut(BaseModel):
    themes: list[ThemeOut]


# ---------- Stage 6: plan ----------

LessonRole = Literal["introduce", "deepen", "apply", "integrate"]


class LessonPlan(BaseModel):
    title: str
    role: LessonRole
    objectives: list[str]
    key_points: list[str]
    group_ids: list[str]  # claim groups the lesson draws on
    exercise: str


class ArcPlan(BaseModel):
    title: str
    goal: str
    theme_ids: list[str]
    lessons: list[LessonPlan]


class CoursePlanOut(BaseModel):
    title: str
    summary: str
    arcs: list[ArcPlan]


# ---------- Stage 7: lessons ----------

class StyleGuide(BaseModel):
    """How lessons should be written and voiced. Starts as a default; feedback updates it."""
    tone: str = "warm, clear and encouraging; speaks directly to the learner"
    pace: str = "steady; one idea per slide, pausing to recap after each concept"
    depth: str = "explain the why before the how; define every new term"
    examples: str = "one concrete, realistic example per concept"
    target_minutes: int = 8
    voice_backend: str = "edge"
    voice_name: str = ""
    voice_speed: float = 1.0
    extra_rules: list[str] = []


SlideLayout = Literal["title", "bullets", "code", "summary"]


class SlideOut(BaseModel):
    layout: SlideLayout
    heading: str
    bullets: list[str]  # short on-screen text; empty for a title slide
    code: str  # code shown on a code slide; empty otherwise
    narration: str  # what the voice says while this slide is shown


class QuizQuestionOut(BaseModel):
    question: str
    options: list[str]
    answer_index: int
    explanation: str


class LessonOut(BaseModel):
    title: str
    slides: list[SlideOut]
    quiz: list[QuizQuestionOut]


class StyleGuideOut(BaseModel):
    """StyleGuide with every field required, so the model must restate each one."""
    tone: str
    pace: str
    depth: str
    examples: str
    target_minutes: int
    voice_backend: Literal["piper", "edge"]
    voice_name: str
    voice_speed: float
    extra_rules: list[str]


class FeedbackStyleOut(BaseModel):
    style: StyleGuideOut
    changes: list[str]  # what changed and why, in plain words
    replan: bool  # true if the feedback means the course plan itself should change
    replan_reason: str
