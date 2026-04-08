Desktop build icon directory.

- Default icon path used by electron-builder: `build/icons/icon.ico`
- `scripts/build-win.js` auto-creates a minimal placeholder icon if missing.
- For production branding, replace `icon.ico` with your real app icon (256×256 권장, 다중 해상도 포함 `.ico`).
- NSIS 추가 비트맵·브랜딩: `build/installer/README.md`
