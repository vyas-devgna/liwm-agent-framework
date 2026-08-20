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
`social-preview.png` are derived from `logo.png` programmatically rather than
drawn again, so they cannot drift apart.

## The register

Classical line engraving — a banknote portrait or a Wall Street Journal hedcut.
All tone comes from hatching density, never from gradients, so the mark is
genuinely monochrome and reproduces anywhere: one ink, one plate.

This is a deliberate rejection of the flat geometric app-icon look. A friendly
geometric mark would have been faster to make and impossible to remember, and
the style is doing conceptual work here: engraving is the visual language of
share certificates, seals and currency — of *provenance*, which is the thing
this project is actually about.

The load-bearing constraint is the **silhouette**. Interior hatching may be as
fine as it likes, but the outer contour has to be strong and closed enough that
the mark still reads at 32 pixels once that hatching blurs into solid tone.
That is how banknote portraits work, and it is what lets one drawing serve both
a README hero and a favicon.

## Palette

| Role | Hex | Notes |
|---|---|---|
| Ink | `#1A1A1A` | Near-black; softer than `#000` against a dark page |
| Paper | `#F5F3EF` | Warm off-white, not clinical |
| Accent | `#C8873A` | Amber, for docs and diagrams only — never in the mark |

The mark is one ink colour. Restraint is what lets it survive being shrunk.

## Rules

- Tone from line density only. No gradients, airbrush, soft shading, or blur.
- No frame, oval border, guilloche, ribbon, or background pattern.
- No text baked into any image. `social-preview.png` deliberately leaves its
  right side empty so typography can be set in real type.
- Regenerating one file means regenerating `logo.png` and re-deriving the rest.
  Never redraw a variant by hand — that is how a brand starts to wobble.

## Why the favicon is not a faithful miniature

`logo.png` carries all its tone in the **alpha** channel: every visible pixel is
the same `#1A1A1A`, and the hatching is rendered as varying opacity. That is
what makes `logo-dark.png` an exact recolour — swap the RGB, keep the alpha, and
the engraving is preserved perfectly.

It also means that shrinking the mark averages the hatching toward a pale grey.
At 32 pixels that is still legible; at 16 it dissolves into a smudge. So the
favicon's alpha is deliberately pushed toward solid:

    magick favicon-source.png -channel A -level '0%,40%' +channel favicon.png

The favicon exists to be tiny, and being unreadable at its working size is a
worse sin than being a slightly heavier version of the master. `logo.png`
remains the faithful one.

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
