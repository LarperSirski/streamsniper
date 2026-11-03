# StreamSniper

![StreamSniper Logo](ui/StreamSniper.png)

**Keep an eye on the channels you follow.**

StreamSniper is a Windows desktop application that monitors YouTube channels for new uploads and live streams, automatically records streams, and saves recordings locally.

## Features

- Monitor multiple YouTube channels.
- Detect new uploads and live streams.
- Automatically or manually record live streams.
- Browse recordings and view their metadata.
- Recover interrupted recordings.
- Customize recording locations.
- Receive Discord webhook notifications.
- Upload recordings to YouTube (Private, Unlisted, or Public).

## Requirements

- Windows 10/11
- Python 3.10+ (source installation)
- FFmpeg installed and added to `PATH`
- Internet connection

## Installation

```powershell
git clone https://github.com/LarperSirski/streamsniper.git
cd streamsniper
.\run_modern.bat
```

The launcher automatically creates a virtual environment, installs dependencies, and starts the application.

To update:

```powershell
git pull
.\run_modern.bat
```

## Usage

1. Open **Channels** and add a YouTube channel using its URL.
2. Enable **Auto Record** if you want to automatically record its live streams.
3. Go to **Overview** and click **Start Monitoring**.
4. StreamSniper checks channels every 90 seconds by default.
5. View active recordings in Overview and completed recordings under **Recorded Streams**.

**Note:** StreamSniper must remain open, and your PC must stay awake and connected to the internet.

## Optional Integrations

### Discord Notifications

Configure a Discord webhook URL under **Settings** to receive notifications.

### YouTube Uploads

Connect your YouTube account through the **Upload** page using a Google Cloud OAuth Desktop client. Choose the recording and its visibility before uploading.

## Build

To create a standalone Windows executable:

```powershell
.\build_windows.bat
```

The executable is generated in the project folder. FFmpeg is still required.

## Run Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Data Storage

| Data | Location |
|---|---|
| Recordings | `%USERPROFILE%\Videos\StreamSniper` |
| Settings, channels & logs | `%LOCALAPPDATA%\StreamSniper` |

## Contributing

Contributions are welcome! Fork the repository, make your changes, and submit a pull request.

## Disclaimer

StreamSniper does not bypass DRM, paywalls, memberships, or private-stream restrictions. Only record or upload content you own or are authorized to use. Follow YouTube's terms of service and applicable laws.

**StreamSniper is community-built beta software.**
