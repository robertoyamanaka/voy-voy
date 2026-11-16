// Process tap + private aggregate device + IOProc.
// Adapted from audiotee (MIT, (C) 2025 Nick Payne) — see NOTICE.
import AVFoundation
import AudioToolbox
import CoreAudio
import Foundation

enum TapError: Error, CustomStringConvertible {
  case status(String, OSStatus)
  case format(String)
  var description: String {
    switch self {
    case .status(let what, let s): return "\(what) failed (\(s))"
    case .format(let what): return what
    }
  }
}

/// Converts the tap's float mono stream to int16 mono at `sampleRate`.
final class Int16Converter {
  private let converter: AVAudioConverter
  private let source: AVAudioFormat
  private let target: AVAudioFormat
  private var inBuf: AVAudioPCMBuffer?
  private var outBuf: AVAudioPCMBuffer?

  init(source asbd: AudioStreamBasicDescription, sampleRate: Double) throws {
    var src = asbd
    guard let source = AVAudioFormat(streamDescription: &src),
      let target = AVAudioFormat(
        commonFormat: .pcmFormatInt16, sampleRate: sampleRate, channels: 1, interleaved: true),
      let converter = AVAudioConverter(from: source, to: target)
    else { throw TapError.format("cannot build converter from \(asbd)") }
    self.source = source
    self.target = target
    self.converter = converter
  }

  func convert(_ data: UnsafeRawPointer, bytes: Int, emit: (UnsafeRawPointer, Int) -> Void) {
    let bpf = Int(source.streamDescription.pointee.mBytesPerFrame)
    guard bpf > 0 else { return }
    let frames = AVAudioFrameCount(bytes / bpf)
    let outFrames = AVAudioFrameCount(ceil(Double(frames) * target.sampleRate / source.sampleRate)) + 32
    if inBuf == nil || inBuf!.frameCapacity < frames {
      inBuf = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: frames)
    }
    if outBuf == nil || outBuf!.frameCapacity < outFrames {
      outBuf = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: outFrames)
    }
    guard let inBuf, let outBuf else { return }
    inBuf.audioBufferList.pointee.mBuffers.mData!.copyMemory(from: data, byteCount: frames == 0 ? 0 : Int(frames) * bpf)
    inBuf.frameLength = frames
    outBuf.frameLength = 0
    var consumed = false  // hand the input over exactly once per call (no duplicated audio)
    var error: NSError?
    _ = converter.convert(to: outBuf, error: &error) { _, status in
      if consumed {
        status.pointee = .noDataNow
        return nil
      }
      consumed = true
      status.pointee = .haveData
      return inBuf
    }
    if outBuf.frameLength > 0 {
      emit(outBuf.audioBufferList.pointee.mBuffers.mData!, Int(outBuf.frameLength) * 2)
    }
  }
}

final class ProcessTap {
  private var tapID = AudioObjectID(kAudioObjectUnknown)
  private var aggregateID = AudioObjectID(kAudioObjectUnknown)
  private var ioProcID: AudioDeviceIOProcID?
  private var converter: Int16Converter?

  init(processObjects: [AudioObjectID], mute: Bool = false) throws {
    let description = CATapDescription(monoMixdownOfProcesses: processObjects)
    description.name = "voy-tap"
    description.isPrivate = true
    // mute: capture the app's audio without it playing on the Mac's speakers.
    description.muteBehavior = mute ? .mutedWhenTapped : .unmuted
    var status = AudioHardwareCreateProcessTap(description, &tapID)
    guard status == noErr else { throw TapError.status("AudioHardwareCreateProcessTap", status) }

    let aggregate: [String: Any] = [
      kAudioAggregateDeviceNameKey: "voy-tap-aggregate",
      kAudioAggregateDeviceUIDKey: UUID().uuidString,
      kAudioAggregateDeviceSubDeviceListKey: [] as CFArray,
      kAudioAggregateDeviceMasterSubDeviceKey: 0,
      kAudioAggregateDeviceIsPrivateKey: true,
      kAudioAggregateDeviceIsStackedKey: false,
    ]
    status = AudioHardwareCreateAggregateDevice(aggregate as CFDictionary, &aggregateID)
    guard status == noErr else {
      destroy()
      throw TapError.status("AudioHardwareCreateAggregateDevice", status)
    }

    guard let tapUID = readString(tapID, kAudioTapPropertyUID) else {
      destroy()
      throw TapError.format("cannot read tap UID")
    }
    var address = propertyAddress(kAudioAggregateDevicePropertyTapList)
    let list = [tapUID as CFString] as CFArray
    status = withUnsafePointer(to: list) {
      AudioObjectSetPropertyData(aggregateID, &address, 0, nil, UInt32(MemoryLayout<CFArray>.size), $0)
    }
    guard status == noErr else {
      destroy()
      throw TapError.status("set aggregate tap list", status)
    }
  }

  private func streamFormat() throws -> AudioStreamBasicDescription {
    var address = propertyAddress(kAudioTapPropertyFormat)
    var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
    var asbd = AudioStreamBasicDescription()
    let status = AudioObjectGetPropertyData(tapID, &address, 0, nil, &size, &asbd)
    guard status == noErr else { throw TapError.status("read tap format", status) }
    return asbd
  }

  func start(sampleRate: Double, onPCM: @escaping (UnsafeRawPointer, Int) -> Void) throws {
    let format = try streamFormat()
    let converter = try Int16Converter(source: format, sampleRate: sampleRate)
    self.converter = converter
    logJSON(["event": "format", "source_rate": format.mSampleRate, "channels": Int(format.mChannelsPerFrame), "out_rate": sampleRate])
    let queue = DispatchQueue(label: "voy-tap.io", qos: .userInteractive)
    var status = AudioDeviceCreateIOProcIDWithBlock(&ioProcID, aggregateID, queue) {
      _, inInput, _, _, _ in
      let buffer = inInput.pointee.mBuffers
      guard let data = buffer.mData, buffer.mDataByteSize > 0 else { return }
      converter.convert(UnsafeRawPointer(data), bytes: Int(buffer.mDataByteSize), emit: onPCM)
    }
    guard status == noErr else { throw TapError.status("AudioDeviceCreateIOProcIDWithBlock", status) }
    status = AudioDeviceStart(aggregateID, ioProcID)
    guard status == noErr else { throw TapError.status("AudioDeviceStart", status) }
  }

  func destroy() {
    if let ioProcID {
      AudioDeviceStop(aggregateID, ioProcID)
      AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
      self.ioProcID = nil
    }
    if aggregateID != kAudioObjectUnknown {
      AudioHardwareDestroyAggregateDevice(aggregateID)
      aggregateID = AudioObjectID(kAudioObjectUnknown)
    }
    if tapID != kAudioObjectUnknown {
      AudioHardwareDestroyProcessTap(tapID)
      tapID = AudioObjectID(kAudioObjectUnknown)
    }
  }
}
