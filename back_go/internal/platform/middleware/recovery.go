package middleware

import (
	"log"
	"net/http"

	"brandymanager/back_go/internal/platform/httpx"
)

func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if err := recover(); err != nil {
				log.Printf("panic recovered: %v", err)
				httpx.Error(w, http.StatusInternalServerError, "internal_error", "Error interno del servicio Go.")
			}
		}()

		next.ServeHTTP(w, r)
	})
}
