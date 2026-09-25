package player

import (
	"context"
	"errors"
	"testing"
	"time"

	"brandymanager/back_go/internal/django"
)

type fakeDjango struct {
	runtime django.Runtime
	err     error
}

func (f *fakeDjango) Runtime(context.Context, string, bool) (django.Runtime, error) {
	return f.runtime, f.err
}
func (f *fakeDjango) Telemetry(context.Context, string, django.TelemetryBatch) (django.TelemetryResult, error) {
	return django.TelemetryResult{}, f.err
}
func (f *fakeDjango) Commands(context.Context, string) ([]django.Command, error) { return nil, f.err }
func (f *fakeDjango) Ack(context.Context, string, string, string, map[string]any, string) error {
	return f.err
}

func playableRuntime(now time.Time) django.Runtime {
	duration := int64(60000)
	runtime := django.Runtime{
		Device:              django.RuntimeDevice{ID: "device-1", CompanyID: "company-1", ZoneID: "zone-1", ChannelID: "channel-1", ConfigurationVersion: 7},
		Manifest:            &django.RuntimeManifest{ID: "manifest-1", Version: 3, GeneratedAt: now.Add(-time.Minute), ValidUntil: now.Add(time.Hour)},
		OperationalSnapshot: &django.OperationalSnapshot{ID: "snapshot-1", Version: 4, PlaybackPolicy: map[string]any{"order_mode": "SEQUENTIAL"}},
	}
	runtime.OperationalSnapshot.Data.Schedule.SnapshotData = django.ScheduleSnapshot{
		Timezone:   "Europe/Madrid",
		ValidFrom:  now.In(time.FixedZone("CEST", 7200)).Format("2006-01-02"),
		ValidUntil: now.In(time.FixedZone("CEST", 7200)).Format("2006-01-02"),
		Blocks:     []django.ScheduleBlock{{ID: "block-1", DayOfWeek: (int(now.In(time.FixedZone("CEST", 7200)).Weekday()) + 6) % 7, StartTime: "00:00:00", EndTime: "23:59:59", ContentType: "PLAYLIST", PlaylistSnapshotID: "playlist-snapshot-1"}},
	}
	runtime.OperationalSnapshot.Data.Assets = []django.SnapshotAsset{
		{PlaylistSnapshotID: "playlist-snapshot-1", PlaylistSnapshotItemID: "item-1", AudioContentID: "content-1", AudioAssetID: "asset-1", AssetAvailable: true, Position: 1},
		{PlaylistSnapshotID: "playlist-snapshot-1", PlaylistSnapshotItemID: "item-2", AudioContentID: "content-2", AudioAssetID: "asset-2", AssetAvailable: true, Position: 2},
	}
	runtime.Manifest.Items = []django.ManifestItem{
		{AssetID: "asset-1", AudioContentID: "content-1", Title: "One", DurationMS: &duration, MIMEType: "audio/wav", ChecksumSHA256: "etag-1", StreamPath: "/one", OfflineCacheable: true},
		{AssetID: "asset-2", AudioContentID: "content-2", Title: "Two", DurationMS: &duration, MIMEType: "audio/wav", ChecksumSHA256: "etag-2", StreamPath: "/two", OfflineCacheable: true},
	}
	return runtime
}

func TestManifestUsesPublishedSnapshotAndSignedCursor(t *testing.T) {
	now := time.Date(2026, 9, 7, 10, 0, 0, 0, time.UTC)
	client := &fakeDjango{runtime: playableRuntime(now)}
	service := NewService(client, "cursor-secret", 2)

	manifest, err := service.Manifest(context.Background(), "token", "device-1", "", false, now)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.ExecutionObserved {
		t.Fatal("configuration calculation must not claim observed execution")
	}
	if manifest.Current == nil || len(manifest.Next) != 1 {
		t.Fatalf("unexpected queue: %#v", manifest)
	}
	if manifest.ContinuationToken == "" {
		t.Fatal("missing signed cursor")
	}

	renewed, err := service.Manifest(context.Background(), "token", "device-1", manifest.ContinuationToken, false, now)
	if err != nil {
		t.Fatal(err)
	}
	if renewed.Current == nil {
		t.Fatal("renewed queue is empty")
	}
	if _, err := service.Manifest(context.Background(), "token", "device-1", manifest.ContinuationToken+"x", false, now); err == nil {
		t.Fatal("tampered cursor accepted")
	}
}

func TestManifestReportsNoScheduleWithoutFallback(t *testing.T) {
	now := time.Date(2026, 9, 7, 10, 0, 0, 0, time.UTC)
	runtime := playableRuntime(now)
	runtime.OperationalSnapshot.Data.Schedule.SnapshotData.Blocks = nil
	service := NewService(&fakeDjango{runtime: runtime}, "cursor-secret", 2)

	manifest, err := service.Manifest(context.Background(), "token", "device-1", "", false, now)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.Reason != "NO_SCHEDULE_CONTENT" || manifest.Current != nil {
		t.Fatalf("unexpected result: %#v", manifest)
	}
}

func TestRuntimeCacheNeverOutlivesManifestAuthorization(t *testing.T) {
	now := time.Date(2026, 9, 7, 10, 0, 0, 0, time.UTC)
	client := &fakeDjango{runtime: playableRuntime(now)}
	service := NewService(client, "cursor-secret", 2)
	if _, err := service.Manifest(context.Background(), "token", "device-1", "", false, now); err != nil {
		t.Fatal(err)
	}
	client.err = errors.New("django down")
	if manifest, err := service.Manifest(context.Background(), "token", "device-1", "", false, now.Add(time.Minute)); err != nil || manifest.Source != "valid_published_cache" {
		t.Fatalf("valid cache not used: %#v %v", manifest, err)
	}
	if _, err := service.Manifest(context.Background(), "token", "device-1", "", false, now.Add(2*time.Hour)); err == nil {
		t.Fatal("expired authorization cache was extended")
	}
}

func TestUnavailableAssetsAreNotQueued(t *testing.T) {
	now := time.Date(2026, 9, 7, 10, 0, 0, 0, time.UTC)
	runtime := playableRuntime(now)
	runtime.Manifest.Items = nil
	service := NewService(&fakeDjango{runtime: runtime}, "cursor-secret", 2)
	manifest, err := service.Manifest(context.Background(), "token", "device-1", "", false, now)
	if err != nil {
		t.Fatal(err)
	}
	if manifest.Reason != "NO_AVAILABLE_ASSETS" {
		t.Fatalf("unexpected reason %q", manifest.Reason)
	}
}

func TestShuffleIsDeterministicForPublishedVersionAndDay(t *testing.T) {
	now := time.Date(2026, 9, 7, 10, 0, 0, 0, time.UTC)
	runtime := playableRuntime(now)
	runtime.OperationalSnapshot.Checksum = "published-checksum"
	runtime.OperationalSnapshot.PlaybackPolicy["order_mode"] = "SHUFFLE"
	service := NewService(&fakeDjango{runtime: runtime}, "cursor-secret", 2)

	first, err := service.Manifest(context.Background(), "token", "device-1", "", false, now)
	if err != nil {
		t.Fatal(err)
	}
	second, err := service.Manifest(context.Background(), "token", "device-1", "", false, now)
	if err != nil {
		t.Fatal(err)
	}
	if first.Current == nil || second.Current == nil || first.Current.AssetID != second.Current.AssetID {
		t.Fatal("shuffle changed for the same published version and instant")
	}
}
