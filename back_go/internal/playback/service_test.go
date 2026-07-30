package playback

import "testing"

func TestQueueCommandRequiresCommandType(t *testing.T) {
	service := NewService()

	_, err := service.QueueCommand(CommandRequest{ZoneID: "zone-1"})

	if err == nil {
		t.Fatal("expected validation error")
	}
}

func TestQueueCommandRequiresDeviceOrZone(t *testing.T) {
	service := NewService()

	_, err := service.QueueCommand(CommandRequest{CommandType: "pause"})

	if err == nil {
		t.Fatal("expected validation error")
	}
}

func TestQueueCommandCreatesAcceptedCommand(t *testing.T) {
	service := NewService()

	command, err := service.QueueCommand(CommandRequest{
		ZoneID:      "zone-1",
		CommandType: "pause",
	})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if command.ID == "" {
		t.Fatal("expected command id")
	}
	if command.Status != "accepted" {
		t.Fatalf("expected accepted status, got %q", command.Status)
	}
}
