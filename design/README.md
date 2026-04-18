# Mitchell Design System

A coherent visual language for the work of **Jonathan S. Mitchell** (Coe College) — spanning teaching slides, research papers, figures, and interactive simulations. Two modes: **light** (papers, reports) and **dark** (lectures, presentations). One vocabulary of uncertainty, silhouettes, and ColorBrewer ramps.

This system is designed to be used from Claude Code, from hand-written HTML, or referenced while writing R/ggplot2, matplotlib, or D3 code. The CSS files and chart primitives live here; the rules for translating them into other languages live below.

---

## Index

| File / folder | What's in it |
|---|---|
| `colors_and_type.css` | Design tokens: fonts, colors, neutrals, ColorBrewer ramps, semantic type classes, light/dark mode. |
| `chart_style.css` | SVG chart primitives — axes, violins, CI bands, phylograms, silhouettes, legends. |
| `lib/chart_primitives.jsx` | React/JSX helpers: `Figure`, `AxisX`, `AxisY`, `Violin`, `CIBand`, `Histogram`, `Scatter`, `RampStrip`, `linScale`, `logScale`. |
| `ui_kits/figures/` | Light-mode paper/report layout — two-column article w/ inline figures. |
| `ui_kits/slides/` | Dark-mode 1280×720 lecture slide templates (title, concept, chart, quote, takeaway). |
| `ui_kits/web/` | Interactive simulation shell — sidebar of parameters, posterior panels, trace plots. |
| `preview/` | Individual specimen cards — one per token / motif / component. |
| `assets/samples/` | Original research figures (Mitchell et al.) copied from the `Figures/` attachment, for reference. |
| `SKILL.md` | Agent-Skill manifest, compatible with Claude Code. |

**Sources referenced.** The attached `Figures/` directory contained ~50 PDFs and lecture screenshots from Jonathan Mitchell's research and teaching: violin plots of log body mass, dinosaur / bird morphospace scatter plots, colored phylograms (viridis, PuOr), network/food-web diagrams with silhouettes, rate-through-time ribbons, small-multiples parameter sweeps, and BAMM/MCMC-style diagnostic plots. Representative examples are in `assets/samples/`.

---

## Content fundamentals

**Voice is empirical and precise — never marketing.** Short declarative sentences. Numbers quoted with uncertainty intervals. Greek parameters in italic serif inline (*ψ*, *λ*, *μ*, *ρ*).

**Casing.** Sentence case in headings. `ALL CAPS` only for small uppercase eyebrow labels ("FIGURE 3 · MORPHOSPACE"). Never title-case marketing headlines.

**Person.** Mostly third-person passive in papers ("We show that…", "Simulations were run on…"). First-person plural in lecture voice ("We infer rates from trees. Trees lose fossils."). Never "you" except in pedagogy.

**Emoji.** No. Unicode is reserved for Greek letters (ψ λ μ ρ α β ≤ ≥ × ± −) and en/em dashes (– —).

**Math inline.** Italic serif for parameters: *ψ = 0.1*. Mono (JetBrains Mono) for code and model specifications.

**Citation style.** `Mitchell 2015 Evolution` — sans, muted, bottom-left of figures. Author year Journal, no comma, no italics for journal (saves visual weight on dark slides).

**Vibe.** Confident, honest about uncertainty, slightly dry. Assume the reader knows what a posterior is.

---

## Visual foundations

**Two modes, one grammar.**
- **Light (papers/reports)** — pure white background, serif body (Crimson Pro), square figure frames, 1.25px axis rules, black silhouettes.
- **Dark (lectures/presentations)** — pure black (`#000`) background, sans display (Inter), white silhouettes, hot-red accent (`#ff4a3d`) for emphasis. No gray backgrounds.

**Type.** Serif `Crimson Pro` (substitute for Charter/Iowan Old Style) for paper voice; sans `Inter` (substitute for Gill Sans/Avenir — see caveat below) for lecture + UI; mono `JetBrains Mono` for code. Scale is modular-1.25, from 12 to 64px. Line heights tighter on display (1.15), loose on body (1.55–1.75). Text-wrap: pretty on paragraphs, balance on headings.

**Color — the paper/dark palette is almost achromatic**, with *color reserved for data*. Brand accents are four earthy hues (crimson, ochre, moss, indigo); accent use is restrained.

