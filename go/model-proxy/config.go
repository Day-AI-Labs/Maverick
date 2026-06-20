package proxy

import (
	"os"
	"strconv"
	"strings"
)

// ConfigFromEnv builds the proxy config from the proxy process's own
// environment (MAVERICK_PROXY_*), mirroring model_proxy.config_from_env.
//
// Unlike the Python original it does NOT fall back to the agent's TOML config:
// the whole point of running the proxy out-of-process is that its key and
// settings live in its OWN environment, which is also the documented deploy
// path. Returns nil when no upstream is configured.
func ConfigFromEnv() *Config {
	upstream := strings.TrimSpace(os.Getenv("MAVERICK_PROXY_UPSTREAM"))
	if upstream == "" {
		return nil
	}
	key := strings.TrimSpace(os.Getenv("MAVERICK_PROXY_KEY"))
	listen := strings.TrimSpace(os.Getenv("MAVERICK_PROXY_LISTEN"))
	authStyle := strings.ToLower(strings.TrimSpace(os.Getenv("MAVERICK_PROXY_AUTH_STYLE")))
	clientToken := strings.TrimSpace(os.Getenv("MAVERICK_PROXY_CLIENT_TOKEN"))
	allowedRoutes := ParseAllowedRoutes(os.Getenv("MAVERICK_PROXY_ALLOWED_ROUTES"))

	if authStyle != "bearer" && authStyle != "x-api-key" {
		authStyle = "bearer"
	}
	host, port := splitListen(listen)
	return &Config{
		Upstream:      upstream,
		APIKey:        key,
		ListenHost:    host,
		ListenPort:    port,
		AuthStyle:     authStyle,
		ClientToken:   clientToken,
		AllowedRoutes: allowedRoutes,
	}
}

// splitListen mirrors model_proxy._split_listen: "host:port", "host", or empty.
func splitListen(listen string) (string, int) {
	if listen == "" {
		return "127.0.0.1", DefaultPort
	}
	if strings.Contains(listen, ":") {
		i := strings.LastIndex(listen, ":")
		host, portStr := listen[:i], listen[i+1:]
		port, err := strconv.Atoi(portStr)
		if err != nil {
			return "127.0.0.1", DefaultPort
		}
		if host == "" {
			host = "127.0.0.1"
		}
		return host, port
	}
	return listen, DefaultPort
}
