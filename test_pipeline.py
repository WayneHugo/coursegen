"""End-to-end test: the real SDK talks to a fake HTTP server that plays Claude."""

import json
from pathlib import Path

import anthropic
import httpx2 as httpx
import pytest

from coursegen.llm import LLM
from coursegen.memory import Memory
from coursegen.models import CourseSpec, ThemeOut
from coursegen.pipeline import Pipeline, check_plan, order_themes

ROLES = ["introduce", "deepen", "apply", "integrate"]


def _msg(content, stop="end_turn"):
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": content, "stop_reason": stop, "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _sse(message: dict) -> httpx.Response:
    """Encode a full message as the streaming events the API would send."""
    content = message.pop("content")
    events = [("message_start", {"type": "message_start", "message": {**message, "content": [], "stop_reason": None}})]
    for i, block in enumerate(content):
        if block["type"] == "text":
            events += [
                ("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}}),
            ]
        else:
            events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": block}))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events += [
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
                           "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)
    return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})


def _json(obj):
    return _msg([{"type": "text", "text": json.dumps(obj)}])


def fake_claude(requests: list):
    """Answer each request according to which stage's prompt it carries."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"body": body, "headers": dict(request.headers)})
        prompt = body["messages"][0]["content"]
        if body.get("tools"):  # research call with web search
            if len(body["messages"]) == 1 and "core concepts" in prompt:
                return _sse(_msg([
                    {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "q"}},
                    {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
                        {"type": "web_search_result", "url": "https://docs.example/a", "title": "Docs A",
                         "encrypted_content": "x", "page_age": None}]},
                ], stop="pause_turn"))
            return _sse(_msg([
                {"type": "text", "text": "Variables hold values [https://docs.example/a]."}]))
        if "Plan the web research" in prompt:
            return _sse(_json({"angles": [
                {"angle": "core concepts", "query": "python variables", "why": "basics"},
                {"angle": "common mistakes", "query": "python mistakes", "why": "pitfalls"}]}))
        if "atomic notes" in prompt:
            return _sse(_json({"notes": [
                {"claim": "Variables hold values", "evidence": "docs say so", "source_url": "https://docs.example/a",
                 "concepts": ["variables"], "kind": "definition"}]}))
        if "Compare these notes" in prompt:
            return _sse(_json({"groups": [
                {"merged_claim": "Variables hold values", "note_ids": ["n0", "n1", "bogus"],
                 "status": "consensus", "conflict": ""}]}))
        if "Cluster these claim groups" in prompt:
            return _sse(_json({"themes": [
                {"id": "t-loops", "name": "Loops", "summary": "s", "group_ids": ["g0"], "prerequisites": ["t-vars"]},
                {"id": "t-vars", "name": "Variables", "summary": "s", "group_ids": ["g0"], "prerequisites": []}]}))
        if "Plan the course" in prompt:
            lesson = lambda r: {"title": f"L {r}", "role": r, "objectives": ["o"], "key_points": ["k"],
                                "group_ids": ["g0"], "exercise": "e"}
            return _sse(_json({"title": "Python Basics", "summary": "sum", "arcs": [
                {"title": "Foundations", "goal": "g", "theme_ids": ["t-vars"], "lessons": [lesson(r) for r in ROLES]}]}))
        if "Write the lesson as" in prompt:
            narration = " ".join(["word"] * 150)  # 8 slides x 150 words = target for 8 minutes
            slides = [{"layout": "title", "heading": "Welcome", "bullets": [], "code": "", "narration": narration}]
            slides += [{"layout": "code", "heading": f"Step {k}", "bullets": ["point"], "code": "x = 1",
                        "narration": narration} for k in range(6)]
            slides += [{"layout": "summary", "heading": "Recap", "bullets": ["done"], "code": "", "narration": narration}]
            answer = 0 if "fix them" in prompt else 9  # first draft has a bad answer_index
            return _sse(_json({"title": "Meet Variables", "slides": slides, "quiz": [
                {"question": "What is a variable?", "options": ["A name for a value", "A loop", "A file", "A bug"],
                 "answer_index": answer, "explanation": "It names a value."}]}))
        if "Current style guide" in prompt:
            style = json.loads(prompt.split("Current style guide:\n")[1].split("\n\nLearner feedback")[0])
            style.update(target_minutes=6, voice_speed=0.9)
            return _sse(_json({"style": style, "changes": ["Shorter lessons", "Slower voice"],
                               "replan": False, "replan_reason": ""}))
        raise AssertionError(f"unexpected prompt: {prompt[:80]}")
    return handler


@pytest.fixture
def run(tmp_path):
    requests: list = []
    client = anthropic.Anthropic(api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(fake_claude(requests))))
    spec = CourseSpec(topic="Python basics", num_arcs=1)
    pipe = Pipeline(spec, tmp_path / "courses", LLM(client), Memory(tmp_path / "mem.jsonl"), log=lambda _: None)
    return pipe, requests, tmp_path


def test_full_pipeline(run):
    pipe, requests, tmp = run
    plan = pipe.run()
    assert plan.title == "Python Basics"
    md = (pipe.dir / "plan.md").read_text()
    assert "Arc 1: Foundations" in md and "<https://docs.example/a>" in md

    # Themes came back loops-first; ordering puts the prerequisite first.
    themes = json.loads((pipe.dir / "themes.json").read_text())
    assert [t["id"] for t in themes] == ["t-vars", "t-loops"]
    # Unknown note ids from the model are dropped.
    assert json.loads((pipe.dir / "compare.json").read_text())[0]["note_ids"] == ["n0", "n1"]
    # pause_turn was resumed and the search result became a source.
    research = json.loads((pipe.dir / "research.json").read_text())
    core = next(d for d in research if d["angle"] == "core concepts")
    assert core["sources"][0]["url"] == "https://docs.example/a"

    bodies = [r["body"] for r in requests]
    assert all(b["model"] == "claude-opus-5-5" and b["fallbacks"] == "default" for b in bodies)
    assert all("server-side-fallback-2026-07-01" in r["headers"]["anthropic-beta"] for r in requests)
    structured = [b for b in bodies if "tools" not in b]
    assert all(b["output_config"]["format"]["type"] == "json_schema" for b in structured)
    assert all("thinking" not in b for b in bodies)
    assert json.loads((pipe.dir / "state.json").read_text())["status"] == "planned"


def test_resume_uses_saved_stages(run):
    pipe, requests, _ = run
    pipe.run()
    n = len(requests)
    pipe.run()
    assert len(requests) == n  # nothing re-requested
    pipe.reset_from("plan")
    pipe.run()
    assert len(requests) == n + 1  # only the plan stage reran


def test_memory_recall_on_next_course(run, tmp_path):
    pipe, _, tmp = run
    pipe.run()
    recalled = Memory(tmp / "mem.jsonl").recall("python variables values")
    assert recalled and recalled[0].from_memory


def test_order_themes_breaks_cycles():
    t = lambda i, p: ThemeOut(id=i, name=i, summary="", group_ids=[], prerequisites=p)
    out = order_themes([t("a", ["b"]), t("b", ["a"]), t("c", ["zzz"])])
    assert sorted(x.id for x in out) == ["a", "b", "c"]
    pos = {x.id: i for i, x in enumerate(out)}
    for x in out:
        for p in x.prerequisites:
            assert pos[p] < pos[x.id]


def test_check_plan_flags_bad_arcs():
    from coursegen.models import ArcPlan, CoursePlanOut, LessonPlan
    les = LessonPlan(title="", role="introduce", objectives=[], key_points=[], group_ids=[], exercise="")
    plan = CoursePlanOut(title="", summary="", arcs=[ArcPlan(title="", goal="", theme_ids=[], lessons=[les])])
    assert len(check_plan(plan, 2)) == 2


class FakeVoice:
    name = "fake"

    def __init__(self):
        self.texts = []

    def synthesize(self, text, out_stem):
        import wave
        self.texts.append(text)
        path = out_stem.with_suffix(".wav")
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000)
            f.writeframes(b"\0\0" * 800)  # 0.1 s of silence
        return path


def _args(tmp, **kw):
    import argparse
    base = dict(topic="Python basics", out=tmp / "courses", lesson="1.1", voice=None, voice_name=None,
                rewrite=False, file=None)
    return argparse.Namespace(**{**base, **kw})


def test_sample_then_feedback(run):
    from coursegen.cli import cmd_feedback, cmd_sample
    pipe, requests, tmp = run
    pipe.run()
    voice = FakeVoice()
    player = cmd_sample(_args(tmp), pipe.llm, voice=voice)

    lesson_dir = pipe.dir / "lessons" / "1-1"
    data = json.loads((lesson_dir / "lesson.json").read_text())
    assert len(voice.texts) == len(data["slides"]) == 8
    assert all((lesson_dir / s["audio"]).exists() for s in data["slides"])
    assert data["slides"][0]["seconds"] == pytest.approx(0.1)
    assert data["quiz"][0]["answer_index"] == 0  # the bad first draft was sent back and fixed
    assert data["sources"] == ["https://docs.example/a"]
    page = player.read_text()
    assert "Meet Variables" in page and "</script" not in page.split('id="data">')[1].split("</script>")[0]
    assert json.loads((pipe.dir / "state.json").read_text())["status"] == "awaiting_feedback"

    # Re-running reuses the saved script: no new lesson-writing request.
    n = len(requests)
    cmd_sample(_args(tmp), pipe.llm, voice=FakeVoice())
    assert len(requests) == n

    fb = tmp / "feedback.json"
    fb.write_text(json.dumps({"lesson": "1.1", "pace": "too fast", "length": "too long", "comments": ""}))
    cmd_feedback(_args(tmp, file=fb), pipe.llm)
    style = json.loads((pipe.dir / "style_guide.json").read_text())
    assert style["target_minutes"] == 6 and style["voice_speed"] == 0.9
    assert json.loads((pipe.dir / "state.json").read_text())["status"] == "ready_to_produce"


def test_cli_defaults_to_plan():
    from coursegen.cli import build_parser, main
    assert build_parser().parse_args(["plan", "X"]).arcs == 3
    with pytest.raises(SystemExit):
        main(["status", "no such course", "--out", "/nonexistent"])


def test_voice_speed_mapping():
    from coursegen.voice import get_voice
    assert get_voice("edge", speed=0.9).rate == "-10%"
    assert get_voice("piper", speed=0.8).length_scale == pytest.approx(1.25)


def test_edge_is_default_and_failures_are_clear(tmp_path, monkeypatch):
    import edge_tts
    from coursegen.models import StyleGuide
    from coursegen.voice import EdgeVoice, VoiceError
    assert StyleGuide().voice_backend == "edge"

    class Boom:
        def __init__(self, *a, **k): pass
        async def save(self, path): raise ConnectionError("403")
    monkeypatch.setattr(edge_tts, "Communicate", Boom)
    with pytest.raises(VoiceError, match="speech.platform.bing.com"):
        EdgeVoice().synthesize("hi", tmp_path / "x")
