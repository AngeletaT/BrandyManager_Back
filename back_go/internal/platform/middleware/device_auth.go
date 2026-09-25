package middleware

import (
	"context"
	"crypto/sha256"
	"errors"
	"net/http"
	"sync"
	"time"

	"brandymanager/back_go/internal/django"
	platformauth "brandymanager/back_go/internal/platform/auth"
	"brandymanager/back_go/internal/platform/httpx"
)

type introspector interface {
	Introspect(context.Context, string) (django.Principal, error)
}

type cachedPrincipal struct {
	principal django.Principal
	expires   time.Time
}

type DeviceAuthenticator struct {
	client introspector
	ttl    time.Duration
	mu     sync.Mutex
	cache  map[[32]byte]cachedPrincipal
}

func NewDeviceAuthenticator(client introspector, ttl time.Duration) *DeviceAuthenticator {
	if ttl <= 0 {
		ttl = 10 * time.Second
	}
	return &DeviceAuthenticator{client: client, ttl: ttl, cache: make(map[[32]byte]cachedPrincipal)}
}

func (a *DeviceAuthenticator) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		token := bearerToken(r.Header.Get("Authorization"))
		if token == "" {
			httpx.Error(w, http.StatusUnauthorized, "device_authentication_required", "Se requiere una credencial de dispositivo.")
			return
		}
		principal, err := a.authenticate(r.Context(), token)
		if err != nil {
			var upstream *django.UpstreamError
			if errors.As(err, &upstream) && upstream.Status >= 400 && upstream.Status < 500 {
				httpx.Error(w, http.StatusUnauthorized, "device_session_invalid", "La sesion del dispositivo no es valida.")
				return
			}
			httpx.Error(w, http.StatusServiceUnavailable, "device_authentication_unavailable", "No se pudo validar la sesion del dispositivo.")
			return
		}
		ctx := platformauth.WithPrincipal(r.Context(), platformauth.Principal{
			Authenticated: true, Token: token, Source: "device_introspection",
			DeviceID: principal.DeviceID, CompanyID: principal.CompanyID,
			ZoneID: principal.ZoneID, CredentialID: principal.CredentialID,
		})
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func (a *DeviceAuthenticator) authenticate(ctx context.Context, token string) (django.Principal, error) {
	now := time.Now()
	key := sha256.Sum256([]byte(token))
	a.mu.Lock()
	entry, ok := a.cache[key]
	if ok && now.Before(entry.expires) {
		a.mu.Unlock()
		return entry.principal, nil
	}
	delete(a.cache, key)
	a.mu.Unlock()

	principal, err := a.client.Introspect(ctx, token)
	if err != nil {
		return django.Principal{}, err
	}
	expires := now.Add(a.ttl)
	tokenExpiry := time.Unix(principal.ExpiresAt, 0)
	if tokenExpiry.Before(expires) {
		expires = tokenExpiry
	}
	if !principal.Active || !expires.After(now) {
		return django.Principal{}, errors.New("inactive device credential")
	}
	a.mu.Lock()
	if len(a.cache) > 2048 {
		for cachedKey, cached := range a.cache {
			if now.After(cached.expires) {
				delete(a.cache, cachedKey)
			}
		}
		if len(a.cache) > 2048 {
			for cachedKey := range a.cache {
				delete(a.cache, cachedKey)
				break
			}
		}
	}
	a.cache[key] = cachedPrincipal{principal: principal, expires: expires}
	a.mu.Unlock()
	return principal, nil
}
