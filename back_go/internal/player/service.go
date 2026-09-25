package player

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	_ "time/tzdata"

	"brandymanager/back_go/internal/django"
)

type djangoClient interface {
	Runtime(context.Context, string, bool) (django.Runtime, error)
	Telemetry(context.Context, string, django.TelemetryBatch) (django.TelemetryResult, error)
	Commands(context.Context, string) ([]django.Command, error)
	Ack(context.Context, string, string, string, map[string]any, string) error
}

type Service struct {
	client         djangoClient
	cursorSecret   []byte
	manifestWindow int
	mu             sync.RWMutex
	cache          map[string]django.Runtime
}

type Manifest struct {
	ManifestID           string         `json:"manifest_id,omitempty"`
	DeviceID             string         `json:"device_id"`
	ChannelID            string         `json:"channel_id,omitempty"`
	ZoneID               string         `json:"zone_id"`
	ConfigurationVersion int            `json:"configuration_version"`
	PublishedVersion     int            `json:"published_version,omitempty"`
	GeneratedAt          time.Time      `json:"generated_at"`
	ValidUntil           time.Time      `json:"valid_until"`
	ServerTime           time.Time      `json:"server_time"`
	PlaybackPolicy       map[string]any `json:"playback_policy"`
	Current              *QueueItem     `json:"current"`
	PositionMS           int64          `json:"position_ms"`
	Next                 []QueueItem    `json:"next"`
	ContinuationToken    string         `json:"continuation_token,omitempty"`
	Reason               string         `json:"reason,omitempty"`
	ExecutionObserved    bool           `json:"execution_observed"`
	Offline              OfflinePolicy  `json:"offline"`
	Source               string         `json:"source"`
}

type OfflinePolicy struct {
	AuthorizedUntil time.Time `json:"authorized_until"`
	MaxItems        int       `json:"max_items"`
}

type QueueItem struct {
	AssetID            string `json:"asset_id"`
	AudioContentID     string `json:"audio_content_id"`
	Title              string `json:"title"`
	DurationMS         *int64 `json:"duration_ms"`
	MIMEType           string `json:"mime_type"`
	URL                string `json:"url"`
	ETag               string `json:"etag"`
	SizeBytes          int64  `json:"size_bytes"`
	OfflineCacheable   bool   `json:"offline_cacheable"`
	PlaylistSnapshotID string `json:"playlist_snapshot_id,omitempty"`
	SnapshotItemID     string `json:"snapshot_item_id,omitempty"`
}

type cursorPayload struct {
	ManifestID string `json:"m"`
	Version    int    `json:"v"`
	Index      int    `json:"i"`
	ExpiresAt  int64  `json:"e"`
}

func NewService(client djangoClient, cursorSecret string, manifestWindow int) *Service {
	if manifestWindow < 1 {
		manifestWindow = 10
	}
	return &Service{client: client, cursorSecret: []byte(cursorSecret), manifestWindow: manifestWindow, cache: make(map[string]django.Runtime)}
}

func (s *Service) Manifest(ctx context.Context, token, deviceID, cursor string, force bool, now time.Time) (Manifest, error) {
	runtime, source, err := s.runtime(ctx, token, deviceID, force, now)
	if err != nil {
		return Manifest{}, err
	}
	if runtime.Device.ID != deviceID {
		return Manifest{}, errors.New("runtime identity mismatch")
	}
	return s.build(runtime, cursor, now, source)
}

func (s *Service) runtime(ctx context.Context, token, deviceID string, force bool, now time.Time) (django.Runtime, string, error) {
	runtime, err := s.client.Runtime(ctx, token, force)
	if err == nil {
		if runtime.Manifest != nil && runtime.Manifest.ValidUntil.After(now) {
			s.mu.Lock()
			s.cache[deviceID] = runtime
			s.mu.Unlock()
		}
		return runtime, "django", nil
	}
	s.mu.RLock()
	cached, ok := s.cache[deviceID]
	s.mu.RUnlock()
	if ok && cached.Manifest != nil && cached.Manifest.ValidUntil.After(now) {
		return cached, "valid_published_cache", nil
	}
	return django.Runtime{}, "", fmt.Errorf("runtime unavailable: %w", err)
}

