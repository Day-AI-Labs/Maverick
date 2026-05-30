# Maverick — Launch Readiness Assessment

This public readiness note intentionally avoids listing sensitive audit findings,
affected components, private branch names, or unfinished security remediation
steps. Maintainers should keep those details in the private security tracker
until fixes are merged and released.

## Public launch criteria

The project should be considered ready for a public release only when:

1. All launch-blocking fixes have been reviewed and merged.
2. CI passes on the supported platform and Python-version matrix.
3. Package publishing, documentation deployment, and release environments are
   configured by project owners.
4. Release artifacts are built from the intended tag and smoke-tested in a clean
   environment.
5. Public release notes avoid disclosing unresolved security issues.

## Verification guidance

Perform final verification from the merged release branch and published
artifacts, not from private working branches. Keep detailed audit evidence,
security triage notes, and component-specific remediation plans outside the
public repository until coordinated disclosure is safe.
