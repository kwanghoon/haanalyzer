# HA ECA Conflict Analyzer

A tool to analyze Home Assistant automations for structural issues using an Event–Action flow graph (EFG).

## Overview
- Parses one or more YAML documents containing automations.
- Builds an EFG connecting Events → Actions and Actions → compatible state Events.
- Detects three issue types: redundancy, inconsistency, and circularity.
- Emits a JSON report with a summary and detailed findings.

## CLI
- Command: `ha_eca_conflict_analyzer.py`
- Options:
  - `--in <path>`: Path to `automations.yaml` (reads from stdin if omitted).
  - `--out <path|stdout>`: Where to write the JSON report. Use `stdout` to print to console.

Examples:
```bash
# Read from file, write to another file
python3 ha_eca_conflict_analyzer.py --in automations.yaml --out report.json

# Read from stdin, write to file
cat automations.yaml | python3 ha_eca_conflict_analyzer.py --out report.json

# Read from file, print to stdout
python3 ha_eca_conflict_analyzer.py --in automations.yaml --out stdout
```

## Data Model
- Event: `kind`, `entity_id`, `to`, `extra`
- Action: `domain`, `service`, `entity_id`, `value`, `extra`

Notes:
- `Event.kind == "state"` for state triggers; other events use `platform[:event_type]`.
- `Action.value` reflects the state effect if known (e.g., `switch.turn_on → on`).
- `extra` stores normalized metadata as a hashable, sorted tuple of `(key, value)`.

## Key Functions
- `parse_ha_automations(yaml_text)`: Flattens YAML into a list of automation dicts.
- `build_efg(automations)`: Constructs the EFG with Events, Actions, and edges.
- `detect_redundancy(g)`: Finds actions reachable multiple times from the same event.
- `detect_inconsistency(g)`: Finds conflicting actions on the same entity from an event.
- `detect_circularity(g)`: Finds cycles (including self-loops) in the EFG.
- `analyze_ha_automations(yaml_text)`: Orchestrates parsing, graph build, detection, and returns a JSON-ready dict.

## Edge Construction Logic
- Event → Action: added for every normalized pair extracted from automations.
- Action → Event: added when the action’s `value` is compatible with a state event for the same `entity_id`.
  - Conditions: `event.kind == "state"`, same `entity_id`, and `(event.to is None) or (action.value is None) or (event.to == action.value)`.

## Output
- `summary`: counts of events, actions, edges, and issue totals.
- `redundancy`: list of events with actions reachable via multiple distinct paths.
- `inconsistency`: list of conflicting actions targeting the same entity.
- `circularity`: list of cycles detected in the graph.

## Generate HTML Docs (pydoc)
You can generate HTML documentation directly from docstrings using the standard library:
```bash
# From the workspace root
python3 -m pydoc -w ha_eca_conflict_analyzer
# This writes ha_eca_conflict_analyzer.html in the current directory
# Move it into doc/ if desired
mv ha_eca_conflict_analyzer.html doc/
```

## Development Notes
- Designed to be robust to typical Home Assistant automation structures.
- Uses deterministic normalization to ensure stable hashing and comparison of events/actions.
- Avoids raising exceptions for incomplete automations; skips when events or actions are missing.