func (s *Service) build(runtime django.Runtime, cursor string, now time.Time, source string) (Manifest, error) {
	result := Manifest{
		DeviceID: runtime.Device.ID, ZoneID: runtime.Device.ZoneID, ChannelID: runtime.Device.ChannelID,
		ConfigurationVersion: runtime.Device.ConfigurationVersion, GeneratedAt: now, ServerTime: now,
		PlaybackPolicy: map[string]any{}, ExecutionObserved: false, Reason: runtime.Reason, Source: source,
	}
	if runtime.OperationalSnapshot != nil {
		result.PublishedVersion = runtime.OperationalSnapshot.Version
		result.ConfigurationVersion = runtime.OperationalSnapshot.Version
		result.PlaybackPolicy = runtime.OperationalSnapshot.PlaybackPolicy
	}
	if runtime.Manifest == nil {
		result.ValidUntil = now
		return result, nil
	}
	result.ManifestID = runtime.Manifest.ID
	result.GeneratedAt = runtime.Manifest.GeneratedAt
	result.ValidUntil = runtime.Manifest.ValidUntil
	result.Offline = OfflinePolicy{AuthorizedUntil: runtime.Manifest.ValidUntil, MaxItems: s.manifestWindow}
	if result.Reason != "" {
		return result, nil
	}

	assets, blockReason := resolveAssets(runtime, now)
	if blockReason != "" {
		result.Reason = blockReason
		return result, nil
	}
	if len(assets) == 0 {
		result.Reason = "NO_AVAILABLE_ASSETS"
		return result, nil
	}
	index, positionMS := deterministicPosition(assets, now)
	if cursor != "" {
		payload, err := s.verifyCursor(cursor, runtime.Manifest, result.ConfigurationVersion, now)
		if err != nil {
			return Manifest{}, err
		}
		index = payload.Index % len(assets)
		positionMS = 0
	}
	result.PositionMS = positionMS
	items := make([]QueueItem, 0, min(s.manifestWindow, len(assets)))
	for offset := 0; offset < s.manifestWindow && offset < len(assets); offset++ {
		items = append(items, assets[(index+offset)%len(assets)])
	}
	result.Current = &items[0]
	if len(items) > 1 {
		result.Next = items[1:]
	}
	result.ContinuationToken = s.signCursor(cursorPayload{
		ManifestID: runtime.Manifest.ID, Version: result.ConfigurationVersion,
		Index: (index + len(items)) % len(assets), ExpiresAt: runtime.Manifest.ValidUntil.Unix(),
	})
	return result, nil
}

