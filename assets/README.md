# Brand assets

Drop the generated files in beside this one. Every reference in the docs uses
these exact names, so nothing needs editing once they exist.

| File | Size | Background | Used by |
|---|---|---|---|
| `logo.png` | 1024×1024 | transparent | README hero (light) |
| `logo-dark.png` | 1024×1024 | transparent | README hero (dark) |
| `mark.png` | 512×512 | transparent | docs headers, small placements (light) |
| `mark-dark.png` | 512×512 | transparent | docs headers, small placements (dark) |
| `favicon.png` | 256×256 | transparent | repo favicon, tab icon |
| `social-preview.png` | 1280×640 | solid `#161719` | GitHub social preview card |
| `thesis.png` | 1600×800 | transparent | README, the credulous/skeptical contrast |

## The idea

An elephant never forgets. LIWM's argument is that forgetting is not the
problem — remembering *indiscriminately* is. So the character is a skeptical
elephant: it remembers, and it asks where you heard that. The trunk holding a
scrap of paper up for inspection is the provenance gate, drawn.

`thesis.png` is the whole README in one image: the difference is not whether the
agent remembers, it is what gets written down.

## Palette

| Role | Hex | Notes |
|---|---|---|
| Ink | `#161719` | Near-black; softer than `#000` against a dark page |
| Paper | `#FAF9F6` | Warm off-white, not clinical |
| Accent — verified | `#C8873A` | Amber reads as an archival seal, not "tech blue" |
| Quarantine | `#8C3A2E` | The refusal state in diagrams |

One accent only. A second would dilute it.

## Rules

- No gradients, no 3D, no glow, no drop shadows, no AI-cliché circuitry.
- No text baked into any image — `social-preview.png` deliberately leaves its
  right two-thirds empty so typography can be set in real type.
- The mascot is not the mark. `logo.png` dies below ~120px; `mark.png` is the
  reductive version that survives a favicon.
- Keep the character consistent across `logo`, `social-preview` and `thesis`.

## Setting the social preview

GitHub does not read this directory automatically:

    Settings → General → Social preview → Upload an image

Upload `social-preview.png` there once it exists.

## Licence

The assets are covered by the repository's [MIT licence](../LICENSE) along with
everything else. Attribution is appreciated but not required.
