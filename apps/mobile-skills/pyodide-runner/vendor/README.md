# vendor/ — put Pyodide here (not committed)

The runner loads Pyodide from `./vendor/pyodide/pyodide.js` only. No CDN
hot-link is committed, and no binaries are committed — you vendor the
release yourself:

```bash
cd apps/mobile-skills/pyodide-runner/vendor
curl -LO https://github.com/pyodide/pyodide/releases/download/0.26.4/pyodide-0.26.4.tar.bz2
# Verify before extracting. TODO (fill on download): pin the sha256 here —
# compute it with `sha256sum pyodide-0.26.4.tar.bz2` and cross-check the
# value against the official pyodide 0.26.4 release notes/assets page.
sha256sum pyodide-0.26.4.tar.bz2
tar xjf pyodide-0.26.4.tar.bz2     # extracts to vendor/pyodide/
test -f pyodide/pyodide.js && echo OK
```

The placeholder above is deliberate: this environment has no network
access, so committing a checksum we could not compute ourselves would be
fabrication. Fill it in on first download and commit the pin.
