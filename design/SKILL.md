---
name: mitchell-design
description: Use this skill to generate well-branded interfaces and assets for the Mitchell Design System (Jonathan S. Mitchell, Coe College) — research papers, teaching slides, scientific figures, and interactive simulations. Handles both light mode (papers, reports) and dark mode (lectures, presentations). Contains type, color, ColorBrewer ramps, chart primitives, silhouette conventions, and three UI kits (paper figures, slides, web simulations).
user-invocable: true
---

Read the `README.md` file within this skill first — it contains the full visual foundations, content fundamentals, chart rules, and iconography. Then explore:

- `colors_and_type.css` and `chart_style.css` — the authoritative design tokens. Always load these instead of reinventing colors, type, or axis styles.
- `lib/chart_primitives.jsx` — React/JSX helpers for axes, violins, CI bands, histograms, scatter. Import these before hand-rolling SVG.
- `ui_kits/figures/` — light-mode paper/report template.
- `ui_kits/slides/` — dark-mode 1280×720 lecture slide templates.
- `ui_kits/web/` — interactive simulation shell (sidebar params + posterior panels).
- `preview/` — specimen cards per token / motif / component. Good reference when picking colors or styling a plot.
- `assets/samples/` — original Mitchell research figures, for visual calibration.

**When asked to create visual artifacts** (slides, mocks, throwaway prototypes, figures, simulations, web apps):
- Copy assets out of this skill into the target project rather than linking across skill boundaries.
- Produce static HTML files the user can view directly.
- Always load `colors_and_type.css` + `chart_style.css`; pick mode (`class="mds-root"` + optional `mds-dark`) based on context — papers/reports default to light, slides/presentations default to dark, interactive apps default to light.
- For data plots, follow the **Chart rules** section of README strictly (axes 1.25px, serif tick labels, ColorBrewer ramps, uncertainty as ribbons).
- Use silhouettes from `assets/silhouettes/` where available; flag if missing rather than drawing your own.

**When working on production code** (R/ggplot2, matplotlib, Observable, D3): copy the rules in README's "Chart rules" section into the project's plotting theme. Keep the same token names where possible so the visual language carries across tools.

**When invoked without guidance**, ask what the user wants to produce (slide? figure? paper layout? web app? theme for R/Python?), ask a few clarifying questions (mode, audience, data shape, what needs to be conveyed), and act as an expert scientific-design collaborator whose output is either HTML artifacts or production-quality plotting code, depending on the need.
