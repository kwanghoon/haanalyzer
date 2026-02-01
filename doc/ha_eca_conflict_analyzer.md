# HA ECA 충돌 분석기

Event–Action Flow Graph(EFG)을 이용해 Home Assistant 자동화를 분석하고 구조적 이슈를 찾아내는 도구입니다.

## 개요
- 자동화가 포함된 하나 이상의 YAML 문서를 파싱합니다.
- 이벤트 → 액션, 액션 → 호환되는 상태 이벤트를 연결하는 EFG를 구성합니다.
- 중복(redundancy), 불일치(inconsistency), 순환(circularity) 세 가지 이슈를 탐지합니다.
- 요약과 상세 결과를 담은 JSON 보고서를 출력합니다.

## CLI
- 명령: `ha_eca_conflict_analyzer.py`
- 옵션:
  - `--in <path>`: `automations.yaml` 경로(생략 시 stdin에서 읽음).
  - `--out <path|stdout>`: JSON 보고서를 저장할 위치. 콘솔 출력은 `stdout` 사용.

예시:
```bash
# 파일에서 읽고 다른 파일로 저장
python3 ha_eca_conflict_analyzer.py --in automations.yaml --out report.json

# stdin에서 읽고 파일로 저장
cat automations.yaml | python3 ha_eca_conflict_analyzer.py --out report.json

# 파일에서 읽고 stdout으로 출력
python3 ha_eca_conflict_analyzer.py --in automations.yaml --out stdout
```

## 데이터 모델
- Event: `kind`, `entity_id`, `to`, `extra`
- Action: `domain`, `service`, `entity_id`, `value`, `extra`

설명:
- 상태 트리거의 경우 `Event.kind == "state"`; 기타 이벤트는 `platform[:event_type]` 형식을 사용합니다.
- `Action.value`는 알려진 경우 액션의 상태 효과를 반영합니다(예: `switch.turn_on → on`).
- `extra`는 정규화된 메타데이터를 `(key, value)`의 정렬된 튜플로 저장하며, 해시 가능하도록 변환됩니다.

## 핵심 함수
- `parse_ha_automations(yaml_text)`: YAML을 평탄화하여 자동화 딕셔너리 목록으로 변환.
- `build_efg(automations)`: 이벤트, 액션, 간선을 포함하는 EFG를 구성.
- `detect_redundancy(g)`: 동일 이벤트에서 여러 경로로 도달 가능한 액션 탐지.
- `detect_inconsistency(g)`: 동일 엔티티를 대상으로 하는 상충 액션 탐지.
- `detect_circularity(g)`: 그래프 내 사이클(자기 루프 포함) 탐지.
- `analyze_ha_automations(yaml_text)`: 파싱/그래프 구성/탐지를 오케스트레이션하고 JSON 딕셔너리를 반환.

## 에지 구성 로직
- Event → Action: 자동화에서 추출된 모든 정규화된 이벤트-액션 쌍에 대해 추가.
- Action → Event: 동일 `entity_id`에 대해 액션의 `value`가 상태 이벤트와 호환될 때 추가.
  - 조건: `event.kind == "state"`, `entity_id` 동일, 그리고 `(event.to is None) or (action.value is None) or (event.to == action.value)`.

## 출력 형식
- `summary`: 이벤트/액션/에지 수와 각 이슈 총계.
- `redundancy`: 여러 서로 다른 경로로 액션에 도달 가능한 이벤트 목록.
- `inconsistency`: 동일 엔티티를 겨냥하는 상충 액션 목록.
- `circularity`: 그래프에서 탐지된 사이클 목록.

## HTML 문서 생성(pydoc)
표준 라이브러리의 pydoc을 사용해 도크스트링에서 HTML 문서를 직접 생성할 수 있습니다.
```bash
# 워크스페이스 루트에서 실행
python3 -m pydoc -w ha_eca_conflict_analyzer
# 현재 디렉터리에 ha_eca_conflict_analyzer.html이 생성됩니다
# 필요하면 doc/ 디렉터리로 이동하세요
mv ha_eca_conflict_analyzer.html doc/
```

## 개발 노트
- 일반적인 Home Assistant 자동화 구조에 견고하도록 설계되었습니다.
- 이벤트/액션의 비교와 해싱이 안정적이도록 결정적 정규화를 사용합니다.
- 불완전한 자동화에 대해 예외를 던지지 않으며, 이벤트 또는 액션이 없으면 해당 항목을 건너뜁니다.
