# Image Classifier — Flutter frontend

Single-page Flutter app replicating the Explorer / Classified UI.

## Run

```bash
flutter pub get
flutter run -d chrome   # or -d linux / -d windows / -d macos
```

## What's wired up

- **Explorer / Classified toggle** — top center segmented control.
- **Run button** (top right, orange play icon) — calls
  `POST {backendBaseUrl}/runclassification` with `{"path": "<current path>"}`
  and expects back per-class counts/sizes. Edit `backendBaseUrl` at the top
  of `lib/main.dart`.
- **Path bar** — editable `TextField`; press Enter to "navigate" (currently
  just updates state — see the `TODO` in `_navigateTo()` for wiring a real
  directory-listing endpoint).
- **View mode toggle** (next to the path bar) — switches between details
  (tree/list) and large-icon (grid) rendering, for both tabs.
- **Classified tab** — always exactly 4 boxes/rows: Screenshots, Memes,
  Wallpapers, Photos. Tap one to select it.
- **Status bar** (bottom) — shows only the size of the currently selected
  class, nothing else. Empty when no class is selected.

## Not wired up (stubbed with dummy data)

- Explorer's actual folder/file listing — replace `_dummyFolders` /
  `_dummyFiles` and the `_navigateTo()` TODO with a real API call.

## Backend response shape expected by `/runclassification`

```json
{
  "screenshot": { "count": 120, "size_bytes": 543210 },
  "memes":      { "count": 40,  "size_bytes": 123456 },
  "wallpaper":  { "count": 12,  "size_bytes": 987654 },
  "photos":     { "count": 300, "size_bytes": 5432100 }
}
```
