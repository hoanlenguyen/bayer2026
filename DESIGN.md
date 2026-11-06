# Design decisions

Read this before changing or adding a screen.

## Brief
- **Product:** decides whether a plant's analytics question needs an existing report reused or extended, a new one created, or can't be met.
- **Users:** non-technical plant staff in any department, plus report owners who approve changes.
- **Main jobs:** get a trustworthy answer to "do we already have this?", approve or reject a build, check whether an asset can be trusted.
- **Platform:** desktop first; everything must still work at 375px.

## Look
- **Face:** Clean: white sidebar, `#F7F7F7` content area, flat white cards with a hairline border. Shadows only on floating layers (search results).
- **Main colour:** navy `#232F3F`, used for text and as `--accent` in `frontend/src/styles.css`. The dark theme uses a lighter tint of it, because `#232F3F` is unreadable on dark surfaces.
- **Font:** IBM Plex Sans; IBM Plex Mono only for IDs, code and score values.
- **Themes:** light only for now: `data-theme="light"` in `frontend/index.html` locks the `#F7F7F7` background and `#232F3F` text. The dark tokens remain in `styles.css`; remove that attribute to follow the system theme again. Never hard-code a colour.
- **Corners:** 12px for cards and controls 40px or taller, 8px below that, 24px for the composer and chat bubbles.

## Screens
- **Ask:** the verdict card is the answer. It holds the decision, the three scores with their pass mark, what is missing, and the one action that follows. Approval lives only there.
- **How this was decided:** plain language by default. Agent traces, Python rules, weights, thresholds and raw specs appear with the "Technical details" switch, so the demo can still show the mechanics.
- **Estate Explorer, details:** each fact appears once. Status is in the header; owner and trust are under Governance.
- **Estate Explorer, graph:** filters are one row above the canvas so the graph gets the width. The key sits under the canvas.
- **Knowledge graph (`/cala-graph`):** full-screen rotating 3D map of the live catalog, styled after the graph on cala.ai: one warm grey for all dots (`--kg-dot`), a small caption card at the bottom right. Items are grouped by domain (workspace): close together inside a domain, clearly apart from other domains, with each domain's name above its group. KPIs are shared across domains, so they form their own labelled group in the middle. Real links between domains are drawn lighter than links inside a domain (`--kg-line-far`) and don't affect the layout, so groups stay apart; hovering an item strengthens its own links. Hovering or tapping an item turns it coral (`--kg-dot-hover`), shows its name in a tooltip below it, turns its linked items amber (`--kg-dot-linked`), and pauses the rotation; the card adds its type, status and domain. Only real items are drawn: `ILLUSTRATIVE_DOTS` in `KnowledgeGraph.tsx` is off. It needs the backend, and has no links into the Explorer and no search.

## Rules
- Every decision shows its scores (see `CLAUDE.md`).
- One primary button per view: the action the screen exists for.
- No avatar on assistant messages; the user's bubble is enough to tell the two apart.
