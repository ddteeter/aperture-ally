import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)  // Dock icon + window; the menu-bar item stays while the window is closed

// `kill` / logout send SIGTERM, which would end the app without applicationWillTerminate, leaving the server
// running (and the camera held). Treat SIGTERM and SIGINT like Quit.
var signalSources: [DispatchSourceSignal] = []
for sig in [SIGTERM, SIGINT] {
    signal(sig, SIG_IGN)
    let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    src.setEventHandler { NSApp.terminate(nil) }
    src.resume()
    signalSources.append(src)
}
app.run()
