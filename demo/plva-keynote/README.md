# PLVA one-minute demo

Open **PLVA-DEMO.html** in Chrome or Edge. It is self-contained and works offline. `index.html` is the editable version, with `scenes.js` and `player.js` beside it.

## Present

- **Right arrow, Space, Enter, or Next:** advance one scene.
- **Left arrow:** return one scene.
- **P / Play 60s:** play or pause the timeline. Use **R** first to begin from the start.
- **R:** reset.
- **N / Notes:** show or hide the current narration cue. Hide notes before recording.
- **F / Stage:** hide controls and request fullscreen.
- **Escape:** leave stage mode or close help.

The first Next types the prompt. The second submits it and shows the loading/activity state. Subsequent advances reveal protection, form filling, a draft result, skill creation, and a fresh-input reuse example. Manual advances stop autoplay, so the presenter controls the pace. Autoplay from the start lasts exactly 60 seconds.

Use a 16:9 screen or recording canvas. The scene artwork uses a 1920×1080 coordinate system and scales sharply. If a browser blocks fullscreen, F still hides the controls; the browser's own F11 can fill the display.

## Files

- `PLVA-DEMO.html` — portable offline demo, ready to open.
- `images/` — twelve separate **3840×2160 PNGs**, numbered in presentation order, plus a timing manifest.
- `editable/` — matching editable SVG screens.
- `STORYBOARD.png` — contact sheet of all twelve scenes.
- `NARRATION.md` — timed narration and recording notes.
- `design-reference/` — the generated, approved light-navigation screen.
- `IMAGE-PROMPTS.md` — image-generation prompt record.
- `scenes.js`, `player.js`, `index.html` — editable presentation source.
- `export.cjs` — rebuilds PNGs, SVGs, the contact sheet, and portable HTML. It uses Node and Sharp.

## What the demo represents

This is a **scripted product walkthrough using synthetic data**. Typing, activity messages, checks, and results are presentation states. It makes no API calls, executes no browser tasks, and does not submit a shipment or expose actual private records. The footer keeps that distinction visible. Activity labels describe intended actions, not hidden model reasoning.

The workflow is grounded in the existing shipment example and generated skill procedure. The current repository contains a tested live privacy/runtime path and a separate skill module; this presentation does not prove that their end-to-end integration has completed. Use actual recorded runs for any live-execution claims in the hackathon submission.

## How conference demos like this work

They commonly use a presenter-controlled state sequence: keyboard events reveal a prepared state, run an animation or short clip, and pause at the next speaking point. [Reveal.js fragments](https://revealjs.com/fragments/) support incremental reveals and [Auto-Animate](https://revealjs.com/auto-animate/) transitions matching elements across states. [Arcade](https://www.arcade.software/post/turn-your-videos-into-interactive-arcades) supports videos with pause points and hotspots. These explain the technique; the exact tool used in the unspecified OpenAI conference demo is not verified.

This player implements that pattern locally with a small explicit scene timeline, deterministic animations, and keyboard controls. It has no dependency on a hosted demo platform or internet connection.
