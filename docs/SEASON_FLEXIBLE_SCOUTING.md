# Season-flexible scouting

The robot detector can train on labelled FRC footage from multiple years because its single class
is `robot`. It must not be expected to know a new game's pieces, scoring rules, goal names, or
actions without labelled examples and a reviewed season profile.

The 2026 sheet provided by the team is a useful layout reference. It contains four different
types of information, which must stay separate:

| Sheet concept | Source | Cross-season handling |
|---|---|---|
| Fuel / primary scoring total | model or manually reviewed `shot_made` events | Rename and filter through the season profile; do not hardcode `Fuel`. |
| Adjusted score | derived comparison against alliance or official score | Calculate after the match; never train it as an image label. |
| Driving, scoring, defense ratings | human scout | Collect as subjective input; an image model cannot infer these reliably. |
| Last-three-match average / trend | historical aggregate | Derive only from completed prior matches. |

## What changes each FRC season

1. Add `contracts/seasons/<year>.json` with verified field dimensions, periods, game pieces,
   legal goals, and official point values. This is a shared-contract change: the analysis,
   ingest, and web owners must agree before it lands.
2. Create a local scouting profile from `configs/scouting_profile.example.json`. Rename the
   objective counters for that game and set subjective-rating weights agreed by the drive team.
3. Collect and human-review labelled frames for the season's detectable actions. A detector
   trained only on 2026 robot boxes can still locate robots in another year, but it cannot
   reliably recognise a different piece or score action without examples.
4. Train a new, versioned model folder. Never overwrite a prior model or raw events.
5. Verify on matches the model did not see during training, then compare aggregate values to
   official scores and human scouting.

## Stable objective metrics

These are meaningful only when the season's event labelling supports them: robot presence,
attempts, made actions, reloads, median cycle time, accuracy, defense time, immobility, fouls,
and points contributed. Goal names and point values remain season-configured.

## The local scouting-profile format

`configs/scouting_profile.schema.json` describes the non-contract profile. It holds display
labels and aggregation choices, not match data. `configs/scouting_profile.example.json` mirrors
the provided sheet with generic names: primary scoring actions, derived points, 1-10 subjective
ratings weighted 50/35/15, and a three-match moving average.

The profile deliberately does not modify `contracts/`. Once the team agrees on the fields to
store and display, it can be wired into the API and web UI through a coordinated contract change.
