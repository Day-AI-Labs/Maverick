# Maverick Launch Checklist

This public checklist is intentionally limited to non-sensitive release gates.
Operational details that identify unfinished security fixes, affected
components, or private branches belong in the maintainers' private release
tracker until the fixes have shipped.

## Public launch gates

1. Confirm the release branch contains all reviewed launch-blocking fixes.
2. Confirm CI is green for the supported Python versions and platforms.
3. Configure required publishing environments and package publisher settings.
4. Verify documentation deployment settings.
5. Build and smoke-test release artifacts in a clean environment.
6. Tag and publish only after the private release checklist is complete.

## Maintainer note

Do not use public repository files to enumerate unmerged security findings,
private branch names, affected components, exploit paths, or exact remediation
steps. Keep those details in a private issue, advisory, or security tracker until
coordinated disclosure is appropriate.
