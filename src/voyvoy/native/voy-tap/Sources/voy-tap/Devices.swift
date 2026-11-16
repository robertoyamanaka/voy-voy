import CoreAudio
import Foundation

// MARK: - Core Audio property helpers

func propertyAddress(
  _ selector: AudioObjectPropertySelector,
  scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal,
  element: AudioObjectPropertyElement = kAudioObjectPropertyElementMain
) -> AudioObjectPropertyAddress {
  AudioObjectPropertyAddress(mSelector: selector, mScope: scope, mElement: element)
}

let systemObject = AudioObjectID(kAudioObjectSystemObject)

func readObjectIDs(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> [AudioObjectID] {
  var address = propertyAddress(selector)
  var size: UInt32 = 0
  guard AudioObjectGetPropertyDataSize(object, &address, 0, nil, &size) == noErr, size > 0 else {
    return []
  }
  var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
  guard AudioObjectGetPropertyData(object, &address, 0, nil, &size, &ids) == noErr else { return [] }
  return ids
}

func readString(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> String? {
  var address = propertyAddress(selector)
  var size = UInt32(MemoryLayout<CFString?>.size)
  var value: Unmanaged<CFString>?
  let status = withUnsafeMutablePointer(to: &value) {
    AudioObjectGetPropertyData(object, &address, 0, nil, &size, $0)
  }
  guard status == noErr, let value else { return nil }
  return value.takeRetainedValue() as String
}

func readUInt32(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector) -> UInt32? {
  var address = propertyAddress(selector)
  var size = UInt32(MemoryLayout<UInt32>.size)
  var value: UInt32 = 0
  guard AudioObjectGetPropertyData(object, &address, 0, nil, &size, &value) == noErr else { return nil }
  return value
}

// MARK: - Devices

struct DeviceInfo: Codable {
  let uid: String
  let name: String
  let input: Bool
  let output: Bool
}

private func hasStreams(_ device: AudioObjectID, scope: AudioObjectPropertyScope) -> Bool {
  var address = propertyAddress(kAudioDevicePropertyStreams, scope: scope)
  var size: UInt32 = 0
  return AudioObjectGetPropertyDataSize(device, &address, 0, nil, &size) == noErr && size > 0
}

func listDevices() -> [DeviceInfo] {
  readObjectIDs(systemObject, kAudioHardwarePropertyDevices).compactMap { id in
    guard let uid = readString(id, kAudioDevicePropertyDeviceUID) else { return nil }
    let name = readString(id, kAudioObjectPropertyName) ?? uid
    return DeviceInfo(
      uid: uid, name: name,
      input: hasStreams(id, scope: kAudioObjectPropertyScopeInput),
      output: hasStreams(id, scope: kAudioObjectPropertyScopeOutput))
  }
}

func deviceID(forUID uid: String) -> AudioObjectID? {
  readObjectIDs(systemObject, kAudioHardwarePropertyDevices).first {
    readString($0, kAudioDevicePropertyDeviceUID) == uid
  }
}

func defaultInputUID() -> String? {
  guard let id = readObjectIDs(systemObject, kAudioHardwarePropertyDefaultInputDevice).first else {
    return nil
  }
  return readString(id, kAudioDevicePropertyDeviceUID)
}

func setDefaultInput(uid: String) -> String? {
  guard let id = deviceID(forUID: uid) else { return "no device with uid \(uid)" }
  guard hasStreams(id, scope: kAudioObjectPropertyScopeInput) else { return "\(uid) is not an input device" }
  var address = propertyAddress(kAudioHardwarePropertyDefaultInputDevice)
  var value = id
  let status = AudioObjectSetPropertyData(
    systemObject, &address, 0, nil, UInt32(MemoryLayout<AudioObjectID>.size), &value)
  return status == noErr ? nil : "AudioObjectSetPropertyData failed (\(status))"
}
