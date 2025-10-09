#!/usr/bin/env python3
# (script body identical to previous cell; see below)
import argparse
import sys
import yaml
import json
from collections import defaultdict, Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Set, Any

@dataclass(frozen=True)
class Event:
    kind: str
    entity_id: Optional[str]
    to: Optional[str]
    extra: Tuple[Tuple[str, Any], ...] = ()
    def label(self) -> str:
        base = f"{self.kind}"
        if self.entity_id:
            base += f"({self.entity_id}"
            if self.to is not None:
                base += f"→{self.to}"
            base += ")"
        if self.extra:
            base += f"[{dict(self.extra)}]"
        return base

@dataclass(frozen=True)
class Action:
    domain: str
    service: str
    entity_id: Optional[str]
    value: Optional[str] = None
    extra: Tuple[Tuple[str, Any], ...] = ()
    def label(self) -> str:
        base = f"{self.domain}.{self.service}"
        if self.entity_id:
            base += f"({self.entity_id}"
            if self.value is not None:
                base += f"={self.value}"
            base += ")"
        if self.extra:
            base += f"[{dict(self.extra)}]"
        return base

CONFLICT_CATALOG: Dict[Tuple[str, str], Set[Tuple[str, str]]] = {
    ("switch", "turn_on"):  {("switch", "turn_off")},
    ("switch", "turn_off"): {("switch", "turn_on")},
    ("light", "turn_on"):   {("light", "turn_off")},
    ("light", "turn_off"):  {("light", "turn_on")},
    ("lock", "lock"):       {("lock", "unlock")},
    ("lock", "unlock"):     {("lock", "lock")},
    ("cover", "open_cover"):  {("cover", "close_cover")},
    ("cover", "close_cover"): {("cover", "open_cover")},
    ("valve", "open_valve"):  {("valve", "close_valve")},
    ("valve", "close_valve"): {("valve", "open_valve")},
    ("media_player", "play"):  {("media_player", "stop"), ("media_player", "pause")},
    ("media_player", "stop"):  {("media_player", "play")},
    ("media_player", "mute"):  {("media_player", "unmute")},
    ("media_player", "unmute"):{("media_player", "mute")},
    ("climate", "set_hvac_mode:cool"): {("climate", "set_hvac_mode:heat")},
    ("climate", "set_hvac_mode:heat"): {("climate", "set_hvac_mode:cool")},
    ("homeassistant", "turn_on"): {("homeassistant", "turn_off")},
    ("homeassistant", "turn_off"): {("homeassistant", "turn_on")},
    ("cover", "open_cover"): {("cover", "close_cover")},
    ("cover", "close_cover"): {("cover", "open_cover")},
}

ACTION_STATE_EFFECTS: Dict[Tuple[str, str], str] = {
    ("switch", "turn_on"): "on",
    ("switch", "turn_off"): "off",
    ("light", "turn_on"): "on",
    ("light", "turn_off"): "off",
    ("lock", "lock"): "locked",
    ("lock", "unlock"): "unlocked",
    ("cover", "open_cover"): "open",
    ("cover", "close_cover"): "closed",
    ("valve", "open_valve"): "open",
    ("valve", "close_valve"): "closed",
    ("media_player", "play"): "playing",
    ("media_player", "stop"): "idle",
    ("media_player", "pause"): "paused",
    ("media_player", "mute"): "muted",
    ("media_player", "unmute"): "unmuted",
    ("climate", "set_hvac_mode"): "hvac_mode_changed",
}

def make_hashable(obj):
    if isinstance(obj, dict):
        return frozenset((k, make_hashable(v)) for k, v in obj.items())
    elif isinstance(obj, list):
        return tuple(make_hashable(x) for x in obj)
    elif isinstance(obj, set):
        return frozenset(make_hashable(x) for x in obj)
    elif isinstance(obj, tuple):
        return tuple(make_hashable(x) for x in obj)
    else:
        return obj

