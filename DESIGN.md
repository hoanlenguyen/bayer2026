# Design decisions

Read this before changing or adding a screen.

## Brief
- **Product:** decides whether a plant's analytics question needs an existing report reused or extended, a new one created, or can't be met.
- **Users:** non-technical plant staff in any department, plus report owners who approve changes.
- **Main jobs:** get a trustworthy answer to "do we already have this?", approve or reject a build, check whether an asset can be trusted.
- **Platform:** desktop first; everything must still work at 375px.

## Look
- **Face:** Clean: white sidebar, `#F7F7F7` content area. On Ask and Explorer, cards and panels use the same `#F7F7F7` with a hairline border and dark text, to match the knowledge graph; warm grey is only for hints and switched-off controls. Shadows only on floating layers (search results).
- **Colours:** every page uses the knowledge graph's palette, from the tokens in `frontend/src/styles.css`. Warm charcoal `#3C3835` for text and `--accent`, warm grey `#6B6360` for secondary text and all graph dots, warm-tinted neutrals for lines and surfaces. Coral means selected or hovered and amber means linked, in both graphs. Darker coral, amber and a green carry status (`--bad`, `--warn`, `--ok`), so text stays readable. Item types are never told apart by colour: they use labels and letters on the dot.
- **Font:** IBM Plex Sans; IBM Plex Mono only for IDs, code and score values. Both ship with the app (`@fontsource`, imported in `frontend/src/main.tsx`), so they need no outside network. Sidebar links change page without a reload, so the fonts and sidebar never redraw.
- **Themes:** light only for now: the `#F7F7F7` background and `#3C3835` text apply even when the system is in dark mode. The dark tokens remain in `styles.css` and apply only with `data-theme="dark"` on `<html>`. Never hard-code a colour.
- **Corners:** 12px for cards and controls 40px or taller, 8px below that, 24px for the composer and chat bubbles.

## Screens
- **Ask:** the verdict card is the answer. It holds the decision, the three scores with their pass mark, what is missing, and the one action that follows. Approval lives only there.
- **How this was decided:** plain language by default. Agent traces, Python rules, weights, thresholds and raw specs appear with the "Technical details" switch, so the demo can still show the mechanics.
- **Estate Explorer, details:** each fact appears once. Status is in the header; owner and trust are under Governance.
- **Estate Explorer, graph:** filters are one row above the canvas so the graph gets the width. The key sits under the canvas.
- **Knowledge graph (`/cala-graph`):** full-screen rotating 3D map of the live catalog, styled after the graph on cala.ai: one warm grey for all dots (`--kg-dot`), a small caption card at the bottom right. Items are grouped by domain (workspace): close together inside a domain, clearly apart from other domains, with each domain's name above its group. KPIs are shared across domains, so they form their own labelled group in the middle. Real links between domains are drawn lighter than links inside a domain (`--kg-line-far`) and don't affect the layout, so groups stay apart; hovering an item strengthens its own links. Hovering or tapping an item turns it coral (`--kg-dot-hover`), shows its name in a tooltip below it, turns its linked items amber (`--kg-dot-linked`), and pauses the rotation; the card adds its type, status and domain. Clicking an item keeps this highlight after the pointer leaves and opens a panel on the right listing its linked items by relationship, with a search box that filters them by name or type; clicking a row selects that item, so people can walk the chain from domain to model to report; clicking it again, clicking empty space or pressing Esc clears it, and dragging never pins. Only real items are drawn: `ILLUSTRATIVE_DOTS` in `KnowledgeGraph.tsx` is off. It needs the backend, and has no links into the Explorer. A search at the top left finds any item and selects it.

## Rules
- Every decision shows its scores (see `CLAUDE.md`).
- One primary button per view: the action the screen exists for.
- No avatar on assistant messages; the user's bubble is enough to tell the two apart.
