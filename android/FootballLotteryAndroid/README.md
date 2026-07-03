# Football Lottery Android App

First Android shell for the `android` branch. It calls the existing Python backend and renders `/api/analysis` JSON.

## Run Backend

From the repository root:

```powershell
football-lottery-agent ui --host 0.0.0.0 --port 8765 --no-open
```

Backend URL examples:

- Android emulator: `http://10.0.2.2:8765`
- Physical phone: `http://192.168.1.8:8765`

## Open in Android Studio

Open:

```text
android/FootballLotteryAndroid
```

Current scope:

- Backend URL setting
- Issue input
- Analysis generation
- Deadline and metrics summary
- Choose-9 keep/drop display
- 14-match prediction list
- Match detail with probabilities, scorelines, and reasons
