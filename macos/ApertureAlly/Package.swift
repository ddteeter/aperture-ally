// swift-tools-version:5.9
// "Aperture Ally.app": supervises the Python server, shows the UI in its own window, and speaks in-process.
// Build the .app with scripts/build-mac-app.sh.
import PackageDescription

let package = Package(
    name: "ApertureAlly",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(name: "ApertureAlly", path: "Sources/ApertureAlly"),
    ]
)