def _normalize_event(trigger: Dict[str, Any]) -> List['Event']:
    if trigger.get("platform") == "state" or trigger.get("type") == "state" or trigger.get("trigger") == "state":
        entity = trigger.get("entity_id")
        to = trigger.get("to")
        if isinstance(entity, list):
            return [Event(kind="state", entity_id=e, to=to,
                          extra=make_hashable(tuple(sorted({k:v for k,v in trigger.items()
                                    if k not in ("platform","entity_id","to","from")}.items())) )
                                                )
                    for e in entity]
        else:
            return [Event(kind="state", entity_id=entity, to=to,
                          extra=make_hashable( tuple(sorted({k:v for k,v in trigger.items()
                                                    if k not in ("platform","entity_id","to","from")}.items())) )
                                              )]
    kind = trigger.get("platform", "event")
    name = trigger.get("event_type")
    extra = dict(trigger)
    return [Event(kind=kind if not name else f"{kind}:{name}", entity_id=None, to=None,
                  extra=make_hashable( tuple(sorted(extra.items())) )                   )]

def _normalize_action(step: Dict[str, Any]) -> List['Action']:
    out: List[Action] = []
    if "service" in step or "action" in step:
        service = step.get("service") or step.get("action")
        if isinstance(service, str) and "." in service:
            domain, svc = service.split(".", 1)
        else:
            domain, svc = "unknown", str(service)
        entity = None
        if "entity_id" in step:
            entity = step["entity_id"]
        elif "target" in step and isinstance(step["target"], dict):
            entity = step["target"].get("entity_id")
        entities = entity if isinstance(entity, list) else [entity]
        for e in entities:
            value = None
            if (domain, svc) in ACTION_STATE_EFFECTS:
                value = ACTION_STATE_EFFECTS[(domain, svc)]
            elif domain == "climate" and svc == "set_hvac_mode":
                mode = step.get("data", {}).get("hvac_mode") or step.get("data_template", {}).get("hvac_mode")
                value = "cool" if mode == "cool" else ("heat" if mode == "heat" else "hvac_mode_changed")
            out.append(Action(domain=domain, service=svc, entity_id=e, value=value,
                              extra=tuple(sorted({k:make_hashable(v) for k,v in step.items()
                                                  if k not in ("service","entity_id","target","data","data_template")}.items()))))
    elif "choose" in step and isinstance(step["choose"], list):
        for choice in step["choose"]:
            for act in choice.get("sequence", []):
                out.extend(_normalize_action(act))
        if "default" in step:
            for act in step["default"]:
                out.extend(_normalize_action(act))
    elif "repeat" in step and isinstance(step["repeat"], dict):
        for act in step["repeat"].get("sequence", []):
            out.extend(_normalize_action(act))
    return make_hashable(out)

def parse_ha_automations(yaml_text: str) -> List[Dict[str, Any]]:
    docs = list(yaml.safe_load_all(yaml_text))
    automations: List[Dict[str, Any]] = []
    for doc in docs:
        if isinstance(doc, list):
            automations.extend(doc)
        elif isinstance(doc, dict) and "automation" in doc:
            automations.extend(doc["automation"])
        elif isinstance(doc, dict):
            automations.append(doc)
    return automations

class EFG:
    def __init__(self):
        from collections import defaultdict
        self.events: Set[Event] = set()
        self.actions: Set[Action] = set()
        self.id_map: Dict[Any, int] = {}
        self.rev_id_map: Dict[int, Any] = {}
        self.next_id = 0
        self.edges: Dict[int, Set[int]] = defaultdict(set)
    def _get_id(self, node: Any) -> int:
        if node not in self.id_map:
            idx = self.next_id
            self.id_map[node] = idx
            self.rev_id_map[idx] = node
            self.next_id += 1
        return self.id_map[node]
    def add_event(self, e: Event) -> int:
        self.events.add(e)
        return self._get_id(("E", e))
    def add_action(self, a: Action) -> int:
        self.actions.add(a)
        return self._get_id(("A", a))
    def add_edge(self, src: Any, dst: Any):   
        s = self._get_id(src)
        d = self._get_id(dst)
        self.edges[s].add(d)
    def nodes(self) -> List[int]:
        return list(self.rev_id_map.keys())
    def label(self, node_id: int) -> str:
        kind, obj = self.rev_id_map[node_id]
        prefix = "E:" if kind == "E" else "A:"
        return prefix + obj.label()

