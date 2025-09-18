## 홈 어시스턴트 오토메이션 분석
 - Redundancy: 동일 이벤트에서 동일 액션이 여러 경로로 중복 실행 가능
 - Inconsistency: 동일 이벤트가 같은 엔티티에 상충 명령(예: light.turn_on vs light.turn_off) 야기
 - Circularity: E→A→E 순환 경로(Tarjan SCC) 탐지

### 가정
- 조건은 양분기 모두 가능한 것으로 간주(모델체킹보다 느슨하지만 경고에 유용)
- state 트리거 위주로 E→A, A→E를 연결.비 state 트리거(time, sun, event)는 E→A만 고려(기본 A→E 연결은 없음)
- 충돌 테이블 및 액션→상태 효과는 CONFLICT_CATALOG, ACTION_STATE_EFFECTS에 추가 가능

## 사용법

```
$ python ha_eca_conflict_analyzer.py --in automations_circularity.yaml
{
  "summary": {
    "events": 3,
    "actions": 3,
    "edges": 6,
    "redundancy_issues": 0,
    "inconsistency_issues": 0,
    "circularity_issues": 1
  },
  "redundancy": [],
  "inconsistency": [],
  "circularity": [
    {
      "cycle_nodes": "A:lock.unlock(lock.front=unlocked) → E:state(light.l2→on) → A:light.turn_on(light.l2=on) → E:state(switch.out2→on) → A:switch.turn_on(switch.out2=on) → E:state(lock.front→unlocked)",
      "size": 6,
      "issue": "Circularity: cycle in event flow graph"
    }
  ]
}

$ python ha_eca_conflict_analyzer.py --in automations_inconsistency.yaml
{
  "summary": {
    "events": 2,
    "actions": 4,
    "edges": 5,
    "redundancy_issues": 0,
    "inconsistency_issues": 1,
    "circularity_issues": 0
  },
  "redundancy": [],
  "inconsistency": [
    {
      "event": "E:state(binary_sensor.presence_1→on)",
      "action1": "light.turn_on(light.l1=on)",
      "action2": "light.turn_off(light.l1=off)",
      "entity": "light.l1",
      "issue": "Inconsistency: conflicting actions reachable from same event"
    }
  ],
  "circularity": []
}

$ python ha_eca_conflict_analyzer.py --in automations_redundancy.yaml
{
  "summary": {
    "events": 2,
    "actions": 2,
    "edges": 4,
    "redundancy_issues": 1,
    "inconsistency_issues": 0,
    "circularity_issues": 0
  },
  "redundancy": [
    {
      "event": "E:state(binary_sensor.motion_1→on)",
      "action": "A:media_player.play(media_player.mp1=playing)",
      "paths_count": 2,
      "issue": "Redundancy: action reachable more than once from event"
    }
  ],
  "inconsistency": [],
  "circularity": []
}
```