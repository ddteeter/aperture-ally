// audiolat: native-audio latency spike helper for Aperture Ally.
//
// Subcommands (all timestamps are CLOCK_UPTIME_RAW nanoseconds == mach_absolute_time in ns,
// the same clock as Python's time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)):
//   devices                          list CoreAudio devices (id, name, in/out, default, volume, latency)
//   now                              print the clock
//   get-default-output               print the default output device id
//   set-default-output <id>          set the default (and system) output device
//   get-volume <id> / set-volume <id> <0..1>
//   record <name> <out.f32> <anchors.txt>
//        record mono float32 from the named input device until stdin closes; anchors.txt gets one
//        "sampleIndex hostNs" line per tap buffer so the harness can map clock -> sample
//   player <outputDeviceName> [tickFile] [ioBufferFrames]
//        long-lived: reads commands on stdin, one per line, and acks "ack <cmd> <recvNs> <doneNs>":
//          tick          play the pre-loaded tick buffer (default Tink.aiff) (AVAudioEngine/AVAudioPlayerNode, explicit device)
//          speak <text>  AVSpeechSynthesizer.speak (system default output; pre-warmed)
//          interrupt <t> stopSpeaking(.immediate) + speak(t)
//          rspeak <text> AVSpeechSynthesizer.write -> buffers scheduled on a player node (explicit device)
//          cspeak <text> play a buffer pre-rendered at startup (cache) with its leading silence trimmed
//          quit
//        emits "event didStart|didFinish|didCancel <ns>" from the synthesizer delegate
//   speak-once <text>                speak with AVSpeechSynthesizer and exit(0) the moment didFinish fires
//   render-info <text>               render with AVSpeechSynthesizer.write; print lead/active/total ms
//   file-info <path>                 lead/active/total ms of an audio file (threshold -50 dBFS)

import AVFoundation
import CoreAudio
import Foundation

setvbuf(stdout, nil, _IOLBF, 0)

func nowNs() -> UInt64 { clock_gettime_nsec_np(CLOCK_UPTIME_RAW) }
var tb = mach_timebase_info_data_t()
mach_timebase_info(&tb)
func hostToNs(_ h: UInt64) -> UInt64 { h * UInt64(tb.numer) / UInt64(tb.denom) }
func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }

// MARK: CoreAudio helpers

func prop<T>(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector,
             _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal,
             _ elem: AudioObjectPropertyElement = kAudioObjectPropertyElementMain, initial: T) -> T? {
    var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: scope, mElement: elem)
    var v = initial
    var size = UInt32(MemoryLayout<T>.size)
    let st = AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &v)
    return st == noErr ? v : nil
}

func allDevices() -> [AudioDeviceID] {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices,
                                          mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
    return ids
}

func deviceName(_ id: AudioDeviceID) -> String {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioObjectPropertyName,
                                          mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var name: Unmanaged<CFString>?
    var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, &name) == noErr, let n = name else { return "?" }
    return n.takeRetainedValue() as String
}

func channels(_ id: AudioDeviceID, _ scope: AudioObjectPropertyScope) -> Int {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyStreamConfiguration,
                                          mScope: scope, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(id, &addr, 0, nil, &size) == noErr, size > 0 else { return 0 }
    let raw = UnsafeMutableRawPointer.allocate(byteCount: Int(size), alignment: 16)
    defer { raw.deallocate() }
    guard AudioObjectGetPropertyData(id, &addr, 0, nil, &size, raw) == noErr else { return 0 }
    let abl = UnsafeMutableAudioBufferListPointer(raw.assumingMemoryBound(to: AudioBufferList.self))
    return abl.reduce(0) { $0 + Int($1.mNumberChannels) }
}

func findDevice(_ name: String, _ scope: AudioObjectPropertyScope) -> AudioDeviceID {
    for d in allDevices() where deviceName(d) == name && channels(d, scope) > 0 { return d }
    die("device not found: \(name)")
}

func defaultDevice(_ sel: AudioObjectPropertySelector) -> AudioDeviceID {
    prop(AudioObjectID(kAudioObjectSystemObject), sel, initial: AudioDeviceID(0)) ?? 0
}

