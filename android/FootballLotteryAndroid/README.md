# Football Lottery Android

Android client for the football lottery analysis backend.

## Run the backend for a phone

From the repository root, double-click:

```text
start_mobile_backend.bat
```

Keep that window open while using the phone app. It prints backend address candidates such as `http://192.168.1.20:8765`.

## Run the app

Open `android/FootballLotteryAndroid` in Android Studio and run the `app` configuration.

Default backend URL:

```text
http://10.0.2.2:8765
```

Use this value when running in the standard Android emulator. For a physical phone, use one of the addresses printed by `start_mobile_backend.bat`, for example:

```text
http://192.168.1.20:8765
```

The phone and computer must be on the same network, and Windows Firewall may need to allow Python or port `8765`.

## Current features

- Generate an issue analysis report.
- Read report history from `/api/history`.
- Open generated HTML or Markdown reports in the system browser.
- Run a single-match prediction with optional 3-way odds.
- Save the backend URL locally after editing it in Settings.
- Test the backend connection from Settings before running analysis.

## Build from command line

```powershell
.\gradlew.bat assembleDebug
```

The debug APK is generated under:

```text
app/build/outputs/apk/debug/app-debug.apk
```
