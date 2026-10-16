"""A self-contained HTML slide player: slides advance as their narration finishes."""

from __future__ import annotations

import html
import json


def render_player(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return _TEMPLATE.replace("__TITLE__", html.escape(data["title"])).replace("__DATA__", payload)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  --bg: #f6f5f1; --surface: #ffffff; --ink: #1d1d1b; --muted: #6b6a65; --line: #e3e1da;
  --accent: #2f5bd3; --accent-ink: #ffffff; --good: #1f7a4a; --bad: #b3261e; --code-bg: #f1f0ec;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #151514; --surface: #1f1f1d; --ink: #ecebe6; --muted: #a09f99; --line: #34332f;
          --accent: #7e9ef0; --accent-ink: #0f1420; --good: #5cc28b; --bad: #f08a80; --code-bg: #2a2a27; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
       font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 24px 16px 64px; }
header p { margin: 0; color: var(--muted); font-size: 14px; }
header h1 { margin: 4px 0 20px; font-size: 22px; }
.stage { position: relative; aspect-ratio: 16 / 9; background: var(--surface); border: 1px solid var(--line);
         border-radius: 12px; padding: clamp(18px, 5%, 48px); display: flex; flex-direction: column;
         justify-content: center; overflow: hidden; }
@media (max-width: 600px) { .stage { aspect-ratio: auto; min-height: 56vw; } }
.stage h2 { margin: 0 0 0.6em; font-size: clamp(20px, 3.6vw, 36px); line-height: 1.2; }
.stage.title { text-align: center; }
.stage.title h2 { font-size: clamp(24px, 5vw, 48px); }
.stage ul { margin: 0; padding-left: 1.1em; font-size: clamp(15px, 2.2vw, 22px); }
.stage li { margin: 0.35em 0; }
.stage pre { margin: 0.4em 0 0; background: var(--code-bg); border-radius: 8px; padding: 14px;
             overflow: auto; font-size: clamp(12px, 1.7vw, 17px); line-height: 1.45; }
.stage .num { position: absolute; right: 16px; bottom: 10px; color: var(--muted); font-size: 13px; }
.bar { display: flex; gap: 4px; margin: 12px 0; }
.bar button { flex: 1; height: 6px; border: 0; padding: 0; border-radius: 3px; background: var(--line); cursor: pointer; }
.bar button.done { background: var(--accent); opacity: 0.45; }
.bar button.on { background: var(--accent); }
.controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
button.btn { font: inherit; border: 1px solid var(--line); background: var(--surface); color: var(--ink);
             border-radius: 8px; padding: 8px 14px; cursor: pointer; }
button.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); min-width: 92px; }
.controls label { color: var(--muted); font-size: 14px; display: flex; gap: 6px; align-items: center; }
.controls .spacer { flex: 1; }
select { font: inherit; background: var(--surface); color: var(--ink); border: 1px solid var(--line); border-radius: 6px; padding: 4px; }
.caption { margin-top: 12px; padding: 12px 14px; background: var(--surface); border: 1px solid var(--line);
           border-radius: 8px; color: var(--muted); }
section.card { margin-top: 32px; background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 20px; }
section.card h3 { margin: 0 0 12px; }
.q { margin: 0 0 18px; }
.q p { margin: 0 0 6px; font-weight: 600; }
.q label { display: block; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
.q label.right { color: var(--good); font-weight: 600; }
.q label.wrong { color: var(--bad); text-decoration: line-through; }
.q .why { margin: 4px 8px; color: var(--muted); font-size: 14px; }
.fb { display: grid; gap: 14px; }
.fb fieldset { border: 0; padding: 0; margin: 0; }
.fb legend { font-weight: 600; margin-bottom: 4px; }
.fb .opts { display: flex; gap: 6px; flex-wrap: wrap; }
.fb .opts label { border: 1px solid var(--line); border-radius: 999px; padding: 4px 12px; cursor: pointer; font-size: 14px; }
.fb .opts input { display: none; }
.fb .opts label:has(input:checked) { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
textarea { width: 100%; min-height: 80px; font: inherit; background: var(--bg); color: var(--ink);
           border: 1px solid var(--line); border-radius: 8px; padding: 8px; }
code.cmd { display: block; margin-top: 10px; padding: 10px; background: var(--code-bg); border-radius: 6px; font-size: 13px; overflow-wrap: anywhere; }
.sources a { color: var(--accent); overflow-wrap: anywhere; }
.muted { color: var(--muted); font-size: 14px; }
</style>
</head>
<body>
<main>
  <header><p id="kicker"></p><h1 id="title"></h1></header>
  <div class="stage" id="stage"></div>
  <div class="bar" id="bar"></div>
  <div class="controls">
    <button class="btn" id="prev" aria-label="Previous slide">◀</button>
    <button class="btn primary" id="play">▶ Play</button>
    <button class="btn" id="next" aria-label="Next slide">▶</button>
    <span class="spacer"></span>
    <label>Speed <select id="speed"><option>0.9</option><option selected>1</option><option>1.25</option><option>1.5</option></select></label>
    <label><input type="checkbox" id="cc" checked> Captions</label>
  </div>
  <div class="caption" id="caption"></div>
  <audio id="audio" preload="auto"></audio>

  <section class="card" id="quiz"><h3>Check your understanding</h3><div id="qs"></div>
    <button class="btn primary" id="check">Check answers</button> <span class="muted" id="score"></span></section>

  <section class="card" id="feedback"><h3>How was this lesson?</h3>
    <p class="muted">This is a sample. Your answers shape how every other lesson is written and voiced.</p>
    <form class="fb" id="fb"></form>
    <p><button class="btn primary" id="save">Save feedback</button></p>
    <p class="muted">Then run:</p><code class="cmd" id="cmd"></code>
  </section>

  <section class="card sources" id="sources"><h3>Sources</h3><ol id="srcs"></ol></section>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById("data").textContent);
const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, kids = []) => { const n = Object.assign(document.createElement(tag), props); n.append(...kids); return n; };
const audio = $("audio");
let i = 0, playing = false;