def build_efg(automations: List[Dict[str, Any]]) -> EFG:
    g = EFG()
    rules: List[Tuple[List[Event], List[Action], str]] = []
    for i, auto in enumerate(automations):
        name = str(auto.get("alias") or auto.get("id") or auto.get("description") or f"rule_{i}")
        triggers = auto.get("trigger") or auto.get("triggers") or []
        triggers = triggers if isinstance(triggers, list) else [triggers]
        events: List[Event] = []
        for t in triggers:
            events.extend(_normalize_event(t))
        steps = auto.get("action") or auto.get("sequence") or auto.get("actions") or []
        steps = steps if isinstance(steps, list) else [steps]
        actions: List[Action] = []
        for s in steps:
            actions.extend(_normalize_action(s))
        if not events or not actions:
            continue
        for a in actions:
            rules.append((events, [a], name))
    for evs, acts, _name in rules:
        for e in evs:
            for a in acts:
                g.add_edge(("E", e), ("A", a))
                g.add_event(e)
                g.add_action(a)
    all_events = list(g.events)
    for a in list(g.actions):
        resulting_state = a.value
        for e in all_events:
            if e.kind == "state" and e.entity_id and a.entity_id and e.entity_id == a.entity_id:
                if e.to is None or resulting_state is None or e.to == resulting_state:
                    g.add_edge(("A", a), ("E", e))
                # else:
                #     print(f"DEBUG: Action {a.label()}", file=sys.stderr)
                #     print(f"DEBUG: Event {e.label()}", file=sys.stderr)
                #     print(file=sys.stderr)
    return g

def tarjan_scc(nodes: List[int], edges: Dict[int, Set[int]]) -> List[List[int]]:
    index = 0
    indices: Dict[int, int] = {}
    lowlink: Dict[int, int] = {}
    stack: List[int] = []
    onstack: Set[int] = set()
    sccs: List[List[int]] = []
    def strongconnect(v: int):
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)
        for w in edges.get(v, set()):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            comp = []
            while True:
                w = stack.pop()
                onstack.remove(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)
    for v in nodes:
        if v not in indices:
            strongconnect(v)
    return sccs

def reachable_actions_from_event(g: EFG, start_event_id: int, path_limit: int = 6) -> Counter:
    counts: Counter = Counter()
    def dfs(node_id: int, depth: int, visited: List[int]):
        if depth > path_limit:
            return
        kind, _obj = g.rev_id_map[node_id]
        if kind == "A":
            counts[node_id] += 1
        for nxt in g.edges.get(node_id, set()):
            if nxt in visited:
                continue
            dfs(nxt, depth + 1, visited + [nxt])
    dfs(start_event_id, 0, [start_event_id])
    return counts

def _conflict_key(a: Action) -> Tuple[str, str]:
    if a.domain == "climate" and a.service == "set_hvac_mode":
        mode = a.value if a.value in ("cool","heat") else "other"
        return (a.domain, f"{a.service}:{mode}")
    return (a.domain, a.service)

def detect_redundancy(g: EFG) -> List[Dict[str, Any]]:
    issues = []
    for e in g.events:
        e_id = g._get_id(("E", e))
        multiset = reachable_actions_from_event(g, e_id, path_limit=6)
        for a_id, cnt in multiset.items():
            if cnt >= 2:
                issues.append({
                    "event": g.label(e_id),
                    "action": g.label(a_id),
                    "paths_count": int(cnt),
                    "issue": "Redundancy: action reachable more than once from event"
                })
    return issues

