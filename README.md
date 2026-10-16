# coursegen

The course app so far. Give it a topic and it:
1. researches the web, makes notes, compares sources, groups them into themes, and plans a course in arcs of four lessons, foundations first
2. writes and records **one sample lesson** as slides with narration, then **waits for your feedback**
3. turns your feedback into a style guide that every other lesson will follow

```
plan:     topic → queries → research → notes → compare → themes → plan.md
sample:   lesson 1.1 → script → per-slide audio → lessons/1-1/index.html   (status: awaiting_feedback)
feedback: your reaction → style_guide.json                                (status: ready_to_produce)
```

| Stage | What it does |
|---|---|
| `queries` | Picks 6–10 search angles (overview, core concepts, examples, mistakes, advanced topics, recent changes) |
| `research` | Uses Claude with web search and web fetch to write a research dossier for each angle, with source URLs. Angles run in parallel |
| `notes` | Breaks each dossier into atomic notes (claim, evidence, source, concepts, kind), then adds related notes saved from earlier courses |
| `compare` | Groups notes that make the same claim and marks each group as consensus, contested, or single-source |
| `themes` | Groups claims into themes with prerequisites, then sorts them so foundations come first |
| `plan` | Plans arcs of four lessons each (introduce → deepen → apply → integrate). It checks the plan and fixes it once if it breaks those rules |

## Run

```bash
pip install -r requirements.txt   # includes edge-tts (the voice)
export ANTHROPIC_API_KEY=...        # or: ant auth login

# 1. Research and plan
python -m coursegen plan "Python for data analysis" --level beginner \
    --goal "clean and chart a CSV with pandas" --arcs 3

# 2. Write and record the sample lesson (1.1 by default)
python -m coursegen sample "Python for data analysis"
#    → open courses/python-for-data-analysis/lessons/1-1/index.html

# 3. React to it: use the form at the bottom of the lesson page, then
python -m coursegen feedback "Python for data analysis" --file ~/Downloads/feedback.json
#    (or leave out --file to answer the questions in the terminal)

# Hear the sample again in the updated style
python -m coursegen sample "Python for data analysis" --rewrite

python -m coursegen status "Python for data analysis"
```

### The sample lesson
- **Slides plus audio, no video.** Each slide has its own narration clip. The page plays them in order and moves to the next slide when a clip ends. It has play/pause, previous/next, speed and captions controls, works with the keyboard (space and arrow keys), and fits a phone screen.
- After the slides come a quiz, a list of sources, and the feedback form (pace, depth, examples, length, voice, slides, comments).
- `lessons/1-1/` also holds `script.json` (the lesson text), `transcript.md`, `lesson.json` and the `audio/` files.
- The lesson is checked before it's recorded: quiz answers must point to a real option, and the narration length must be within reach of the target. If a check fails, the lesson is sent back once to be fixed.

### Voices (free)
| `--voice` | What it is | Cost / setup |
|---|---|---|
| `edge` (default) | Microsoft Edge's online neural voices, through `edge-tts` | Free and no key. It's unofficial, so it may change or be rate-limited. Fine while the app is experimental. Needs network access to `speech.platform.bing.com` |
| `piper` | Open-source voices that run offline on your CPU | Free. Optional: `pip install piper-tts`. Downloads the voice once (~60 MB) into `voices/` from Hugging Face |

Pick a different voice with `--voice-name`, for example `en-US-GuyNeural` or `en-GB-SoniaNeural` for edge (list them all with `edge-tts --list-voices`), or `en_US-amy-medium` for Piper. If `ffmpeg` is installed, the audio is compressed to mp3. Otherwise it stays as wav.

The output goes to `courses/<topic-slug>/`:
- `plan.md`: the readable course plan. Every lesson lists the claims it draws on, a marker for how well sources agree on each, and the source URLs
- one JSON file per stage, plus `state.json`

**Resuming.** Every stage saves its result. If you run the same command again, saved stages are skipped and the run continues from where it stopped. To redo part of a run, use `--redo-from compare` (or any later stage).

**Memory.** Notes from every course are added to `memory/notes.jsonl`, and later courses on related topics reuse them. Recall works by matching keywords. You can switch to a vector store later without changing the `Memory` interface.

## Settings

| Env var | Default | |
|---|---|---|
| `COURSEGEN_MODEL` | `claude-opus-5-5` | The model used for every stage |
| `COURSEGEN_NO_FALLBACK` | unset | Set it to turn off the server-side refusal fallback (`fallbacks: "default"`) |

## Tests

```bash
pip install pytest && python -m pytest -q
```

The tests run the real Anthropic SDK against a fake HTTP server, so they need no API key, and they use a fake voice. They cover planning, resuming, sending a paused web search back to continue (`pause_turn`), memory, prerequisite ordering, plan checks, writing and recording the sample (including fixing a bad first draft), and feedback updating the style guide.

## Next step
**Produce the rest:** write and record every remaining lesson with the style guide, one arc at a time, then build a course page that links all the lessons.
