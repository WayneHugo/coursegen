"""The research → plan pipeline. Each stage saves its output, so a run can resume."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, TypeAdapter

from coursegen.llm import LLM, LLMError
from coursegen.memory import Memory
from coursegen.models import (
    ClaimGroup,
    ComparisonOut,
    CoursePlanOut,
    CourseSpec,
    Dossier,
    Note,
    NoteSetOut,
    ResearchPlanOut,
    SearchAngle,
    ThemeOut,
    ThemesOut,
)
from coursegen.render import render_plan

STAGES = ["queries", "research", "notes", "compare", "themes", "plan"]
LESSONS_PER_ARC = 4
LESSON_ROLES = ["introduce", "deepen", "apply", "integrate"]

SYSTEM = (
    "You are the research and curriculum team behind an online course platform. "
    "You build accurate, well-sourced courses that teach foundations before advanced material. "
    "Never invent sources or URLs; only use what you actually found."
)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "course"


def _dump(obj) -> str:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json(indent=2)
    return json.dumps([o.model_dump() if isinstance(o, BaseModel) else o for o in obj], indent=2)


class Pipeline:
    def __init__(self, spec: CourseSpec, workdir: Path, llm: LLM, memory: Memory,
                 log: Callable[[str], None] = print, workers: int = 4):
        self.spec = spec
        self.dir = workdir / slugify(spec.topic)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm
        self.memory = memory
        self.log = log
        self.workers = workers

    # ---------- checkpointing ----------

    def _path(self, stage: str) -> Path:
        return self.dir / f"{stage}.json"

    def _cached(self, stage: str, type_):
        p = self._path(stage)
        if p.exists():
            self.log(f"[{stage}] using saved result")
            return TypeAdapter(type_).validate_json(p.read_text())
        return None

    def _save(self, stage: str, value) -> None:
        self._path(stage).write_text(_dump(value))
        write_state(self.dir)

    def reset_from(self, stage: str) -> None:
        for s in STAGES[STAGES.index(stage):]:
            self._path(s).unlink(missing_ok=True)

    # ---------- run ----------

    def run(self) -> CoursePlanOut:
        (self.dir / "spec.json").write_text(self.spec.model_dump_json(indent=2))
        write_state(self.dir)
        angles = self.stage_queries()
        dossiers = self.stage_research(angles)
        notes = self.stage_notes(dossiers)
        groups = self.stage_compare(notes)
        themes = self.stage_themes(groups)
        plan = self.stage_plan(themes, groups)
        (self.dir / "plan.md").write_text(render_plan(self.spec, plan, themes, groups, notes))
        return plan

    def _brief(self) -> str:
        s = self.spec
        return f"Topic: {s.topic}\nLearner level: {s.level}\nLearner goal: {s.goal or 'general understanding'}"

    # Stage 1: decide what to search for.
    def stage_queries(self) -> list[SearchAngle]:
        if (cached := self._cached("queries", list[SearchAngle])) is not None:
            return cached
        self.log("[queries] planning search angles")
        out = self.llm.structured(
            SYSTEM,
            f"{self._brief()}\n\n"
            "Plan the web research for this course. Give 6-10 distinct search angles that together cover: "
            "an overview, core concepts and definitions, how it works, worked examples and tutorials, "
            "common mistakes, best practices, advanced topics, and recent changes. "
            "Each angle gets one precise search query.",
            ResearchPlanOut,
            effort="medium",
        )
        self._save("queries", out.angles)
        return out.angles

    # Stage 2: search and read the web, one dossier per angle, in parallel.
    def stage_research(self, angles: list[SearchAngle]) -> list[Dossier]:
        if (cached := self._cached("research", list[Dossier])) is not None:
            return cached

        def one(a: SearchAngle) -> Dossier | None:
            self.log(f"[research] {a.angle}: {a.query}")
            try:
                return self.llm.research(
                    SYSTEM,
                    f"{self._brief()}\n\nResearch angle: {a.angle}\nStarting query: {a.query}\n\n"
                    "Search the web, open the most useful pages, and write a detailed research dossier "
                    "for this angle. Prefer official documentation, textbooks, and recognised experts. "
                    "For every fact, name the source URL it came from in brackets, like [https://...]. "
                    "Note where sources disagree.",
                    a.angle, a.query,
                )
            except LLMError as e:
                self.log(f"[research] skipped '{a.angle}': {e}")
                return None

        with ThreadPoolExecutor(self.workers) as pool:
            dossiers = [d for d in pool.map(one, angles) if d and d.text]
        if not dossiers:
            raise LLMError("research produced nothing; check the API key and network access")
        self._save("research", dossiers)
        return dossiers

    # Stage 3: read each dossier into atomic notes, then add notes from memory.
    def stage_notes(self, dossiers: list[Dossier]) -> list[Note]:
        if (cached := self._cached("notes", list[Note])) is not None:
            return cached

        def one(d: Dossier) -> list[Note]:
            self.log(f"[notes] reading '{d.angle}' ({len(d.sources)} sources)")
            known = "\n".join(f"- {s.url} {s.title}" for s in d.sources)
            out = self.llm.structured(
                SYSTEM,
                f"{self._brief()}\n\nResearch angle: {d.angle}\n\nSources found:\n{known}\n\n"
                f"Dossier:\n{d.text}\n\n"
                "Turn this dossier into atomic notes: one claim per note, with a short piece of evidence, "
                "the source URL it came from (use only URLs that appear above), the concepts it involves, "
                "and what kind of note it is. Keep every useful claim, example, and pitfall.",
                NoteSetOut,
                effort="low",
            )
            return [Note(id="", angle=d.angle, **n.model_dump()) for n in out.notes]

        with ThreadPoolExecutor(self.workers) as pool:
            notes = [n for batch in pool.map(one, dossiers) for n in batch]
        recalled = self.memory.recall(f"{self.spec.topic} {' '.join(d.query for d in dossiers)}")
        if recalled:
            self.log(f"[notes] recalled {len(recalled)} notes from memory")
        notes += recalled
        for i, n in enumerate(notes):
            n.id = f"n{i}"
        self.memory.save(self.spec.topic, notes)
        self._save("notes", notes)
        return notes

    # Stage 4: compare notes across sources.
    def stage_compare(self, notes: list[Note]) -> list[ClaimGroup]:
        if (cached := self._cached("compare", list[ClaimGroup])) is not None:
            return cached
        self.log(f"[compare] cross-checking {len(notes)} notes")
        listing = "\n".join(
            f"{n.id} [{n.kind}] {n.claim} — {n.evidence} (source: {n.source_url}"
            f"{', from memory' if n.from_memory else ''})"
            for n in notes
        )
        out = self.llm.structured(
            SYSTEM,
            f"{self._brief()}\n\nNotes:\n{listing}\n\n"
            "Compare these notes. Group notes that make the same or closely related claim, and write one "
            "merged claim per group. Mark each group: 'consensus' if two or more independent sources agree, "
            "'contested' if sources conflict (describe the conflict), or 'single_source'. "
            "Every note id must appear in exactly one group. Drop nothing.",
            ComparisonOut,
            effort="high",
        )
        valid = {n.id for n in notes}
        groups = [
            ClaimGroup(id=f"g{i}", **{**g.model_dump(), "note_ids": [x for x in g.note_ids if x in valid]})
            for i, g in enumerate(out.groups)
        ]
        self._save("compare", groups)
        return groups

    # Stage 5: merge claim groups into themes with prerequisites, foundations first.
    def stage_themes(self, groups: list[ClaimGroup]) -> list[ThemeOut]:
        if (cached := self._cached("themes", list[ThemeOut])) is not None:
            return cached
        self.log(f"[themes] merging {len(groups)} claim groups into themes")
        listing = "\n".join(f"{g.id} ({g.status}) {g.merged_claim}" for g in groups)
        out = self.llm.structured(
            SYSTEM,
            f"{self._brief()}\n\nClaim groups:\n{listing}\n\n"
            "Cluster these claim groups into teachable themes (aim for about "
            f"{self.spec.num_arcs * 2}-{self.spec.num_arcs * 3}). For each theme give a short slug id, name, "
            "summary, the claim groups it covers, and the ids of themes a learner must understand first. "
            "Foundational themes have no prerequisites. Do not create circular prerequisites.",
            ThemesOut,
            effort="high",
        )
        themes = order_themes(out.themes)
        self._save("themes", themes)
        return themes

    # Stage 6: plan arcs of four lessons over the ordered themes.
    def stage_plan(self, themes: list[ThemeOut], groups: list[ClaimGroup]) -> CoursePlanOut:
        if (cached := self._cached("plan", CoursePlanOut)) is not None:
            return cached
        self.log(f"[plan] planning {self.spec.num_arcs} arcs")
        group_text = {g.id: g.merged_claim for g in groups}
        listing = "\n\n".join(
            f"{i + 1}. {t.id}: {t.name} (needs: {', '.join(t.prerequisites) or 'nothing'})\n   {t.summary}\n"
            + "\n".join(f"   - {gid}: {group_text.get(gid, '')}" for gid in t.group_ids)
            for i, t in enumerate(themes)
        )
        prompt = (
            f"{self._brief()}\n\nThemes, already in teaching order (foundations first):\n{listing}\n\n"
            f"Plan the course as exactly {self.spec.num_arcs} arcs. Each arc has exactly {LESSONS_PER_ARC} "
            "lessons with these roles, in order: introduce (the core idea), deepen (how it works), "
            "apply (a worked example or exercise), integrate (connect it to earlier arcs and check "
            "understanding). Arc 1 must cover the foundational themes. Follow the theme order; never teach "
            "a theme before its prerequisites. Each lesson lists the claim group ids it draws on."
        )
        plan = self.llm.structured(SYSTEM, prompt, CoursePlanOut, effort="high")
        problems = check_plan(plan, self.spec.num_arcs)
        if problems:
            self.log(f"[plan] fixing: {'; '.join(problems)}")
            plan = self.llm.structured(
                SYSTEM,
                f"{prompt}\n\nA previous draft had these problems, fix them:\n- " + "\n- ".join(problems),
                CoursePlanOut,
                effort="high",
            )
            if problems := check_plan(plan, self.spec.num_arcs):
                self.log(f"[plan] warning, still: {'; '.join(problems)}")
        self._save("plan", plan)
        return plan


def course_status(course_dir: Path) -> str:
    """planning → planned → awaiting_feedback → ready_to_produce"""
    if (course_dir / "style_guide.json").exists():
        return "ready_to_produce"
    if (course_dir / "sample.json").exists():
        return "awaiting_feedback"
    if (course_dir / "plan.json").exists():
        return "planned"
    return "planning"


def write_state(course_dir: Path) -> dict:
    spec = json.loads((course_dir / "spec.json").read_text()) if (course_dir / "spec.json").exists() else {}
    state = {
        "spec": spec,
        "completed": [s for s in STAGES if (course_dir / f"{s}.json").exists()],
        "status": course_status(course_dir),
    }
    if (course_dir / "sample.json").exists():
        state["sample"] = json.loads((course_dir / "sample.json").read_text())
    (course_dir / "state.json").write_text(json.dumps(state, indent=2))
    return state


class Course:
    """Everything the planning stages saved for one course, loaded from disk."""

    def __init__(self, course_dir: Path):
        if not (course_dir / "plan.json").exists():
            raise FileNotFoundError(f"no course plan in {course_dir}; run the plan step first")
        self.dir = course_dir
        self.spec = CourseSpec.model_validate_json((course_dir / "spec.json").read_text())
        self.plan = CoursePlanOut.model_validate_json((course_dir / "plan.json").read_text())
        self.groups = TypeAdapter(list[ClaimGroup]).validate_json((course_dir / "compare.json").read_text())
        self.notes = TypeAdapter(list[Note]).validate_json((course_dir / "notes.json").read_text())


def order_themes(themes: list[ThemeOut]) -> list[ThemeOut]:
    """Topological sort so prerequisites come first. Unknown ids are dropped; cycles are broken."""
    by_id = {t.id: t for t in themes}
    for t in themes:
        t.prerequisites = [p for p in t.prerequisites if p in by_id and p != t.id]
    ordered: list[ThemeOut] = []
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(t: ThemeOut) -> None:
        if t.id in done:
            return
        if t.id in visiting:  # cycle: drop the back edge
            return
        visiting.add(t.id)
        for p in list(t.prerequisites):
            if p in visiting:
                t.prerequisites.remove(p)
            else:
                visit(by_id[p])
        visiting.discard(t.id)
        done.add(t.id)
        ordered.append(t)

    for t in themes:  # keep the model's order where the graph allows it
        visit(t)
    return ordered


def check_plan(plan: CoursePlanOut, num_arcs: int) -> list[str]:
    problems = []
    if len(plan.arcs) != num_arcs:
        problems.append(f"expected {num_arcs} arcs, got {len(plan.arcs)}")
    for i, arc in enumerate(plan.arcs, 1):
        roles = [lesson.role for lesson in arc.lessons]
        if roles != LESSON_ROLES:
            problems.append(f"arc {i} lessons must be {LESSON_ROLES}, got {roles}")
    return problems

