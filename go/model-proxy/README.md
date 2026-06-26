# Go model proxy (`go/model-proxy`)

A faithful Go port of `maverick.model_proxy`: a tiny out-of-process proxy that
holds the provider API key the agent process must **not**. The agent points a
provider `base_url` at this proxy and sends requests with no usable credential;
the proxy strips whatever the client sent, injects the real key, and forwards to
the single configured upstream. The key never lives in the agent's address
space.

## Why a second language here

This is the one carve where the win is **concurrency, not CPU**. The proxy sits
in the inference data path — every model call funnels through it. Python's
`ThreadingHTTPServer` serializes the actual forwarding work behind the GIL; Go
serves each request on its own goroutine, so concurrent calls forward in
parallel. That's throughput/density for hosted/multi-tenant deployments, not
lower single-call latency.

The **behaviour is identical**. The security-critical decision logic —
`BuildRequest` (drop the client's auth + hop-by-hop headers, inject the proxy's
key, refuse a host outside the allow-set), `Authenticate` (constant-time client
token check), `RouteAllowed` (allow-list only model-inference routes) — is a
byte-for-byte port and is parity-tested against the real Python (see below).

## Run

Config comes from the proxy's **own** environment (never the agent's config):

```bash
export MAVERICK_PROXY_UPSTREAM=https://api.anthropic.com
export MAVERICK_PROXY_KEY=sk-ant-...          # the real key, injected upstream
export MAVERICK_PROXY_CLIENT_TOKEN=some-shared-secret  # agent must present this
export MAVERICK_PROXY_AUTH_STYLE=x-api-key     # or "bearer" (default)
# optional: MAVERICK_PROXY_LISTEN=127.0.0.1:8765
#           MAVERICK_PROXY_ALLOWED_ROUTES="POST /v1/messages, POST /v1/embeddings"

go run ./cmd/model-proxy            # listen
go run ./cmd/model-proxy -check     # validate config and exit
```

The agent then uses the proxy as its provider base URL, with
`MAVERICK_PROXY_CLIENT_TOKEN` as its (useless-elsewhere) api key.

Unlike the Python entry point this reads config **only** from the environment —
no TOML fallback — because running out-of-process means its settings and key
live in its own environment, which is also the documented deploy path.

## Parity with Python

`maverick.model_proxy` is the source of truth. `gen_parity.py` drives a battery
of inputs through the **real Python functions** and writes
`testdata/parity.json`; `parity_test.go` replays it through the Go port and
asserts byte-identical decisions (URLs, forwarded headers, auth/route verdicts,
SSRF blocks). Regenerate after changing either side so they can't drift:

```bash
python3 go/model-proxy/gen_parity.py     # from the repo root, with maverick-core installed
go test ./go/model-proxy/...             # build + unit + parity + concurrency, run with -race in CI
```

CI (`.github/workflows/go-model-proxy.yml`) regenerates the fixture from Python
and fails on any diff, so the committed fixture always matches the current
Python.
