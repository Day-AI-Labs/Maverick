package proxy

import (
	"bytes"
	"io"
	"net/http"
	"strconv"
	"time"
)

// lastHeaderValue returns the last value of a (possibly multi-valued) header,
// matching Python's dict(headers) semantics in model_proxy.py: a duplicate
// header collapses to its LAST value, not a comma-join. Joining diverged from
// the source of truth on the auth-header comparison (a client sending two
// Authorization headers would be compared against "a, b").
func lastHeaderValue(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return values[len(values)-1]
}

// HTTPUpstream is the production Upstream over net/http. The response is
// buffered whole (matching the Python proxy: an SSE stream is forwarded
// complete), which keeps the proxy simple and correct.
type HTTPUpstream struct {
	Client *http.Client
}

// NewHTTPUpstream builds an upstream caller with the given per-request timeout
// (the Python default is 600s).
func NewHTTPUpstream(timeout time.Duration) *HTTPUpstream {
	return &HTTPUpstream{Client: &http.Client{Timeout: timeout}}
}

// Do issues the upstream request and buffers the response.
func (h *HTTPUpstream) Do(method, url string, headers map[string]string, body []byte) (int, map[string]string, []byte, error) {
	req, err := http.NewRequest(method, url, bytes.NewReader(body))
	if err != nil {
		return 0, nil, nil, err
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := h.Client.Do(req)
	if err != nil {
		return 0, nil, nil, err
	}
	defer resp.Body.Close()
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return 0, nil, nil, err
	}
	respHeaders := make(map[string]string, len(resp.Header))
	for k, vs := range resp.Header {
		respHeaders[k] = lastHeaderValue(vs)
	}
	return resp.StatusCode, respHeaders, respBody, nil
}

// Server is the net/http listener. Go serves each request on its own goroutine,
// so concurrent forwards run in parallel rather than being GIL-serialized the
// way Python's ThreadingHTTPServer is — the reason this path is in Go.
type Server struct {
	Config   *Config
	Upstream Upstream
}

// ServeHTTP implements http.Handler. It mirrors model_proxy.serve._Handler._do:
// read the body, hand the raw request to Handle, and write back the buffered
// result. self.path in Python includes the query string, so we pass the full
// request URI (RouteAllowed strips the query before matching).
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		body = nil
	}
	headers := make(map[string]string, len(r.Header))
	for k, vs := range r.Header {
		headers[k] = lastHeaderValue(vs)
	}
	status, respHeaders, out := Handle(s.Config, r.Method, r.URL.RequestURI(), headers, body, s.Upstream)
	for k, v := range respHeaders {
		w.Header().Set(k, v)
	}
	w.Header().Set("Content-Length", strconv.Itoa(len(out)))
	w.WriteHeader(status)
	_, _ = w.Write(out)
}
