# Lightwork JetBrains plugin (live-run scaffold)

A minimal IntelliJ-platform plugin: a **Lightwork Runs** tool window that
streams a run's events live from the self-hosted dashboard SSE endpoint
(`GET /api/v1/goals/{id}/events/stream`), mirroring the VS Code extension's
"Watch run live" command.

**Build requirements (not possible in this repo's CI):** JetBrains
IntelliJ Platform Gradle plugin (`org.jetbrains.intellij.platform`), JDK 17+.
Create a Gradle project with these sources; `runIde` to test. Configure the
dashboard URL/token under Settings → Tools → Lightwork.

Security model: talks only to YOUR dashboard host; sends the
`Authorization: Bearer <token>` header when a dashboard token is configured.
