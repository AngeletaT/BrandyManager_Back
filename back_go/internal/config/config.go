package config

import (
	"os"
	"time"
)

type Config struct {
	ServiceName       string
	Environment       string
	Port              string
	DjangoAPIBaseURL  string
	AuthMode          string
	ReadHeaderTimeout time.Duration
}

func Load() Config {
	return Config{
		ServiceName:       env("SERVICE_NAME", "brandymanager-go"),
		Environment:       env("APP_ENV", "local"),
		Port:              env("PORT", "8080"),
		DjangoAPIBaseURL:  env("DJANGO_API_BASE_URL", "http://back_django:8000"),
		AuthMode:          env("AUTH_MODE", "passthrough"),
		ReadHeaderTimeout: 5 * time.Second,
	}
}

func env(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}
