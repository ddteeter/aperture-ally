import AppKit
import WebKit

/// One app for the whole tool: menu-bar status, the UI in its own window, the server, and speech.
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private let speech = SpeechService()
    private var companion: CompanionServer!
    private var server: ServerSupervisor!
    private var statusItem: NSStatusItem!
    private var window: NSWindow?
    private var web: WKWebView?
    private var shownUI = false

    private static let port = 8765
    private static let companionPort: UInt16 = 8767

    func applicationDidFinishLaunching(_ note: Notification) {
        buildMainMenu()
        speech.start()
        companion = CompanionServer(port: Self.companionPort, speech: speech)
        companion.start()
        server = ServerSupervisor(port: Self.port, backendDir: Self.backendDir(), companionPort: Int(Self.companionPort))
        server.onChange = { [weak self] st in self?.serverChanged(st) }
        buildStatusItem()
        showWindow()
        server.start()
    }

    /// The repo's backend/ folder: baked into Info.plist by scripts/build-mac-app.sh (override with
    /// APERTURE_ALLY_REPO for development).
    static func backendDir() -> URL {
        let repo = ProcessInfo.processInfo.environment["APERTURE_ALLY_REPO"]
            ?? Bundle.main.object(forInfoDictionaryKey: "ApertureAllyRepo") as? String
            ?? FileManager.default.currentDirectoryPath
        return URL(fileURLWithPath: repo).appendingPathComponent("backend")
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { false }

    func applicationShouldHandleReopen(_ app: NSApplication, hasVisibleWindows: Bool) -> Bool {
        showWindow()
        return true
    }

    func applicationWillTerminate(_ note: Notification) {
        speech.stop(reason: "quit")
        server.stop()
    }

    // MARK: window

    @objc func showWindow() {
        if let w = window {
            w.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")  // Inspect Element, for debugging
        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = self
        web.loadHTMLString(Self.waitingPage("Starting Aperture Ally…"), baseURL: nil)
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1470, height: 900),
                         styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        w.title = "Aperture Ally"
        w.contentView = web
        w.collectionBehavior = [.fullScreenPrimary]
        w.setFrameAutosaveName("ApertureAllyMain")  // remembers size and position
        w.isReleasedWhenClosed = false
        if !w.setFrameUsingName("ApertureAllyMain") { w.center() }
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        window = w
        self.web = web
        if case .running = server?.state { loadUI() }
        if case .attached = server?.state { loadUI() }
    }

    private func loadUI() {
        shownUI = true
        web?.load(URLRequest(url: server.url))
    }

    /// The mark (docs/design/icons/mark-on-dark.svg, mark 2a) for the page shown while the server starts.
    static let markSVG = ##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="-50 -50 100 100" width="56" height="56"><defs><mask id="g" maskUnits="userSpaceOnUse" x="-50" y="-50" width="100" height="100"><rect x="-50" y="-50" width="100" height="100" fill="#fff"></rect><g fill="none" stroke="#000" stroke-width="3.5" stroke-linejoin="round"><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -18.78 35.32 L-45 46 L-33.16 22.37 A40 40 0 0 1 -38.12 12.12 Z"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(60)"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(120)"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(180)"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(240)"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(300)"></path></g></mask></defs><g mask="url(#g)"><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -18.78 35.32 L-45 46 L-33.16 22.37 A40 40 0 0 1 -38.12 12.12 Z" fill="#79c0e8"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(60)" fill="#ececec"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(120)" fill="#ececec"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(180)" fill="#ececec"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(240)" fill="#ececec"></path><path d="M7 12.12 L-8.56 39.07 A40 40 0 0 1 -38.12 12.12 Z" transform="rotate(300)" fill="#ececec"></path></g></svg>"##

    static func waitingPage(_ msg: String) -> String {
        """
        <html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#161616;color:#b8b8b8;
        font:15px -apple-system,sans-serif"><div style="display:flex;flex-direction:column;align-items:center;gap:18px">
        \(markSVG)<div>\(msg)</div></div></body></html>
        """
    }

    @objc func openInBrowser() { NSWorkspace.shared.open(server.url) }
    @objc func restartServer() { server.restart() }
    @objc func openLog() { NSWorkspace.shared.open(server.logURL) }

    // MARK: server state

    private func serverChanged(_ st: ServerSupervisor.State) {
        styleStatusButton(st)
        rebuildStatusMenu()
        switch st {
        case .running, .attached:
            if !shownUI { loadUI() } else { web?.reload() }
        case .restarting(let why), .stopped(let why):
            shownUI = false
            web?.loadHTMLString(Self.waitingPage(why), baseURL: nil)
        case .starting:
            break
        }
    }

    /// The mark as a template image (macOS tints it for light/dark menu bars). Dimmed while the server starts
    /// or restarts; a "!" beside it when the server has stopped.
    private func styleStatusButton(_ st: ServerSupervisor.State) {
        guard let button = statusItem?.button else { return }
        if button.image == nil, let img = Bundle.main.image(forResource: "StatusIcon") {
            img.isTemplate = true
            img.size = NSSize(width: 18, height: 18)
            button.image = img
            button.imagePosition = .imageLeft
        }
        switch st {
        case .running, .attached:
            button.appearsDisabled = false
            button.title = button.image == nil ? "◉" : ""
        case .starting, .restarting:
            button.appearsDisabled = true
            button.title = button.image == nil ? "◌" : ""
        case .stopped:
            button.appearsDisabled = false
            button.title = button.image == nil ? "⊘" : "!"
        }
        button.toolTip = "Aperture Ally · \(Self.describe(st))"
    }

    static func describe(_ st: ServerSupervisor.State) -> String {
        switch st {
        case .running: return "Server running"
        case .attached: return "Using a server started elsewhere"
        case .starting: return "Server starting…"
        case .restarting(let why): return why
        case .stopped(let why): return "Server stopped: \(why)"
        }
    }

    // MARK: menus

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        styleStatusButton(server?.state ?? .starting)
        rebuildStatusMenu()
    }

    private func rebuildStatusMenu() {
        let m = NSMenu()
        let state = NSMenuItem(title: Self.describe(server?.state ?? .starting), action: nil, keyEquivalent: "")
        state.isEnabled = false
        m.addItem(state)
        let voice = NSMenuItem(title: "Speech: \(speech.ready ? speech.voiceName : (speech.lastError ?? "starting"))",
                               action: nil, keyEquivalent: "")
        voice.isEnabled = false
        m.addItem(voice)
        m.addItem(.separator())
        m.addItem(withTitle: "Open Aperture Ally", action: #selector(showWindow), keyEquivalent: "")
        m.addItem(withTitle: "Open in Browser", action: #selector(openInBrowser), keyEquivalent: "")
        m.addItem(.separator())
        m.addItem(withTitle: "Restart Server", action: #selector(restartServer), keyEquivalent: "")
        m.addItem(withTitle: "Show Server Log", action: #selector(openLog), keyEquivalent: "")
        m.addItem(.separator())
        m.addItem(withTitle: "Quit Aperture Ally", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        for item in m.items where item.action != nil && item.action != #selector(NSApplication.terminate(_:)) {
            item.target = self
        }
        statusItem.menu = m
    }

    /// App, Edit (copy/paste in the web view needs it), View (full screen) and Window menus.
    private func buildMainMenu() {
        let main = NSMenu()
        func sub(_ title: String, _ items: [NSMenuItem]) {
            let top = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            top.submenu = menu
            main.addItem(top)
        }
        sub("Aperture Ally", [
            NSMenuItem(title: "Open in Browser", action: #selector(openInBrowser), keyEquivalent: ""),
            NSMenuItem(title: "Restart Server", action: #selector(restartServer), keyEquivalent: ""),
            .separator(),
            NSMenuItem(title: "Hide Aperture Ally", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h"),
            NSMenuItem(title: "Quit Aperture Ally", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"),
        ])
        sub("Edit", [
            NSMenuItem(title: "Undo", action: Selector(("undo:")), keyEquivalent: "z"),
            NSMenuItem(title: "Redo", action: Selector(("redo:")), keyEquivalent: "Z"),
            .separator(),
            NSMenuItem(title: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x"),
            NSMenuItem(title: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c"),
            NSMenuItem(title: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v"),
            NSMenuItem(title: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a"),
        ])
        let fs = NSMenuItem(title: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        fs.keyEquivalentModifierMask = [.control, .command]
        sub("View", [fs])
        sub("Window", [
            NSMenuItem(title: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m"),
            NSMenuItem(title: "Show Aperture Ally", action: #selector(showWindow), keyEquivalent: "0"),
        ])
        for top in main.items {
            for item in top.submenu?.items ?? [] where [#selector(openInBrowser), #selector(restartServer),
                                                        #selector(showWindow)].contains(item.action) {
                item.target = self
            }
        }
        NSApp.mainMenu = main
    }

    // MARK: WKNavigationDelegate: links that leave the app open in the browser

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, action.navigationType == .linkActivated,
           url.host != "127.0.0.1" && url.host != "localhost" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
}
