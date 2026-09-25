package django

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"brandymanager/back_go/internal/platform/requestid"
)

const maxResponseBytes = 2 << 20

type Client struct {
	baseURL      string
	serviceToken string
	httpClient   *http.Client
}

type UpstreamError struct {
	Status int
	Code   string
}

func (e *UpstreamError) Error() string {
	return fmt.Sprintf("django upstream returned %d (%s)", e.Status, e.Code)
}

type Principal struct {
	Active       bool   `json:"active"`
	DeviceID     string `json:"device_id"`
	CompanyID    string `json:"company_id"`
	ZoneID       string `json:"zone_id"`
	CredentialID string `json:"credential_id"`
	ExpiresAt    int64  `json:"expires_at"`
}

type Runtime struct {
	Device              RuntimeDevice        `json:"device"`
	Reason              string               `json:"reason"`
	OperationalSnapshot *OperationalSnapshot `json:"operational_snapshot"`
	Manifest            *RuntimeManifest     `json:"manifest"`
}

type RuntimeDevice struct {
	ID                   string `json:"id"`
	CompanyID            string `json:"company_id"`
	ZoneID               string `json:"zone_id"`
	ChannelID            string `json:"channel_id"`
	ConfigurationVersion int    `json:"configuration_version"`
	ZoneTimezone         string `json:"zone_timezone"`
}

type OperationalSnapshot struct {
	ID                 string         `json:"id"`
	Version            int            `json:"version"`
	Checksum           string         `json:"checksum"`
	GeneratedAt        time.Time      `json:"generated_at"`
	ChannelID          string         `json:"channel_id"`
	ChannelSnapshotID  string         `json:"channel_snapshot_id"`
	ScheduleSnapshotID string         `json:"schedule_snapshot_id"`
	Data               SnapshotData   `json:"data"`
	PlaybackPolicy     map[string]any `json:"playback_policy"`
}

type SnapshotData struct {
	Zone struct {
		ID        string `json:"id"`
		SiteID    string `json:"site_id"`
		CompanyID string `json:"company_id"`
		Timezone  string `json:"timezone"`
	} `json:"zone"`
	Schedule struct {
		SnapshotID      string           `json:"snapshot_id"`
		SnapshotVersion int              `json:"snapshot_version"`
		SnapshotData    ScheduleSnapshot `json:"snapshot_data"`
	} `json:"schedule"`
	PlaylistSnapshots []PlaylistSnapshotReference `json:"playlist_snapshots"`
	Assets            []SnapshotAsset             `json:"assets"`
}

type PlaylistSnapshotReference struct {
	PlaylistSnapshotID string `json:"playlist_snapshot_id"`
	Weight             int    `json:"weight"`
	Priority           int    `json:"priority"`
	ActiveFrom         string `json:"active_from"`
	ActiveUntil        string `json:"active_until"`
}

type ScheduleSnapshot struct {
	ScheduleID      string              `json:"schedule_id"`
	ScheduleVersion int                 `json:"schedule_version"`
	Timezone        string              `json:"timezone"`
	ValidFrom       string              `json:"valid_from"`
	ValidUntil      string              `json:"valid_until"`
	Blocks          []ScheduleBlock     `json:"blocks"`
	Exceptions      []ScheduleException `json:"exceptions"`
}

type ScheduleBlock struct {
	ID                 string `json:"id"`
	DayOfWeek          int    `json:"day_of_week"`
	StartTime          string `json:"start_time"`
	EndTime            string `json:"end_time"`
	ContentType        string `json:"content_type"`
	PlaylistSnapshotID string `json:"playlist_snapshot_id"`
	ChannelSnapshotID  string `json:"channel_snapshot_id"`
	Priority           int    `json:"priority"`
	VolumeOverride     *int   `json:"volume_override"`
}

type ScheduleException struct {
	ID                 string `json:"id"`
	Date               string `json:"date"`
	StartTime          string `json:"start_time"`
	EndTime            string `json:"end_time"`
	Action             string `json:"action"`
	PlaylistSnapshotID string `json:"playlist_snapshot_id"`
	Priority           int    `json:"priority"`
	VolumeOverride     *int   `json:"volume_override"`
}

type SnapshotAsset struct {
	PlaylistSnapshotID     string `json:"playlist_snapshot_id"`
	PlaylistSnapshotItemID string `json:"playlist_snapshot_item_id"`
	AudioContentID         string `json:"audio_content_id"`
	AudioAssetID           string `json:"audio_asset_id"`
	AssetAvailable         bool   `json:"asset_available"`
	Position               int    `json:"position"`
	Weight                 int    `json:"weight"`
}

