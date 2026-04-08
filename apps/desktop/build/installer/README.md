# Windows 설치 프로그램용 선택 리소스

`electron-builder` NSIS 타깃은 기본적으로 `build/icons/icon.ico` 만 있으면 동작합니다.

선택 사항(브랜딩 강화):

| 파일 | 용도 | 권장 크기 |
|------|------|-----------|
| `../icons/icon.ico` | 앱·설치 마법사 아이콘 | 256×256 포함 다중 해상도 |
| `sidebar.bmp` | 설치 마법사 옆면 이미지 | 164×314 |
| `header.bmp` | 설치 마법사 상단 이미지 | 150×57 |

`sidebar.bmp` / `header.bmp` 를 추가한 경우 `package.json` 의 `build.nsis` 에 `installerSidebar` / `installerHeader` 경로를 지정하세요.

코드 서명(배포 시): `docs/deployment_desktop.md` 의 **코드 서명** 절을 참고하세요.