def detect_inconsistency(g: EFG) -> List[Dict[str, Any]]:
    issues = []
    for e in g.events:
        e_id = g._get_id(("E", e))
        multiset = reachable_actions_from_event(g, e_id, path_limit=6)
        actions = [g.rev_id_map[a_id][1] for a_id in multiset.keys()]
        by_entity: Dict[Optional[str], List[Action]] = defaultdict(list)
        for a in actions:
            by_entity[a.entity_id].append(a)
        for entity, acts in by_entity.items():
            n = len(acts)
            for i in range(n):
                for j in range(i+1, n):
                    a1, a2 = acts[i], acts[j]
                    k1, k2 = _conflict_key(a1), _conflict_key(a2)
                    if (k1 in CONFLICT_CATALOG and k2 in CONFLICT_CATALOG[k1]) or \
                       (k2 in CONFLICT_CATALOG and k1 in CONFLICT_CATALOG[k2]):
                        issues.append({
                            "event": g.label(e_id),
                            "action1": a1.label(),
                            "action2": a2.label(),
                            "entity": entity,
                            "issue": "Inconsistency: conflicting actions reachable from same event"
                        })
                    # else:
                    #     print(f"DEBUG: {a1}", file=sys.stderr)
                    #     print(f"DEBUG: {a2}", file=sys.stderr)
                    #     print(f"DEBUG: {k1}", file=sys.stderr)
                    #     print(f"DEBUG: {k2}", file=sys.stderr)
                    #     print(f"\n", file=sys.stderr)
    return issues

def detect_circularity(g: EFG) -> List[Dict[str, Any]]:
    issues = []
    sccs = tarjan_scc(g.nodes(), g.edges)
    for comp in sccs:
        if len(comp) > 1:
            labels = [g.label(n) for n in comp]
            issues.append({
                "cycle_nodes": " → ".join(labels),
                "size": len(comp),
                "issue": "Circularity: cycle in event flow graph"
            })
        else:
            v = comp[0]
            if v in g.edges and v in g.edges[v]:
                issues.append({
                    "cycle_nodes": g.label(v),
                    "size": 1,
                    "issue": "Circularity: self-loop"
                })
    return issues

def analyze_ha_automations(yaml_text: str) -> Dict[str, Any]:
    automations = parse_ha_automations(yaml_text)
    print (f"Parsed {len(automations)} automations", file=sys.stderr)

    g = build_efg(automations)
    print (f"EFG has {len(g.events)} events, {len(g.actions)} actions, {sum(len(v) for v in g.edges.values())} edges", file=sys.stderr) 
    redundancy = detect_redundancy(g)
    inconsistency = detect_inconsistency(g)
    circularity = detect_circularity(g)
    return {
        "summary": {
            "events": len(g.events),
            "actions": len(g.actions),
            "edges": sum(len(v) for v in g.edges.values()),
            "redundancy_issues": len(redundancy),
            "inconsistency_issues": len(inconsistency),
            "circularity_issues": len(circularity),
        },
        "redundancy": redundancy,
        "inconsistency": inconsistency,
        "circularity": circularity,
    }

def main(argv=None) -> int:
    import argparse, sys, json
    p = argparse.ArgumentParser(description="Analyze HA automations for ECA conflicts.")
    p.add_argument("--in", dest="infile", help="Path to automations.yaml (if omitted, read from stdin).")
    p.add_argument("--out", dest="outfile", help="Path to write JSON report (optional).")
    args = p.parse_args(argv)
    if args.infile:
        with open(args.infile, "r", encoding="utf-8") as f:
            yaml_text = f.read()
    else:
        yaml_text = sys.stdin.read()
    report = analyze_ha_automations(yaml_text)
    out_json = json.dumps(report, ensure_ascii=False, indent=2)
    if args.outfile:
        with open(args.outfile, "w", encoding="utf-8") as f:
            f.write(out_json)
    # print(out_json)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
