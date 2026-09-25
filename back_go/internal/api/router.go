package api

import (
	"net/http"

	"brandymanager/back_go/internal/audio"
	"brandymanager/back_go/internal/config"
	"brandymanager/back_go/internal/django"
	"brandymanager/back_go/internal/operations"
	"brandymanager/back_go/internal/platform/middleware"
	"brandymanager/back_go/internal/platform/requestid"
	"brandymanager/back_go/internal/player"
)

func NewRouter(cfg config.Config) http.Handler {
	operationsService := operations.NewService()
	audioProxy := audio.NewProxy(cfg.DjangoAPIBaseURL, cfg.DjangoServiceToken)
	djangoClient := django.NewClient(cfg.DjangoAPIBaseURL, cfg.DjangoServiceToken, cfg.DjangoTimeout)
	playerService := player.NewService(djangoClient, cfg.PlayerCursorSecret, cfg.ManifestQueueSize)
	deviceAuth := middleware.NewDeviceAuthenticator(djangoClient, cfg.DeviceAuthCacheTTL)
	handler := handler{
		cfg:               cfg,
		operationsService: operationsService,
		audioProxy:        audioProxy,
		playerService:     playerService,
	}

	root := http.NewServeMux()
	root.HandleFunc("GET /health", handler.health)

	api := http.NewServeMux()
	api.HandleFunc("GET /api/system", handler.system)
	api.HandleFunc("GET /api/modules", handler.modules)
	api.HandleFunc("GET /api/modules/{module}/status", handler.moduleStatus)
	root.Handle("/api/", middleware.DjangoJWT(cfg.AuthMode)(api))

	playerAPI := http.NewServeMux()
	playerAPI.HandleFunc("GET /api/player/manifest/current", handler.playerManifest)
	playerAPI.HandleFunc("POST /api/player/manifest/refresh", handler.playerManifest)
	playerAPI.HandleFunc("GET /api/player/queue/current", handler.playerManifest)
	playerAPI.HandleFunc("POST /api/player/telemetry", handler.playerTelemetry)
	playerAPI.HandleFunc("POST /api/player/heartbeat", handler.playerHeartbeat)
	playerAPI.HandleFunc("GET /api/player/commands", handler.playerCommands)
	playerAPI.HandleFunc("POST /api/player/commands/{command_id}/ack", handler.playerCommandAck)
	playerAPI.HandleFunc("GET /api/player/audio/assets/{asset_id}/stream/", handler.streamAudioAsset)
	root.Handle("/api/player/", deviceAuth.Middleware(playerAPI))

	return requestid.Middleware(middleware.CORS(cfg.FrontendOrigins)(middleware.Recover(root)))
}
