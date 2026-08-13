# Football Lottery Android

Standalone Android client for the football lottery analysis engine.

## Run the app

Open `android/FootballLotteryAndroid` in Android Studio and run the `app` configuration, or install the generated debug APK.

The Android app now includes the analysis engine locally through Chaquopy. You do not need to start a computer backend or enter a backend URL.

The phone still needs internet access when generating a current issue analysis, because it fetches official schedule, odds, and team information directly from the data sources.

The Settings screen has a local engine test button for checking that the embedded engine starts correctly.

## Current features

- Generate an issue analysis report.
- Save a Feishu custom-bot webhook and automatically send ticket recommendations after each analysis.
- Read report history generated on the phone.
- Long-press an analysis history group or entry to delete it after confirmation.
- When network failures force simple-analysis fallback, list the unavailable information sources in each match's conclusion reasons.
- Run a single-match prediction with optional 3-way odds.
- Test the embedded local analysis engine from Settings.

## Feishu delivery

Open **Settings** in the Android app, paste a Feishu group custom-bot webhook, enable automatic delivery, save, and use **Test delivery**. The webhook is stored only in the app's local preferences. A failed delivery does not discard the locally generated analysis or history entry.

## Build from command line

```powershell
.\gradlew.bat assembleDebug
```

The debug APK is generated under:

```text
app/build/outputs/apk/debug/app-debug.apk
```
