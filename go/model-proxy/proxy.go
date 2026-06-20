// Package proxy is a Go port of maverick.model_proxy: a tiny out-of-process
// model proxy that holds the provider API key the agent process must not.
//
// The agent points a provider base_url at this proxy and sends requests with no
// usable credential; the proxy strips whatever the client sent, injects the
// real key, and forwards to the single configured upstream. The key never lives
// in the agent's address space.
//
// Why Go: the security-critical decision logic (BuildRequest / Authenticate /
// RouteAllowed) is a faithful, byte-for-byte port of the Python original and is
// exhaustively parity-tested against it. The reason to run it here rather than
// in Python is the listener: this sits in the inference data path, and Go's
// goroutine-per-request model forwards concurrent calls without the GIL
// serialization of Python's ThreadingHTTPServer — throughput/density, not
// per-call latency. Behaviour is identical; concurrency is not.
package proxy

import (
	"crypto/subtle"
	"net/url"
	"sort"
	"strings"
	"unicode"
)

// Connection-specific headers that must never be forwarded, plus the
// client-supplied credential headers the proxy replaces with its own. Keys are
// lowercase; lookups lowercase the candidate first. Mirrors _HOP_BY_HOP.
var hopByHop = map[string]struct{}{
	"connection": {}, "keep-alive": {}, "proxy-authenticate": {},
	"proxy-authorization": {}, "te": {}, "trailers": {}, "transfer-encoding": {},
	"upgrade": {}, "host": {}, "content-length": {},
}

// Client credential headers stripped before forwarding. Mirrors _AUTH_HEADERS.
var authHeaders = map[string]struct{}{
	"authorization": {}, "x-api-key": {}, "api-key": {},
}

// DefaultPort matches model_proxy.DEFAULT_PORT.
const DefaultPort = 8765

// proxyTokenHeader matches model_proxy._PROXY_TOKEN_HEADER.
const proxyTokenHeader = "x-maverick-proxy-token"

// DefaultAllowedRoutes mirrors model_proxy.DEFAULT_ALLOWED_ROUTES: only
// model-inference routes are forwarded by default, so a reachable local proxy
// is not a general provider-key oracle.
var DefaultAllowedRoutes = map[string]struct{}{
	"POST /v1/messages":              {},
	"POST /v1/messages/count_tokens": {},
	"POST /v1/chat/completions":      {},
	"POST /v1/responses":             {},
	"POST /v1/completions":           {},
	"POST /v1/embeddings":            {},
}

// Config is the proxy configuration. Mirrors model_proxy.ProxyConfig.
type Config struct {
	Upstream      string
	APIKey        string
	ListenHost    string
	ListenPort    int
	AuthStyle     string // "bearer" | "x-api-key"
	AllowHosts    map[string]struct{}
	ClientToken   string
	AllowedRoutes map[string]struct{}
}

// allowed returns the host allow-set: AllowHosts if set, else the single
// upstream host. Mirrors ProxyConfig.allowed().
func (c *Config) allowed() map[string]struct{} {
	if len(c.AllowHosts) > 0 {
		return c.AllowHosts
	}
	host := hostnameOf(c.Upstream)
	if host == "" {
		return map[string]struct{}{}
	}
	return map[string]struct{}{host: {}}
}

// configuredRoutes mirrors model_proxy._configured_routes: the configured set,
// or the safe defaults when none is configured.
func (c *Config) configuredRoutes() map[string]struct{} {
	if len(c.AllowedRoutes) > 0 {
		return c.AllowedRoutes
	}
	return DefaultAllowedRoutes
}

// hostnameOf returns the hostname of a URL the way Python's urlparse(...).hostname
// does: lowercased, without port or userinfo. Returns "" when absent.
func hostnameOf(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return ""
	}
	return strings.ToLower(u.Hostname())
}