func setDefaultOutput(_ id: AudioDeviceID) {
    for sel in [kAudioHardwarePropertyDefaultOutputDevice, kAudioHardwarePropertyDefaultSystemOutputDevice] {
        var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal,
                                              mElement: kAudioObjectPropertyElementMain)
        var v = id
        let st = AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil,
                                            UInt32(MemoryLayout<AudioDeviceID>.size), &v)
        if st != noErr { die("set default failed \(st)") }
    }
}

func volumeElements(_ id: AudioDeviceID) -> [UInt32] {
    for e: UInt32 in [0] where prop(id, kAudioDevicePropertyVolumeScalar, kAudioDevicePropertyScopeOutput, e, initial: Float32(0)) != nil {
        return [e]
    }
    return [1, 2].filter { prop(id, kAudioDevicePropertyVolumeScalar, kAudioDevicePropertyScopeOutput, $0, initial: Float32(0)) != nil }
}

func getVolume(_ id: AudioDeviceID) -> Float32 {
    let els = volumeElements(id)
    return els.compactMap { prop(id, kAudioDevicePropertyVolumeScalar, kAudioDevicePropertyScopeOutput, $0, initial: Float32(0)) }.max() ?? -1
}

func setVolume(_ id: AudioDeviceID, _ v: Float32) {
    for e in volumeElements(id) {
        var addr = AudioObjectPropertyAddress(mSelector: kAudioDevicePropertyVolumeScalar,
                                              mScope: kAudioDevicePropertyScopeOutput, mElement: e)
        var x = v
        AudioObjectSetPropertyData(id, &addr, 0, nil, UInt32(MemoryLayout<Float32>.size), &x)
    }
}

func latencyInfo(_ id: AudioDeviceID, _ scope: AudioObjectPropertyScope) -> String {
    let lat = prop(id, kAudioDevicePropertyLatency, scope, initial: UInt32(0)) ?? 0
    let so = prop(id, kAudioDevicePropertySafetyOffset, scope, initial: UInt32(0)) ?? 0
    let buf = prop(id, kAudioDevicePropertyBufferFrameSize, scope, initial: UInt32(0)) ?? 0
    let sr = prop(id, kAudioDevicePropertyNominalSampleRate, initial: Float64(0)) ?? 0
    return "sr=\(sr) latencyFrames=\(lat) safetyOffset=\(so) bufferFrames=\(buf)"
}

func setUnitDevice(_ unit: AudioUnit?, _ id: AudioDeviceID) {
    guard let unit else { die("no audio unit") }
    var d = id
    let st = AudioUnitSetProperty(unit, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &d,
                                  UInt32(MemoryLayout<AudioDeviceID>.size))
    if st != noErr { die("set unit device failed \(st)") }
}

// MARK: buffer helpers

func activeInfo(_ buf: AVAudioPCMBuffer, thresholdDb: Float = -50) -> (lead: Double, active: Double, total: Double) {
    let n = Int(buf.frameLength), sr = buf.format.sampleRate
    let thr = powf(10, thresholdDb / 20)
    var first = -1, last = -1
    func val(_ i: Int) -> Float {
        if let f = buf.floatChannelData { return abs(f[0][i]) }
        if let s = buf.int16ChannelData { return abs(Float(s[0][i]) / 32768) }
        if let s = buf.int32ChannelData { return abs(Float(s[0][i]) / 2147483648) }
        return 0
    }
    for i in 0..<n where val(i) > thr { if first < 0 { first = i }; last = i }
    if first < 0 { return (0, 0, Double(n) / sr) }
    return (Double(first) / sr * 1000, Double(last - first) / sr * 1000, Double(n) / sr * 1000)
}

func concat(_ bufs: [AVAudioPCMBuffer]) -> AVAudioPCMBuffer? {
    guard let f = bufs.first?.format else { return nil }
    let total = bufs.reduce(0) { $0 + Int($1.frameLength) }
    guard let out = AVAudioPCMBuffer(pcmFormat: f, frameCapacity: AVAudioFrameCount(max(total, 1))) else { return nil }
    let bpf = Int(f.streamDescription.pointee.mBytesPerFrame)
    var off = 0
    for b in bufs {
        let src = b.audioBufferList.pointee.mBuffers.mData!
        let dst = out.audioBufferList.pointee.mBuffers.mData! + off * bpf
        memcpy(dst, src, Int(b.frameLength) * bpf)
        off += Int(b.frameLength)
    }
    out.frameLength = AVAudioFrameCount(total)
    return out
}

