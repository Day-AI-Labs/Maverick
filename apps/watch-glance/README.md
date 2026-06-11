# Maverick watch glance (watchOS scaffold)

A minimal SwiftUI watchOS app + complication rendering the fixed glance
payload from a self-hosted Maverick dashboard:

```
GET http://<your-host>:8765/api/v1/glance
-> {active, done_today, failed_today, spend_today, last_result, as_of}
```

**Build requirements (not possible in this repo's CI):** Xcode 16+ on macOS
with the watchOS SDK; create a watchOS App target named `MaverickGlance` and
add the two Swift files. Set `MAVERICK_GLANCE_URL` (and the dashboard token
if configured) in the scheme's environment or the in-app settings.

Security model: the watch talks only to YOUR dashboard host; include the
`Authorization: Bearer <MAVERICK_DASHBOARD_TOKEN>` header when the dashboard
sets one. Nothing else leaves the watch.
