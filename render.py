"""Render the course plan as a readable Markdown file."""

from __future__ import annotations

from coursegen.models import ClaimGroup, CoursePlanOut, CourseSpec, Note, ThemeOut

_BADGE = {"consensus": "✓", "contested": "⚠", "single_source": "·"}


def render_plan(spec: CourseSpec, plan: CoursePlanOut, themes: list[ThemeOut],
                groups: list[ClaimGroup], notes: list[Note]) -> str:
    gmap = {g.id: g for g in groups}
    nmap = {n.id: n for n in notes}
    tmap = {t.id: t for t in themes}
    lines = [
        f"# {plan.title}",
        "",
        f"**Topic:** {spec.topic} · **Level:** {spec.level}" + (f" · **Goal:** {spec.goal}" if spec.goal else ""),
        "",
        plan.summary,
        "",
        f"_{len(notes)} notes → {len(groups)} claim groups → {len(themes)} themes → {len(plan.arcs)} arcs._",
        "",
    ]
    for a, arc in enumerate(plan.arcs, 1):
        names = ", ".join(tmap[t].name for t in arc.theme_ids if t in tmap)
        lines += [f"## Arc {a}: {arc.title}", "", f"_{arc.goal}_", "", f"Themes: {names}", ""]
        for n, lesson in enumerate(arc.lessons, 1):
            lines += [f"### {a}.{n} {lesson.title}  `{lesson.role}`", "", "**Objectives**"]
            lines += [f"- {o}" for o in lesson.objectives]
            lines += ["", "**Key points**"] + [f"- {k}" for k in lesson.key_points]
            lines += ["", f"**Exercise:** {lesson.exercise}", "", "**Draws on**"]
            for gid in lesson.group_ids:
                g = gmap.get(gid)
                if not g:
                    continue
                urls = sorted({nmap[x].source_url for x in g.note_ids if x in nmap})
                lines.append(f"- {_BADGE[g.status]} {g.merged_claim}" + (f" — _{g.conflict}_" if g.conflict else ""))
                lines += [f"  - <{u}>" for u in urls]
            lines.append("")
    lines += ["---", "✓ consensus · ⚠ contested · · single source", ""]
    return "\n".join(lines)
