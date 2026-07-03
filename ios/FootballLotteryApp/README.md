# Football Lottery iPhone App

This is the first SwiftUI shell for the mobile branch. It calls the existing Python backend and renders the app-ready `report` JSON from `/api/analysis`.

## Run Backend

From the repository root:

```powershell
football-lottery-agent ui --host 0.0.0.0 --port 8765 --no-open
```

For the iPhone simulator, the default app backend URL can stay:

```text
http://127.0.0.1:8765
```

For a physical iPhone, use the computer's LAN IP:

```text
http://192.168.1.8:8765
```

## Open in Xcode

Open:

```text
ios/FootballLotteryApp/FootballLotteryApp.xcodeproj
```

Before running on a device:

- Set `PRODUCT_BUNDLE_IDENTIFIER` to your own bundle id.
- Set `DEVELOPMENT_TEAM` in Signing & Capabilities.
- Keep the app on the same network as the backend during local testing.

## Current Scope

- Backend URL setting
- Issue input
- Analysis generation
- History report list
- Deadline and metrics summary
- Choose-9 keep/drop display
- 14-match prediction list
- Match detail with probabilities, scorelines, and reasons
