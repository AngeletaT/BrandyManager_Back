package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"time"
)

type healthResponse struct {
	Service string `json:"service"`
	Status  string `json:"status"`
	Time    string `json:"time"`
}

type playerStatusResponse struct {
	Service          string `json:"service"`
	Status           string `json:"status"`
	DjangoAPIBaseURL string `json:"django_api_base_url"`
}

func main() {
	port := getEnv("PORT", "8080")
	djangoAPIBaseURL := getEnv("DJANGO_API_BASE_URL", "http://back_django:8000")

	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/api/player/status", playerStatusHandler(djangoAPIBaseURL))

	server := &http.Server{
		Addr:              ":" + port,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}

	log.Printf("brandymanager go backend listening on :%s", port)
	if err := server.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}

func healthHandler(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, healthResponse{
		Service: "back_go",
		Status:  "ok",
		Time:    time.Now().UTC().Format(time.RFC3339),
	})
}

func playerStatusHandler(djangoAPIBaseURL string) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, playerStatusResponse{
			Service:          "back_go",
			Status:           "ready",
			DjangoAPIBaseURL: djangoAPIBaseURL,
		})
	}
}

func writeJSON(w http.ResponseWriter, statusCode int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		log.Printf("could not encode response: %v", err)
	}
}

func getEnv(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}
