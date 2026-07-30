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
		ServiceName:       "brandymanager-go-test",
		Environment:       "test",
		Port:              "0",
		DjangoAPIBaseURL:  "http://back_django:8000",
		AuthMode:          "passthrough",
		ReadHeaderTimeout: time.Second,
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

func TestAPIV1RequiresDjangoBearerToken(t *testing.T) {
	router := NewRouter(testConfig())
	request := httptest.NewRequest(http.MethodGet, "/api/v1/modules", nil)
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusUnauthorized {
		t.Fatalf("expected status %d, got %d", http.StatusUnauthorized, response.Code)
	}
}

func TestModulesReturnsOperationalDomains(t *testing.T) {
	router := NewRouter(testConfig())
	request := authenticatedRequest(http.MethodGet, "/api/v1/modules", nil)
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
	if body.Data[0].ManagedBy != "go" {
		t.Fatalf("expected module managed by go, got %q", body.Data[0].ManagedBy)
	}
}

func TestQueuePlaybackCommandAcceptsValidCommand(t *testing.T) {
	router := NewRouter(testConfig())
	payload := []byte(`{"zone_id":"zone-1","command_type":"pause"}`)
	request := authenticatedRequest(http.MethodPost, "/api/v1/playback/commands", bytes.NewReader(payload))
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusAccepted {
		t.Fatalf("expected status %d, got %d", http.StatusAccepted, response.Code)
	}
}

func TestQueuePlaybackCommandRejectsInvalidCommand(t *testing.T) {
	router := NewRouter(testConfig())
	payload := []byte(`{"zone_id":"zone-1","command_type":"unknown"}`)
	request := authenticatedRequest(http.MethodPost, "/api/v1/playback/commands", bytes.NewReader(payload))
	response := httptest.NewRecorder()

	router.ServeHTTP(response, request)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("expected status %d, got %d", http.StatusBadRequest, response.Code)
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
