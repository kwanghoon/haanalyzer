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
    """
    불변 이벤트를 나타내는 데이터 클래스.

    속성:
        kind: 이벤트 종류/범주(예: "state", "event").
        entity_id: 이벤트가 참조하는 엔티티 ID(예: "sensor.living_room"), 없을 수 있음.
        to: 목표 값/상태(예: 상태 트리거의 "to"), 없을 수 있음.
        extra: 추가 메타데이터 (키-값) 튜플의 튜플. 해시 가능 형태.
    """
    kind: str
    entity_id: Optional[str]
    to: Optional[str]
    extra: Tuple[Tuple[str, Any], ...] = ()

    def label(self) -> str:
        """
        사람이 읽기 쉬운 간결한 라벨을 반환합니다.

        형식:
        - 기본: kind
        - entity_id가 있으면 "(entity_id)"를 붙이고, to가 있으면 "(entity_id→to)"로 표기
        - extra가 있으면 "[{...}]"로 dict 렌더링하여 첨부

        반환:
            str: 예) "state(sensor.temp→25)[{'unit': '°C'}]"
        """
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
    """
    Home Assistant 서비스 호출을 나타내는 불변(해시 가능) 데이터 클래스.

    속성:
        domain: 통합 도메인 (예: "light", "switch").
        service: 도메인 내 서비스 이름 (예: "turn_on").
        entity_id: 대상 엔티티 ID (예: "light.kitchen"), 없을 수 있음.
        value: 엔티티에 연관된 값(예: 설정 값). 라벨에 표시될 수 있으며, 없을 수 있음.
        extra: 추가 파라미터 (키-값) 튜플의 튜플. 해시 가능 형태로 비교/라벨에 사용.

    참고:
        - dataclass를 frozen으로 설정하여 해시 가능하고 키로 안전하게 사용할 수 있게 합니다.
        - 라벨 생성 시 extra는 dict로 변환해 가독성을 높입니다.
    """
    domain: str
    service: str
    entity_id: Optional[str]
    value: Optional[str] = None
    extra: Tuple[Tuple[str, Any], ...] = ()

    def label(self) -> str:
        """
        액션의 간결하고 사람이 읽기 쉬운 라벨을 반환합니다.

        형식:
            "<domain>.<service>"
            선택적으로 "(<entity_id>)" 또는 "(<entity_id>=<value>)"를 뒤에 붙이고,
            extra 파라미터가 있으면 "[{...}]"로 dict 형태를 덧붙입니다.

        예시:
            "light.turn_on"
            "light.turn_on(light.kitchen)"
            "climate.set_temperature(climate.living_room=21)"
            "script.run()[{'speed': 'fast'}]"

        반환:
            str: 액션과 그 파라미터를 요약하는 고유 문자열.
        """
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
    """
    원시 트리거 딕셔너리를 하나 이상의 표준 Event 객체로 정규화합니다.

    이 함수는 "state" 유형 트리거와 일반 이벤트 트리거를 해석하여
    비교나 중복 제거에 적합한 안정적이고 해시 가능한 표현을 생성합니다.

    동작:
    - 상태(state) 트리거 (trigger["platform"] == "state" 또는 trigger["type"] == "state" 또는 trigger["trigger"] == "state"):
        - "entity_id"가 리스트인 경우 각 엔티티마다 하나의 Event를 생성하고, 아니면 단일 Event를 생성합니다.
        - Event.kind 는 "state" 입니다.
        - Event.entity_id 는 트리거의 "entity_id" 입니다.
        - Event.to 는 트리거의 "to" 값입니다.
        - Event.extra 는 트리거에서 "platform", "entity_id", "to", "from" 을 제외한 키-값을
          정렬된 튜플로 만들고, 이후 해시 가능하게 변환하여 저장합니다.

    - 비-상태 트리거:
        - "event_type" 이 있으면 Event.kind 는 "platform:event_type", 없으면 "platform" (없을 경우 "event" 기본값) 입니다.
        - Event.entity_id 와 Event.to 는 None 입니다.
        - Event.extra 는 트리거 전체 키-값을 정렬된 튜플로 만들고, 해시 가능하게 변환하여 저장합니다.

    인자:
        trigger: 트리거를 설명하는 딕셔너리. 일반적인 키:
            - "platform": 트리거 플랫폼 (예: "state", "event").
            - "type" 또는 "trigger": "state" 트리거의 대체 표시.
            - "entity_id": 단일 또는 리스트 엔티티 ID (state 트리거).
            - "to": 목표 상태 (state 트리거).
            - "from": 이전 상태 (정규화 extra에서는 제외).
            - "event_type": 이벤트 이름 (event 트리거).
            - 기타 키는 필요 시 Event.extra에 포함됩니다.

    반환값:
        정규화된 Event 객체 리스트. state 트리거에서 entity_id가 리스트면 다수, 아니면 단일 요소 리스트.

    참고:
        - Event.extra 는 (키, 값) 정렬 튜플을 기반으로 해시 가능하게 만들어
          의미적으로 동일한 트리거에 대해 결정적 해시/동등성을 제공합니다.
    """
    # state 계열 트리거 판별
    if trigger.get("platform") == "state" or trigger.get("type") == "state" or trigger.get("trigger") == "state":
        entity = trigger.get("entity_id")
        to = trigger.get("to")
        # entity_id가 리스트인 경우 개별 Event 생성
        if isinstance(entity, list):
            return [Event(
                        kind="state",
                        entity_id=e,
                        to=to,
                        # 정규화 시 불필요한 키 제외 후 정렬/해시 가능 변환
                        extra=make_hashable(tuple(sorted({
                            k: v for k, v in trigger.items()
                            if k not in ("platform", "entity_id", "to", "from")
                        }.items())))
                    )
                    for e in entity]
        # 단일 entity_id 처리
        else:
            return [Event(
                kind="state",
                entity_id=entity,
                to=to,
                extra=make_hashable(tuple(sorted({
                    k: v for k, v in trigger.items()
                    if k not in ("platform", "entity_id", "to", "from")
                }.items())))
            )]
    # 비-상태 트리거 처리
    kind = trigger.get("platform", "event")
    name = trigger.get("event_type")
    extra = dict(trigger)
    return [Event(
        kind=kind if not name else f"{kind}:{name}",
        entity_id=None,
        to=None,
        # 전체 트리거를 정렬 후 해시 가능 변환
        extra=make_hashable(tuple(sorted(extra.items())))
    )]

