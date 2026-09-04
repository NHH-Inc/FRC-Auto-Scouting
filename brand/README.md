# Brand

`tengen-logo.svg` — full lockup, mark plus wordmark.
`tengen-mark.svg` — mark alone, for icons. Not the lockup shrunk: the wordmark is unreadable
below about 96px, so the icon drops it entirely.
`emoji/` — the Discord set, and `server-icon.png`.
`make_emoji.py` — regenerates every PNG from geometry.

## Why the PNGs are drawn rather than converted

Discord will not accept SVG, and rasterising one needs a rendering library that is awkward to
install on Windows. All of this is geometry anyway — hexagons, stars, boxes — so `make_emoji.py`
draws it directly with Pillow and the conversion step disappears.

Pillow does not antialias shape edges, so everything is drawn at 4× and downsampled with LANCZOS.
Skip that and a 128px hexagon has visibly stepped diagonals: fine in isolation, cheap-looking next
to real emoji in the picker.

## Why these emoji and not a public pack

Sites like emoji.gg host 125,000 emoji, but they are user-uploaded works by named creators and
many are derivative of copyrighted material. Downloading someone's art in bulk and re-uploading it
without attribution is poor practice even where it is tolerated.

The genuinely useful ones there — coloured bullets, ticks, status dots — are trivial geometry. So
they are generated here instead: one coherent set in the project palette, with no licensing
question, rather than a grab-bag in eight different styles.

The project-specific ones exist because this project talks about specific things:

| | |
|---|---|
| `:tengen:` | the mark |
| `:tengen_pass:` `:tengen_fail:` `:tengen_building:` | build status |
| `:tengen_merged:` | a merged pull request |
| `:bbox:` | a detection box on a robot — what the detector produces |
| `:track:` | a trajectory — what tracking produces when it works |
| `:stats:` | per-team output |
| `:dot_*:` `:arrow_*:` `:prio_*:` | general utility, in-palette |

## Contrast

`:tengen:` fills its hexagon navy rather than leaving it transparent. Steel on transparent looks
right on Discord's dark default and disappears entirely for anyone on light — an emoji has to
carry its own background.
