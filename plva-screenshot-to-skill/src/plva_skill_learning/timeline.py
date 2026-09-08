"""Stable evidence ordering and conservative display condensation."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .common import SkillforgeError, canonical, check_schema


def build_timeline(recording, window_size=24, overlap=4):
    if type(window_size) is not int or type(overlap) is not int or not 2 <= window_size <= 128 or not 0 <= overlap < window_size:
        raise SkillforgeError("invalid_window", "Window size must be 2–128, with smaller nonnegative overlap.")
    events = deepcopy(sorted(recording["events"], key=lambda event: event["sequence"]))
    hashes = {f["frame_id"]: f["sha256"] for f in recording["manifest"]["frames"]}
    observations = []
    previous = None
    for event in events:
        if event["type"] != "observation":
            # Any action, check, or recovery breaks a display duplicate run.
            previous = None
            continue
        metadata = {k: v for k, v in event.items() if k not in {"event_id", "sequence", "time_ms", "frame_id"}}
        fingerprint = (hashes[event["frame_id"]], canonical(metadata))
        if previous is not None and fingerprint == previous:
            observations[-1]["event_ids"].append(event["event_id"])
            if event["frame_id"] not in observations[-1]["frame_ids"]:
                observations[-1]["frame_ids"].append(event["frame_id"])
        else:
            observations.append({**event, "event_ids": [event["event_id"]], "frame_ids": [event["frame_id"]]})
        previous = fingerprint
    windows = []
    start = 0
    while start < len(events):
        windows.append(events[start:start + window_size])
        if start + window_size >= len(events):
            break
        start += window_size - overlap
    notices = list(recording.get("warnings", []))
    if len(windows) > 1:
        notices.append("Windows overlap by stable event IDs; transitions across gaps remain unknown.")
    return {"events": events, "observations": observations, "windows": windows, "warnings": notices}


def evidence_map(recording, workflow):
    events = {event["event_id"]: event for event in recording["events"]}
    frames = {frame["frame_id"] for frame in recording["manifest"]["frames"]}

    def link(target_id, refs, basis):
        if any(ref not in events for ref in refs):
            raise SkillforgeError("missing_reference", "A workflow evidence reference does not exist in the recording.")
        associated = set()
        # Follow explicit immediate evidence only; never invent a transition.
        for ref in refs:
            event = events[ref]
            if event["type"] == "observation":
                associated.add(event["frame_id"])
            for related in [event.get("before_event_id"), event.get("after_event_id"), *event.get("evidence_ids", [])]:
                other = events.get(related)
                if other and other["type"] == "observation":
                    associated.add(other["frame_id"])
        return {"target_id": target_id, "event_ids": list(dict.fromkeys(refs)), "frame_ids": sorted(associated), "basis": basis}

    links = []
    for step in workflow["steps"]:
        links.append(link(step["step_id"], step["evidence_ids"], step["basis"]))
    for check in workflow["checks"]:
        links.append(link(check["check_id"], check["evidence_ids"], check["basis"]))
    result = {"schema_version": "1.0", "recording_id": recording["manifest"]["recording_id"], "bundle_digest": recording["bundle_digest"], "data_class": recording["manifest"]["provenance"]["data_class"], "event_ids": list(events), "frame_ids": sorted(frames), "links": links, "outcome": deepcopy(recording["manifest"]["outcome"]), "local_recording_available": Path(recording["bundle_path"]).is_dir()}
    check_schema(result, "evidence-map")
    return result
