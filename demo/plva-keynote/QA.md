# Demo checks

September 8, 2026.

- Exported 12 PNGs at 3840×2160 and their matching SVG sources.
- Reviewed the full storyboard and a rendered prompt screen.
- Browser Next moved from the initial scene to typed prompt.
- Right arrow moved from the typed prompt to submitted/loading state.
- Ran the complete automatic sequence in Chrome: it reached scene 12, stopped automatically, and displayed 01:00 / 01:00.
- Light navigation was applied to the scene source and the separately generated design reference.
- UI screens and narration are explicitly a scripted walkthrough using synthetic records. No live agent calls or shipment operations occur in the player.

After playback validation, minor content corrections changed the field count to three and shortened narration cues. Timeline durations and navigation behavior remain unchanged.

Second-customer scenes now consistently use [NAME_2], [EMAIL_2], and [ADDRESS_2], making the new inputs visually distinct from the first customer's references. The corresponding SVGs, 4K PNGs, storyboard, and portable demo were regenerated. `npm run check` verifies the customer distinction, 60-second timeline, portable source, and exported assets.

The player now requires four main clicks: Enter prompt, Run task, Create skill, and Reuse skill. It automatically shows every intermediate scene and pauses at scenes 2, 6, 8, and 12. Player checks use a controlled animation clock to cover all four actions, duplicate clicks, pause/resume, Back/Reset, keyboard handling, deep links, typing, and uninterrupted 60-second autoplay.
