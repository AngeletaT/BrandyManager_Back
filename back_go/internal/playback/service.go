package playback

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"time"
)

type CommandRequest struct {
	DeviceID    string         `json:"device_id"`
	ZoneID      string         `json:"zone_id"`
	CommandType string         `json:"command_type"`
	Payload     map[string]any `json:"payload,omitempty"`
}

type Command struct {
	ID          string         `json:"id"`
	DeviceID    string         `json:"device_id,omitempty"`
	ZoneID      string         `json:"zone_id,omitempty"`
	CommandType string         `json:"command_type"`
	Payload     map[string]any `json:"payload,omitempty"`
	Status      string         `json:"status"`
	RequestedAt string         `json:"requested_at"`
}

type Service struct{}

func NewService() Service {
	return Service{}
}

func (s Service) QueueCommand(request CommandRequest) (Command, error) {
	if request.CommandType == "" {
		return Command{}, errors.New("command_type is required")
	}
	if request.DeviceID == "" && request.ZoneID == "" {
		return Command{}, errors.New("device_id or zone_id is required")
	}
	if !isAllowedCommand(request.CommandType) {
		return Command{}, errors.New("command_type is not supported")
	}

	return Command{
		ID:          newUUID(),
		DeviceID:    request.DeviceID,
		ZoneID:      request.ZoneID,
		CommandType: request.CommandType,
		Payload:     request.Payload,
		Status:      "accepted",
		RequestedAt: time.Now().UTC().Format(time.RFC3339),
	}, nil
}

func isAllowedCommand(commandType string) bool {
	switch commandType {
	case "set_volume", "change_channel", "pause", "resume", "skip", "sync", "restart", "refresh_configuration":
		return true
	default:
		return false
	}
}

func newUUID() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "00000000-0000-4000-8000-000000000000"
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return hex.EncodeToString(b[0:4]) + "-" +
		hex.EncodeToString(b[4:6]) + "-" +
		hex.EncodeToString(b[6:8]) + "-" +
		hex.EncodeToString(b[8:10]) + "-" +
		hex.EncodeToString(b[10:16])
}
