import AppKit
import Foundation

/// In-process speech with the system voice (the one `say` and Spoken Content use).
///
/// Why NSSpeechSynthesizer and not AVSpeechSynthesizer: on this Mac AVSpeechSynthesizer can only see the
/// compact voices downloaded into its own catalog (compact Samantha: robotic), while the system voice chosen
/// in System Settings → Accessibility → Spoken Content (a Siri voice) is available to `say` and to
/// NSSpeechSynthesizer. A blind A/B on 2026-09-28 confirmed NSSpeechSynthesizer sounds identical to `say`.
/// In-process it avoids `say`'s ~960 ms per-utterance process + voice load, and a new utterance replaces the
/// playing one immediately. `rate` is words per minute, the same scale as `say -r`.
/// Everything here runs on the main queue.
final class SpeechService: NSObject, NSSpeechSynthesizerDelegate {
    enum Outcome: String { case done, cancelled, error }

    private let synth = NSSpeechSynthesizer()  // default voice = the system voice
    private var generation = 0
    private var current: (id: String, gen: Int, finish: (Outcome, String?) -> Void)?
    private(set) var voiceName = "System voice"
    private(set) var lastError: String?
    private(set) var ready = false

    /// Trailing silence so Bluetooth outputs (AirPods) don't clip the last word; same as the `say` path.
    private static let tail = " [[slnc 400]]"

    func start() {
        synth.delegate = self
        warmUp()
    }

    /// Render once to a file (silent): loads the voice, the expensive part.
    private func warmUp() {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("aperture-ally-warmup.aiff")
        if !synth.startSpeaking("Ready.", to: url) {
            lastError = "speech synthesizer failed to start"
            return
        }
        generation += 1  // the warm-up's didFinish is ignored
    }

    /// Speak `text`, replacing anything playing. `started` fires as soon as speaking begins;
    /// `finish` fires once, when speech has ended (`done`) or was replaced/stopped (`cancelled`).
    func speak(id: String, text: String, wpm: Double?, voice: String?,
               started: @escaping () -> Void, finish: @escaping (Outcome, String?) -> Void) {
        stop(reason: "replaced")
        if synth.isSpeaking { synth.stopSpeaking() }  // e.g. the warm-up render
        generation += 1
        current = (id, generation, finish)
        _ = synth.setVoice(voice.flatMap(Self.voiceIdentifier(named:)))  // nil → system voice
        synth.rate = Float(wpm ?? 175)
        if synth.startSpeaking(text + Self.tail) {
            started()
        } else {
            finishCurrent(.error, "speech synthesizer refused the text")
        }
    }

    /// Stop whatever is playing (optionally only if it is utterance `id`).
    func stop(id: String? = nil, reason: String = "stopped") {
        if let id, current?.id != id { return }
        guard current != nil else { return }
        generation += 1
        synth.stopSpeaking()
        finishCurrent(.cancelled, reason)
    }

    private static func voiceIdentifier(named name: String) -> NSSpeechSynthesizer.VoiceName? {
        NSSpeechSynthesizer.availableVoices.first {
            (NSSpeechSynthesizer.attributes(forVoice: $0)[.name] as? String) == name
        }
    }

    private func finishCurrent(_ outcome: Outcome, _ detail: String?) {
        guard let c = current else { return }
        current = nil
        c.finish(outcome, detail)
    }

    // MARK: NSSpeechSynthesizerDelegate

    func speechSynthesizer(_ sender: NSSpeechSynthesizer, didFinishSpeaking finishedSpeaking: Bool) {
        if !ready {
            ready = true  // warm-up render finished
            return
        }
        guard let c = current, c.gen == generation else { return }
        finishCurrent(finishedSpeaking ? .done : .cancelled, finishedSpeaking ? nil : "interrupted")
    }
}
