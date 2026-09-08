# PLVA one-minute demo

Open **PLVA-DEMO.html** in Chrome or Edge. It is self-contained and works offline. `index.html` is the editable version, with `scenes.js` and `player.js` beside it.

## Present

- **Right arrow, Space, Enter, or the main button:** start the next action. Each action plays through automatically and pauses at its stopping point.
- **Left arrow:** return to the previous stopping point.
- **P / Play 60s:** start the full timeline, or pause/resume an active sequence. Use **R** first to begin from the start.
- **R:** reset.
- **N / Notes:** show or hide the current narration cue. Hide notes before recording.
- **F / Stage:** hide controls and request fullscreen.
- **Escape:** leave stage mode or close help.

Present the complete story with **four clicks**:

1. **Enter prompt:** type the request, then pause at the ready prompt.
2. **Run task:** show loading, protect details, fill the form, and pause at the first draft.
3. **Create skill:** extract the procedure and pause at the inspectable skill.
4. **Reuse skill:** introduce the new customer, show the changed form and `_2` references, and finish with the result and closing message.

Extra advances during playback are ignored. Pause/resume remains available; Back and Reset cancel the current sequence. The four stopping points are scenes 2, 6, 8, and 12. The underlying visual states stay available through direct scene links. Play 60s from the start still runs exactly 60 seconds; manual mode adds however long you pause to speak.

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

## Website

Run `npm run build` to assemble the public demo in `dist/`; no dependency installation is needed for this build. Run `npm run check` to verify the timeline, customer references, portable source, and exported assets. The website opens directly into the presentation and includes a separate 4K image-download page.

Run `npm run deploy` with an authenticated Cloudflare account to publish the static demo as the `plva-demo` Worker. The command uses Wrangler 4.130.0. Deployment is a manual command; a GitHub push alone does not publish the site.

For artwork changes, run `npm run export` with Sharp available, then build and check again. The first customer uses private references ending in `_1`; the second uses `_2` throughout its ticket, changed form, and results.

## What the demo represents

This is a **scripted product walkthrough using synthetic data**. Typing, activity messages, checks, and results are presentation states. It makes no API calls, executes no browser tasks, and does not submit a shipment or expose actual private records. The footer keeps that distinction visible. Activity labels describe intended actions, not hidden model reasoning.

The workflow is grounded in the existing shipment example and generated skill procedure. The current repository contains a tested live privacy/runtime path and a separate skill module; this presentation does not prove that their end-to-end integration has completed. Use actual recorded runs for any live-execution claims in the hackathon submission.

## How conference demos like this work

They commonly use a presenter-controlled state sequence: keyboard events reveal a prepared state, run an animation or short clip, and pause at the next speaking point. [Reveal.js fragments](https://revealjs.com/fragments/) support incremental reveals and [Auto-Animate](https://revealjs.com/auto-animate/) transitions matching elements across states. [Arcade](https://www.arcade.software/post/turn-your-videos-into-interactive-arcades) supports videos with pause points and hotspots. These explain the technique; the exact tool used in the unspecified OpenAI conference demo is not verified.

This player implements that pattern locally with a small explicit scene timeline, deterministic animations, and keyboard controls. It has no dependency on a hosted demo platform or internet connection.
