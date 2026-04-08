# Readiness Report: KIS 모의투자 자동매매

작성일: 2026-04-08  
판정 대상: "지금 바로 모의투자 자동매매가 가능한지"

## 최종 판정

**조건부 사용 가능 (PARTIAL READY)**  
핵심 자동매매 루프(종목선정 -> 전략 -> 리스크 -> 주문 -> 동기화)는 동작 경로가 연결되어 있으며, 회원가입/로그인/브로커 등록/연결 테스트도 동작합니다.  
다만, 운영 관점에서 사용자 스코프 정합성 및 일부 성과 지표 정확도(추정치 포함) 보완이 필요합니다.

## 항목별 판정 (PASS / PARTIAL / FAIL)

| 항목 | 판정 | 근거 | PASS가 아닌 경우 사유 |
|---|---|---|---|
| 회원가입 가능 | PASS | `POST /api/auth/register` 라우트 및 사용자 모델/저장소 연결 | - |
| 로그인 가능 | PASS | `POST /api/auth/login` JWT 발급/검증 경로 동작 | - |
| 브로커 등록 가능 | PASS | `POST /api/broker-accounts/me` 암호화 저장 + 상태 관리 | - |
| 한투 모의계정 연결 성공 | PASS | `POST /api/broker-accounts/me/test-connection` 토큰 발급/호스트 검증 | - |
| 자동 종목선정 가능 | PASS | premarket/intraday에서 스크리너 refresh 및 후보 스냅샷 갱신 | - |
| 전략판단 가능 | PASS | 신호 엔진 스냅샷/전략 평가 경로 및 런타임 tick 실행 연결 | - |
| 주문 생성 가능 | PASS | 주문 엔진 실행 + 리스크 승인 + 주문 추적 스토어 연계 | - |
| KIS mock 주문 가능 | PASS | Paper 경로에서 openapivts 강제, live 혼선 차단 | - |
| 체결/잔고/손익 자동 반영 가능 | PARTIAL | tick 후 `portfolio_sync` 자동 수행, snapshot/fills 반영 | 사용자별 1:1 분리 저장/동기화는 아직 미완료 |
| 대시보드/성과화면 실제 결과 반영 | PARTIAL | `dashboard/summary`, `performance/*` 실데이터 기반 집계 + 출처 필드 제공 | 월수익률/승률/손익비 등 일부 지표는 이력/리플레이 기반 추정치 |

## 지금 바로 쓸 수 있는 범위

- 단일 운영 계정 기준으로 아래 흐름은 즉시 사용 가능:
  - 회원가입 -> 로그인 -> 브로커 등록 -> 연결 테스트
  - Paper 시작(앱) -> 자동 루프 실행(장전/장중/장후)
  - 주문/체결 추적, 포트폴리오 동기화, 대시보드/성과 확인
- 시작 API:
  - `POST /api/paper-trading/start` (`link_runtime_engine=true` 기본)
  - `GET /api/paper-trading/status`, `GET /api/runtime-engine/status`
  - `GET /api/dashboard/summary`, `GET /api/performance/metrics`

## 실사용 전 반드시 보완할 항목 10개

1. 사용자별 `open_orders`/`fills`/`portfolio_data` 완전 분리 저장 구조
2. 대시보드의 서버 런타임 계정 vs 앱 사용자 계정 정합성 강제 검증
3. 체결 리플레이 손익 계산에 수수료/세금/FIFO 정밀 반영
4. 공휴일/반장/특이장 캘린더를 포함한 시장 스케줄러 고도화
5. `risk_off` 자동 전환 후 운영자 액션 가이드 및 알림 채널(슬랙/메일) 연계
6. 런타임 로그/heartbeat/EOD 리포트 보관 정책(회전/압축/만료) 확정
7. 장중 시세 조회 실패 시 백오프/재시도/서킷브레이커 정책 명문화
8. 모바일/데스크톱 UI에서 추정치와 실측치 배지 표시 강화
9. E2E 통합 테스트를 CI에서 자동 실행(브로커 mock + 회귀 테스트)
10. 운영 배포 환경에서 비밀키/DB 백업/복구/감사로그 정책 문서화

## 리스크 메모

- 현재 구현은 **paper 자동매매 운영 검증 단계**로는 충분하지만,
- 다중 사용자 동시 운영과 성과 지표 정밀 회계 기준까지는 추가 보완이 필요합니다.
