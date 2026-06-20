package proxy

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// fakeUpstream records the last forwarded call and returns a canned response,
// the Go analogue of the Python tests' injected `client=`.
type fakeUpstream struct {
	status      int
	respHeaders map[string]string
	respBody    []byte
	err         error

	mu         sync.Mutex
	lastURL    string
	lastMethod string
	lastHeader map[string]string
	calls      int32
	delay      time.Duration
}

func (f *fakeUpstream) Do(method, url string, headers map[string]string, body []byte) (int, map[string]string, []byte, error) {
	atomic.AddInt32(&f.calls, 1)
	if f.delay > 0 {
		time.Sleep(f.delay)
	}
	f.mu.Lock()
	f.lastURL, f.lastMethod, f.lastHeader = url, method, headers
	f.mu.Unlock()
	if f.err != nil {
		return 0, nil, nil, f.err
	}
	return f.status, f.respHeaders, f.respBody, nil
}

func authedConfig() *Config {
	return &Config{
		Upstream:    "https://api.anthropic.com",
		APIKey:      "REAL_KEY",
		AuthStyle:   "bearer",
		ClientToken: "CLIENT",
	}
}

func authHeader() map[string]string {
	return map[string]string{"Authorization": "Bearer CLIENT"}
}

func TestHandleUnauthenticated(t *testing.T) {
	up := &fakeUpstream{status: 200}
	status, _, body := Handle(authedConfig(), "POST", "/v1/messages", map[string]string{}, nil, up)
	if status != 401 {
		t.Fatalf("status = %d, want 401", status)
	}
	if got := atomic.LoadInt32(&up.calls); got != 0 {
		t.Fatalf("upstream called %d times on auth failure, want 0", got)
	}
	if string(body) != "proxy authentication required" {
		t.Fatalf("body = %q", body)
	}
}

func TestHandleRouteNotAllowed(t *testing.T) {
	up := &fakeUpstream{status: 200}
	status, _, _ := Handle(authedConfig(), "POST", "/v1/secret", authHeader(), nil, up)
	if status != 403 {
		t.Fatalf("status = %d, want 403", status)
	}
	if atomic.LoadInt32(&up.calls) != 0 {
		t.Fatal("upstream called on disallowed route")
	}
}

func TestHandleForwardInjectsKeyAndStripsHopByHop(t *testing.T) {
	up := &fakeUpstream{
		status:      200,
		respHeaders: map[string]string{"Content-Type": "application/json", "Connection": "keep-alive"},
		respBody:    []byte(`{"ok":true}`),
	}
	reqHeaders := map[string]string{
		"Authorization": "Bearer CLIENT", // client cred -> stripped + replaced
		"Connection":    "keep-alive",    // hop-by-hop -> stripped
		"X-Trace":       "abc",           // passthrough
	}
	status, respHeaders, body := Handle(authedConfig(), "POST", "/v1/messages", reqHeaders, []byte("{}"), up)
	if status != 200 {
		t.Fatalf("status = %d, want 200", status)
	}
	if string(body) != `{"ok":true}` {
		t.Fatalf("body = %q", body)
	}
	if _, leaked := respHeaders["Connection"]; leaked {
		t.Fatal("hop-by-hop Connection leaked in response headers")
	}
	// The forwarded request must carry the REAL key, not the client's.
	up.mu.Lock()
	defer up.mu.Unlock()
	if up.lastHeader["Authorization"] != "Bearer REAL_KEY" {
		t.Fatalf("injected auth = %q, want 'Bearer REAL_KEY'", up.lastHeader["Authorization"])
	}
	if _, ok := up.lastHeader["Connection"]; ok {
		t.Fatal("hop-by-hop Connection forwarded upstream")
	}
	if up.lastHeader["X-Trace"] != "abc" {
		t.Fatal("passthrough header dropped")
	}
	if up.lastURL != "https://api.anthropic.com/v1/messages" {
		t.Fatalf("upstream url = %q", up.lastURL)
	}
}

func TestHandleBlockedHostSSRF(t *testing.T) {
	up := &fakeUpstream{status: 200}
	// The host allow-set is the structural SSRF guard: the resolved upstream host
	// (always the configured upstream, since the path is appended to it) must be
	// in the allow-set. Configure an allow-set that EXCLUDES the upstream host and
	// the request must be refused 403, never forwarded. (An absolute URL in the
	// path can't redirect the host — it just becomes part of the upstream path —
	// which the parity fixture confirms against Python.)
	cfg := authedConfig()
	cfg.AllowHosts = map[string]struct{}{"api.openai.com": {}}
	status, _, body := Handle(cfg, "POST", "/v1/messages", authHeader(), nil, up)
	if status != 403 {
		t.Fatalf("status = %d, want 403", status)
	}
	if atomic.LoadInt32(&up.calls) != 0 {
		t.Fatal("blocked-host request was forwarded")
	}
	if !strings.Contains(string(body), "not in allow-set") {
		t.Fatalf("body = %q", body)
	}
}

