# Changelog

## 1.1.0
- **Check for updates** in the new ⋯ options menu (also `--check-update` / `--update`).
  It only goes online when you click it. Updates are verified by SHA-256 and replace the
  AppImage in place, so menu entries keep working.
- About dialog and a shortcut to the models folder.

## 1.0.1
- Fixed long videos getting stuck repeating the same subtitle line for the rest of the
  file. Each 30-second window is now decoded independently, and any remaining runs of
  repeated lines are detected and re-transcribed automatically.

## 1.0.0
- First release.
