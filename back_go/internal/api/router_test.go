package api

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"brandymanager/back_go/internal/config"
)

func testConfig() config.Config {
	return config.Config{
		ServiceName:        "brandymanager-go-test",
		Environment:        "test",
		Port:               "0",
		DjangoAPIBaseURL:   "http://back_django:8000",
		DjangoServiceToken: "service-token",
		AuthMode:           "passthrough",
		FrontendOrigins:    "http://localhost:5173",
		ReadHeaderTimeout:  time.Second,
	}
}

func TestHealthDoesNotRequireAuthentication(t *testing.T) {
	router := NewRouter(testConfig())
	request := httptest.NewRequest(http.MethodGet, "/health", nil)
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d", http.StatusOK, response.Code)
	}
}

func TestAPIRequiresDjangoBearerToken(t *testing.T) {
	router := NewRouter(testConfig())
	request := httptest.NewRequest(http.MethodGet, "/api/modules", nil)
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusUnauthorized {
		t.Fatalf("expected status %d, got %d", http.StatusUnauthorized, response.Code)
	}
}

func TestCORSPreflightAllowsFrontendOrigin(t *testing.T) {
	router := NewRouter(testConfig())
	request := httptest.NewRequest(http.MethodOptions, "/api/modules", nil)
	request.Header.Set("Origin", "http://localhost:5173")
	request.Header.Set("Access-Control-Request-Method", http.MethodGet)
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusNoContent {
		t.Fatalf("expected status %d, got %d", http.StatusNoContent, response.Code)
	}
	if response.Header().Get("Access-Control-Allow-Origin") != "http://localhost:5173" {
		t.Fatalf("expected frontend origin to be allowed")
	}
}

func TestModulesReturnsOperationalDomains(t *testing.T) {
	router := NewRouter(testConfig())
	request := authenticatedRequest(http.MethodGet, "/api/modules", nil)
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d", http.StatusOK, response.Code)
	}

	var body struct {
		Data []struct {
			Code      string `json:"code"`
			ManagedBy string `json:"managed_by"`
		} `json:"data"`
	}
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("could not decode response: %v", err)
	}
	if len(body.Data) == 0 {
		t.Fatal("expected at least one operational module")
	}
	managedByCode := map[string]string{}
	for _, module := range body.Data {
		managedByCode[module.Code] = module.ManagedBy
	}
	if managedByCode["scheduling"] != "django" {
		t.Fatalf("expected scheduling configuration managed by django, got %q", managedByCode["scheduling"])
	}
	if managedByCode["playback"] != "go" {
		t.Fatalf("expected playback managed by go, got %q", managedByCode["playback"])
	}
}

func TestAudioProxyForwardsDeviceAuthorizationRangeAndServiceToken(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer device.access.token" {
			t.Fatalf("device authorization was not forwarded")
		}
		if r.Header.Get("X-BrandyManager-Service-Token") != "service-token" {
			t.Fatalf("service token was not forwarded")
		}
		if r.URL.Path == "/api/internal/player-token/introspect/" {
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{
				"active": true, "device_id": "device-1", "company_id": "company-1",
				"zone_id": "zone-1", "credential_id": "credential-1", "expires_at": time.Now().Add(time.Minute).Unix(),
			})
			return
		}
		if r.Header.Get("Range") != "bytes=0-3" {
			t.Fatalf("range was not forwarded")
		}
		w.Header().Set("Content-Type", "audio/wav")
		w.Header().Set("Content-Range", "bytes 0-3/12")
		w.Header().Set("Accept-Ranges", "bytes")
		w.Header().Set("ETag", `"checksum"`)
		w.WriteHeader(http.StatusPartialContent)
		_, _ = w.Write([]byte("RIFF"))
	}))
	defer upstream.Close()

	cfg := testConfig()
	cfg.DjangoAPIBaseURL = upstream.URL
	router := NewRouter(cfg)
	request := httptest.NewRequest(http.MethodGet, "/api/player/audio/assets/asset-id/stream/", nil)
	request.Header.Set("Authorization", "Bearer device.access.token")
	request.Header.Set("Range", "bytes=0-3")
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusPartialContent {
		t.Fatalf("expected status %d, got %d", http.StatusPartialContent, response.Code)
	}
	if response.Body.String() != "RIFF" {
		t.Fatalf("expected proxied body, got %q", response.Body.String())
	}
	if response.Header().Get("Content-Range") != "bytes 0-3/12" {
		t.Fatalf("expected content range to be preserved")
	}
}

func authenticatedRequest(method string, target string, body *bytes.Reader) *http.Request {
	var reader io.Reader
	if body != nil {
		reader = body
	}
	request := httptest.NewRequest(method, target, reader)
	request.Header.Set("Authorization", "Bearer django.jwt.token")
	return request
}