func trimLead(_ buf: AVAudioPCMBuffer) -> AVAudioPCMBuffer {
    let info = activeInfo(buf)
    let start = max(0, Int(info.lead / 1000 * buf.format.sampleRate) - 32)
    let n = Int(buf.frameLength) - start
    let out = AVAudioPCMBuffer(pcmFormat: buf.format, frameCapacity: AVAudioFrameCount(n))!
    let bpf = Int(buf.format.streamDescription.pointee.mBytesPerFrame)
    memcpy(out.audioBufferList.pointee.mBuffers.mData!, buf.audioBufferList.pointee.mBuffers.mData! + start * bpf, n * bpf)
    out.frameLength = AVAudioFrameCount(n)
    return out
}

// MARK: speech

final class Speech: NSObject, AVSpeechSynthesizerDelegate {
    let synth = AVSpeechSynthesizer()
    var onFinish: (() -> Void)?
    var quiet = false
    override init() { super.init(); synth.delegate = self }
    func utt(_ t: String, volume: Float = 1) -> AVSpeechUtterance {
        let u = AVSpeechUtterance(string: t)
        u.volume = volume
        u.prefersAssistiveTechnologySettings = false
        return u
    }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didStart u: AVSpeechUtterance) {
        if !quiet { print("event didStart \(nowNs())") }
    }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) {
        if !quiet { print("event didFinish \(nowNs())") }
        onFinish?()
    }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) {
        if !quiet { print("event didCancel \(nowNs())") }
    }
    /// Render text to buffers synchronously on a background wait (the callback arrives on another queue).
    func render(_ t: String) -> [AVAudioPCMBuffer] {
        var out: [AVAudioPCMBuffer] = []
        let done = DispatchSemaphore(value: 0)
        synth.write(utt(t)) { b in
            guard let p = b as? AVAudioPCMBuffer else { return }
            if p.frameLength == 0 { done.signal(); return }
            out.append(p)
        }
        if Thread.isMainThread {  // the write callback may need the main run loop: spin it while we wait
            let deadline = Date().addingTimeInterval(10)
            while done.wait(timeout: .now()) == .timedOut && Date() < deadline {
                RunLoop.main.run(until: Date().addingTimeInterval(0.005))
            }
        } else {
            _ = done.wait(timeout: .now() + 10)
        }
        return out
    }
}

// MARK: commands

let args = CommandLine.arguments
guard args.count >= 2 else { die("usage: audiolat <cmd> ...") }

switch args[1] {
case "now":
    print(nowNs())

case "devices":
    let dout = defaultDevice(kAudioHardwarePropertyDefaultOutputDevice)
    let din = defaultDevice(kAudioHardwarePropertyDefaultInputDevice)
    for d in allDevices() {
        let i = channels(d, kAudioObjectPropertyScopeInput), o = channels(d, kAudioObjectPropertyScopeOutput)
        var s = "\(d)\t\(deviceName(d))\tin=\(i) out=\(o)"
        if d == dout { s += " [default out]" }
        if d == din { s += " [default in]" }
        if o > 0 { s += " vol=\(getVolume(d)) out:\(latencyInfo(d, kAudioObjectPropertyScopeOutput))" }
        if i > 0 { s += " in:\(latencyInfo(d, kAudioObjectPropertyScopeInput))" }
        print(s)
    }

case "get-default-output":
    print(defaultDevice(kAudioHardwarePropertyDefaultOutputDevice))

case "set-default-output":
    setDefaultOutput(AudioDeviceID(args[2])!)

case "get-volume":
    print(getVolume(AudioDeviceID(args[2])!))

case "set-volume":
    setVolume(AudioDeviceID(args[2])!, Float32(args[3])!)

case "record":
    // HAL IOProc directly on the mic: inInputTime is CoreAudio's timestamp for the first frame of each buffer.
    let dev = findDevice(args[2], kAudioObjectPropertyScopeInput)
    guard let data = FileHandle(forWritingAtPath: { FileManager.default.createFile(atPath: args[3], contents: nil); return args[3] }()),
          let anc = FileHandle(forWritingAtPath: { FileManager.default.createFile(atPath: args[4], contents: nil); return args[4] }())
    else { die("cannot open outputs") }
    anc.write("# hal-ioproc \(latencyInfo(dev, kAudioObjectPropertyScopeInput))\n".data(using: .utf8)!)
    var written: Int64 = 0
    let q = DispatchQueue(label: "writer")
    var procID: AudioDeviceIOProcID?
    let st = AudioDeviceCreateIOProcIDWithBlock(&procID, dev, nil) { _, inData, inTime, _, _ in
        let abl = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inData))
        guard let b = abl.first, let p = b.mData else { return }
        let ch = Int(max(b.mNumberChannels, 1))
        let n = Int(b.mDataByteSize) / 4 / ch
        var mono = [Float](repeating: 0, count: n)
        let f = p.assumingMemoryBound(to: Float.self)
        for i in 0..<n { mono[i] = f[i * ch] }
        let host = inTime.pointee.mFlags.contains(.hostTimeValid) ? hostToNs(inTime.pointee.mHostTime) : 0
        let line = "\(written) \(host) \(inTime.pointee.mSampleTime)\n"
        written += Int64(n)
        let d = mono.withUnsafeBufferPointer { Data(buffer: $0) }
        q.async { data.write(d); anc.write(line.data(using: .utf8)!) }
    }
    if st != noErr { die("ioproc \(st)") }
    AudioDeviceStart(dev, procID)
    print("recording \(nowNs())")
    DispatchQueue.global().async {
        while readLine() != nil {}
        AudioDeviceStop(dev, procID)
        q.sync { data.closeFile(); anc.closeFile() }
        print("stopped \(nowNs())")
        exit(0)
    }
    dispatchMain()

