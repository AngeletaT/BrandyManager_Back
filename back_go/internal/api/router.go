package api

import (
	"net/http"

	"brandymanager/back_go/internal/config"
	"brandymanager/back_go/internal/operations"
	"brandymanager/back_go/internal/platform/middleware"
	"brandymanager/back_go/internal/platform/requestid"
	"brandymanager/back_go/internal/playback"
)

func NewRouter(cfg config.Config) http.Handler {
	operationsService := operations.NewService()
	playbackService := playback.NewService()
	handler := handler{
		cfg:               cfg,
		operationsService: operationsService,
		playbackService:   playbackService,
	}

	root := http.NewServeMux()
	root.HandleFunc("GET /health", handler.health)

	apiV1 := http.NewServeMux()
	apiV1.HandleFunc("GET /api/v1/system", handler.system)
	apiV1.HandleFunc("GET /api/v1/modules", handler.modules)
	apiV1.HandleFunc("GET /api/v1/modules/{module}/status", handler.moduleStatus)
	apiV1.HandleFunc("POST /api/v1/playback/commands", handler.queuePlaybackCommand)

	root.Handle("/api/v1/", middleware.DjangoJWT(cfg.AuthMode)(apiV1))

	return requestid.Middleware(middleware.Recover(root))
}
