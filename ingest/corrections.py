"""The corrections layer.

Doc 0, three times over:

    "Corrections never overwrite model output."
    "events stores raw model output only."
    "Keeping both is the whole point: overwriting destroys the ability to measure whether
     the model is improving."

So corrections are stored as their own rows and composed onto raw events at read time.
`?raw=true` skips this entirely and returns what the model actually said, which is what the
accuracy comparison and the training-data export need.

If this module is ever bypassed and an event row is UPDATEd in place, the original
prediction is gone permanently -- there is no recovering it from the corrections table,
because a correction records the new value, not the old one.
"""

from .serializers import event_to_dict


def apply_corrections(events, corrections) -> list[dict]:
    """Compose corrections onto raw events. `events` are ORM rows, `corrections` ORM rows."""
    by_id: dict[str, dict] = {e.event_id: event_to_dict(e) for e in events}
    deleted: set[str] = set()

    # Oldest first, so a later correction to the same event wins.
    ordered = sorted(corrections, key=lambda c: (c.created_at is None, c.created_at))

    for correction in ordered:
        action = correction.action
        event_id = correction.event_id

        if action == "delete":
            deleted.add(event_id)
            continue

        if action == "create":
            fields = dict(correction.fields or {})
            fields["event_id"] = event_id
            fields.setdefault("schema_version", 1)
            fields.setdefault("source", "manual")
            by_id[event_id] = fields
            deleted.discard(event_id)
            continue

        if action == "edit":
            target = by_id.get(event_id)
            if target is None or not correction.fields:
                # An edit against an event that no longer exists is a no-op, not an error.
                continue
            by_id[event_id] = {**target, **correction.fields}

    rows = [row for event_id, row in by_id.items() if event_id not in deleted]
    rows.sort(key=lambda r: r.get("t_seconds") or 0.0)
    return rows
