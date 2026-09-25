package audio

import (
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Proxy struct {
	baseURL      string
	serviceToken string
	client       *http.Client
}

func NewProxy(baseURL string, serviceToken string) Proxy {
	return Proxy{
		baseURL:      strings.TrimRight(baseURL, "/"),
		serviceToken: serviceToken,
		client: &http.Client{Transport: &http.Transport{
			Proxy:                 http.ProxyFromEnvironment,
			ResponseHeaderTimeout: 10 * time.Second,
		}},
	}
}

func (p Proxy) ServeAsset(w http.ResponseWriter, r *http.Request, assetID string) error {
	target := p.baseURL + "/api/internal/audio/assets/" + url.PathEscape(assetID) + "/stream/"
	request, err := http.NewRequestWithContext(r.Context(), http.MethodGet, target, nil)
	if err != nil {
		return err
	}
	request.Header.Set("Authorization", r.Header.Get("Authorization"))
	request.Header.Set("X-BrandyManager-Service-Token", p.serviceToken)
	for _, header := range []string{"Range", "If-None-Match", "If-Range", "X-Request-ID"} {
		if value := r.Header.Get(header); value != "" {
			request.Header.Set(header, value)
		}
	}

	response, err := p.client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()

	for _, header := range []string{
		"Accept-Ranges", "Cache-Control", "Content-Length", "Content-Range",
		"Content-Type", "ETag", "X-Content-Type-Options", "X-Request-ID",
	} {
		if value := response.Header.Get(header); value != "" {
			w.Header().Set(header, value)
		}
	}
	w.WriteHeader(response.StatusCode)
	_, _ = io.Copy(w, response.Body)
	return nil
}
