# Design decisions

Read this before changing or adding a screen.

## Brief
- **Product:** decides whether a plant's analytics question needs an existing report reused or extended, a new one created, or can't be met.
- **Users:** non-technical plant staff in any department, plus report owners who approve changes.
- **Main jobs:** get a trustworthy answer to "do we already have this?", approve or reject a build, check whether an asset can be trusted.
- **Platform:** desktop first; everything must still work at 375px.

## Look
- **Face:** Clean: white sidebar, grey content area, flat white cards with a hairline border. Shadows only on floating layers (search results).
- **Accent:** teal, `--accent` in `frontend/src/styles.css`.
- **Font:** IBM Plex Sans; IBM Plex Mono only for IDs, code and score values.
- **Themes:** light and dark both supported through the tokens at the top of `styles.css`. Never hard-code a colour.
- **Corners:** 12px for cards and controls 40px or taller, 8px below that, 24px for the composer and chat bubbles.

## Screens
- **Ask:** the verdict card is the answer. It holds the decision, the three scores with their pass mark, what is missing, and the one action that follows. Approval lives only there.
- **How this was decided:** plain language by default. Agent traces, Python rules, weights, thresholds and raw specs appear with the "Technical details" switch, so the demo can still show the mechanics.
- **Estate Explorer, details:** each fact appears once. Status is in the header; owner and trust are under Governance.
- **Estate Explorer, graph:** filters are one row above the canvas so the graph gets the width. The key sits under the canvas.

## Rules
- Every decision shows its scores (see `CLAUDE.md`).
- One primary button per view: the action the screen exists for.
- No avatar on assistant messages; the user's bubble is enough to tell the two apart.
