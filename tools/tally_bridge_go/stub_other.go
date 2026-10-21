//go:build !windows

package main

import "fmt"

const (
	mbInfo  = 0x40
	mbError = 0x10
)

func message(text string, icon uintptr)              { fmt.Println("[message]", text) }
func hidden(name string, args ...string) error      { fmt.Println("[cmd]", name, args); return nil }
func startHidden(path string) error                 { fmt.Println("[start]", path); return nil }
func alreadyRunning() bool                          { return false }
