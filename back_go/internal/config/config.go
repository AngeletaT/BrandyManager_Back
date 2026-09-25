package config

import (
	"errors"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	ServiceName        string
	Environment        string
	Port               string
	DjangoAPIBaseURL   string
	DjangoServiceToken string
	AuthMode           string
	FrontendOrigins    string
	ReadHeaderTimeout  time.Duration
	DjangoTimeout      time.Duration
	DeviceAuthCacheTTL time.Duration
	PlayerCursorSecret string
	ManifestQueueSize  int
	MaxTelemetryBytes  int64
}

func (c Config) Validate() error {
	if strings.EqualFold(c.Environment, "production") {
		if c.AuthMode != "django_jwt" {
			return errors.New("AUTH_MODE must validate Django JWTs in production")
		}
		if c.DjangoServiceToken == "" || strings.HasPrefix(c.DjangoServiceToken, "change-me-") {
			return errors.New("DJANGO_SERVICE_TOKEN must be configured in production")
		}
		if c.PlayerCursorSecret == "" || strings.HasPrefix(c.PlayerCursorSecret, "change-me-") {
			return errors.New("PLAYER_CURSOR_SECRET must be configured in production")
		}
	}
	return nil
}

func Load() Config {
	return Config{
		ServiceName:        env("SERVICE_NAME", "brandymanager-go"),
		Environment:        env("APP_ENV", "local"),
		Port:               env("PORT", "8080"),
		DjangoAPIBaseURL:   env("DJANGO_API_BASE_URL", "http://back_django:8000"),
		DjangoServiceToken: env("DJANGO_SERVICE_TOKEN", ""),
		AuthMode:           env("AUTH_MODE", "django_jwt"),
		FrontendOrigins:    env("FRONTEND_ORIGINS", "http://localhost:5173"),
		ReadHeaderTimeout:  5 * time.Second,
		DjangoTimeout:      durationEnv("DJANGO_TIMEOUT_SECONDS", 8*time.Second),
		DeviceAuthCacheTTL: durationEnv("DEVICE_AUTH_CACHE_SECONDS", 10*time.Second),
		PlayerCursorSecret: env("PLAYER_CURSOR_SECRET", env("DJANGO_SERVICE_TOKEN", "")),
		ManifestQueueSize:  intEnv("PLAYER_MANIFEST_QUEUE_SIZE", 10),
		MaxTelemetryBytes:  int64(intEnv("PLAYER_TELEMETRY_MAX_BYTES", 262144)),
	}
}

func env(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func intEnv(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed < 1 {
		return fallback
	}
	return parsed
}

func durationEnv(key string, fallback time.Duration) time.Duration {
	return time.Duration(intEnv(key, int(fallback/time.Second))) * time.Second
}
