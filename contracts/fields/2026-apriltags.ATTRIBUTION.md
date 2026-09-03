# 2026-apriltags.json

Copied verbatim from WPILib's published field layout:

    wpilibsuite/allwpilib
    fields/src/main/native/resources/org/wpilib/fields/frc/2026-rebuilt-welded.json

"2026 FRC Rebuilt Welded" — 32 tags. This is the **welded** variant, which WPILib treats as the
2026 default. An AndyMark variant (`2026-rebuilt-andymark.json`) also exists and differs slightly;
if footage comes from an AndyMark field, that file is the correct one.

Positions are published in **metres** with the origin at a field corner. `apriltag_layout.py`
converts to feet at load, once, because the rest of this project works in feet.

Not modified in any way. No coordinate here is estimated, interpolated or filled in — a fabricated
tag position would yield a mapping that is confidently wrong everywhere it is used.

allwpilib is BSD-3-Clause. GitHub reports its licence as NOASSERTION because the repository mixes
several licences across vendored components; the field layout files themselves carry the project's
BSD-3-Clause terms. Retain this notice with the file.
