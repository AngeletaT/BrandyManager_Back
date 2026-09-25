package auth

import "context"

type Principal struct {
	Authenticated bool   `json:"authenticated"`
	Token         string `json:"-"`
	Source        string `json:"source"`
	DeviceID      string `json:"device_id,omitempty"`
	CompanyID     string `json:"company_id,omitempty"`
	ZoneID        string `json:"zone_id,omitempty"`
	CredentialID  string `json:"credential_id,omitempty"`
}

type contextKey struct{}

func WithPrincipal(ctx context.Context, principal Principal) context.Context {
	return context.WithValue(ctx, contextKey{}, principal)
}

func PrincipalFrom(ctx context.Context) (Principal, bool) {
	principal, ok := ctx.Value(contextKey{}).(Principal)
	return principal, ok
}
