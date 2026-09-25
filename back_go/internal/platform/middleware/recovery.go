package middleware

import (
	"log"
	"net/http"

	"brandymanager/back_go/internal/platform/httpx"
	"brandymanager/back_go/internal/platform/requestid"
)

func Recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if err := recover(); err != nil {
				log.Printf(`{"level":"error","event":"panic_recovered","request_id":%q}`, requestid.FromContext(r.Context()))
				httpx.Error(w, http.StatusInternalServerError, "internal_error", "Error interno del servicio Go.")
			}
		}()

		next.ServeHTTP(w, r)
	})
}