def _normalize_action(step: Dict[str, Any]) -> List['Action']:
    """
    Home Assistant 자동화/스크립트의 단일 스텝을 평탄화된 Action 객체 목록으로 정규화합니다.

        데이터 모델:
        - Action: domain, service, entity_id, value, extra

    동작:
    - domain, service: "service" 또는 "action" 스텝을 파싱하여 "domain.service"에서 
      (domain, service)를 추출하고, 도메인이 없으면 "unknown" 사용.
    - entity_id: "entity_id" 또는 "target.entity_id"로 대상 엔티티를 해석(단일/리스트 모두 지원).
    - value: ACTION_STATE_EFFECTS를 사용해 Action.value를 추정. climate.set_hvac_mode는
      hvac_mode가 "cool"/"heat"이면 해당 값, 아니면 "hvac_mode_changed"로 처리.
    - extra: 부가 메타데이터는 Action.extra에 (키, 값) 정렬 튜플로 저장하되
      "service","entity_id","target","data","data_template"는 제외. 값은 make_hashable 적용.
    - 분기/반복 구조("choose"의 각 시퀀스와 "default", "repeat.sequence")를 재귀적으로 평탄화.

    비-서비스 스텝은 액션을 생성하지 않습니다.

    매개변수:
        step: 단일 자동화/스크립트 스텝 딕셔너리.

    반환값:
        Tuple[Action, ...]: 스텝 및 중첩 시퀀스에서 발견된 모든 원자적 서비스 호출을 나타내는
        해시 가능한 Action 시퀀스.
    """
    out: List[Action] = []
    if "service" in step or "action" in step:
        # 서비스 문자열 추출 및 (domain, service) 분리
        service = step.get("service") or step.get("action")
        if isinstance(service, str) and "." in service:
            domain, svc = service.split(".", 1)
        else:
            domain, svc = "unknown", str(service)

        # 대상 엔티티(entity_id 또는 target.entity_id) 추출
        entity = None
        if "entity_id" in step:
            entity = step["entity_id"]
        elif "target" in step and isinstance(step["target"], dict):
            entity = step["target"].get("entity_id")

        # 단일/리스트 모두 순회할 수 있도록 리스트로 정규화
        entities = entity if isinstance(entity, list) else [entity]

        for e in entities:
            # 액션이 유도하는 상태 값 추정
            value = None
            if (domain, svc) in ACTION_STATE_EFFECTS:
                value = ACTION_STATE_EFFECTS[(domain, svc)]
            elif domain == "climate" and svc == "set_hvac_mode":
                mode = step.get("data", {}).get("hvac_mode") or step.get("data_template", {}).get("hvac_mode")
                value = "cool" if mode == "cool" else ("heat" if mode == "heat" else "hvac_mode_changed")

            # 부가 메타데이터(extra) 구성: 제외 키를 빼고 정렬/해시 가능 변환
            extra = tuple(sorted({
                k: make_hashable(v)
                for k, v in step.items()
                if k not in ("service", "entity_id", "target", "data", "data_template")
            }.items()))

            out.append(Action(domain=domain, service=svc, entity_id=e, value=value, extra=extra))

    elif "choose" in step and isinstance(step["choose"], list):
        # 분기(choose) 각 선택지의 sequence 평탄화
        for choice in step["choose"]:
            for act in choice.get("sequence", []):
                out.extend(_normalize_action(act))
        # default 블록 처리
        if "default" in step:
            for act in step["default"]:
                out.extend(_normalize_action(act))

    elif "repeat" in step and isinstance(step["repeat"], dict):
        # 반복(repeat) 내부 sequence 평탄화
        for act in step["repeat"].get("sequence", []):
            out.extend(_normalize_action(act))

    # 호출 측에서 extend 가능하도록 해시 가능한 시퀀스로 반환
    return make_hashable(out)

