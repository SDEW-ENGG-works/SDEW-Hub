# SDEW Tally Bridge (Go)

Lets the SDEW Hub website read the Tally of the computer it is opened on (see ../../README.md).
Double-click `SDEW-Tally-Bridge.exe` once per computer: it copies itself to `%LOCALAPPDATA%\SDEW`,
starts with Windows (no window) and listens on http://localhost:9001 -> Tally http://localhost:9000.
`SDEW-Tally-Bridge.exe --uninstall` removes it. Optional `%LOCALAPPDATA%\SDEW\bridge.json`:
`{"tally": "http://localhost:9000", "port": 9001, "origins": ["https://another-host"]}`. Log: `%LOCALAPPDATA%\SDEW\bridge.log`.

Rebuild (any OS with Go 1.22+):
    GOOS=windows GOARCH=amd64 go build -ldflags "-H=windowsgui -s -w" -o SDEW-Tally-Bridge.exe .
