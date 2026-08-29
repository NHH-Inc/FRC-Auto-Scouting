"""The corrections layer, SCHEMA_VERSION 2.

Doc 0, three times over:

    "Corrections never overwrite model output."
    "events and tracks store raw model output only."
    "Keeping both is the whole point: overwriting destroys the ability to measure whether
     the model is improving."

Corrections are stored as their own rows and composed onto raw records at read time.
`raw=true` skips this entirely and returns what the model actually said, which is what the
accuracy comparison and the training-data export need.

If this module is ever bypassed and an event row is UPDATEd in place, the original prediction
is gone permanently -- a correction records the new value, not the old one.
"""

from .serializers import event_to_dict, track_to_dict


def _sorted(corrections):
    return sorted(corrections, key=lambda c: (c.created_at is None, c.created_at))


def apply_corrections(events, corrections) -> list[dict]:
    """Compose corrections onto raw events. Both arguments are ORM rows.

    A TRACK-scoped correction re-attributes the track and every event on it, as one action.
    Doc 3 calls that the primary correction path: one bad OCR read mislabels forty-odd events
    and every box on that robot.
    """
    by_id: dict[str, dict] = {e.event_id: event_to_dict(e) for e in events}
    deleted: set[str] = set()

    for correction in _sorted(corrections):
        action = correction.action
        target = correction.target_id

        if correction.scope == "track":
            try:
                track_id = int(target)
            except (TypeError, ValueError):
                continue
            patch = correction.fields or {}
            for row in by_id.values():
                if row.get("track_id") != track_id:
                    continue
                row.update(patch)
                row["corrected"] = True
                row["correction_id"] = correction.correction_id
            continue

        if action == "delete":
            deleted.add(target)
            continue

        if action == "create":
            fields = dict(correction.fields or {})
            fields["event_id"] = target
            fields.setdefault("schema_version", 2)
            fields.setdefault("source", "manual")
            fields["corrected"] = True
            fields["correction_id"] = correction.correction_id
            by_id[target] = fields
            deleted.discard(target)
            continue

        if action == "edit":
            existing = by_id.get(target)
            if existing is None or not correction.fields:
                # An edit against an event that no longer exists is a no-op, not an error.
                continue
            by_id[target] = {
                **existing,
                **correction.fields,
                "corrected": True,
                "correction_id": correction.correction_id,
            }

    rows = [row for event_id, row in by_id.items() if event_id not in deleted]
    rows.sort(key=lambda r: r.get("t_seconds") or 0.0)
    return rows


def apply_track_corrections(tracks, corrections) -> list[dict]:
    """Compose track-scoped corrections onto the tracks themselves.

    Without this the overlay keeps the old bumper label even though every event on the track
    was re-attributed -- the boxes read `team` from the track, not from events.
    """
    rows = {t.track_id: track_to_dict(t) for t in tracks}
    for correction in _sorted(corrections):
        if correction.scope != "track" or not correction.fields:
            continue
        try:
            track_id = int(correction.target_id)
        except (TypeError, ValueError):
            continue
        row = rows.get(track_id)
        if row is None:
            continue
        for key in ("team", "alliance", "team_confidence"):
            if key in correction.fields:
                row[key] = correction.fields[key]
    return list(rows.values())
