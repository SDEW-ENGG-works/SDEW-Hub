// SDEW Tally Bridge - lets the SDEW Hub website (https://sdew-hub.vercel.app) read the Tally on THIS computer.
//
// A web page cannot read Tally (localhost:9000) itself: Tally does not send the headers a browser needs.
// This program passes the page's requests on:  browser -> http://localhost:9001 (this) -> Tally localhost:9000.
//
// Double-click once: it copies itself to %LOCALAPPDATA%\SDEW, starts with Windows (no window) and runs now.
//   SDEW-Tally-Bridge.exe --uninstall   stops starting with Windows and removes the copy.
// Settings (optional) in %LOCALAPPDATA%\SDEW\bridge.json: {"tally": "http://localhost:9000", "port": 9001, "origins": [...]}
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
	"unicode/utf16"

)

const appName = "SDEW Tally Bridge"
const runKey = `Software\Microsoft\Windows\CurrentVersion\Run`
const runValue = "SDEWTallyBridge"

var version = "1.0"

type Config struct {
	Tally   string   `json:"tally"`
	Port    int      `json:"port"`
	Origins []string `json:"origins"`
}

var cfg = Config{Tally: "http://localhost:9000", Port: 9001}
var origins = map[string]bool{
	"https://sdew-hub.vercel.app": true,
	"http://localhost:8050":       true,
	"http://127.0.0.1:8050":       true,
}

const companiesXML = `<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST><TYPE>Collection</TYPE>` +
	`<ID>SDEWHubCompanies</ID></HEADER><BODY><DESC><STATICVARIABLES><SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>` +
	`</STATICVARIABLES><TDL><TDLMESSAGE><COLLECTION NAME="SDEWHubCompanies" ISMODIFY="No"><TYPE>Company</TYPE>` +
	`<FETCH>Name</FETCH></COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>`

var companyRx = regexp.MustCompile(`<COMPANY NAME="([^"]+)"`)

func installDir() string {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		base = os.TempDir()
	}
	return filepath.Join(base, "SDEW")
}

func installedExe() string { return filepath.Join(installDir(), "SDEW-Tally-Bridge.exe") }

func samePath(a, b string) bool {
	a, _ = filepath.Abs(a)
	b, _ = filepath.Abs(b)
	return strings.EqualFold(filepath.Clean(a), filepath.Clean(b))
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	tmp := dst + ".new"
	out, err := os.Create(tmp)
	if err != nil {
		return err
	}
	if _, err = io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	out.Close()
	os.Remove(dst)
	return os.Rename(tmp, dst)
}

func portBusy(port int) bool {
	c, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 500*time.Millisecond)
	if err == nil {
		c.Close()
		return true
	}
	return false
}

// stop a running copy (it answers /quit) so the new one can take the port
func stopRunning(port int) {
	cl := http.Client{Timeout: 2 * time.Second}
	req, _ := http.NewRequest("POST", fmt.Sprintf("http://127.0.0.1:%d/quit", port), nil)
	if r, err := cl.Do(req); err == nil {
		r.Body.Close()
	}
	for i := 0; i < 20 && portBusy(port); i++ {
		time.Sleep(150 * time.Millisecond)
	}
}

