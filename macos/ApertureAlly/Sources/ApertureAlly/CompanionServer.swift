import Foundation
import Network

/// Newline-delimited JSON on 127.0.0.1 (loopback only) for the Python backend's `companion` speech provider.
///
///   → {"op":"ping"}                                   ← {"event":"pong","voice":"Samantha","ready":true}
///   → {"op":"speak","id":"u1","text":"…","rate_wpm":270,"voice":null}
///                                                     ← {"id":"u1","event":"started"}
///                                                     ← {"id":"u1","event":"done"|"cancelled"|"error","detail":…}
///   → {"op":"stop","id":"u1"}   (id optional: stop whatever is playing)
final class CompanionServer {
    private let port: UInt16
    private let speech: SpeechService
    private var listener: NWListener?
    private(set) var status = "not started"

    init(port: UInt16, speech: SpeechService) {
        self.port = port
        self.speech = speech
    }

    func start() {
        let params = NWParameters.tcp
        params.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: port)!)
        params.allowLocalEndpointReuse = true
        do {
            let l = try NWListener(using: params)
            l.newConnectionHandler = { [weak self] c in self?.accept(c) }
            l.stateUpdateHandler = { [weak self] st in
                DispatchQueue.main.async { self?.status = "\(st)" }
            }
            l.start(queue: .main)
            listener = l
        } catch {
            status = "failed: \(error)"
        }
    }

    private func accept(_ c: NWConnection) {
        c.start(queue: .main)
        receive(c, buffer: Data())
    }

    private func receive(_ c: NWConnection, buffer: Data) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            var buf = buffer
            if let data { buf.append(data) }
            while let nl = buf.firstIndex(of: 0x0A) {
                let line = buf[buf.startIndex..<nl]
                buf = Data(buf[buf.index(after: nl)...])
                self.handle(line, on: c)
            }
            if isComplete || error != nil {
                c.cancel()
                return
            }
            self.receive(c, buffer: buf)
        }
    }

    private func send(_ obj: [String: Any], on c: NWConnection) {
        guard var d = try? JSONSerialization.data(withJSONObject: obj) else { return }
        d.append(0x0A)
        c.send(content: d, completion: .contentProcessed { _ in })
    }

    private func handle(_ line: Data, on c: NWConnection) {
        guard let msg = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let op = msg["op"] as? String else {
            send(["event": "error", "detail": "bad request"], on: c)
            return
        }
        switch op {
        case "ping":
            send(["event": "pong", "voice": speech.voiceName, "ready": speech.ready, "error": speech.lastError as Any], on: c)
        case "speak":
            let id = msg["id"] as? String ?? UUID().uuidString
            let text = msg["text"] as? String ?? ""
            speech.speak(id: id, text: text, wpm: msg["rate_wpm"] as? Double, voice: msg["voice"] as? String,
                         started: { [weak self] in self?.send(["id": id, "event": "started"], on: c) },
                         finish: { [weak self] outcome, detail in
                             self?.send(["id": id, "event": outcome.rawValue, "detail": detail as Any], on: c)
                         })
        case "stop":
            speech.stop(id: msg["id"] as? String)
        default:
            send(["event": "error", "detail": "unknown op \(op)"], on: c)
        }
    }
}
