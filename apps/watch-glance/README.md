# Maverick watch glance (watchOS scaffold)

A minimal SwiftUI watchOS app + complication rendering the fixed glance
payload from a self-hosted Maverick dashboard:

```
GET https://<your-host>:8765/api/v1/glance
-> {active, done_today, failed_today, spend_today, last_result, as_of}
```

**Build requirements (not possible in this repo's CI):** Xcode 16+ on macOS
with the watchOS SDK; create a watchOS App target named `MaverickGlance` and
add the two Swift files. Set `MAVERICK_GLANCE_URL` (and the dashboard token
if configured) in the scheme's environment or the in-app settings. The
URL must use HTTPS for any non-localhost dashboard; plain HTTP is accepted
only for loopback development (`localhost`, `127.0.0.1`, or `::1`).

Security model: the watch talks only to YOUR dashboard host; include the
`Authorization: Bearer <MAVERICK_DASHBOARD_TOKEN>` header when the dashboard
sets one. Because that bearer token grants dashboard API access, never send
it to a remote dashboard over cleartext HTTP. Nothing else leaves the watch.