func TestHandleUpstreamErrorIs502(t *testing.T) {
	up := &fakeUpstream{err: fmt.Errorf("dial tcp: connection refused")}
	status, _, body := Handle(authedConfig(), "POST", "/v1/messages", authHeader(), nil, up)
	if status != 502 {
		t.Fatalf("status = %d, want 502", status)
	}
	if !strings.HasPrefix(string(body), "proxy error: ") {
		t.Fatalf("body = %q", body)
	}
}

func TestServeHTTPEndToEnd(t *testing.T) {
	up := &fakeUpstream{status: 201, respHeaders: map[string]string{"Content-Type": "application/json"}, respBody: []byte(`{"id":1}`)}
	srv := &Server{Config: authedConfig(), Upstream: up}
	ts := httptest.NewServer(srv)
	defer ts.Close()

	req, _ := http.NewRequest("POST", ts.URL+"/v1/messages?beta=1", strings.NewReader("{}"))
	req.Header.Set("Authorization", "Bearer CLIENT")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 201 {
		t.Fatalf("status = %d, want 201", resp.StatusCode)
	}
	got, _ := io.ReadAll(resp.Body)
	if string(got) != `{"id":1}` {
		t.Fatalf("body = %q", got)
	}
	// Query string is preserved into the upstream URL (matches Python self.path).
	up.mu.Lock()
	defer up.mu.Unlock()
	if up.lastURL != "https://api.anthropic.com/v1/messages?beta=1" {
		t.Fatalf("upstream url = %q", up.lastURL)
	}
}

// TestConcurrentForwards is the reason this is in Go: many in-flight requests
// are served on separate goroutines, so a slow upstream does not serialize them
// the way Python's GIL would. With 50 concurrent calls each delayed 20ms, total
// wall time must stay far below the serialized 1s.
func TestConcurrentForwards(t *testing.T) {
	up := &fakeUpstream{status: 200, respBody: []byte("ok"), delay: 20 * time.Millisecond}
	srv := &Server{Config: authedConfig(), Upstream: up}
	ts := httptest.NewServer(srv)
	defer ts.Close()

	const n = 50
	start := time.Now()
	var wg sync.WaitGroup
	errs := make(chan error, n)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			req, _ := http.NewRequest("POST", ts.URL+"/v1/messages", strings.NewReader("{}"))
			req.Header.Set("Authorization", "Bearer CLIENT")
			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				errs <- err
				return
			}
			resp.Body.Close()
			if resp.StatusCode != 200 {
				errs <- fmt.Errorf("status %d", resp.StatusCode)
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Fatal(err)
	}
	if elapsed := time.Since(start); elapsed > 500*time.Millisecond {
		t.Fatalf("50 concurrent 20ms calls took %v; not running concurrently", elapsed)
	}
	if got := atomic.LoadInt32(&up.calls); got != n {
		t.Fatalf("upstream calls = %d, want %d", got, n)
	}
}

// Regression: a multi-valued header collapses to its LAST value (Python's
// dict(headers)), not a comma-join. A client sending two Authorization headers
// must be compared against the last one, matching model_proxy.py.
func TestLastHeaderValue(t *testing.T) {
	cases := []struct {
		in   []string
		want string
	}{
		{nil, ""},
		{[]string{}, ""},
		{[]string{"only"}, "only"},
		{[]string{"first", "second"}, "second"},
		{[]string{"a", "b", "c"}, "c"},
	}
	for _, c := range cases {
		if got := lastHeaderValue(c.in); got != c.want {
			t.Errorf("lastHeaderValue(%v) = %q, want %q", c.in, got, c.want)
		}
	}
}

func TestServeHTTPDuplicateAuthUsesLast(t *testing.T) {
	up := &fakeUpstream{status: 200, respBody: []byte("ok")}
	srv := &Server{Config: authedConfig(), Upstream: up}
	ts := httptest.NewServer(srv)
	defer ts.Close()

	// Two Authorization headers: the last must be the one auth sees. Send the
	// wrong one first, the correct token last -> request is authorized.
	req, _ := http.NewRequest("POST", ts.URL+"/v1/messages", strings.NewReader("{}"))
	req.Header.Add("Authorization", "Bearer WRONG")
	req.Header.Add("Authorization", "Bearer CLIENT")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("status = %d, want 200 (last Authorization value should authorize)", resp.StatusCode)
	}
}