func resolveAssets(runtime django.Runtime, now time.Time) ([]QueueItem, string) {
	if runtime.OperationalSnapshot == nil || runtime.Manifest == nil {
		return nil, runtime.Reason
	}
	schedule := runtime.OperationalSnapshot.Data.Schedule.SnapshotData
	location, err := time.LoadLocation(schedule.Timezone)
	if err != nil {
		return nil, "INVALID_SCHEDULE_TIMEZONE"
	}
	local := now.In(location)
	date := local.Format("2006-01-02")
	if schedule.ValidFrom != "" && date < schedule.ValidFrom {
		return nil, "NO_SCHEDULE_CONTENT"
	}
	if schedule.ValidUntil != "" && date > schedule.ValidUntil {
		return nil, "NO_SCHEDULE_CONTENT"
	}

	playlistID := ""
	for _, exception := range sortedExceptions(schedule.Exceptions) {
		if exception.Date == date && containsLocalTime(exception.StartTime, exception.EndTime, local) {
			if exception.Action == "SILENCE" {
				return nil, "SCHEDULED_SILENCE"
			}
			if exception.Action == "REPLACE" {
				playlistID = exception.PlaylistSnapshotID
				break
			}
		}
	}
	if playlistID == "" {
		pythonWeekday := (int(local.Weekday()) + 6) % 7
		matched := false
		for _, block := range sortedBlocks(schedule.Blocks) {
			if block.DayOfWeek != pythonWeekday || !containsLocalTime(block.StartTime, block.EndTime, local) {
				continue
			}
			matched = true
			if block.ContentType == "SILENCE" {
				return nil, "SCHEDULED_SILENCE"
			}
			if block.ContentType == "PLAYLIST" {
				playlistID = block.PlaylistSnapshotID
			}
			break
		}
		if !matched {
			return nil, "NO_SCHEDULE_CONTENT"
		}
	}

	manifestAssets := make(map[string]django.ManifestItem, len(runtime.Manifest.Items))
	for _, asset := range runtime.Manifest.Items {
		manifestAssets[asset.AssetID] = asset
	}
	snapshotAssets := append([]django.SnapshotAsset(nil), runtime.OperationalSnapshot.Data.Assets...)
	weights := make(map[string]int, len(runtime.OperationalSnapshot.Data.PlaylistSnapshots))
	priorities := make(map[string]int, len(runtime.OperationalSnapshot.Data.PlaylistSnapshots))
	active := make(map[string]bool, len(runtime.OperationalSnapshot.Data.PlaylistSnapshots))
	for _, reference := range runtime.OperationalSnapshot.Data.PlaylistSnapshots {
		weights[reference.PlaylistSnapshotID] = max(1, reference.Weight)
		priorities[reference.PlaylistSnapshotID] = reference.Priority
		active[reference.PlaylistSnapshotID] = withinAbsoluteWindow(now, reference.ActiveFrom, reference.ActiveUntil)
	}
	sort.SliceStable(snapshotAssets, func(i, j int) bool {
		leftPriority := priorities[snapshotAssets[i].PlaylistSnapshotID]
		rightPriority := priorities[snapshotAssets[j].PlaylistSnapshotID]
		if leftPriority != rightPriority {
			return leftPriority > rightPriority
		}
		if snapshotAssets[i].PlaylistSnapshotID == snapshotAssets[j].PlaylistSnapshotID {
			return snapshotAssets[i].Position < snapshotAssets[j].Position
		}
		return snapshotAssets[i].PlaylistSnapshotID < snapshotAssets[j].PlaylistSnapshotID
	})
	queue := make([]QueueItem, 0, len(snapshotAssets))
	type weightedItem struct {
		item   QueueItem
		weight int
	}
	weighted := make([]weightedItem, 0, len(snapshotAssets))
	for _, frozen := range snapshotAssets {
		if playlistID != "" && frozen.PlaylistSnapshotID != playlistID {
			continue
		}
		if isActive, known := active[frozen.PlaylistSnapshotID]; known && !isActive {
			continue
		}
		asset, ok := manifestAssets[frozen.AudioAssetID]
		if !frozen.AssetAvailable || !ok || asset.DurationMS == nil || *asset.DurationMS <= 0 {
			continue
		}
		item := QueueItem{
			AssetID: asset.AssetID, AudioContentID: asset.AudioContentID, Title: asset.Title,
			DurationMS: asset.DurationMS, MIMEType: asset.MIMEType, URL: asset.StreamPath,
			ETag: asset.ChecksumSHA256, SizeBytes: asset.SizeBytes, OfflineCacheable: asset.OfflineCacheable,
			PlaylistSnapshotID: frozen.PlaylistSnapshotID, SnapshotItemID: frozen.PlaylistSnapshotItemID,
		}
		weighted = append(weighted, weightedItem{item: item, weight: max(1, frozen.Weight) * max(1, weights[frozen.PlaylistSnapshotID])})
	}
	mode, _ := runtime.OperationalSnapshot.PlaybackPolicy["order_mode"].(string)
	seed := runtime.OperationalSnapshot.Checksum + ":" + local.Format("2006-01-02")
	if mode == "SHUFFLE" || mode == "WEIGHTED" {
		sort.SliceStable(weighted, func(i, j int) bool {
			left := deterministicScore(seed, weighted[i].item.SnapshotItemID, weighted[i].weight, mode == "WEIGHTED")
			right := deterministicScore(seed, weighted[j].item.SnapshotItemID, weighted[j].weight, mode == "WEIGHTED")
			if left == right {
				return weighted[i].item.SnapshotItemID < weighted[j].item.SnapshotItemID
			}
			return left < right
		})
	}
	for _, candidate := range weighted {
		queue = append(queue, candidate.item)
	}
	return queue, ""
}

