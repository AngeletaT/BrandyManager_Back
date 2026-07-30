package httpx

import (
	"encoding/json"
	"log"
	"net/http"
)

type Envelope struct {
	Data any `json:"data"`
	Meta any `json:"meta,omitempty"`
}

type ErrorEnvelope struct {
	Error APIError `json:"error"`
}

type APIError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func JSON(w http.ResponseWriter, statusCode int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		log.Printf("could not encode response: %v", err)
	}
}

func Data(w http.ResponseWriter, statusCode int, data any) {
	JSON(w, statusCode, Envelope{Data: data})
}

func Error(w http.ResponseWriter, statusCode int, code string, message string) {
	JSON(w, statusCode, ErrorEnvelope{
		Error: APIError{
			Code:    code,
			Message: message,
		},
	})
}
