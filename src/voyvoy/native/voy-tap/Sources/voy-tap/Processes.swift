import CoreAudio
import Foundation

/// A process Core Audio knows about (it has used audio since it started).
struct AudioProcess {
  let objectID: AudioObjectID
  let pid: Int32
  let bundleID: String
  let isRunningOutput: Bool
}

/// `--app` keys → bundle-ID prefixes, in `auto` priority order.
/// Chrome renders audio in Helper processes whose bundle IDs share the prefix.
let appBundlePrefixes: [(app: String, prefix: String)] = [
  ("chrome", "com.google.Chrome"),
  ("arc", "company.thebrowser.Browser"),
  ("slack", "com.tinyspeck.slackmacgap"),
  ("zoom", "us.zoom.xos"),
]

func listAudioProcesses() -> [AudioProcess] {
  readObjectIDs(systemObject, kAudioHardwarePropertyProcessObjectList).map { id in
    var pid: Int32 = -1
    var address = propertyAddress(kAudioProcessPropertyPID)
    var size = UInt32(MemoryLayout<Int32>.size)
    _ = AudioObjectGetPropertyData(id, &address, 0, nil, &size, &pid)
    return AudioProcess(
      objectID: id,
      pid: pid,
      bundleID: readString(id, kAudioProcessPropertyBundleID) ?? "",
      isRunningOutput: (readUInt32(id, kAudioProcessPropertyIsRunningOutput) ?? 0) != 0)
  }
}

struct TapTarget {
  let label: String
  let processes: [AudioProcess]
}

/// One look at the current process list. Returns a target only when at least one
/// matching process is playing audio right now; the tap then covers every matching
/// process object (so a Chrome Helper that starts playing later is included).
func findTarget(app: String?, pids: [Int32]) -> TapTarget? {
  let processes = listAudioProcesses()
  if !pids.isEmpty {
    let matches = processes.filter { pids.contains($0.pid) }
    let label = "pid:" + pids.map(String.init).joined(separator: ",")
    return matches.contains(where: \.isRunningOutput) ? TapTarget(label: label, processes: matches) : nil
  }
  let wanted = (app == nil || app == "auto") ? appBundlePrefixes : appBundlePrefixes.filter { $0.app == app }
  for entry in wanted {
    let matches = processes.filter { $0.bundleID.hasPrefix(entry.prefix) }
    if matches.contains(where: \.isRunningOutput) {
      return TapTarget(label: entry.prefix, processes: matches)
    }
  }
  return nil
}

func waitForTarget(app: String?, pids: [Int32], timeout: Double) -> TapTarget? {
  let deadline = Date().addingTimeInterval(timeout)
  repeat {
    if let target = findTarget(app: app, pids: pids) { return target }
    Thread.sleep(forTimeInterval: 1.0)
  } while Date() < deadline
  return findTarget(app: app, pids: pids)
}
