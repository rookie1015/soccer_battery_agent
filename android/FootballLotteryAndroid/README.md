# Football Lottery Android

Standalone Android client for the football lottery analysis engine.

## Run the app

Open `android/FootballLotteryAndroid` in Android Studio and run the `app` configuration, or install the generated debug APK.

The Android app now includes the analysis engine locally through Chaquopy. You do not need to start a computer backend or enter a backend URL.

The phone still needs internet access when generating a current issue analysis, because it fetches official schedule, odds, and team information directly from the data sources.

The Settings screen has a local engine test button for checking that the embedded engine starts correctly.

## Current features

- Generate an issue analysis report.
- Read report history generated on the phone.
- Run a single-match prediction with optional 3-way odds.
- Test the embedded local analysis engine from Settings.

## Build from command line

```powershell
.\gradlew.bat assembleDebug
```

The debug APK is generated under:

```text
app/build/outputs/apk/debug/app-debug.apk
```