def parse_ha_automations(yaml_text: str) -> List[Dict[str, Any]]:
    """
    Home Assistant 자동화 YAML을 평탄화된 자동화 딕셔너리 목록으로 파싱합니다.

    이 함수는 '---'로 구분된 하나 이상의 YAML 문서를 읽고,
    일반적인 Home Assistant 자동화 레이아웃을 정규화합니다:
      - 자동화 딕셔너리 리스트
      - "automation" 키가 있는 매핑(값은 딕셔너리 리스트)
      - 단일 자동화 딕셔너리

    매개변수:
        yaml_text (str): 하나 이상의 자동화 문서를 포함한 YAML 문자열.

    반환값:
        List[Dict[str, Any]]: 입력 순서를 유지한 자동화 딕셔너리 목록.

    예외:
        yaml.YAMLError: YAML이 잘못되어 파싱할 수 없는 경우.
    """
    docs = list(yaml.safe_load_all(yaml_text))
    automations: List[Dict[str, Any]] = []
    for doc in docs:
        # 리스트 형태: 각 항목을 자동화로 간주하여 추가
        if isinstance(doc, list):
            automations.extend(doc)
        # 매핑 형태: "automation" 키 아래의 리스트를 추가
        elif isinstance(doc, dict) and "automation" in doc:
            automations.extend(doc["automation"])
        # 단일 딕셔너리 형태: 하나의 자동화로 추가
        elif isinstance(doc, dict):
            automations.append(doc)
        # 기타/None: 무시
    return automations

class EFG:
    """
    간단한 이벤트-플로우 그래프(Event-Flow Graph, EFG).

    기능:
    - 노드를 ("E", event) 또는 ("A", action) 2-튜플로 구분하여 관리합니다.
    - 각 노드에 안정적인 정수 ID를 부여하고, ID 기반 인접 리스트로 간선을 저장합니다.
    - Event, Action 객체는 label() -> str 메서드를 구현해야 합니다.

    속성:
    - events: 그래프에 추가된 Event 객체 집합.
    - actions: 그래프에 추가된 Action 객체 집합.
    - id_map: 노드 키(예: ("E", event))를 정수 ID로 매핑.
    - rev_id_map: 정수 ID를 노드 키로 역매핑.
    - next_id: 다음에 할당할 정수 ID.
    - edges: 인접 리스트(노드 ID -> 후속 노드 ID 집합).
    """
    def __init__(self):
        """
        빈 EFG를 초기화하고 ID 매핑/인접 리스트 구조를 생성합니다.
        """
        from collections import defaultdict
        self.events: Set[Event] = set()
        self.actions: Set[Action] = set()
        self.id_map: Dict[Any, int] = {}
        self.rev_id_map: Dict[int, Any] = {}
        self.next_id = 0
        self.edges: Dict[int, Set[int]] = defaultdict(set)

    def _get_id(self, node: Any) -> int:
        """
        노드 키에 대한 고유 정수 ID를 반환합니다. 없으면 새로 생성합니다.

        매개변수:
        - node: ("E", event) 또는 ("A", action) 형태의 노드 키.

        반환값:
        - int: 해당 노드 키에 할당된 정수 ID.
        """
        if node not in self.id_map:
            idx = self.next_id
            self.id_map[node] = idx
            self.rev_id_map[idx] = node
            self.next_id += 1
        return self.id_map[node]

    def add_event(self, e: Event) -> int:
        """
        이벤트 노드를 그래프에 추가하고 그 ID를 반환합니다.

        매개변수:
        - e: Event 객체 (label() 메서드 필요)

        반환값:
        - int: 추가된 이벤트 노드의 정수 ID.
        """
        self.events.add(e)
        return self._get_id(("E", e))

    def add_action(self, a: Action) -> int:
        """
        액션 노드를 그래프에 추가하고 그 ID를 반환합니다.

        매개변수:
        - a: Action 객체 (label() 메서드 필요)

        반환값:
        - int: 추가된 액션 노드의 정수 ID.
        """
        self.actions.add(a)
        return self._get_id(("A", a))

    def add_edge(self, src: Any, dst: Any):
        """
        방향 간선(src -> dst)을 추가합니다.

        매개변수:
        - src: 소스 노드 키 (("E", event) 또는 ("A", action))
        - dst: 목적 노드 키 (("E", event) 또는 ("A", action))

        비고:
        - 내부적으로 노드 키를 정수 ID로 변환하여 저장합니다.
        """
        s = self._get_id(src)
        d = self._get_id(dst)
        self.edges[s].add(d)

    def nodes(self) -> List[int]:
        """
        그래프에 존재하는 모든 노드 ID 목록을 반환합니다.
        """
        return list(self.rev_id_map.keys())

    def label(self, node_id: int) -> str:
        """
        주어진 노드 ID의 사람이 읽기 쉬운 라벨을 반환합니다.

        매개변수:
        - node_id: 노드의 정수 ID

        반환값:
        - str: 이벤트는 "E:<event_label>", 액션은 "A:<action_label>" 형식.
        """
        kind, obj = self.rev_id_map[node_id]
        prefix = "E:" if kind == "E" else "A:"
        return prefix + obj.label()

