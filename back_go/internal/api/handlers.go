package api

import (
	"encoding/json"
	"net/http"
	"time"

	"brandymanager/back_go/internal/config"
	"brandymanager/back_go/internal/operations"
	"brandymanager/back_go/internal/platform/httpx"
	"brandymanager/back_go/internal/playback"
)

type handler struct {
	cfg               config.Config
	operationsService operations.Service
	playbackService   playback.Service
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

func (h handler) queuePlaybackCommand(w http.ResponseWriter, r *http.Request) {
	var request playback.CommandRequest
	if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
		httpx.Error(w, http.StatusBadRequest, "invalid_json", "El cuerpo de la peticion no es JSON valido.")
		return
	}

	command, err := h.playbackService.QueueCommand(request)
	if err != nil {
		httpx.Error(w, http.StatusBadRequest, "invalid_playback_command", err.Error())
		return
	}

	httpx.Data(w, http.StatusAccepted, command)
}
