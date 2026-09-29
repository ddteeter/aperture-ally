import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)  // Dock icon + window; the menu-bar item stays while the window is closed
app.run()
