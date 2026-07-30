package auth

import "context"

type Principal struct {
	Authenticated bool   `json:"authenticated"`
	Token         string `json:"-"`
	Source        string `json:"source"`
}

type contextKey struct{}

func WithPrincipal(ctx context.Context, principal Principal) context.Context {
	return context.WithValue(ctx, contextKey{}, principal)
}

func PrincipalFrom(ctx context.Context) (Principal, bool) {
	principal, ok := ctx.Value(contextKey{}).(Principal)
	return principal, ok
}