$("kicker").textContent = `${D.course} · Lesson ${D.number}`;
$("title").textContent = D.title;
D.slides.forEach((_, k) => $("bar").append(el("button", { title: `Slide ${k + 1}`, onclick: () => go(k, playing) })));

function show() {
  const s = D.slides[i], st = $("stage");
  st.className = "stage " + s.layout;
  st.replaceChildren(el("h2", { textContent: s.heading }));
  if (s.bullets.length) st.append(el("ul", {}, s.bullets.map((b) => el("li", { textContent: b }))));
  if (s.code) st.append(el("pre", {}, [el("code", { textContent: s.code })]));
  st.append(el("span", { className: "num", textContent: `${i + 1} / ${D.slides.length}` }));
  [...$("bar").children].forEach((b, k) => b.className = k === i ? "on" : k < i ? "done" : "");
  $("caption").textContent = s.narration;
  audio.src = s.audio;
  audio.playbackRate = +$("speed").value;
}
function go(k, autoplay) {
  i = Math.max(0, Math.min(D.slides.length - 1, k));
  show();
  if (autoplay) audio.play().catch(() => setPlaying(false));
}
function setPlaying(p) { playing = p; $("play").textContent = p ? "❚❚ Pause" : "▶ Play"; }
$("play").onclick = () => { if (playing) { audio.pause(); setPlaying(false); } else { setPlaying(true); audio.play(); } };
$("prev").onclick = () => go(i - 1, playing);
$("next").onclick = () => go(i + 1, playing);
$("speed").onchange = () => audio.playbackRate = +$("speed").value;
$("cc").onchange = () => $("caption").hidden = !$("cc").checked;
audio.onended = () => { if (i < D.slides.length - 1) go(i + 1, true); else { setPlaying(false); $("quiz").scrollIntoView({ behavior: "smooth" }); } };
document.addEventListener("keydown", (e) => {
  if (e.target.closest("textarea, input, select")) return;
  if (e.key === " ") { e.preventDefault(); $("play").click(); }
  if (e.key === "ArrowRight") $("next").click();
  if (e.key === "ArrowLeft") $("prev").click();
});
show();

// Quiz
D.quiz.forEach((q, k) => {
  const opts = q.options.map((o, j) => el("label", {}, [el("input", { type: "radio", name: "q" + k, value: j }), " " + o]));
  $("qs").append(el("div", { className: "q" }, [el("p", { textContent: `${k + 1}. ${q.question}` }), ...opts,
    el("div", { className: "why", hidden: true, textContent: q.explanation })]));
});
$("check").onclick = () => {
  let right = 0;
  [...$("qs").children].forEach((box, k) => {
    const q = D.quiz[k], picked = box.querySelector("input:checked");
    box.querySelectorAll("label").forEach((l, j) => l.className = j === q.answer_index ? "right" : (picked && +picked.value === j ? "wrong" : ""));
    box.querySelector(".why").hidden = false;
    if (picked && +picked.value === q.answer_index) right++;
  });
  $("score").textContent = `${right} of ${D.quiz.length} correct`;
};

// Feedback
const QUESTIONS = [
  ["pace", "Pace", ["too slow", "just right", "too fast"]],
  ["depth", "Depth", ["too basic", "just right", "too advanced"]],
  ["examples", "Examples", ["need more", "just right", "too many"]],
  ["length", "Length", ["too short", "just right", "too long"]],
  ["voice", "Voice", ["good", "okay", "change it"]],
  ["slides", "Slides", ["too much text", "just right", "too sparse"]],
];
QUESTIONS.forEach(([key, label, options]) => $("fb").append(el("fieldset", {}, [el("legend", { textContent: label }),
  el("div", { className: "opts" }, options.map((o) => el("label", {}, [el("input", { type: "radio", name: key, value: o }), o])))])));
$("fb").append(el("fieldset", {}, [el("legend", { textContent: "Anything else?" }), el("textarea", { name: "comments", placeholder: "What worked, what didn't, what you'd change" })]));
$("cmd").textContent = `python -m coursegen feedback "${D.topic}" --file feedback.json`;
$("save").onclick = () => {
  const f = new FormData($("fb")), out = { lesson: D.number };
  QUESTIONS.forEach(([k]) => out[k] = f.get(k) || "");
  out.comments = f.get("comments") || "";
  const a = el("a", { href: URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: "application/json" })), download: "feedback.json" });
  a.click();
};

// Sources
if (D.sources && D.sources.length) D.sources.forEach((u) => $("srcs").append(el("li", {}, [el("a", { href: u, textContent: u, target: "_blank", rel: "noopener" })])));
else $("sources").hidden = true;
</script>
</body>
</html>
"""
