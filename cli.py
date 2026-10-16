"""Command line.

  python -m coursegen plan "Topic" --level beginner --goal "..." --arcs 3
  python -m coursegen sample "Topic"                 # write + record lesson 1.1, then wait
  python -m coursegen feedback "Topic" [--file feedback.json]
  python -m coursegen status "Topic"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from coursegen.feedback import ask_interactively, update_style
from coursegen.lesson import check_lesson, lesson_key, lesson_sources, record_lesson, write_lesson
from coursegen.llm import LLM, LLMError
from coursegen.memory import Memory
from coursegen.models import CourseSpec, LessonOut, StyleGuide
from coursegen.pipeline import STAGES, Course, Pipeline, slugify, write_state
from coursegen.voice import VoiceError, get_voice

COMMANDS = ("plan", "sample", "feedback", "status")


def _course_dir(args) -> Path:
    return args.out / slugify(args.topic)


def cmd_plan(args, llm: LLM) -> None:
    spec = CourseSpec(topic=args.topic, level=args.level, goal=args.goal, num_arcs=args.arcs)
    pipeline = Pipeline(spec, args.out, llm, Memory(args.memory))
    if args.redo_from:
        pipeline.reset_from(args.redo_from)
    plan = pipeline.run()
    print(f"\nDone: {plan.title}\nPlan: {pipeline.dir / 'plan.md'}")
    print(f'Next: python -m coursegen sample "{args.topic}"')


def cmd_sample(args, llm: LLM, voice=None) -> Path:
    course = Course(_course_dir(args))
    arc_no, lesson_no = (int(x) for x in args.lesson.split("."))
    if not (1 <= arc_no <= len(course.plan.arcs) and 1 <= lesson_no <= len(course.plan.arcs[arc_no - 1].lessons)):
        sys.exit(f"error: no lesson {args.lesson} in this plan")
    style_path = course.dir / "style_guide.json"
    style = StyleGuide.model_validate_json(style_path.read_text()) if style_path.exists() else StyleGuide()
    if args.voice:
        style.voice_backend, style.voice_name = args.voice, args.voice_name or ""

    key = lesson_key(arc_no, lesson_no)
    out_dir = course.dir / "lessons" / key
    out_dir.mkdir(parents=True, exist_ok=True)
    script_path = out_dir / "script.json"

    if script_path.exists() and not args.rewrite:
        print(f"[write] using saved script for {args.lesson}")
        lesson = LessonOut.model_validate_json(script_path.read_text())
    else:
        print(f"[write] writing lesson {args.lesson}")
        lesson = write_lesson(llm, course.spec, course.plan, arc_no, lesson_no, course.groups, course.notes, style)
        if problems := check_lesson(lesson, style):
            print(f"[write] fixing: {'; '.join(problems)}")
            lesson = write_lesson(llm, course.spec, course.plan, arc_no, lesson_no, course.groups,
                                  course.notes, style, fix=problems)
            if problems := check_lesson(lesson, style):
                print(f"[write] warning, still: {'; '.join(problems)}")
        script_path.write_text(lesson.model_dump_json(indent=2))

    plan_lesson = course.plan.arcs[arc_no - 1].lessons[lesson_no - 1]
    meta = {
        "course": course.plan.title,
        "topic": course.spec.topic,
        "number": args.lesson,
        "sources": lesson_sources(plan_lesson.group_ids, course.groups, course.notes),
    }
    voice = voice or get_voice(style.voice_backend, style.voice_name or None, style.voice_speed)
    player = record_lesson(lesson, voice, out_dir, meta)

    (course.dir / "sample.json").write_text(json.dumps({"lesson": key, "number": args.lesson,
                                                         "player": str(player.relative_to(course.dir))}))
    write_state(course.dir)
    print(f"\nSample lesson ready: {player}")
    print("Open it in a browser, watch it, then fill in the feedback form at the bottom and run:")
    print(f'  python -m coursegen feedback "{args.topic}" --file feedback.json')
    print("Status: awaiting feedback. Nothing else will be written until then.")
    return player


def cmd_feedback(args, llm: LLM) -> None:
    course_dir = _course_dir(args)
    sample_path = course_dir / "sample.json"
    if not sample_path.exists():
        sys.exit(f'error: no sample lesson yet; run: python -m coursegen sample "{args.topic}"')
    sample = json.loads(sample_path.read_text())
    feedback = json.loads(args.file.read_text()) if args.file else ask_interactively(sample["number"])

    style_path = course_dir / "style_guide.json"
    style = StyleGuide.model_validate_json(style_path.read_text()) if style_path.exists() else StyleGuide()
    transcript = (course_dir / "lessons" / sample["lesson"] / "transcript.md").read_text()
    result = update_style(llm, style, feedback, transcript)

    history = course_dir / "feedback.jsonl"
    with history.open("a") as f:
        f.write(json.dumps(feedback) + "\n")
    new_style = StyleGuide.model_validate(result.style.model_dump())
    new_style.voice_speed = min(1.25, max(0.75, new_style.voice_speed))
    new_style.target_minutes = min(30, max(3, new_style.target_minutes))
    style_path.write_text(new_style.model_dump_json(indent=2))
    write_state(course_dir)

    print("\nStyle guide updated:" if result.changes else "\nNo changes needed.")
    for c in result.changes:
        print(f"  - {c}")
    if result.replan:
        print(f"\nThe feedback suggests changing the course plan itself: {result.replan_reason}")
        print(f'  python -m coursegen plan "{args.topic}" --level <new level> --redo-from plan')
    print(f'\nTo hear the sample again in the new style: python -m coursegen sample "{args.topic}" --rewrite')
    print("Status: ready to produce the remaining lessons.")


def cmd_status(args) -> None:
    course_dir = _course_dir(args)
    if not (course_dir / "spec.json").exists():
        sys.exit(f"no course for '{args.topic}' in {args.out}")
    print(json.dumps(write_state(course_dir), indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="coursegen", description="Research a topic and build a course.")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp):
        sp.add_argument("topic")
        sp.add_argument("--out", type=Path, default=Path("courses"), help="where courses are saved")

    sp = sub.add_parser("plan", help="research the topic and plan the course")
    common(sp)
    sp.add_argument("--level", default="beginner", help="beginner, intermediate, advanced")
    sp.add_argument("--goal", default="", help="what the learner wants to be able to do")
    sp.add_argument("--arcs", type=int, default=3, help="number of 4-lesson arcs")
    sp.add_argument("--memory", type=Path, default=Path("memory/notes.jsonl"))
    sp.add_argument("--redo-from", choices=STAGES, help="discard saved results from this stage on")

    sp = sub.add_parser("sample", help="write and record one sample lesson, then wait for feedback")
    common(sp)
    sp.add_argument("--lesson", default="1.1", help="which lesson, as arc.lesson (default 1.1)")
    sp.add_argument("--voice", choices=["edge", "piper"], help="free voice: edge (default, online) or piper (offline)")
    sp.add_argument("--voice-name", help="e.g. en-US-GuyNeural, en-GB-SoniaNeural (edge) or en_US-amy-medium (piper)")
    sp.add_argument("--rewrite", action="store_true", help="rewrite the script instead of reusing it")

    sp = sub.add_parser("feedback", help="give feedback on the sample lesson")
    common(sp)
    sp.add_argument("--file", type=Path, help="feedback.json saved from the lesson page")

    sp = sub.add_parser("status", help="show where a course is up to")
    common(sp)
    return p


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "plan")  # `coursegen "Topic"` still means plan
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            cmd_status(args)
            return
        llm = LLM()
        {"plan": cmd_plan, "sample": cmd_sample, "feedback": cmd_feedback}[args.command](args, llm)
    except (LLMError, VoiceError, FileNotFoundError) as e:
        sys.exit(f"error: {e}\nSaved work is kept; rerun the same command to resume.")
