package main

import (
	"context"
	"math/rand/v2"
	"sync"
	"time"

	"go.mau.fi/whatsmeow/proto/waCompanionReg"
	"go.mau.fi/whatsmeow/store"
	"go.mau.fi/whatsmeow/types"
)

// Linked devices show this to the phone owner, and WhatsApp sees it at
// pairing. The library default ("whatsmeow", unknown platform) marks the
// session as automated; a person links WhatsApp Web from Chrome on a PC.
func useBrowserIdentity() {
	store.SetOSInfo("Windows", [3]uint32{10, 0, 19045})
	store.DeviceProps.PlatformType = waCompanionReg.DeviceProps_CHROME.Enum()
}

// How long a line stays "online" after its last activity. A person closes
// the chat a little after answering; the exact time varies.
const (
	onlineMin = 40 * time.Second
	onlineMax = 150 * time.Second
)

// presenceSender is the part of the WhatsApp client presence needs.
type presenceSender interface {
	SendPresence(ctx context.Context, state types.Presence) error
}

// presence shows a line online while it answers and offline otherwise, the
// way a person opens and leaves WhatsApp. Being offline the rest of the time
// also keeps the phone getting its notifications.
type presence struct {
	mu     sync.Mutex
	online bool
	timer  *time.Timer
	idle   func() time.Duration
}

func newPresence() *presence {
	return &presence{idle: func() time.Duration {
		return onlineMin + time.Duration(rand.Int64N(int64(onlineMax-onlineMin)))
	}}
}

// offline is sent once on connect: it also gives WhatsApp the push name,
// without which contacts see "-" as the sender.
func (p *presence) offline(ctx context.Context, client presenceSender) error {
	if p == nil {
		return nil
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.timer != nil {
		p.timer.Stop()
		p.timer = nil
	}
	p.online = false
	return client.SendPresence(ctx, types.PresenceUnavailable)
}

// touch marks activity: online now if it was not, and offline again after a
// quiet while.
func (p *presence) touch(ctx context.Context, client presenceSender) error {
	if p == nil {
		return nil
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	var err error
	if !p.online {
		if err = client.SendPresence(ctx, types.PresenceAvailable); err == nil {
			p.online = true
		}
	}
	if p.timer != nil {
		p.timer.Stop()
	}
	p.timer = time.AfterFunc(p.idle(), func() {
		p.mu.Lock()
		defer p.mu.Unlock()
		if p.online && client.SendPresence(context.Background(), types.PresenceUnavailable) == nil {
			p.online = false
		}
		p.timer = nil
	})
	return err
}

func (p *presence) stop() {
	if p == nil {
		return
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.timer != nil {
		p.timer.Stop()
		p.timer = nil
	}
}