def build_efg(automations: List[Dict[str, Any]]) -> EFG:
    """
    평탄화된 자동화 목록으로부터 이벤트-플로우 그래프(EFG)를 구성합니다.

    각 자동화에서 트리거/이벤트와 액션/스텝을 추출하여 Event, Action으로 정규화한 뒤
    다음과 같은 방향 그래프를 생성합니다:

    - 모든 이벤트-액션 쌍에 대해 이벤트 노드에서 액션 노드로 간선을 추가합니다.
    - 각 액션이 만들어내는 상태가 동일 엔티티의 상태 이벤트와 호환되면
      액션 노드에서 해당 상태 이벤트 노드로 간선을 추가합니다
      (event.kind == "state", entity_id 일치, 그리고 event.to가 None이거나
       action.value가 None이거나 event.to == action.value).

    유효한 이벤트나 액션이 없는 자동화는 건너뜁니다.
    다중 액션 자동화는 동일한 이벤트 집합을 공유하는 액션별 규칙으로 분할합니다.

    매개변수:
        automations: 자동화 딕셔너리 목록. 각 항목에는 다음이 포함될 수 있습니다:
            - "alias", "id", "description"(선택): 규칙 이름으로 사용.
            - "trigger"/"triggers": 트리거(하나 또는 목록); Event로 정규화.
            - "action"/"sequence"/"actions": 액션(하나 또는 목록); Action으로 정규화.

    반환값:
        EFG: 이벤트 → 액션 및 액션 → 상태 이벤트 간선이 포함된 그래프.

    참고:
        - _normalize_event, _normalize_action 헬퍼를 사용해 입력을 파싱합니다.
        - 그래프 구성은 EFG.add_edge, EFG.add_event, EFG.add_action을 사용합니다.
        - 의도적으로 예외를 발생시키지 않으며, 불완전한 자동화는 무시됩니다.
    
    사용 함수:
        - _normalize_event(trigger): 단일 트리거 딕셔너리를 Event 목록으로 변환합니다.
        - _normalize_action(step): 단일 액션 딕셔너리를 Action 목록으로 변환합니다.
    """
    g = EFG()  # 그래프 초기화
    rules: List[Tuple[List[Event], List[Action], str]] = []

    # 자동화별로 이벤트/액션을 정규화하고 규칙 목록 구성
    for i, auto in enumerate(automations):
        name = str(auto.get("alias") or auto.get("id") or auto.get("description") or f"rule_{i}")

        # 트리거(이벤트) 수집 및 정규화
        triggers = auto.get("trigger") or auto.get("triggers") or []
        triggers = triggers if isinstance(triggers, list) else [triggers]
        events: List[Event] = []
        for t in triggers:
            events.extend(_normalize_event(t))

        # 액션(스텝) 수집 및 정규화
        steps = auto.get("action") or auto.get("sequence") or auto.get("actions") or []
        steps = steps if isinstance(steps, list) else [steps]
        actions: List[Action] = []
        for s in steps:
            actions.extend(_normalize_action(s))

        # 유효한 이벤트/액션이 없으면 건너뜀
        if not events or not actions:
            continue

        # 다중 액션을 액션별 규칙으로 분할
        for a in actions:
            rules.append((events, [a], name))

    # 이벤트 → 액션 간선 추가 및 노드 등록
    for evs, acts, _name in rules:
        for e in evs:
            for a in acts:
                g.add_edge(("E", e), ("A", a))
                g.add_event(e)
                g.add_action(a)

    # 액션 → 이벤트 간선 추가 (액션이 유도하는 상태와 호환되는 상태 이벤트로 연결)
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
    """
    Tarjan의 알고리즘으로 방향 그래프의 강연결요소(SCC)를 계산합니다.

    이 구현은 깊이 우선 탐색(DFS)을 수행하며 각 정점에 index와 lowlink 값을 부여합니다.
    서로 상호 도달 가능한(사이클을 이루는) 정점들은 동일한 SCC로 묶입니다.

    매개변수:
        nodes: 탐색을 시작할 정점 ID 목록. 이들로부터 간선을 따라 도달 가능한 정점은
            `nodes`에 없어도 발견되어 SCC에 포함됩니다.
        edges: 각 정점에서 나가는 간선의 인접 리스트(정점 -> 후속 정점 집합).
            키로 존재하지 않는 정점은 나가는 간선이 없는 것으로 간주합니다.

    반환값:
        SCC들의 목록. 각 SCC는 정점 ID들의 리스트로 표현됩니다.

    참고:
        - 시간 복잡도는 O(V + E)입니다. 여기서 V는 발견된 정점 수, E는 발견된 간선 수입니다.
        - 파이썬의 set 순회 특성상 SCC들의 순서 및 SCC 내 정점들의 순서는 결정적이지 않을 수 있습니다.
        - 매우 깊은 그래프에서는 재귀 한도를 조정해야 할 수 있습니다(예: sys.setrecursionlimit).
        - `nodes`로부터 도달 불가능한 정점은 결과에 포함되지 않습니다.

    예시:
        nodes = [1, 2, 3, 4]
        edges = {1: {2}, 2: {3, 4}, 3: {1}, 4: set()}
        가능한 결과:
            [[3, 2, 1], [4]]
        정확한 순서는 달라질 수 있습니다.
    """
    index = 0
    indices: Dict[int, int] = {}   # 각 정점의 DFS 방문 순서(index)
    lowlink: Dict[int, int] = {}   # 각 정점에서 역방향/트리 간선을 통해 도달 가능한 최소 index
    stack: List[int] = []          # 현재 DFS 스택
    onstack: Set[int] = set()      # 스택 포함 여부 추적
    sccs: List[List[int]] = []     # 결과 SCC 목록

    def strongconnect(v: int):
        # v 초기화: index/lowlink 설정, 스택 푸시
        nonlocal index
        indices[v] = index
        lowlink[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)

        # v의 모든 후속 정점 w에 대해 처리
        for w in edges.get(v, set()):
            if w not in indices:
                # 트리 간선: 아직 방문하지 않은 w를 재귀 탐색
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                # 후방 간선: 스택에 있는 w를 통해 갱신
                lowlink[v] = min(lowlink[v], indices[w])

        # v가 SCC의 루트인지 판정
        if lowlink[v] == indices[v]:
            comp: List[int] = []
            # 스택에서 v까지 팝하여 하나의 SCC 구성
            while True:
                w = stack.pop()
                onstack.remove(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(comp)

    # 주어진 시작 정점들로부터 탐색 수행
    for v in nodes:
        if v not in indices:
            strongconnect(v)

    return sccs

def reachable_actions_from_event(g: EFG, start_event_id: int, path_limit: int = 6) -> Counter:
    """
    EFG(Event Flow Graph)에서 특정 시작 이벤트 노드(start_event_id)로부터 도달 가능한
    액션 노드 ID들을, 각 액션에 도달하는 서로 다른 단순 경로 수(깊이 제한 내)로
    계수한 Counter를 반환합니다.

    동작:
    - 시작 노드에서 깊이 제한 DFS를 수행합니다.
    - 방문한 노드가 액션(kind가 "A")이면 해당 노드 ID를 카운트합니다.
    - g.edges를 따라 후속 노드로 진행하며, 현재 경로(visited)에 이미 포함된 노드는
      재방문하지 않아 순환을 방지합니다.
    - depth > path_limit가 되면 더 이상 하위로 확장하지 않습니다.
    - start_event_id가 액션을 가리키는 경우 깊이 0에서 카운트됩니다.

    매개변수:
    - g: EFG 인스턴스. 다음을 제공합니다:
        - edges: Dict[int, Set[int]] — 노드 ID에서 후속 노드 ID 집합으로의 맵.
        - rev_id_map: Dict[int, Tuple[str, Any]] — 노드 ID에서 (kind, obj)로의 역 매핑.
    - start_event_id: 탐색 시작 노드 ID(일반적으로 이벤트).
    - path_limit: 시작점으로부터 탐색할 최대 간선 수(기본값: 6).

    반환값:
    - Counter: 액션 노드 ID를 키로 하고, 시작 노드로부터 깊이 제한 내에
      도달 가능한 서로 다른 단순 경로 수를 값으로 갖는 카운터.

    참고:
    - 그래프가 조밀하거나 연결성이 높은 경우, path_limit에 따라 단순 경로 수가
      지수적으로 증가할 수 있습니다.
    """
    counts: Counter = Counter()

    def dfs(node_id: int, depth: int, visited: List[int]):
        # 깊이 한도 초과 시 중단
        if depth > path_limit:
            return
        kind, _obj = g.rev_id_map[node_id]
        # 액션 노드면 카운트 증가
        if kind == "A":
            counts[node_id] += 1
        # 인접 노드 순회(현재 경로의 노드는 재방문하지 않음)
        for nxt in g.edges.get(node_id, set()):
            if nxt in visited:
                continue
            dfs(nxt, depth + 1, visited + [nxt])

    # DFS 시작
    dfs(start_event_id, 0, [start_event_id])
    return counts

def _conflict_key(a: Action) -> Tuple[str, str]:
    """
    Action에 대한 정규화된 충돌 키(conflict key)를 반환합니다.

    대부분의 액션은 (domain, service) 쌍을 키로 사용합니다. 다만 climate의
    `set_hvac_mode`를 호출하는 경우에는 HVAC 모드를 포함해 구체화하며,
    "cool"과 "heat"만 구분하고 그 외 모드는 "other"로 묶습니다.
    이 정규화는 유사한 액션을 충돌 분석에서 통합하는 데 도움이 됩니다.

    매개변수:
        a (Action): 충돌 키를 추출할 액션.

    반환값:
        Tuple[str, str]: 일반 액션은 (domain, service),
        climate HVAC 모드 액션은 (domain, "set_hvac_mode:<mode>") 형태.
        <mode>는 "cool", "heat", 또는 "other" 입니다.

    예시:
        - climate `set_hvac_mode` 값이 "cool" -> ("climate", "set_hvac_mode:cool")
        - climate `set_hvac_mode` 값이 "auto" -> ("climate", "set_hvac_mode:other")
        - light `turn_on` -> ("light", "turn_on")
    """
    if a.domain == "climate" and a.service == "set_hvac_mode":
        mode = a.value if a.value in ("cool", "heat") else "other"
        return (a.domain, f"{a.service}:{mode}")
    return (a.domain, a.service)

def detect_redundancy(g: EFG) -> List[Dict[str, Any]]:
    """
    이벤트-플로우 그래프(EFG)에서 동일 이벤트로부터 여러 경로로 도달 가능한
    액션을 찾아 중복(redundancy)을 탐지합니다.

    동작:
        - 그래프의 각 이벤트에 대해, 해당 이벤트로부터 도달 가능한 액션의 멀티셋을
          계산합니다(경로 길이 최대 6으로 제한).
        - 동일 액션이 서로 다른 경로로 2회 이상 도달 가능하면 이슈로 기록합니다.

    매개변수:
        g (EFG): Event-Flow Graph 인스턴스. 다음을 제공합니다:
            - events: 이벤트 객체들의 집합/반복자
            - _get_id(tuple): ("E", event) 튜플에 대한 노드 ID 반환
            - label(node_id): 노드 ID의 사람이 읽기 쉬운 라벨 반환
            - reachable_actions_from_event(g, e_id, path_limit)과의 호환성

    반환값:
        List[Dict[str, Any]]: 이슈 딕셔너리 목록. 각 항목은 다음 키를 포함합니다:
            - "event": str — 시작 이벤트 라벨
            - "action": str — 중복으로 도달 가능한 액션 라벨
            - "paths_count": int — 이벤트로부터 액션까지의 서로 다른 경로 수(>= 2)
            - "issue": str — 설명 메시지

    참고:
        - 경로 탐색은 path_limit=6으로 제한됩니다.
        - 단일 이벤트로부터 동일 액션이 여러 경로로 유발될 수 있는 설계 문제를
          식별하는 데 유용합니다.

    사용 함수:
        - reachable_actions_from_event(g, e_id, path_limit): 이벤트로부터 도달 가능한 액션의 멀티셋을 계산
    """
    issues = []
    # 모든 이벤트에 대해 중복 도달 여부 검사
    for e in g.events:
        e_id = g._get_id(("E", e))
        # 이벤트로부터 도달 가능한 액션의 멀티셋(경로 수) 계산
        multiset = reachable_actions_from_event(g, e_id, path_limit=6)
        # 경로 수가 2 이상인 액션을 이슈로 기록
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
    """
    EFG(이벤트-플로우 그래프)에서 동일한 이벤트로부터 도달 가능한 상충(충돌) 액션 쌍을 탐지합니다.

    동작:
    - 각 이벤트에 대해 시작 이벤트로부터 제한된 깊이(path_limit=6)까지 도달 가능한 액션 집합을 계산합니다.
    - 액션을 대상 엔티티(Action.entity_id)별로 그룹화합니다.
    - 각 엔티티 그룹 내 모든 액션 쌍에 대해 _conflict_key(...)와 CONFLICT_CATALOG를 사용해 충돌 여부를 검사합니다.
    - 충돌로 판단되면 이슈 레코드를 생성합니다.

    매개변수:
    - g (EFG): 그래프 객체. 다음을 제공합니다:
        - events: 이벤트 반복자
        - _get_id(tuple): ("E", event) 튜플을 내부 노드 ID로 해석
        - rev_id_map: 내부 ID를 (kind, obj)로 역매핑; rev_id_map[action_id][1]는 Action
        - label(node_id): 사람이 읽기 쉬운 라벨 반환
        - reachable_actions_from_event(...)과의 호환성

    반환값:
    - List[Dict[str, Any]]: 각 이슈 딕셔너리에는 다음 키가 포함됩니다:
        - "event": 시작 이벤트 라벨
        - "action1": 첫 번째 상충 액션 라벨
        - "action2": 두 번째 상충 액션 라벨
        - "entity": 두 액션이 공유하는 entity_id (None 가능)
        - "issue": 고정 설명 문구

    참고:
    - 도달 가능성 탐색은 path_limit=6으로 제한됩니다.
    - 충돌 판정은 대칭적입니다(A가 B와 충돌하거나 B가 A와 충돌하면 보고).
    - 동일 entity_id를 공유하는 액션만 비교합니다.
    - CONFLICT_CATALOG에 없으면 이슈가 보고되지 않습니다.

    복잡도:
    - 이벤트별로 엔티티 그룹 내 액션 쌍 검사 비용은 O(k^2)입니다.

    사용 함수 및 데이터:
        - reachable_actions_from_event(g, e_id, path_limit): 이벤트로부터 도달 가능한 액션 멀티셋 계산
        - _conflict_key(a): 액션의 충돌 키 생성
        - CONFLICT_CATALOG: 충돌 액션 쌍 사전
    """
    issues = []
    for e in g.events:
        e_id = g._get_id(("E", e))
        # 시작 이벤트로부터 도달 가능한 액션 멀티셋(경로 수 포함) 계산
        multiset = reachable_actions_from_event(g, e_id, path_limit=6)
        actions = [g.rev_id_map[a_id][1] for a_id in multiset.keys()]

        # 액션을 대상 엔티티별로 그룹화
        by_entity: Dict[Optional[str], List[Action]] = defaultdict(list)
        for a in actions:
            by_entity[a.entity_id].append(a)

        # 각 엔티티 그룹 내 모든 액션 쌍에 대해 충돌 여부 검사
        for entity, acts in by_entity.items():
            n = len(acts)
            for i in range(n):
                for j in range(i + 1, n):
                    a1, a2 = acts[i], acts[j]
                    k1, k2 = _conflict_key(a1), _conflict_key(a2)
                    if (k1 in CONFLICT_CATALOG and k2 in CONFLICT_CATALOG[k1]) or \
                       (k2 in CONFLICT_CATALOG and k1 in CONFLICT_CATALOG[k2]):
                        # 충돌로 판단되면 이슈 레코드 추가
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
    """
    이벤트 플로우 그래프에서 순환(사이클 및 자기 루프)을 탐지합니다.

    이 함수는 Tarjan의 SCC(강연결요소) 알고리즘을 사용하여 사이클을 식별합니다.
    노드가 2개 이상인 SCC는 사이클로 보고하며, 단일 노드 SCC는 해당 노드에
    자기 루프(자기 자신으로의 에지)가 있을 때만 순환으로 보고합니다.

    매개변수:
        g (EFG): 다음을 제공하는 이벤트 플로우 그래프:
            - nodes(): 그래프 노드들의 반복자
            - edges: 노드 -> 후속 노드 집합으로의 인접 리스트
            - label(node): 노드의 사람이 읽기 쉬운 라벨을 반환하는 함수

    반환값:
        List[Dict[str, Any]]: 이슈 딕셔너리 목록. 각 항목은 다음 키를 포함합니다:
            - "cycle_nodes" (str): 사이클을 이루는 노드 라벨들의 순서를 " → "로 연결한 문자열.
              자기 루프인 경우 단일 노드 라벨.
            - "size" (int): 사이클을 이루는 노드 수(자기 루프는 1).
            - "issue" (str): "Circularity: cycle in event flow graph" 또는
              "Circularity: self-loop" 설명 문구.

    참고:
        - "cycle_nodes"의 라벨 순서는 SCC 순회 결과이며, 유일한 사이클 순서를 의미하지 않을 수 있습니다.
        - 사이클이나 자기 루프가 없으면 빈 리스트를 반환합니다.
        - 시간 복잡도는 Tarjan SCC 알고리즘에 따라 O(|V| + |E|)입니다.

    예시:
        반환 구조:
        [
            {
                "cycle_nodes": "Init → Process → Finish",
                "size": 3,
            },
            {
                "cycle_nodes": "Retry",
            }
        ]

    사용 함수:
        - tarjan_scc(nodes, edges): 그래프의 강연결요소를 계산하는 함수.
    """
    issues = []
    # Tarjan SCC로 강연결요소 계산
    sccs = tarjan_scc(g.nodes(), g.edges)
    for comp in sccs:
        if len(comp) > 1:
            # 노드가 2개 이상이면 사이클로 판단
            labels = [g.label(n) for n in comp]
            issues.append({
                "cycle_nodes": " → ".join(labels),
                "size": len(comp),
                "issue": "Circularity: cycle in event flow graph"
            })
        else:
            # 단일 노드인 경우 자기 루프가 있을 때만 보고
            v = comp[0]
            if v in g.edges and v in g.edges[v]:
                issues.append({
                    "cycle_nodes": g.label(v),
                    "size": 1,
                    "issue": "Circularity: self-loop"
                })
    return issues

def analyze_ha_automations(yaml_text: str) -> Dict[str, Any]:
    """
    Home Assistant 자동화 YAML을 분석하여 구조적 지표와 이슈를 보고합니다.

    기능:
        - YAML에서 자동화를 파싱하고 EFG(Event–Function Graph)를 구성합니다.
        - 중복(redundancy), 불일치(inconsistency), 순환(circularity) 이슈를 탐지합니다.
        - 요약 및 상세 결과를 반환합니다.

    매개변수:
        yaml_text (str): Home Assistant 자동화 정의가 포함된 YAML 텍스트.

    반환값:
        Dict[str, Any]: 다음 키를 포함하는 딕셔너리:
            - summary (dict): 이벤트, 액션, 에지 수와 각 이슈 개수 요약.
            - redundancy (list): 중복 이슈 목록.
            - inconsistency (list): 불일치 이슈 목록.
            - circularity (list): 순환 이슈 목록.

    부수효과:
        처리 진행 상황(파싱된 자동화 개수, EFG 크기)을 stderr로 출력합니다.

    예외:
        YAML 파싱 실패 시 yaml.YAMLError 등 하위 예외가 발생할 수 있습니다.

    사용 함수:
        - parse_ha_automations(yaml_text): YAML에서 자동화 항목을 파싱합니다.
        - build_efg(automations): EFG를 구성합니다.
        - detect_redundancy(g): 중복 이슈를 탐지합니다.
        - detect_inconsistency(g): 불일치 이슈를 탐지합니다.
        - detect_circularity(g): 순환 이슈를 탐지합니다.
    """
    # YAML에서 자동화 항목 파싱
    automations = parse_ha_automations(yaml_text)
    print(f"Parsed {len(automations)} automations", file=sys.stderr)

    # EFG 구성
    g = build_efg(automations)
    print(
        (
            f"EFG has {len(g.events)} events, "
            f"{len(g.actions)} actions, "
            f"{sum(len(v) for v in g.edges.values())} edges"
        ),
        file=sys.stderr
    )

    # 이슈 탐지: 중복, 불일치, 순환
    redundancy = detect_redundancy(g)
    inconsistency = detect_inconsistency(g)
    circularity = detect_circularity(g)

    # 결과 요약과 상세 목록 반환
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
    """
    명령줄 진입점으로 Home Assistant 자동화를 분석하여 
    ECA(Event-Condition-Action) 충돌을 검사하고 JSON 보고서를 생성합니다.

    CLI 옵션
    ----------
    --in : str
        automations.yaml 경로. 생략하면 stdin에서 YAML을 읽습니다.
    --out : str
        JSON 보고서 저장 경로(선택). 생략하면 표준출력으로는 출력하지 않습니다.
        stdout으로 출력하려면 --out stdout을 사용하세요.

    동작
    ----------
    - 지정된 파일 또는 stdin에서 Home Assistant 자동화 YAML을 읽습니다.
    - analyze_ha_automations(yaml_text)를 호출하여 JSON 보고서를 생성합니다.
    - --out이 제공되면 해당 경로로 보고서를 저장합니다. 
    - stdout으로 출력하려면 --out stdout을 사용하세요.

    예시
    ----------
    # 파일에서 읽고 다른 파일로 저장:
    ha_eca_conflict_analyzer.py --in automations.yaml --out report.json

    # stdin에서 읽고 파일로 저장:
    cat automations.yaml | ha_eca_conflict_analyzer.py --out report.json

    # 파일에서 읽고 stdout으로 출력:
    ha_eca_conflict_analyzer.py --in automations.yaml --out stdout
    """
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
    if args.outfile and args.outfile.strip().lower() == "stdout":
        print(out_json)
    elif args.outfile:
        with open(args.outfile, "w", encoding="utf-8") as f:
            f.write(out_json)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