case "record-tap":
    // Same, via an AVAudioEngine input tap (kept to cross-check the tap's timestamps against the HAL's).
    let dev = findDevice(args[2], kAudioObjectPropertyScopeInput)
    guard let data = FileHandle(forWritingAtPath: { FileManager.default.createFile(atPath: args[3], contents: nil); return args[3] }()),
          let anc = FileHandle(forWritingAtPath: { FileManager.default.createFile(atPath: args[4], contents: nil); return args[4] }())
    else { die("cannot open outputs") }
    let engine = AVAudioEngine()
    setUnitDevice(engine.inputNode.audioUnit, dev)
    let fmt = engine.inputNode.inputFormat(forBus: 0)
    anc.write("# sr=\(fmt.sampleRate) ch=\(fmt.channelCount) \(latencyInfo(dev, kAudioObjectPropertyScopeInput))\n".data(using: .utf8)!)
    var written: Int64 = 0
    let q = DispatchQueue(label: "writer")
    engine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: fmt) { buf, when in
        let n = Int(buf.frameLength)
        let d = Data(bytes: buf.floatChannelData![0], count: n * 4)
        let line = "\(written) \(when.isHostTimeValid ? hostToNs(when.hostTime) : 0) \(when.sampleTime)\n"
        written += Int64(n)
        q.async { data.write(d); anc.write(line.data(using: .utf8)!) }
    }
    do { try engine.start() } catch { die("record start: \(error)") }
    print("recording \(nowNs())")
    DispatchQueue.global().async {
        while readLine() != nil {}
        engine.stop()
        q.sync { data.closeFile(); anc.closeFile() }
        print("stopped \(nowNs())")
        exit(0)
    }
    dispatchMain()

