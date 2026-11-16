import CoreAudio
import Foundation

func logJSON(_ fields: [String: Any]) {
  guard let data = try? JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys]) else { return }
  FileHandle.standardError.write(data + Data("\n".utf8))
}

func fail(_ message: String, code: Int32 = 1) -> Never {
  logJSON(["event": "error", "message": message])
  exit(code)
}

let usage = """
  usage:
    voy-tap capture (--app auto|chrome|arc|slack|zoom | --pid N[,N...]) [--sample-rate 24000] [--wait 30] [--mute]
      exit 3: nothing matching is playing audio; exit 4: the tapped app went away
    voy-tap devices
    voy-tap default-input
    voy-tap set-default-input <uid>
  """

/// Writes all bytes to stdout; exits quietly when the reader goes away.
func writeAll(_ pointer: UnsafeRawPointer, _ count: Int) {
  var offset = 0
  while offset < count {
    let n = write(STDOUT_FILENO, pointer + offset, count - offset)
    if n <= 0 { exit(0) }
    offset += n
  }
}

func runCapture(_ args: [String]) -> Never {
  var app: String? = "auto"
  var pids: [Int32] = []
  var sampleRate = 24000.0
  var wait = 30.0
  var i = 0
  var mute = false
  while i < args.count {
    let flag = args[i]
    if flag == "--mute" {
      mute = true
      i += 1
      continue
    }
    guard i + 1 < args.count else { fail("missing value for \(flag)\n\(usage)", code: 2) }
    let value = args[i + 1]
    switch flag {
    case "--app":
      guard value == "auto" || appBundlePrefixes.contains(where: { $0.app == value }) else {
        fail("unknown --app \(value)", code: 2)
      }
      app = value
    case "--pid":
      let parsed = value.split(separator: ",").compactMap { Int32($0) }
      guard !parsed.isEmpty, parsed.count == value.split(separator: ",").count else { fail("bad --pid \(value)", code: 2) }
      pids = parsed
      app = nil
    case "--sample-rate":
      guard let r = Double(value), [8000, 16000, 24000, 44100, 48000].contains(r) else {
        fail("bad --sample-rate \(value)", code: 2)
      }
      sampleRate = r
    case "--wait":
      guard let w = Double(value), w >= 0, w <= 3600 else { fail("bad --wait \(value)", code: 2) }
      wait = w
    default:
      fail("unknown flag \(flag)\n\(usage)", code: 2)
    }
    i += 2
  }

  guard let target = waitForTarget(app: app, pids: pids, timeout: wait) else {
    fail("no matching process is playing audio (app=\(app ?? "-"), pids=\(pids))", code: 3)
  }
  logJSON([
    "event": "tapping", "bundle": target.label,
    "pids": Array(Set(target.processes.map { Int($0.pid) })).sorted(),
  ])

  signal(SIGPIPE, SIG_IGN)
  let tap: ProcessTap
  do {
    tap = try ProcessTap(processObjects: target.processes.map(\.objectID), mute: mute)
    try tap.start(sampleRate: sampleRate) { ptr, count in writeAll(ptr, count) }
  } catch {
    fail("tap failed: \(error)")
  }

  for sig in [SIGINT, SIGTERM, SIGHUP] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler {
      tap.destroy()
      exit(0)
    }
    source.resume()
    signalSources.append(source)
  }

  // Exit 4 once every tapped process is gone (the meeting app quit), instead of
  // streaming nothing forever.
  // Uses Core Audio's own process-object list: an exited process that hasn't been
  // reaped yet (a zombie) still answers kill(pid, 0) but is gone from Core Audio.
  let tapped = Set(target.processes.map(\.objectID))
  let watchdog = DispatchSource.makeTimerSource(queue: .main)
  watchdog.schedule(deadline: .now() + 1, repeating: 1)
  watchdog.setEventHandler {
    let alive = !tapped.isDisjoint(with: readObjectIDs(systemObject, kAudioHardwarePropertyProcessObjectList))
    if !alive {
      logJSON(["event": "target_exited"])
      tap.destroy()
      exit(4)
    }
  }
  watchdog.resume()
  targetWatchdog = watchdog
  dispatchMain()
}

var signalSources: [DispatchSourceSignal] = []
var targetWatchdog: DispatchSourceTimer?

/// Re-launch ourselves as our own TCC "responsible process" so macOS asks for
/// audio-capture permission for voy-tap (embedded Info.plist), instead of
/// silently attributing it to a terminal that cannot show the prompt.
/// Uses the private libsystem call responsibility_spawnattrs_setdisclaim.
func relaunchDisclaimed() -> Never {
  typealias Disclaim = @convention(c) (UnsafeMutablePointer<posix_spawnattr_t?>, Int32) -> Int32
  guard let sym = dlsym(UnsafeMutableRawPointer(bitPattern: -2), "responsibility_spawnattrs_setdisclaim") else {
    fail("responsibility_spawnattrs_setdisclaim unavailable")
  }
  let disclaim = unsafeBitCast(sym, to: Disclaim.self)
  var attr: posix_spawnattr_t?
  posix_spawnattr_init(&attr)
  _ = disclaim(&attr, 1)
  setenv("VOY_TAP_DISCLAIMED", "1", 1)
  let argv: [UnsafeMutablePointer<CChar>?] = CommandLine.arguments.map { strdup($0) } + [nil]
  var child: pid_t = 0
  let exe = Bundle.main.executablePath ?? CommandLine.arguments[0]
  let status = posix_spawn(&child, exe, nil, &attr, argv, environ)
  guard status == 0 else { fail("posix_spawn failed (\(status))") }
  for sig in [SIGINT, SIGTERM, SIGHUP] {
    signal(sig, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .global())
    source.setEventHandler { kill(child, sig) }
    source.resume()
    signalSources.append(source)
  }
  var wstatus: Int32 = 0
  while waitpid(child, &wstatus, 0) == -1 && errno == EINTR {}
  let exited = (wstatus & 0x7f) == 0
  exit(exited ? (wstatus >> 8) & 0xff : 1)
}

let arguments = Array(CommandLine.arguments.dropFirst())
switch arguments.first {
case "capture":
  if ProcessInfo.processInfo.environment["VOY_TAP_DISCLAIMED"] != "1" { relaunchDisclaimed() }
  runCapture(Array(arguments.dropFirst()))
case "devices":
  let data = try! JSONEncoder().encode(listDevices())
  FileHandle.standardOutput.write(data + Data("\n".utf8))
case "default-input":
  guard let uid = defaultInputUID() else { fail("no default input device") }
  print(uid)
case "set-default-input":
  guard arguments.count == 2 else { fail(usage, code: 2) }
  if let error = setDefaultInput(uid: arguments[1]) { fail(error) }
default:
  FileHandle.standardError.write(Data((usage + "\n").utf8))
  exit(2)
}
