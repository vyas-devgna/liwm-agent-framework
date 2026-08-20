# Brand assets

Drop the generated files in beside this one. Every reference in the docs uses
these exact names, so nothing needs editing once they exist.

| File | Size | Background | Used by |
|---|---|---|---|
| `logo.png` | 1024×1024 | transparent | README and docs headers (light mode) |
| `logo-dark.png` | 1024×1024 | transparent | README and docs headers (dark mode) |
| `favicon.png` | 512×512 | transparent | tab icon, small placements |
| `social-preview.png` | 1280×640 | solid `#1A1A1A` | GitHub social preview card |

## The idea

An elephant never forgets. LIWM's argument is that forgetting was never the
problem — remembering *indiscriminately* is. So the mark is an elephant head
whose trunk curls into a question mark: memory that interrogates its sources.

One drawing, four files. `logo-dark.png`, `favicon.png` and
`social-preview.png` are all derived from `logo.png` programmatically rather
than drawn again, so they cannot drift apart.

## Palette

| Role | Hex | Notes |
|---|---|---|
| Ink | `#1A1A1A` | Near-black; softer than `#000` against a dark page |
| Paper | `#F5F3EF` | Warm off-white, not clinical |
| Accent | `#C8873A` | Amber, for docs and diagrams only — not in the mark |

The mark itself is a single solid colour. Restraint is what lets it work at
16 pixels.

## Rules

- Flat only. No gradients, shadows, 3D, texture, brush strokes, or grain.
- No frame, badge, or circle border around the mark.
- No text baked into any image. `social-preview.png` deliberately leaves its
  right side empty so typography can be set in real type.
- Regenerating one file means regenerating `logo.png` and re-deriving the rest.
  Never redraw a variant by hand — that is how a brand starts to wobble.

## Setting the social preview

GitHub does not read this directory automatically:

    Settings → General → Social preview → Upload an image

Upload `social-preview.png` there once it exists.

## Validation

`tools/validate_repo.py` fails when any of the four is missing, because a broken
image on the front page of a project is exactly the kind of thing nobody
notices. CI currently sets `LIWM_ALLOW_MISSING_ASSETS=1` so the check warns
instead; **remove that from `.github/workflows/ci.yml` once the files land.**

## Licence

The assets are covered by the repository's [MIT licence](../LICENSE) along with
everything else. Attribution is appreciated but not required.
