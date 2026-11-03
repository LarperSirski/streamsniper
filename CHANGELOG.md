# Changelog

## Unreleased

### Added

- Added the requested beta attribution note in the UI.
- Added a configurable recording folder, defaulting to `%USERPROFILE%\Videos\StreamSniper`.
- Moved app settings, the channel database, and logs to `%LOCALAPPDATA%\StreamSniper`.

### Changed

- Removed Google Drive and Rclone support; YouTube uploads and Discord notifications remain available.
- Added the StreamSniper icon to the app window, taskbar, and Windows executable.
- Added a Windows app identity to keep the taskbar from using the Python launcher icon.
- Increased interface text sizes for readability and removed the in-app sidebar logo.
- Refreshed the README with setup, storage, and build instructions.
- Excluded generated executables, build output, local data, and environment files from Git.
