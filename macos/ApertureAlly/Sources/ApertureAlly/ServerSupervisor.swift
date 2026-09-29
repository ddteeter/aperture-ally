import Foundation

/// Starts the Python server, watches it, restarts it if it dies, and stops it on quit.
///
/// If a server is already answering on the port (e.g. one started from a terminal while developing), it is
/// used as-is and not managed. The server runs from the repo's backend venv so signals reach Python directly.
final class ServerSupervisor {
    enum State: Equatable { case starting, running, attached, restarting(String), stopped(String) }

    let port: Int
    let backendDir: URL
    let companionPort: Int
    private(set) var state: State = .starting { didSet { if state != oldValue { onChange?(state) } } }
    var onChange: ((State) -> Void)?
    private var process: Process?
    private var stopping = false
    private var failures = 0
    private var health: Timer?
    let logURL: URL

    init(port: Int, backendDir: URL, companionPort: Int) {
        self.port = port
        self.backendDir = backendDir
        self.companionPort = companionPort
        let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("ApertureAlly/logs")
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        logURL = logs.appendingPathComponent("server-console.log")
    }

    var url: URL { URL(string: "http://127.0.0.1:\(port)/")! }

    func start() {
        stopping = false
        checkHealth { [weak self] up in
            guard let self else { return }
            if up {
                self.state = .attached  // someone else's server: use it, don't manage it
            } else {
                self.launch()
            }
            self.health = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in self?.poll() }
        }
    }

    private func executable() -> (URL, [String])? {
        let venv = backendDir.appendingPathComponent(".venv/bin/aperture-ally")
        if FileManager.default.isExecutableFile(atPath: venv.path) {
            return (venv, ["serve", "--port", "\(port)"])
        }
        for p in ["/opt/homebrew/bin/uv", "/usr/local/bin/uv",
                  FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/uv").path]
        where FileManager.default.isExecutableFile(atPath: p) {
            return (URL(fileURLWithPath: p), ["run", "aperture-ally", "serve", "--port", "\(port)"])
        }
        return nil
    }

    private func launch() {
        guard let (exe, args) = executable() else {
            state = .stopped("can't find the backend (run `uv sync` in backend/)")
            return
        }
        let p = Process()
        p.executableURL = exe
        p.arguments = args
        p.currentDirectoryURL = backendDir
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + (env["PATH"] ?? "")
        env["APERTURE_ALLY_SPEECH_PROVIDER"] = "companion"  // speak through this app (falls back to `say`)
        env["APERTURE_ALLY_COMPANION_PORT"] = "\(companionPort)"
        env["PYTHONUNBUFFERED"] = "1"
        p.environment = env
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let h = try? FileHandle(forWritingTo: logURL) {
            h.seekToEndOfFile()
            p.standardOutput = h
            p.standardError = h
        }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async { self?.exited(proc.terminationStatus) }
        }
        do {
            try p.run()
            process = p
            state = .starting
        } catch {
            state = .stopped("launch failed: \(error.localizedDescription)")
        }
    }

    private func exited(_ code: Int32) {
        process = nil
        if stopping { state = .stopped("quit"); return }
        failures += 1
        let delay = min(30.0, pow(2.0, Double(min(failures, 5))))
        state = .restarting("server exited (\(code)); restarting in \(Int(delay)) s")
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self, !self.stopping, self.process == nil else { return }
            self.launch()
        }
    }

    private func poll() {
        checkHealth { [weak self] up in
            guard let self else { return }
            switch (self.state, up) {
            case (.starting, true), (.restarting, true):
                self.failures = 0
                self.state = self.process == nil ? .attached : .running
            case (.attached, false):
                self.launch()  // the terminal server went away: take over
            default:
                break
            }
        }
    }

    private func checkHealth(_ done: @escaping (Bool) -> Void) {
        var req = URLRequest(url: url.appendingPathComponent("api/health"))
        req.timeoutInterval = 1.5
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            let ok = (resp as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { done(ok) }
        }.resume()
    }

    func restart() {
        guard let p = process else { launch(); return }
        failures = 0
        p.terminate()  // terminationHandler relaunches
    }

    /// Quit: SIGTERM, wait up to 5 s for a clean shutdown (it releases the mic and camera), then SIGKILL.
    func stop() {
        stopping = true
        health?.invalidate()
        guard let p = process, p.isRunning else { return }
        p.terminate()
        let deadline = Date().addingTimeInterval(5)
        while p.isRunning && Date() < deadline { RunLoop.current.run(until: Date().addingTimeInterval(0.05)) }
        if p.isRunning { kill(p.processIdentifier, SIGKILL) }
    }
}