func install() {
	me, _ := os.Executable()
	if err := os.MkdirAll(installDir(), 0o755); err != nil {
		message("Could not create "+installDir()+": "+err.Error(), mbError)
		return
	}
	stopRunning(cfg.Port)
	if err := copyFile(me, installedExe()); err != nil {
		message("Could not copy the bridge to "+installedExe()+": "+err.Error(), mbError)
		return
	}
	hidden("reg", "add", `HKCU\`+runKey, "/v", runValue, "/t", "REG_SZ", "/d", `"`+installedExe()+`"`, "/f")
	if err := startHidden(installedExe()); err != nil {
		message("Installed, but could not start: "+err.Error(), mbError)
		return
	}
	time.Sleep(1200 * time.Millisecond)
	tally := "Tally is answering on " + cfg.Tally + "."
	if _, err := tallyPost([]byte(companiesXML), 5*time.Second); err != nil {
		tally = "Tally is NOT answering on " + cfg.Tally + " right now.\nIn TallyPrime: F1 Help > Settings > Connectivity >\nClient/Server configuration: TallyPrime acts as Server (or Both), Port 9000."
	}
	message("SDEW Tally Bridge is installed on this computer.\n\n"+
		"It runs in the background and starts with Windows - nothing else to do.\n"+
		"Open https://sdew-hub.vercel.app > GRIN & Payments > Get data > Pull from Tally:\n"+
		"it now reads THIS computer's Tally.\n\n"+tally+
		"\n\n(If the browser asks to allow access to devices on your local network, press Allow.)", mbInfo)
}

func uninstall() {
	stopRunning(cfg.Port)
	hidden("reg", "delete", `HKCU\`+runKey, "/v", runValue, "/f")
	me, _ := os.Executable()
	if !samePath(me, installedExe()) {
		os.Remove(installedExe())
	}
	message("SDEW Tally Bridge removed: it no longer starts with Windows.", mbInfo)
}

// ---------------------------------------------------------------- the bridge
func decode(raw []byte) string {
	if len(raw) >= 2 && ((raw[0] == 0xff && raw[1] == 0xfe) || (raw[0] == 0xfe && raw[1] == 0xff)) {
		be := raw[0] == 0xfe
		raw = raw[2:]
		return utf16str(raw, be)
	}
	if len(raw) > 3 && raw[1] == 0 {
		return utf16str(raw, false)
	}
	return string(raw)
}

func utf16str(b []byte, bigEndian bool) string {
	n := len(b) / 2
	u := make([]uint16, n)
	for i := 0; i < n; i++ {
		if bigEndian {
			u[i] = uint16(b[2*i])<<8 | uint16(b[2*i+1])
		} else {
			u[i] = uint16(b[2*i+1])<<8 | uint16(b[2*i])
		}
	}
	return string(utf16.Decode(u))
}

func tallyPost(body []byte, timeout time.Duration) (string, error) {
	cl := http.Client{Timeout: timeout, Transport: &http.Transport{Proxy: nil}}
	r, err := cl.Post(cfg.Tally, "text/xml; charset=utf-8", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	defer r.Body.Close()
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		return "", err
	}
	return decode(raw), nil
}

func allowed(origin string) bool {
	if origin == "" || origins[origin] {
		return true
	}
	return strings.HasPrefix(origin, "https://sdew-hub") && strings.HasSuffix(origin, ".vercel.app")
}

func cors(w http.ResponseWriter, r *http.Request) {
	o := r.Header.Get("Origin")
	if o != "" && allowed(o) {
		w.Header().Set("Access-Control-Allow-Origin", o)
		w.Header().Set("Vary", "Origin")
	}
	w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
	w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
	w.Header().Set("Access-Control-Allow-Private-Network", "true")
	w.Header().Set("Access-Control-Max-Age", "600")
}

func writeJSON(w http.ResponseWriter, code int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func handler(w http.ResponseWriter, r *http.Request) {
	cors(w, r)
	if r.Method == http.MethodOptions {
		w.WriteHeader(http.StatusNoContent)
		return
	}
	if !allowed(r.Header.Get("Origin")) {
		writeJSON(w, 403, map[string]string{"error": "This page may not use the Tally bridge"})
		return
	}
	host, _ := os.Hostname()
	switch {
	case r.URL.Path == "/ping" || r.URL.Path == "/":
		out := map[string]interface{}{"ok": true, "bridge": true, "host": host, "tally": cfg.Tally, "version": version}
		text, err := tallyPost([]byte(companiesXML), 10*time.Second)
		if err != nil {
			out["tally_ok"] = false
			out["error"] = "Tally is not answering on " + cfg.Tally + ": " + err.Error() +
				". In TallyPrime: F1 Help > Settings > Connectivity > Client/Server: Server (or Both), port 9000."
		} else {
			names := []string{}
			for _, m := range companyRx.FindAllStringSubmatch(text, -1) {
				names = append(names, m[1])
			}
			out["tally_ok"] = true
			out["companies"] = names
		}
		writeJSON(w, 200, out)
	case r.URL.Path == "/tally" && r.Method == http.MethodPost:
		body, _ := io.ReadAll(io.LimitReader(r.Body, 5<<20))
		text, err := tallyPost(body, 180*time.Second)
		if err != nil {
			writeJSON(w, 502, map[string]string{"error": "Tally is not answering on " + cfg.Tally + ": " + err.Error()})
			return
		}
		log.Printf("tally request from %s: %d bytes answer", r.Header.Get("Origin"), len(text))
		w.Header().Set("Content-Type", "text/xml; charset=utf-8")
		io.WriteString(w, text)
	case r.URL.Path == "/quit" && r.Method == http.MethodPost && r.Header.Get("Origin") == "":
		w.WriteHeader(200)
		go func() { time.Sleep(200 * time.Millisecond); os.Exit(0) }()
	default:
		writeJSON(w, 404, map[string]string{"error": "not found"})
	}
}

func loadConfig() {
	b, err := os.ReadFile(filepath.Join(installDir(), "bridge.json"))
	if err != nil {
		return
	}
	var c Config
	if json.Unmarshal(b, &c) == nil {
		if c.Tally != "" {
			cfg.Tally = strings.TrimRight(c.Tally, "/")
		}
		if c.Port != 0 {
			cfg.Port = c.Port
		}
		for _, o := range c.Origins {
			origins[strings.TrimRight(o, "/")] = true
		}
	}
}

func serve() {
	if alreadyRunning() {
		return
	}
	os.MkdirAll(installDir(), 0o755)
	if f, err := os.OpenFile(filepath.Join(installDir(), "bridge.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644); err == nil {
		log.SetOutput(f)
	}
	log.Printf("%s %s on 127.0.0.1:%d -> %s", appName, version, cfg.Port, cfg.Tally)
	srv := &http.Server{Addr: fmt.Sprintf("127.0.0.1:%d", cfg.Port), Handler: http.HandlerFunc(handler),
		ReadHeaderTimeout: 10 * time.Second}
	if err := srv.ListenAndServe(); err != nil {
		log.Printf("stopped: %v", err)
	}
}

func main() {
	loadConfig()
	for _, a := range os.Args[1:] {
		if a == "--uninstall" || a == "/uninstall" {
			uninstall()
			return
		}
		if a == "--serve" {
			serve()
			return
		}
	}
	me, _ := os.Executable()
	if samePath(me, installedExe()) {
		serve() // started by Windows at logon, or by the installer
		return
	}
	install() // double-clicked from Downloads / a pen drive
}