**Data color follows ColorBrewer religiously:**
- Diverging signed traits → **RdBu** or **PuOr** (e.g. phylograms colored by trait direction).
- Sequential magnitudes → **Viridis** (perceptually uniform, colorblind-safe) or **YlOrRd** (for warm rate ramps).
- Categorical ≤6 → **Dark2**.
- Never use rainbow/jet. Never use gradients for data encoding unless perceptually uniform.

**Uncertainty is the subject.** Every estimate gets a ribbon, violin, or interval. Specific devices:
- **Violin + inner boxplot + white median dot** (matches your published figures).
- **95% HPD ribbons** around median lines, rendered at ~14% opacity of the line color.
- **Open vs. filled circles** to distinguish conditions on scatterplots.
- **Small-multiples** for parameter sweeps, with column + row headers in tiny uppercase sans.

**Silhouettes.** Used heavily as legend elements, plot anchors, and on maps. Pure black (light mode) or white (dark mode), no outline. Source from [PhyloPic](https://phylopic.org) (public-domain / CC). Store as SVG in `assets/silhouettes/`.

**Axes.** Black, 1.25px strokes. Tick labels serif 14px, axis titles serif 16px/500. Italic serif for Greek-letter axis titles. No gridlines by default — add dashed 0.75px gridlines (`--chart-grid`) only when the data genuinely needs them.

**Spacing.** 4px base. Tokens sp-1 (4) through sp-8 (64). Papers use generous margins (72px padding, 2-column grid). Slides use 80–120px outer padding. UI uses 16–24px panel padding.

**Radii.** 0 for figure frames. 2–4px for buttons, inputs. 8px is the maximum for application panels. Never rounded silhouettes or data marks.

**Backgrounds.** Solid only. Pure white (#fff), pure black (#000), or ink-50 (#f7f7f5) for a "paper" feel in web UIs. **No gradients.** No textures. No patterns except in data (hatching as an accessibility fallback for redundant encoding).

**Animation.** Minimal, functional. Slider drags update plots in real time (linear, 60ms). Transitions between slides are straight cuts. On web, hovering a series highlights it (`opacity 1.0`, others go to `0.4`, 120ms ease). No bounces, no spring physics.

**Hover states.** Buttons invert (white bg → black bg). Ghost buttons get a subtle ink-100 background. Chart series highlight by dimming siblings.

**Press states.** No shrink. Background darkens to crimson accent for primary actions. Keyboard focus: 2px solid black outline, 2px offset — accessible and visible in both modes.

**Borders.** Hair (1px ink-200) for UI divisions, rule (1.5px ink-900) for figure frames. Cards have 1px borders, not shadows.

**Shadows.** Very restrained in light mode (`shadow-1`, `shadow-2`). **None in dark mode** — they muddy pure black.

**Transparency / blur.** Almost never. The exception: CI ribbons use rgba alpha. Do not use backdrop-blur.

**Imagery.** B&W silhouettes dominate. Full-color images are rare and always editorial (a bird photograph on a title slide, etc.). When used, imagery is warm, naturalistic, shot in daylight; no duotones, no saturation tweaks.

**Corners.** Square is the default. Anything square-cornered reads as "this is a figure." Anything with 8px radii reads as "this is a UI chrome element, not data."

**Cards.** `1px solid #ececea`, `border-radius: 8px`, 18–24px padding, optional tiny uppercase sans title (`.panel h3`). No shadows.

**Layout rules.**
- Papers: two-column, justified, 15/1.6 serif body, `hyphens: auto`.
- Slides: 1280×720 fixed, content on a ~1160px safe area, footer strip at 24px from bottom.
- Web: 280px sidebar + fluid main, panels in a 2-col/3-col grid.

---

## Chart rules — use in any plotting library

These rules are meant to be copied into R/ggplot2 themes, matplotlib rcParams, Plotly layouts, or D3 axis defaults.

**Axes.**
- Black (light) / white (dark) frame, stroke 1.25px.
- Tick marks **outside** the plot, 6px long.
- Serif tick labels.
- Italic serif axis titles for Greek parameters; roman serif otherwise.
- Time axes read right-to-left when plotting Ma (present on the right).

**Data.**
- Primary series: black (light) or white (dark), 1.75px line.
- Secondary series use the qualitative Dark2 ramp in order.
- Points: 3px radius, filled primary series; open (bg-fill) secondary.
- Never encode category with both color *and* shape unnecessarily — but **do** double-encode when figures will be printed b/w.

**Uncertainty.**
- 95% HPD > 50% HPD, show one by default.
- Ribbons: `fill = line color @ 14% alpha`, `stroke = none`.
- Whisker lines in violin/box plots at axis color.

**Typography in plots.**
- Tick labels 14px.
- Axis titles 16px.
- Panel labels 14px sans uppercase.
- Annotations 13px italic serif.

**ggplot2 sketch** (drop into `theme_mitchell()`):
```r
theme_mitchell <- function(base_size = 14, dark = FALSE) {
  bg  <- if (dark) "#000000" else "#ffffff"
  fg  <- if (dark) "#ffffff" else "#0a0a0a"
  theme_minimal(base_size = base_size, base_family = "Crimson Pro") %+replace%
    theme(
      plot.background  = element_rect(fill = bg, colour = NA),
      panel.background = element_rect(fill = bg, colour = NA),
      panel.grid       = element_blank(),
      panel.border     = element_rect(fill = NA, colour = fg, size = 0.5),
      axis.text        = element_text(colour = fg, size = base_size - 2),
      axis.title       = element_text(colour = fg, size = base_size),
      axis.ticks       = element_line(colour = fg, size = 0.5),
      strip.text       = element_text(family = "Inter", face = "bold",
                                      size = base_size - 4, colour = fg),
      legend.text      = element_text(family = "Inter", size = base_size - 3),
      legend.title     = element_blank()
    )
}
```

**matplotlib sketch:**
```python
import matplotlib as mpl
MITCHELL_LIGHT = {
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": "#0a0a0a", "axes.linewidth": 1.25,
    "axes.labelcolor": "#0a0a0a", "xtick.color": "#0a0a0a", "ytick.color": "#0a0a0a",
    "font.family": "Crimson Pro", "font.size": 14,
    "axes.grid": False, "axes.spines.top": True, "axes.spines.right": True,
}
MITCHELL_DARK = {**MITCHELL_LIGHT, "figure.facecolor": "#000", "axes.facecolor": "#000",
    "axes.edgecolor": "#fff", "axes.labelcolor": "#fff",
    "xtick.color": "#fff", "ytick.color": "#fff"}
```

---

## Iconography

The Mitchell system uses **silhouettes-as-icons**, not a conventional UI icon set. Organisms are the primary visual vocabulary — a theropod silhouette carries more information on a macroevolution slide than any vector glyph.

**Where silhouettes come from.** [PhyloPic](https://phylopic.org) is the canonical source — CC / public-domain organism silhouettes at phylogenetic resolution. Save as SVG in `assets/silhouettes/`, named by clade: `theropod.svg`, `ceratopsian.svg`, `bird.svg`, `mammal.svg`.

**UI icons** (for the web kit) should be **Lucide** (MIT, CDN-available). 1.5–2px strokes, rounded joins, 24px default. Import via CDN: `https://unpkg.com/lucide-static@latest/`.

**No emoji.** No unicode icons except Greek letters and math operators. **No ligature icon fonts** (Material Icons, FontAwesome). One glyph system at a time.

**Logos.** There is no formal Mitchell Lab logo at the time of writing — the word mark (`Mitchell Lab` set in Crimson Pro 600) on its own is the mark. A placeholder monogram is used in `ui_kits/web/` — treat as a sketch; an actual lab mark should replace it.

**⚠️ Placeholder silhouettes.** The specimens in `preview/silhouettes.html` are rough hand-drawn SVG placeholders. **Fetch real silhouettes from PhyloPic** for any finished work.

---

## ⚠️ Flags to the user

- **Fonts are Google Fonts substitutes.** Your slides appear to be set in something close to **Gill Sans / Avenir** (lecture mode) and **Times / Charter** (paper mode). I've substituted **Inter** and **Crimson Pro**, respectively, because they're the closest CDN-available open-source options. If you have Gill Sans / Avenir / Charter licensed, swap the `--mds-sans` and `--mds-serif` variables in `colors_and_type.css`.
- **No real silhouettes.** I was unable to fetch PhyloPic SVGs (fetch is blocked). Please drop a silhouette set into `assets/silhouettes/` and I'll wire them into the preview cards and slide templates.
- **No lab logo.** If there is a formal lab mark, share it and I'll replace the placeholder monogram in `ui_kits/web/`.
- **Content in the kits is illustrative, not real.** The numbers and clades shown in `ui_kits/*/index.html` are plausible placeholders, not your actual results.

---

## Using this system in Claude Code

Download this project (or copy it into your repo's `design/` folder) and drop the `SKILL.md` file alongside. Claude will read `README.md`, treat the CSS tokens as authoritative, and generate figures / pages / slides consistent with the rules above.
