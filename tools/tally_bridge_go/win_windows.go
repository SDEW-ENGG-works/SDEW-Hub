//go:build windows

package main

import (
	"os/exec"
	"syscall"
	"unsafe"
)

// ---------------------------------------------------------------- Windows helpers
var (
	user32      = syscall.NewLazyDLL("user32.dll")
	msgBox      = user32.NewProc("MessageBoxW")
	kernel32    = syscall.NewLazyDLL("kernel32.dll")
	createMutex = kernel32.NewProc("CreateMutexW")
)

func message(text string, icon uintptr) {
	t, _ := syscall.UTF16PtrFromString(text)
	c, _ := syscall.UTF16PtrFromString(appName)
	msgBox.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), icon)
}

const (
	mbInfo  = 0x40
	mbError = 0x10
)

// run a Windows command without a console window
func hidden(name string, args ...string) error {
	c := exec.Command(name, args...)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000}
	return c.Run()
}


func startHidden(path string) error {
	c := exec.Command(path)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	return c.Start()
}

func alreadyRunning() bool {
	name, _ := syscall.UTF16PtrFromString("Local\\SDEWTallyBridge")
	h, _, err := createMutex.Call(0, 0, uintptr(unsafe.Pointer(name)))
	return h != 0 && err == syscall.ERROR_ALREADY_EXISTS
}
