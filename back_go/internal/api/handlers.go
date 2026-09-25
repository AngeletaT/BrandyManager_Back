package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"brandymanager/back_go/internal/audio"
	"brandymanager/back_go/internal/config"
	"brandymanager/back_go/internal/django"
	"brandymanager/back_go/internal/operations"
	platformauth "brandymanager/back_go/internal/platform/auth"
	"brandymanager/back_go/internal/platform/httpx"
	"brandymanager/back_go/internal/player"
)

type handler struct {
	cfg               config.Config
	operationsService operations.Service
	audioProxy        audio.Proxy
	playerService     *player.Service
}

type healthResponse struct {
	Service string `json:"service"`
	Status  string `json:"status"`
	Time    string `json:"time"`
}

type systemResponse struct {
	Service            string                `json:"service"`
	Environment        string                `json:"environment"`
	DjangoAPIBaseURL   string                `json:"django_api_base_url"`
	AuthMode           string                `json:"auth_mode"`
	Boundaries         []operations.Boundary `json:"boundaries"`
	OperationalModules []operations.Module   `json:"operational_modules"`
}

func (h handler) health(w http.ResponseWriter, _ *http.Request) {
	httpx.Data(w, http.StatusOK, healthResponse{
		Service: h.cfg.ServiceName,
		Status:  "ok",
		Time:    time.Now().UTC().Format(time.RFC3339),
	})
}

func (h handler) system(w http.ResponseWriter, _ *http.Request) {
	httpx.Data(w, http.StatusOK, systemResponse{
		Service:            h.cfg.ServiceName,
		Environment:        h.cfg.Environment,
		DjangoAPIBaseURL:   h.cfg.DjangoAPIBaseURL,
		AuthMode:           h.cfg.AuthMode,
		Boundaries:         h.operationsService.Boundaries(),
		OperationalModules: h.operationsService.Modules(),
	})
}

func (h handler) modules(w http.ResponseWriter, _ *http.Request) {
	httpx.Data(w, http.StatusOK, h.operationsService.Modules())
}

func (h handler) moduleStatus(w http.ResponseWriter, r *http.Request) {
	module, err := h.operationsService.ModuleStatus(r.PathValue("module"))
	if err != nil {
		httpx.Error(w, http.StatusNotFound, "module_not_found", "El modulo operativo no existe.")
		return
	}

	httpx.Data(w, http.StatusOK, module)
}

func (h handler) streamAudioAsset(w http.ResponseWriter, r *http.Request) {
	if h.cfg.DjangoServiceToken == "" {
		httpx.Error(w, http.StatusServiceUnavailable, "audio_service_unavailable", "La entrega de audio no esta configurada.")
		return
	}
	if err := h.audioProxy.ServeAsset(w, r, r.PathValue("asset_id")); err != nil {
		httpx.Error(w, http.StatusBadGateway, "audio_upstream_unavailable", "No se pudo obtener el audio autorizado.")
	}
}

func (h handler) playerManifest(w http.ResponseWriter, r *http.Request) {
	principal, ok := platformauth.PrincipalFrom(r.Context())
	if !ok {
		httpx.Error(w, http.StatusUnauthorized, "device_session_invalid", "La sesion del dispositivo no es valida.")
		return
	}
	manifest, err := h.playerService.Manifest(
		r.Context(), principal.Token, principal.DeviceID, r.URL.Query().Get("cursor"),
		r.Method == http.MethodPost, time.Now().UTC(),
	)
	if err != nil {
		if strings.Contains(err.Error(), "continuation token") {
			httpx.Error(w, http.StatusConflict, "queue_cursor_invalid", "La cola ha cambiado; solicita un manifiesto nuevo.")
			return
		}
		httpx.Error(w, http.StatusServiceUnavailable, "runtime_unavailable", "La configuracion publicada no esta disponible.")
		return
	}
	httpx.Data(w, http.StatusOK, manifest)
}

func (h handler) playerTelemetry(w http.ResponseWriter, r *http.Request) {
	principal, _ := platformauth.PrincipalFrom(r.Context())
	r.Body = http.MaxBytesReader(w, r.Body, h.cfg.MaxTelemetryBytes)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var batch django.TelemetryBatch
	if err := decoder.Decode(&batch); err != nil {
		httpx.Error(w, http.StatusBadRequest, "invalid_telemetry", "El lote de telemetria no es valido.")
		return
	}
	if len(batch.Events) == 0 || len(batch.Events) > 100 {
		httpx.Error(w, http.StatusBadRequest, "invalid_telemetry", "El lote debe contener entre 1 y 100 eventos.")
		return
	}
	result, err := h.playerService.Telemetry(r.Context(), principal.Token, batch)
	if err != nil {
		h.playerUpstreamError(w, err)
		return
	}
	httpx.Data(w, http.StatusAccepted, result)
}

func (h handler) playerHeartbeat(w http.ResponseWriter, r *http.Request) {
	h.playerTelemetry(w, r)
}

func (h handler) playerCommands(w http.ResponseWriter, r *http.Request) {
	principal, _ := platformauth.PrincipalFrom(r.Context())
	commands, err := h.playerService.Commands(r.Context(), principal.Token)
	if err != nil {
		h.playerUpstreamError(w, err)
		return
	}
	httpx.Data(w, http.StatusOK, map[string]any{"commands": commands})
}

func (h handler) playerCommandAck(w http.ResponseWriter, r *http.Request) {
	principal, _ := platformauth.PrincipalFrom(r.Context())
	r.Body = http.MaxBytesReader(w, r.Body, 32768)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var request struct {
		Status       string         `json:"status"`
		Result       map[string]any `json:"result"`
		ErrorMessage string         `json:"error_message"`
	}
	if err := decoder.Decode(&request); err != nil {
		httpx.Error(w, http.StatusBadRequest, "invalid_command_ack", "El acuse no es valido.")
		return
	}
	if request.Status != "ACKNOWLEDGED" && request.Status != "EXECUTED" && request.Status != "FAILED" {
		httpx.Error(w, http.StatusBadRequest, "invalid_command_ack", "El estado no es valido.")
		return
	}
	if err := h.playerService.Ack(r.Context(), principal.Token, r.PathValue("command_id"), request.Status, request.Result, request.ErrorMessage); err != nil {
		h.playerUpstreamError(w, err)
		return
	}
	httpx.Data(w, http.StatusOK, map[string]string{"command_id": r.PathValue("command_id"), "status": request.Status})
}

func (h handler) playerUpstreamError(w http.ResponseWriter, err error) {
	var upstream *django.UpstreamError
	if errors.As(err, &upstream) && upstream.Status >= 400 && upstream.Status < 500 {
		httpx.Error(w, upstream.Status, "player_request_rejected", "Django rechazo la operacion del dispositivo.")
		return
	}
	httpx.Error(w, http.StatusServiceUnavailable, "player_service_unavailable", "El servicio operativo no esta disponible.")
}