func withinAbsoluteWindow(now time.Time, start, end string) bool {
	if start != "" {
		parsed, err := time.Parse(time.RFC3339, start)
		if err != nil || now.Before(parsed) {
			return false
		}
	}
	if end != "" {
		parsed, err := time.Parse(time.RFC3339, end)
		if err != nil || !now.Before(parsed) {
			return false
		}
	}
	return true
}

func deterministicScore(seed, itemID string, weight int, weighted bool) float64 {
	digest := sha256.Sum256([]byte(seed + ":" + itemID))
	value := binary.BigEndian.Uint64(digest[:8])
	u := (float64(value) + 1) / (float64(^uint64(0)) + 1)
	if weighted {
		return -math.Log(u) / float64(max(1, weight))
	}
	return u
}

func sortedBlocks(input []django.ScheduleBlock) []django.ScheduleBlock {
	out := append([]django.ScheduleBlock(nil), input...)
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Priority == out[j].Priority {
			return out[i].ID < out[j].ID
		}
		return out[i].Priority > out[j].Priority
	})
	return out
}
func sortedExceptions(input []django.ScheduleException) []django.ScheduleException {
	out := append([]django.ScheduleException(nil), input...)
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Priority == out[j].Priority {
			return out[i].ID < out[j].ID
		}
		return out[i].Priority > out[j].Priority
	})
	return out
}
func containsLocalTime(start, end string, local time.Time) bool {
	parse := func(value string) int {
		parts := strings.Split(value, ":")
		if len(parts) < 2 {
			return -1
		}
		h, _ := strconv.Atoi(parts[0])
		m, _ := strconv.Atoi(parts[1])
		sec := 0
		if len(parts) > 2 {
			sec, _ = strconv.Atoi(strings.Split(parts[2], ".")[0])
		}
		return h*3600 + m*60 + sec
	}
	s, e := parse(start), parse(end)
	current := local.Hour()*3600 + local.Minute()*60 + local.Second()
	return s >= 0 && e > s && current >= s && current < e
}
func deterministicPosition(items []QueueItem, now time.Time) (int, int64) {
	var cycle int64
	for _, item := range items {
		cycle += *item.DurationMS
	}
	if cycle <= 0 {
		return 0, 0
	}
	position := now.UnixMilli() % cycle
	for index, item := range items {
		if position < *item.DurationMS {
			return index, position
		}
		position -= *item.DurationMS
	}
	return 0, 0
}

func (s *Service) signCursor(payload cursorPayload) string {
	raw, _ := json.Marshal(payload)
	body := base64.RawURLEncoding.EncodeToString(raw)
	mac := hmac.New(sha256.New, s.cursorSecret)
	_, _ = mac.Write([]byte(body))
	return body + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
func (s *Service) verifyCursor(value string, manifest *django.RuntimeManifest, configurationVersion int, now time.Time) (cursorPayload, error) {
	parts := strings.Split(value, ".")
	if len(parts) != 2 {
		return cursorPayload{}, errors.New("invalid continuation token")
	}
	mac := hmac.New(sha256.New, s.cursorSecret)
	_, _ = mac.Write([]byte(parts[0]))
	signature, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil || !hmac.Equal(signature, mac.Sum(nil)) {
		return cursorPayload{}, errors.New("invalid continuation token")
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return cursorPayload{}, errors.New("invalid continuation token")
	}
	var payload cursorPayload
	if json.Unmarshal(raw, &payload) != nil || payload.ManifestID != manifest.ID || payload.Version != configurationVersion || payload.ExpiresAt <= now.Unix() {
		return cursorPayload{}, errors.New("stale continuation token")
	}
	return payload, nil
}

func (s *Service) Telemetry(ctx context.Context, token string, batch django.TelemetryBatch) (django.TelemetryResult, error) {
	return s.client.Telemetry(ctx, token, batch)
}
func (s *Service) Commands(ctx context.Context, token string) ([]django.Command, error) {
	return s.client.Commands(ctx, token)
}
func (s *Service) Ack(ctx context.Context, token, commandID, status string, result map[string]any, errorMessage string) error {
	return s.client.Ack(ctx, token, commandID, status, result, errorMessage)
}