case "player":
    let dev = findDevice(args[2], kAudioObjectPropertyScopeOutput)
    let engine = AVAudioEngine()
    setUnitDevice(engine.outputNode.audioUnit, dev)
    if args.count > 4, var frames = UInt32(args[4]), frames > 0 {  // optional smaller IO buffer
        let st = AudioUnitSetProperty(engine.outputNode.audioUnit!, kAudioDevicePropertyBufferFrameSize,
                                      kAudioUnitScope_Global, 0, &frames, UInt32(MemoryLayout<UInt32>.size))
        if st != noErr { die("set buffer frames \(st)") }
    }
    let tinkFile = try! AVAudioFile(forReading: URL(fileURLWithPath: args.count > 3 ? args[3] : "/System/Library/Sounds/Tink.aiff"))
    let tink = AVAudioPCMBuffer(pcmFormat: tinkFile.processingFormat, frameCapacity: AVAudioFrameCount(tinkFile.length))!
    try! tinkFile.read(into: tink)
    let tickNode = AVAudioPlayerNode()
    engine.attach(tickNode)
    engine.connect(tickNode, to: engine.mainMixerNode, format: tink.format)
    let speech = Speech()
    // Pre-warm: render once (gets the voice loaded and tells us the buffer format), and speak once at volume 0.
    speech.quiet = true
    let warm = speech.render("f 5.6")
    guard let sfmt = warm.first?.format else { die("render produced nothing") }
    let speechNode = AVAudioPlayerNode()
    engine.attach(speechNode)
    engine.connect(speechNode, to: engine.mainMixerNode, format: sfmt)
    var cache: [String: AVAudioPCMBuffer] = [:]
    for t in ["f 5.6", "f 8"] { if let b = concat(speech.render(t)) { cache[t] = trimLead(b) } }
    do { try engine.start() } catch { die("engine start: \(error)") }
    tickNode.play(); speechNode.play()
    let warmDone = DispatchSemaphore(value: 0)
    speech.onFinish = { warmDone.signal() }
    speech.synth.speak(speech.utt("f 5.6", volume: 0))
    DispatchQueue.global().async {
        _ = warmDone.wait(timeout: .now() + 5)
        DispatchQueue.main.async {
            speech.onFinish = nil; speech.quiet = false
            print("ready \(nowNs()) speechFormat=\(sfmt) \(latencyInfo(dev, kAudioObjectPropertyScopeOutput)) presentationLatency=\(engine.outputNode.presentationLatency)")
        }
        while let line = readLine() {
            let recv = nowNs()
            if line == "tick" {  // player nodes are thread-safe: schedule straight from the reader thread
                tickNode.scheduleBuffer(tink, at: nil, options: .interrupts)
                print("ack tick \(recv) \(nowNs())")
                continue
            }
            let parts = line.split(separator: " ", maxSplits: 1).map(String.init)
            let cmd = parts.first ?? "", text = parts.count > 1 ? parts[1] : ""
            DispatchQueue.main.async {
                switch cmd {
                case "tick":
                    tickNode.scheduleBuffer(tink, at: nil, options: .interrupts)
                case "speak":
                    speech.synth.speak(speech.utt(text))
                case "interrupt":
                    speech.synth.stopSpeaking(at: .immediate)
                    speech.synth.speak(speech.utt(text))
                case "cspeak":
                    if let b = cache[text] { speechNode.scheduleBuffer(b, at: nil, options: .interrupts) }
                case "rspeak":
                    var first = true
                    speech.synth.write(speech.utt(text)) { b in
                        guard let p = b as? AVAudioPCMBuffer, p.frameLength > 0 else { return }
                        speechNode.scheduleBuffer(p, at: nil, options: first ? .interrupts : [])
                        if first { print("event rbuf \(nowNs())") }; first = false
                    }
                case "quit":
                    exit(0)
                default:
                    print("err unknown \(cmd)")
                }
                print("ack \(cmd) \(recv) \(nowNs())")
            }
        }
        exit(0)
    }
    dispatchMain()

case "speak-once":
    let speech = Speech()
    speech.onFinish = { print("exit \(nowNs())"); exit(0) }
    print("request \(nowNs())")
    speech.synth.speak(speech.utt(args[2]))
    dispatchMain()

case "render-info":
    let speech = Speech()
    speech.quiet = true
    var result = ""
    DispatchQueue.global().async {
        let b = concat(speech.render(args[2]))!
        let i = activeInfo(b)
        result = String(format: "lead_ms=%.1f active_ms=%.1f total_ms=%.1f format=%@", i.lead, i.active, i.total, "\(b.format)")
        DispatchQueue.main.async { print(result); exit(0) }
    }
    dispatchMain()

case "file-info":
    let f = try! AVAudioFile(forReading: URL(fileURLWithPath: args[2]))
    let b = AVAudioPCMBuffer(pcmFormat: f.processingFormat, frameCapacity: AVAudioFrameCount(f.length))!
    try! f.read(into: b)
    let i = activeInfo(b)
    print(String(format: "lead_ms=%.1f active_ms=%.1f total_ms=%.1f", i.lead, i.active, i.total))

default:
    die("unknown command \(args[1])")
}
