### 20개 automation YAML 파일을 분석하여 만든 포괄적인 CFG 문법

주요 특징:

* 11가지 Trigger 타입:
  - State, Time, Sun, Numeric State, Template, Event
  - Home Assistant, Webhook, Zone, Geo Location, Device, Tag, MQTT, Calendar

* 9가지 Condition 타입:
  - State, Numeric State, Time, Sun, Template, Zone
  - 논리 연산: AND, OR, NOT
  - Device

* 11가지 Action 타입:
  - Service 호출, Delay, Wait (template/trigger)
  - Event, Device, Choose, Repeat, If, Parallel, Stop, Variables

* 메타데이터:
  - alias, id, mode (single/restart/queued/parallel)
  - max, max_exceeded, description, variables

* 상세한 데이터 패턴:
  - 조명 제어 (밝기, 색상, 전환, 효과)
  - 알림 (iOS critical alerts, action buttons)
  - 미디어 플레이어 (TTS, 볼륨, announce)
  - Climate, Fan, Cover, Lock, Alarm
  - Entity targeting (entity_id vs target 방식)

* 고급 패턴:
  - Jinja2 템플릿 구문
  - 시간 duration (구조화/문자열 형식)
  - 속성 기반 조건
  - For 루프 in triggers/delays
  - 중첩 조건 (AND/OR/NOT)

 #### 문법은 EBNF 표기법으로 작성되었으며, 실제 automation 파일에서 관찰된 패턴, 일반적인 값, 사용법에 대한 광범위한 주석을 포함하고 있습니다.