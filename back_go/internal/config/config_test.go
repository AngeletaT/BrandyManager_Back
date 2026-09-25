package config

import "testing"

func TestProductionRejectsPassthroughAndPlaceholderSecrets(t *testing.T) {
	base := Config{Environment: "production", AuthMode: "django_jwt", DjangoServiceToken: "real-service-token", PlayerCursorSecret: "real-cursor-secret"}
	if err := base.Validate(); err != nil {
		t.Fatalf("valid production config rejected: %v", err)
	}
	for name, mutate := range map[string]func(*Config){
		"passthrough":         func(c *Config) { c.AuthMode = "passthrough" },
		"service placeholder": func(c *Config) { c.DjangoServiceToken = "change-me-local-service-token" },
		"cursor placeholder":  func(c *Config) { c.PlayerCursorSecret = "change-me-local-player-cursor-secret" },
	} {
		t.Run(name, func(t *testing.T) {
			candidate := base
			mutate(&candidate)
			if err := candidate.Validate(); err == nil {
				t.Fatal("unsafe production configuration was accepted")
			}
		})
	}
}
