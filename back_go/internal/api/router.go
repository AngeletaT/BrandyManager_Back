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

	api := http.NewServeMux()
	api.HandleFunc("GET /api/system", handler.system)
	api.HandleFunc("GET /api/modules", handler.modules)
	api.HandleFunc("GET /api/modules/{module}/status", handler.moduleStatus)
	api.HandleFunc("POST /api/playback/commands", handler.queuePlaybackCommand)

	root.Handle("/api/", middleware.DjangoJWT(cfg.AuthMode)(api))

	return requestid.Middleware(middleware.Recover(root))
}