type RuntimeManifest struct {
	ID             string         `json:"id"`
	Version        int            `json:"version"`
	Status         string         `json:"status"`
	Checksum       string         `json:"checksum"`
	GeneratedAt    time.Time      `json:"generated_at"`
	ValidFrom      time.Time      `json:"valid_from"`
	ValidUntil     time.Time      `json:"valid_until"`
	TotalSizeBytes int64          `json:"total_size_bytes"`
	Items          []ManifestItem `json:"items"`
}

type ManifestItem struct {
	AssetID          string `json:"asset_id"`
	AudioContentID   string `json:"audio_content_id"`
	Title            string `json:"title"`
	DurationMS       *int64 `json:"duration_ms"`
	MIMEType         string `json:"mime_type"`
	ChecksumSHA256   string `json:"checksum_sha256"`
	SizeBytes        int64  `json:"size_bytes"`
	StreamPath       string `json:"stream_path"`
	OfflineCacheable bool   `json:"offline_cacheable"`
}

type TelemetryBatch struct {
	Events []TelemetryEvent `json:"events"`
}
type TelemetryEvent struct {
	EventID              string         `json:"event_id"`
	Sequence             uint64         `json:"sequence"`
	OccurredAt           time.Time      `json:"occurred_at"`
	ManifestID           string         `json:"manifest_id,omitempty"`
	ConfigurationVersion int            `json:"configuration_version,omitempty"`
	AssetID              string         `json:"asset_id,omitempty"`
	EventType            string         `json:"event_type"`
	PositionMS           *int64         `json:"position_ms,omitempty"`
	PlaybackStatus       string         `json:"playback_status,omitempty"`
	Volume               *int           `json:"volume,omitempty"`
	ErrorCode            string         `json:"error_code,omitempty"`
	AppVersion           string         `json:"app_version,omitempty"`
	Technical            map[string]any `json:"technical,omitempty"`
}

type TelemetryResult struct {
	Accepted     int       `json:"accepted"`
	Duplicates   int       `json:"duplicates"`
	LastSequence uint64    `json:"last_sequence"`
	ReceivedAt   time.Time `json:"received_at"`
}

type Command struct {
	CommandID string         `json:"command_id"`
	Type      string         `json:"type"`
	Payload   map[string]any `json:"payload"`
	IssuedAt  time.Time      `json:"issued_at"`
	ExpiresAt time.Time      `json:"expires_at"`
	Status    string         `json:"status"`
}

func NewClient(baseURL, serviceToken string, timeout time.Duration) *Client {
	return &Client{baseURL: strings.TrimRight(baseURL, "/"), serviceToken: serviceToken, httpClient: &http.Client{Timeout: timeout}}
}

func (c *Client) Introspect(ctx context.Context, token string) (Principal, error) {
	var out Principal
	err := c.do(ctx, http.MethodPost, "/api/internal/player-token/introspect/", token, map[string]string{"token": token}, &out)
	return out, err
}

func (c *Client) Runtime(ctx context.Context, token string, force bool) (Runtime, error) {
	var out Runtime
	method := http.MethodGet
	if force {
		method = http.MethodPost
	}
	err := c.do(ctx, method, "/api/internal/player/runtime/", token, nil, &out)
	return out, err
}

func (c *Client) Telemetry(ctx context.Context, token string, batch TelemetryBatch) (TelemetryResult, error) {
	var out TelemetryResult
	err := c.do(ctx, http.MethodPost, "/api/internal/player/telemetry/", token, batch, &out)
	return out, err
}

func (c *Client) Commands(ctx context.Context, token string) ([]Command, error) {
	var out struct {
		Commands []Command `json:"commands"`
	}
	err := c.do(ctx, http.MethodGet, "/api/internal/player/commands/", token, nil, &out)
	return out.Commands, err
}

func (c *Client) Ack(ctx context.Context, token, commandID, status string, result map[string]any, errorMessage string) error {
	path := "/api/internal/player/commands/" + url.PathEscape(commandID) + "/ack/"
	return c.do(ctx, http.MethodPost, path, token, map[string]any{"status": status, "result": result, "error_message": errorMessage}, nil)
}

func (c *Client) do(ctx context.Context, method, path, token string, body, out any) error {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-BrandyManager-Service-Token", c.serviceToken)
	req.Header.Set("Content-Type", "application/json")
	if id := requestid.FromContext(ctx); id != "" {
		req.Header.Set("X-Request-ID", id)
	}
	res, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	limited := io.LimitReader(res.Body, maxResponseBytes+1)
	payload, err := io.ReadAll(limited)
	if err != nil {
		return err
	}
	if len(payload) > maxResponseBytes {
		return errors.New("django response exceeded size limit")
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		var envelope struct {
			Error struct {
				Code string `json:"code"`
			} `json:"error"`
		}
		_ = json.Unmarshal(payload, &envelope)
		return &UpstreamError{Status: res.StatusCode, Code: envelope.Error.Code}
	}
	if out != nil && len(payload) > 0 {
		return json.Unmarshal(payload, out)
	}
	return nil
}
