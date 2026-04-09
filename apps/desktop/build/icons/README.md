Desktop build icon directory.

- Windows 빌드는 **`build/icons/icon.png`** (최소 256×256) 를 사용합니다. `package.json` 의 `build.win.icon` 에 연결되어 있습니다.
- 상용 브랜딩 시 이 PNG를 교체하거나, 멀티 해상도 `.ico` 로 바꾼 뒤 `win.icon` 경로를 함께 수정하세요.
- NSIS 추가 비트맵·브랜딩: `build/installer/README.md`
