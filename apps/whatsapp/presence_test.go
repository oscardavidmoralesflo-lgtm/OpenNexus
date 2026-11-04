package main

import (
	"context"
	"sync"
	"testing"
	"time"

	"go.mau.fi/whatsmeow/proto/waCompanionReg"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/types"
)

type presenceRecorder struct {
	mu   sync.Mutex
	sent []types.Presence
}

func (r *presenceRecorder) SendPresence(_ context.Context, state types.Presence) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.sent = append(r.sent, state)
	return nil
}

func (r *presenceRecorder) states() []types.Presence {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]types.Presence(nil), r.sent...)
}

func TestPresenceGoesOnlineOnceAndOfflineWhenIdle(t *testing.T) {
	rec := &presenceRecorder{}
	p := newPresence()
	p.idle = func() time.Duration { return 30 * time.Millisecond }
	ctx := context.Background()

	if err := p.offline(ctx, rec); err != nil {
		t.Fatal(err)
	}
	_ = p.touch(ctx, rec)
	_ = p.touch(ctx, rec) // still online: nothing new is sent
	time.Sleep(80 * time.Millisecond)

	got := rec.states()
	want := []types.Presence{types.PresenceUnavailable, types.PresenceAvailable, types.PresenceUnavailable}
	if len(got) != len(want) {
		t.Fatalf("sent %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("sent %v, want %v", got, want)
		}
	}
}

func TestBrowserIdentity(t *testing.T) {
	useBrowserIdentity()
	if store.DeviceProps.GetOs() != "Windows" || store.DeviceProps.GetPlatformType() != waCompanionReg.DeviceProps_CHROME {
		t.Fatalf("device shows as %q / %v", store.DeviceProps.GetOs(), store.DeviceProps.GetPlatformType())
	}
}
