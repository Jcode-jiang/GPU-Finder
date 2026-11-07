// 离屏渲染状态栏面板，用于验收外观。
// 用法: panel_snapshot <base-url> <out.png> [dark|light] [family]
import AppKit
import SwiftUI

@main
struct PanelSnapshot {
    @MainActor
    static func main() {
        let args = CommandLine.arguments
        guard args.count >= 3, let url = URL(string: args[1]) else {
            fputs("usage: panel_snapshot <base-url> <out.png> [dark|light] [family]\n", stderr)
            exit(2)
        }
        let outPath = args[2]
        let dark = args.count > 3 && args[3] == "dark"
        let family = args.count > 4 ? args[4] : "all"
        let rentMode = args.contains("rent")
        let mockInstance = args.contains("mockinst")

        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)

        let backend = BackendManager()
        let store = AppStore()
        store.selectedFamily = family
        store.attach(baseURL: url)

        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            if rentMode {
                let platform = args.contains("autodl") ? "autodl"
                    : args.contains("gpushare") ? "gpushare" : "compshare"
                let candidates = (store.snapshot?.offers ?? []).filter {
                    $0.platform == platform && $0.rent != nil && $0.available == true
                }
                let offer = candidates.first(where: { $0.rent?.gpuType == "4090_48G" })
                    ?? candidates.first(where: { $0.rent?.gpuType == "RTX 4090" })
                    ?? candidates.first
                if let offer = offer { store.openRent(offer) }
            }
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 6.0) {
            if rentMode && mockInstance {
                store.rentError = nil
                store.rentQuote = RentQuote(
                    platform: "compshare", gpuType: "4090_48G", region: "cn-wlcb",
                    zone: "cn-wlcb-01", zoneName: "华北二A", cpu: 16, memGb: 96,
                    imageId: "compshareImage-1hftg6805950", imageName: "cuda128_torch280_py312",
                    diskGb: 100, price: 3.61, spot: nil, capacity: true,
                    autoStopMinutes: 60, maxHourlyPrice: 5, enabled: true
                )
                store.rentInstance = RentInstance(
                    uhostId: "uhost-demo-1234", region: "cn-wlcb", zone: "cn-wlcb-01",
                    zoneName: "华北二A", gpuType: "4090_48G", gpu: "RTX 4090 48G",
                    cpu: 16, memGb: 96, price: 3.61, imageName: "cuda128_torch280_py312",
                    name: "gpufinder-demo", state: "Running", ip: "203.0.113.10",
                    sshCommand: "ssh -p 23 root@203.0.113.10", password: "demo-password",
                    released: false, autoStopAt: Int(Date().timeIntervalSince1970) + 3600,
                    error: "", warning: "",
                    ssh: SSHInfo(command: "ssh -p 23 root@203.0.113.10",
                                 password: "demo-password", ip: "203.0.113.10", user: "root")
                )
            }
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + (rentMode ? 8.0 : 3.0)) {
            let height: CGFloat = rentMode ? PanelMetrics.rentHeight(hasInstance: store.rentInstance != nil) : PanelMetrics.overviewHeight(family: family)
            let size = NSSize(width: 404, height: height)
            let backdrop = LinearGradient(
                colors: dark
                    ? [Color(hex: "#101623"), Color(hex: "#1B2233")]
                    : [Color(hex: "#EEF1F8"), Color(hex: "#E3E8F4")],
                startPoint: .topLeading, endPoint: .bottomTrailing
            )
            let root = ZStack {
                backdrop
                MenuBarView(store: store, backend: backend)
            }
            .frame(width: size.width, height: size.height)

            let hosting = NSHostingView(rootView: root)
            hosting.frame = NSRect(origin: .zero, size: size)
            let window = NSWindow(
                contentRect: NSRect(origin: .zero, size: size),
                styleMask: [.borderless], backing: .buffered, defer: false
            )
            window.contentView = hosting
            window.setFrameOrigin(NSPoint(x: -20000, y: -20000))
            window.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
            window.orderFrontRegardless()
            hosting.layoutSubtreeIfNeeded()

            guard let rep = hosting.bitmapImageRepForCachingDisplay(in: hosting.bounds) else {
                fputs("bitmap failed\n", stderr); exit(1)
            }
            hosting.cacheDisplay(in: hosting.bounds, to: rep)
            guard let data = rep.representation(using: .png, properties: [:]) else {
                fputs("png failed\n", stderr); exit(1)
            }
            do {
                try data.write(to: URL(fileURLWithPath: outPath))
                print("saved \(outPath)")
                exit(0)
            } catch {
                fputs("write failed: \(error)\n", stderr); exit(1)
            }
        }

        app.run()
    }
}
