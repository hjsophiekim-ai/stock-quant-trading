// 런타임 설정(비밀값 금지). 저장소 기본은 로컬 개발용 — Windows NSIS 빌드(`build-win.js`)는 패킹 시 Render 등 운영 URL을 임시 주입한 뒤 이 파일을 복원합니다.
window.RUNTIME_CONFIG = {
  BACKEND_URL: "http://127.0.0.1:8000",
  APP_ENV: "development",
};
