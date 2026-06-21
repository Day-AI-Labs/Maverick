#!/usr/bin/env bash
# Verify a Maverick release artifact's Sigstore (cosign keyless) signature.
#
# Every release binary and the SBOM ship with a detached `.sig` (signature) and
# `.pem` (signing certificate). The signature is keyless: it was produced by the
# release workflow's OIDC identity and logged to the public Rekor transparency
# log, so verification proves the artifact was built by THIS repo's release
# workflow -- no shared public key to distribute or trust on faith.
#
#   deploy/verify-release.sh maverick-linux-x86_64
#   deploy/verify-release.sh maverick-linux-x86_64 maverick-linux-x86_64.sig maverick-linux-x86_64.pem
#
# Override the expected signer with IDENTITY_REGEXP (e.g. to pin a tag).
set -euo pipefail

ARTIFACT="${1:?usage: verify-release.sh <artifact> [sig] [cert]}"
SIG="${2:-$ARTIFACT.sig}"
CERT="${3:-$ARTIFACT.pem}"

# The signer is the release workflow in this repo; the OIDC issuer is GitHub.
IDENTITY_REGEXP="${IDENTITY_REGEXP:-^https://github.com/[Dd]ay-[Aa][Ii]-[Ll]abs/[Mm]averick/\.github/workflows/release\.yml@refs/tags/v.*}"
OIDC_ISSUER="${OIDC_ISSUER:-https://token.actions.githubusercontent.com}"

command -v cosign >/dev/null 2>&1 || {
  echo "cosign not found. Install: https://docs.sigstore.dev/cosign/installation/" >&2
  exit 1
}
for f in "$ARTIFACT" "$SIG" "$CERT"; do
  [ -f "$f" ] || { echo "missing file: $f" >&2; exit 1; }
done

echo "Verifying $ARTIFACT"
echo "  signature:   $SIG"
echo "  certificate: $CERT"
echo "  signer:      $IDENTITY_REGEXP"

cosign verify-blob \
  --signature "$SIG" \
  --certificate "$CERT" \
  --certificate-identity-regexp "$IDENTITY_REGEXP" \
  --certificate-oidc-issuer "$OIDC_ISSUER" \
  "$ARTIFACT"

echo "OK: $ARTIFACT signature is valid and was produced by the release workflow."