// ParseAllowedRoutes mirrors model_proxy._parse_allowed_routes: split on commas
// or newlines, normalize each "METHOD /path" (upper method, leading-slash path).
func ParseAllowedRoutes(value string) map[string]struct{} {
	routes := map[string]struct{}{}
	if value == "" {
		return routes
	}
	for _, item := range strings.Split(strings.ReplaceAll(value, "\n", ","), ",") {
		route := strings.TrimSpace(item)
		if route == "" {
			continue
		}
		// Python: route.split(None, 1) -> [method, remainder]. Split on the first
		// run of whitespace and keep the remainder intact (then strip it).
		idx := strings.IndexFunc(route, unicode.IsSpace)
		if idx < 0 {
			continue // only one token (no path) -> skipped, like len(parts) != 2
		}
		method := strings.ToUpper(route[:idx])
		path := strings.TrimSpace(route[idx:])
		if path == "" {
			continue
		}
		if !strings.HasPrefix(path, "/") {
			path = "/" + path
		}
		routes[method+" "+path] = struct{}{}
	}
	return routes
}

// RouteAllowed mirrors model_proxy.route_allowed: the request's METHOD + clean
// path (query stripped, leading slash ensured) must be in the allow-set.
func RouteAllowed(c *Config, method, path string) bool {
	clean := pathOnly(path)
	if clean == "" {
		clean = "/"
	}
	if !strings.HasPrefix(clean, "/") {
		clean = "/" + clean
	}
	key := strings.ToUpper(method) + " " + clean
	_, ok := c.configuredRoutes()[key]
	return ok
}

// pathOnly returns urlparse(path).path: the path component with any query or
// fragment removed.
func pathOnly(path string) string {
	u, err := url.Parse(path)
	if err != nil {
		// Fall back to a manual strip so a malformed path still routes safely.
		if i := strings.IndexAny(path, "?#"); i >= 0 {
			return path[:i]
		}
		return path
	}
	return u.Path
}

// Authenticate mirrors model_proxy.authenticate: a constant-time check that the
// client presented either "Authorization: Bearer <client_token>" or the
// x-maverick-proxy-token header equal to the client token. No token configured
// means deny.
func Authenticate(c *Config, headers map[string]string) bool {
	if c.ClientToken == "" {
		return false
	}
	lowered := lowerHeaders(headers)
	bearer := strings.TrimSpace(lowered["authorization"])
	if constantTimeEqual(bearer, "Bearer "+c.ClientToken) {
		return true
	}
	return constantTimeEqual(strings.TrimSpace(lowered[proxyTokenHeader]), c.ClientToken)
}

// constantTimeEqual compares two strings in constant time, matching the intent
// of Python's hmac.compare_digest on the encoded bytes.
func constantTimeEqual(a, b string) bool {
	return subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

// BuildRequest mirrors model_proxy.build_request: resolve the upstream URL,
// enforce the host allow-set (SSRF guard), drop hop-by-hop + client auth
// headers, and inject the proxy's key in the upstream's scheme. Returns the
// outbound URL and headers, or an error if the host is outside the allow-set.
func BuildRequest(c *Config, path string, headers map[string]string) (string, map[string]string, error) {
	outURL := strings.TrimRight(c.Upstream, "/") + "/" + strings.TrimLeft(path, "/")
	host := hostnameOf(outURL)
	allowed := c.allowed()
	if _, ok := allowed[host]; !ok {
		return "", nil, &HostNotAllowedError{Host: host, Allowed: sortedKeys(allowed)}
	}
	out := map[string]string{}
	for k, v := range headers {
		lk := strings.ToLower(k)
		if _, hop := hopByHop[lk]; hop {
			continue
		}
		if _, auth := authHeaders[lk]; auth {
			continue
		}
		out[k] = v
	}
	if c.AuthStyle == "x-api-key" {
		out["x-api-key"] = c.APIKey
	} else {
		out["Authorization"] = "Bearer " + c.APIKey
	}
	return outURL, out, nil
}

// StripResponseHeaders drops hop-by-hop headers from an upstream response,
// mirroring the filtering in model_proxy.forward.
func StripResponseHeaders(headers map[string]string) map[string]string {
	out := map[string]string{}
	for k, v := range headers {
		if _, hop := hopByHop[strings.ToLower(k)]; hop {
			continue
		}
		out[k] = v
	}
	return out
}

func lowerHeaders(headers map[string]string) map[string]string {
	out := make(map[string]string, len(headers))
	for k, v := range headers {
		out[strings.ToLower(k)] = v
	}
	return out
}

func sortedKeys(m map[string]struct{}) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
