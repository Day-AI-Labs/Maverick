package proxy

import (
	"fmt"
	"strings"
)

// HostNotAllowedError is the SSRF guard failure from BuildRequest: the resolved
// upstream host is outside the allow-set. Its message mirrors the Python
// ValueError: `upstream host 'h' not in allow-set ['a', 'b']`.
type HostNotAllowedError struct {
	Host    string
	Allowed []string // sorted, like Python's sorted(allowed)
}

func (e *HostNotAllowedError) Error() string {
	quoted := make([]string, len(e.Allowed))
	for i, h := range e.Allowed {
		quoted[i] = "'" + h + "'"
	}
	return fmt.Sprintf("upstream host '%s' not in allow-set [%s]",
		e.Host, strings.Join(quoted, ", "))
}
