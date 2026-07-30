package middleware

import (
	"net/http"
	"strings"

	"brandymanager/back_go/internal/platform/auth"
	"brandymanager/back_go/internal/platform/httpx"
)

func DjangoJWT(authMode string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if authMode == "disabled" {
				next.ServeHTTP(w, r.WithContext(auth.WithPrincipal(r.Context(), auth.Principal{
					Authenticated: false,
					Source:        "disabled",
				})))
				return
			}

			token := bearerToken(r.Header.Get("Authorization"))
			if token == "" {
				httpx.Error(w, http.StatusUnauthorized, "authentication_required", "Se requiere un token Bearer emitido por Django.")
				return
			}

			next.ServeHTTP(w, r.WithContext(auth.WithPrincipal(r.Context(), auth.Principal{
				Authenticated: true,
				Token:         token,
				Source:        "django_jwt",
			})))
		})
	}
}

func bearerToken(header string) string {
	const prefix = "Bearer "
	if !strings.HasPrefix(header, prefix) {
		return ""
	}
	return strings.TrimSpace(strings.TrimPrefix(header, prefix))
}
