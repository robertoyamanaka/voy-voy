// swift-tools-version: 5.9
import Foundation
import PackageDescription

// Embed Info.plist (NSAudioCaptureUsageDescription) so macOS can ask for
// audio-capture permission on behalf of voy-tap itself, not the terminal.
let infoPlist = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
  .appendingPathComponent("Info.plist").path

let package = Package(
  name: "voy-tap",
  platforms: [.macOS("14.2")],
  targets: [
    .executableTarget(
      name: "voy-tap",
      path: "Sources/voy-tap",
      linkerSettings: [
        .unsafeFlags([
          "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist",
          "-Xlinker", infoPlist,
        ])
      ])
  ]
)
