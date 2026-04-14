# Desktop Session/JWT 수동 검증

1. 데스크톱 앱 로그인 후 `broker-settings.html` 진입
2. 앱 종료 후 재실행, `dashboard.html` 자동 진입 여부 확인
3. 절전/복귀 후 `dashboard`/`paper-trading`에서 12~15초 polling이 계속 갱신되는지 확인
4. 만료 토큰 상황을 만들려면 서버에서 refresh 토큰 폐기 후 화면 새로고침
   - 기대: `ensureValidBackendSession`이 refresh 1회 시도
   - 실패 시 `clearDesktopSession` 후 로그인 화면으로 이동
5. `broker-settings`에서 저장된 마스킹 정보(앱키/계좌/상품/모드/연결상태)가 자동 복원되는지 확인
