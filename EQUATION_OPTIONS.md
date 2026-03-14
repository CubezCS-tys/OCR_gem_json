# Equation Line Problem — Options

## Root Cause

Azure splits equations into small ink-cluster fragments (`-F (u)`, `= - K 22F (u)`, `rn+1`).  
Gemini reads the whole equation as one coherent line (`K ∂2u/∂x2 = -K λ2F (u)`).  
The fuzzy merger pairs lines 1-to-1 — when they don't align, Azure's garbage stays.

Worst pages: 11 (33% matched), 22 (35% matched) — both are equation-heavy.

---

## Options

### Option 1 — Suppress equation garbage (quickest)
Detect Azure lines that look like orphaned equation fragments (short, no Arabic words,
mostly math chars) and **drop** them from the output if they also failed to fuzzy-match.
- Pro: easy, immediate visual improvement
- Con: loses positional boxes; equation region shows blank in replace-text mode

### Option 2 — Equation-region pass-through
Detect equation regions from Azure (by density of short unmatched lines in a vertical
band) and **replace the whole region** with Gemini's corresponding lines verbatim,
using Gemini's bbox_pct polygons.
- Pro: equations rendered with correct text and reasonable position
- Con: Gemini bbox is less precise than Azure; region detection heuristic needs tuning

### Option 3 — Wider window for equation pages
If a page has low match rate (e.g. < 60%), re-run the merge with a much larger
`window_radius` (e.g. 30 instead of 10) so a single Gemini equation line can
scan and claim a wide band of Azure fragments.
- Pro: no structural changes, just a parameter tweak
- Con: can cause wrong matches on mixed pages (prose + equations)

### Option 4 — LaTeX / MathML extraction prompt
Change the Gemini prompt for equation-dense pages to ask for **LaTeX** instead of
plain Unicode math. Then render equations with MathJax/KaTeX in the HTML output.
This would actually be the best final-quality output.
- Pro: beautiful rendered equations, machine-readable
- Con: significant work — needs MathJax in HTML renderer + new merge strategy for latex lines

---

## Recommendation

Start with **Option 2** (equation-region pass-through) — it gives accurate text
with acceptable position and is a natural extension of the existing injected-line logic.
Follow with **Option 4** later for publication-quality output.
