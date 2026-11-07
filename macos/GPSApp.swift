// GPU Finder — 状态栏控制器与应用入口。
// 界面与数据层见 GPSSUI.swift。

import AppKit
import SwiftUI
import Combine

// MARK: - 状态栏控制器

@MainActor
final class StatusController: NSObject {
    private let statusItem: NSStatusItem
    private let popover = NSPopover()
    private let backend: BackendManager
    private let store = AppStore()
    private var cancellables = Set<AnyCancellable>()

    init(backend: BackendManager) {
        self.backend = backend
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()
        configureButton()
        configurePopover()
        observe()
    }

    private func configureButton() {
        guard let button = statusItem.button else { return }
        if let image = NSImage(systemSymbolName: "memorychip", accessibilityDescription: "GPU Finder") {
            image.isTemplate = true
            button.image = image
            button.imagePosition = .imageLeading
        } else {
            button.title = "GPU"
        }
        button.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .medium)
        button.toolTip = "GPU Finder X · 点击查看多平台 GPU 算力行情"
        button.target = self
        button.action = #selector(handleClick)
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
    }

    private func configurePopover() {
        popover.behavior = .transient
        popover.animates = true
        popover.contentSize = NSSize(width: 404, height: PanelMetrics.overviewHeight(family: "all"))
        let root = MenuBarView(store: store, backend: backend)
        popover.contentViewController = NSHostingController(rootView: root)
    }

    private func observe() {
        backend.$baseURL
            .compactMap { $0 }
            .receive(on: RunLoop.main)
            .sink { [weak self] url in
                self?.store.attach(baseURL: url)
            }
            .store(in: &cancellables)

        store.$snapshot
            .receive(on: RunLoop.main)
            .sink { [weak self] snapshot in
                self?.updateMenuBarTitle(snapshot)
            }
            .store(in: &cancellables)

        store.$selectedFamily
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.updatePopoverSize() }
            .store(in: &cancellables)

        store.$panelMode
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.updatePopoverSize() }
            .store(in: &cancellables)

        store.$rentInstance
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.updatePopoverSize() }
            .store(in: &cancellables)
    }

    private func updatePopoverSize() {
        let height: CGFloat
        if store.panelMode == "rent" {
            height = PanelMetrics.rentHeight(hasInstance: store.rentInstance != nil)
        } else {
            height = PanelMetrics.overviewHeight(family: store.selectedFamily)
        }
        popover.contentSize = NSSize(width: 404, height: height)
    }

    private func updateMenuBarTitle(_ snapshot: Snapshot?) {
        guard let button = statusItem.button else { return }
        let offers = (snapshot?.offers ?? []).filter { $0.available == true && $0.price != nil }
        guard let cheapest = offers.min(by: { ($0.price ?? 0) < ($1.price ?? 0) }) ?? (snapshot?.offers ?? []).filter({ $0.price != nil }).min(by: { ($0.price ?? 0) < ($1.price ?? 0) }) else {
            button.title = ""
            return
        }
        let symbol = (cheapest.currency ?? "CNY").uppercased() == "USD" ? "$" : "¥"
        button.title = String(format: " \(symbol)%.2f", cheapest.price ?? 0)
        let source = cheapest.source == "reference" ? "第三方参考" : "官网"
        button.toolTip = "GPU Finder X · 最低 \(symbol)\(String(format: "%.2f", cheapest.price ?? 0))/时 · \(cheapest.platformName)（\(source)）"
    }

    @objc private func handleClick() {
        let eventType = NSApp.currentEvent?.type
        if eventType == .rightMouseUp {
            showMenu()
        } else {
            togglePopover()
        }
    }

    private func togglePopover() {
        if popover.isShown {
            popover.performClose(nil)
            return
        }
        guard let button = statusItem.button else { return }
        NSApp.activate(ignoringOtherApps: true)
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
        // 点开即刷新行情与实例状态
        Task {
            await store.refresh()
            await store.loadRentState()
            await store.loadOverviewSettings()
            await store.loadCatalog()
        }
    }

    private func showMenu() {
        let menu = NSMenu()
        let refreshItem = NSMenuItem(title: "立即刷新", action: #selector(menuRefresh), keyEquivalent: "r")
        refreshItem.target = self
        menu.addItem(refreshItem)
        let dashItem = NSMenuItem(title: "打开 Dashboard", action: #selector(menuDashboard), keyEquivalent: "d")
        dashItem.target = self
        menu.addItem(dashItem)
        menu.addItem(.separator())
        let quitItem = NSMenuItem(title: "退出 GPU Finder X", action: #selector(menuQuit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)
        guard let button = statusItem.button else { return }
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 3), in: button)
    }

    /// 端到端自检：拉起面板并把状态写入文件，用于构建后验证。
    func runSmokeTest(output: String) {
        togglePopover()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            let report: [String: Any] = [
                "panel_shown": self.popover.isShown,
                "offers": self.store.snapshot?.offers?.count ?? -1,
                "platforms": self.store.snapshot?.platforms?.count ?? -1,
                "backend": self.store.baseURLString,
                "timestamp": ISO8601DateFormatter().string(from: Date()),
            ]
            let path = output.replacingOccurrences(of: "~", with: NSHomeDirectory())
            if let data = try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted]) {
                try? data.write(to: URL(fileURLWithPath: path))
            }
            NSLog("GPUFinder smoke: %@", String(describing: report))
            NSApp.terminate(nil)
        }
    }

    @objc private func menuRefresh() { Task { await store.refresh() } }
    @objc private func menuDashboard() { store.openDashboard() }
    @objc private func menuQuit() { NSApp.terminate(nil) }
}

// MARK: - 应用入口

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusController: StatusController?
    private let backend = BackendManager()

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusController = StatusController(backend: backend)
        backend.start()

        if CommandLine.arguments.contains("--smoke-test") {
            let cache = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Caches/gpufinder", isDirectory: true)
            try? FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
            let output = cache.appendingPathComponent("smoke.json").path
            DispatchQueue.main.asyncAfter(deadline: .now() + 5.0) { [weak self] in
                self?.statusController?.runSmokeTest(output: output)
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        backend.stop()
    }
}

@main
struct GPUFinderMain {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        withExtendedLifetime(delegate) {
            app.run()
        }
    }
}
