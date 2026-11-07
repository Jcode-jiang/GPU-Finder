// GPU Finder — macOS 状态栏算力行情工具
// 打开面板时自动刷新；后端为本地 Python 服务（自动拉起）。
//
// 构建：见 macos/build.sh

import AppKit
import SwiftUI
import Combine

// MARK: - 数据模型

struct Snapshot: Codable {
    var schema: Int?
    var generatedAt: String?
    var generatedTs: Double?
    var durationMs: Int?
    var summary: Summary?
    var platforms: [PlatformReport]?
    var offers: [Offer]?
}

struct Summary: Codable {
    var offers: Int?
    var available: Int?
}

struct PlatformReport: Codable, Identifiable {
    var id: String
    var name: String
    var ok: Bool?
    var mode: String?
    var message: String?
    var latencyMs: Int?
    var offerCount: Int?
    var accent: String?
    var authRequired: Bool?
    var credentialsConfigured: Bool?
    var homepage: String?
}

struct Offer: Codable, Identifiable {
    var id: String
    var platform: String
    var platformName: String
    var gpu: String
    var family: String
    var vramGb: Int?
    var region: String?
    var price: Double?
    var priceLabel: String?
    var billing: String?
    var available: Bool?
    var stock: Int?
    var capacity: Int?
    var status: String?
    var source: String?
    var sourceLabel: String?
    var url: String?
    var notes: String?
    var rent: RentSpec?
}

struct RentSpec: Codable {
    var platform: String?
    var price: Double?
    var gpuType: String?
    var cpu: Int?
    var memGb: Int?
    var region: String?
    var zone: String?
    var zoneName: String?
}

struct RentSettings: Codable {
    var enabled: Bool?
    var imageId: String?
    var diskGb: Int?
    var autoStopMinutes: Int?
    var maxHourlyPrice: Double?
    var namePrefix: String?
}

struct RentImage: Codable, Identifiable {
    var id: String
    var name: String
    var type: String?
}

struct RentZone: Codable, Identifiable {
    var region: String
    var zone: String
    var name: String
    var id: String { zone }
}

struct RentOptions: Codable {
    var ok: Bool?
    var settings: RentSettings?
    var zones: [RentZone]?
    var images: [RentImage]?
    var balance: Double?
}

struct RentQuote: Codable {
    var machineId: String?
    var platform: String?
    var gpuType: String?
    var region: String?
    var zone: String?
    var zoneName: String?
    var cpu: Int?
    var memGb: Int?
    var imageId: String?
    var imageName: String?
    var diskGb: Int?
    var price: Double?
    var spot: Double?
    var capacity: Bool?
    var autoStopMinutes: Int?
    var maxHourlyPrice: Double?
    var enabled: Bool?
}

struct RentQuoteResponse: Codable {
    var ok: Bool?
    var quote: RentQuote?
    var error: String?
}

struct SSHInfo: Codable {
    var command: String?
    var password: String?
    var ip: String?
    var user: String?
}

struct RentInstance: Codable, Identifiable {
    var platform: String?
    var uhostId: String
    var region: String?
    var zone: String?
    var zoneName: String?
    var gpuType: String?
    var gpu: String?
    var cpu: Int?
    var memGb: Int?
    var price: Double?
    var imageName: String?
    var name: String?
    var state: String?
    var ip: String?
    var sshCommand: String?
    var password: String?
    var released: Bool?
    var autoStopAt: Int?
    var error: String?
    var warning: String?
    var ssh: SSHInfo?
    var id: String { uhostId }
    var active: Bool { released != true }
    var isRunning: Bool { (state ?? "").lowercased() == "running" }
    var stateLabel: String {
        let s = (state ?? "").lowercased()
        if s == "running" { return "运行中" }
        if s == "creating" || s == "starting" || s == "pending" { return "初始化中" }
        if s == "stopped" || s == "shutdown" { return "已关机" }
        if s == "released" { return "已释放" }
        if s.hasPrefix("shutdown") || s == "error" || s == "failed" { return "异常" }
        return state ?? "—"
    }
}

struct RentCreateResponse: Codable {
    var ok: Bool?
    var instance: RentInstance?
    var error: String?
}

struct RentInstancesResponse: Codable {
    var ok: Bool?
    var instances: [RentInstance]?
    var settings: RentSettings?
    var error: String?
}

struct ConfigResponse: Codable {
    var rent: RentSettings?
}

struct RentFlowError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

// MARK: - 主题辅助

extension Color {
    init(hex: String) {
        let cleaned = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        var value: UInt64 = 0
        Scanner(string: cleaned).scanHexInt64(&value)
        let r = Double((value >> 16) & 0xFF) / 255.0
        let g = Double((value >> 8) & 0xFF) / 255.0
        let b = Double(value & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b)
    }

    static let brand = Color(hex: "#4B7BFF")
    static let brand2 = Color(hex: "#7A5CF5")
    static let positive = Color(hex: "#18A874")
    static let negative = Color(hex: "#E04B4B")
    static let warning = Color(hex: "#D9902B")
}

extension PlatformReport {
    var accentColor: Color { Color(hex: accent ?? "#64748B") }
    var initial: String {
        switch id {
        case "autodl": return "A"
        case "matpool": return "矩"
        case "compshare": return "优"
        case "gpushare": return "恒"
        default: return String(name.prefix(1))
        }
    }
    var modeLabel: String {
        switch mode {
        case "live": return "实时"
        case "reference": return "参考"
        case "auth": return "需登录"
        case "error": return "失败"
        default: return "—"
        }
    }
}

extension Offer {
    var stockText: String {
        if available == false { return "无货" }
        if available == nil { return "未知" }
        if let stock = stock { return "有货 \(stock)" }
        return "有货"
    }
}

// MARK: - 视觉组件

struct VisualEffectView: NSViewRepresentable {
    var material: NSVisualEffectView.Material = .popover
    var blending: NSVisualEffectView.BlendingMode = .behindWindow

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blending
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
    }
}

final class HoverState: ObservableObject {
    @Published var hovering = false
}

/// 给可点区域加 hover 高亮 + 手型光标
struct HoverBox<Content: View>: View {
    let content: (Bool) -> Content

    @StateObject private var state = HoverState()

    init(@ViewBuilder content: @escaping (Bool) -> Content) {
        self.content = content
    }

    var body: some View {
        content(state.hovering)
            .onHover { inside in
                state.hovering = inside
                if inside { NSCursor.pointingHand.push() } else { NSCursor.pop() }
            }
    }
}

/// 面板头部圆形图标按钮
struct PanelIconButton: View {
    let systemName: String
    var help: String = ""
    var tint: Color = .primary
    let action: () -> Void

    var body: some View {
        HoverBox { hover in
            Button(action: action) {
                Image(systemName: systemName)
                    .font(.system(size: 11, weight: .semibold))
                    .frame(width: 28, height: 28)
                    .background(
                        Circle().fill(hover ? Color.primary.opacity(0.14) : Color.primary.opacity(0.07))
                    )
                    .overlay(
                        Circle().stroke(Color.primary.opacity(hover ? 0.22 : 0.10), lineWidth: 1)
                    )
                    .foregroundStyle(tint)
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .help(help)
        }
    }
}

struct Avatar: View {
    let report: PlatformReport
    var size: CGFloat = 28

    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
            .fill(
                LinearGradient(
                    colors: [report.accentColor, report.accentColor.opacity(0.72)],
                    startPoint: .topLeading, endPoint: .bottomTrailing
                )
            )
            .overlay(
                Text(report.initial)
                    .font(.system(size: size * 0.42, weight: .bold))
                    .foregroundStyle(.white)
            )
            .frame(width: size, height: size)
            .shadow(color: report.accentColor.opacity(0.28), radius: 4, x: 0, y: 2)
    }
}

struct ModeBadge: View {
    let mode: String
    var body: some View {
        let (text, color): (String, Color) = {
            switch mode {
            case "live": return ("实时", .positive)
            case "reference": return ("参考", .warning)
            case "auth": return ("需登录", .warning)
            case "error": return ("失败", .negative)
            default: return ("—", .secondary)
            }
        }()
        Text(text)
            .font(.system(size: 9.5, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 5)
            .padding(.vertical, 1.5)
            .background(Capsule().fill(color.opacity(0.13)))
    }
}

struct StockPill: View {
    let offer: Offer

    var body: some View {
        let (color, dot): (Color, Color) = {
            if offer.available == true { return (.positive, .positive) }
            if offer.available == false { return (.negative, .negative) }
            return (.secondary, .secondary)
        }()
        HStack(spacing: 4) {
            Circle().fill(dot).frame(width: 4.5, height: 4.5)
            Text(offer.stockText).font(.system(size: 10.5, weight: .medium))
        }
        .foregroundStyle(color)
    }
}

struct PriceText: View {
    let price: Double?
    var size: CGFloat = 14

    var body: some View {
        if let price = price {
            HStack(alignment: .firstTextBaseline, spacing: 1) {
                Text("¥").font(.system(size: size * 0.66, weight: .semibold))
                    .foregroundStyle(.secondary)
                Text(String(format: price >= 10 ? "%.1f" : "%.2f", price))
                    .font(.system(size: size, weight: .semibold, design: .rounded))
                    .monospacedDigit()
            }
        } else {
            Text("—").font(.system(size: size, weight: .medium)).foregroundStyle(.secondary)
        }
    }
}

// MARK: - 后端管理

@MainActor
final class BackendManager: ObservableObject {
    @Published var baseURL: URL?
    @Published var error: String?
    @Published var starting = true

    private var process: Process?
    private var pipe: Pipe?
    private var buffer = ""
    private var didResolve = false
    private var reused = false

    var pythonPath: String? {
        let candidates = [
            Bundle.main.resourceURL?.appendingPathComponent("python/bin/python3").path,
            "/usr/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
        ].compactMap { $0 }
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    func start() {
        // 复用已在 8765 运行的实例
        Task {
            if let url = await probe(port: 8765) {
                reused = true
                didResolve = true
                starting = false
                baseURL = url
                return
            }
            spawn()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 25) { [weak self] in
            guard let self = self, !self.didResolve else { return }
            if self.error == nil {
                self.error = "后端启动超时。请确认已安装 Python 3 与命令行工具。"
                self.starting = false
            }
        }
    }

    private func probe(port: Int) async -> URL? {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/health") else { return nil }
        var request = URLRequest(url: url)
        request.timeoutInterval = 0.8
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  obj["app"] as? String == "gpufinder" else { return nil }
            return URL(string: "http://127.0.0.1:\(port)")
        } catch {
            return nil
        }
    }

    private func spawn() {
        guard let python = pythonPath else {
            error = "未找到 python3。请安装 Xcode Command Line Tools（xcode-select --install）。"
            starting = false
            return
        }
        guard let resourceURL = Bundle.main.resourceURL else {
            error = "应用资源缺失，请重新构建。"
            starting = false
            return
        }
        let pythonDir = resourceURL.appendingPathComponent("python").path
        let task = Process()
        task.executableURL = URL(fileURLWithPath: python)
        // 固定 8765，Dashboard 地址稳定、书签不会失效；被占用时服务端会自动换端口
        task.arguments = ["-m", "gpufinder", "serve", "--port", "8765", "--no-scheduler",
                          "--parent-pid", String(ProcessInfo.processInfo.processIdentifier)]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = pythonDir
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        task.environment = env
        task.currentDirectoryURL = resourceURL

        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        self.pipe = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8) else { return }
            Task { @MainActor in self?.consume(text) }
        }
        task.terminationHandler = { [weak self] proc in
            Task { @MainActor in
                guard let self = self, !self.didResolve || proc.terminationStatus != 0 else { return }
                if !self.reused && !self.didResolve {
                    let tail = self.buffer
                        .split(separator: "\n")
                        .suffix(3)
                        .joined(separator: " ")
                    self.error = "后端进程退出（code \(proc.terminationStatus)）\(tail.isEmpty ? "" : "：" + tail)"
                    self.starting = false
                }
            }
        }

        do {
            try task.run()
            process = task
        } catch {
            self.error = "无法启动后端：\(error.localizedDescription)"
            starting = false
        }
    }

    private func consume(_ text: String) {
        buffer += text
        if let range = buffer.range(of: "READY http://127.0.0.1:") {
            let rest = buffer[range.upperBound...]
            let digits = rest.prefix { $0.isNumber }
            if !digits.isEmpty, let port = Int(digits) {
                didResolve = true
                starting = false
                baseURL = URL(string: "http://127.0.0.1:\(port)")
            }
        }
        if buffer.count > 6000 { buffer = String(buffer.suffix(3000)) }
    }

    func stop() {
        pipe?.fileHandleForReading.readabilityHandler = nil
        guard let task = process, task.isRunning else { return }
        task.terminate()
        process = nil
    }
}

// MARK: - 数据仓库

@MainActor
final class AppStore: ObservableObject {
    @Published var snapshot: Snapshot?
    @Published var loading = true
    @Published var refreshing = false
    @Published var error: String?
    @Published var lastUpdated = ""
    @Published var selectedFamily = "all"

    @Published var panelMode = "overview"      // overview | rent
    @Published var rentEnabled = false
    @Published var rentSettings: RentSettings?
    @Published var rentTarget: Offer?
    @Published var rentQuote: RentQuote?
    @Published var rentInstance: RentInstance?
    @Published var rentError: String?
    @Published var rentNotice: String?
    @Published var rentBusy = false
    @Published var rentConfirm = false
    @Published var rentPlatform = "compshare"
    @Published var instances: [RentInstance] = []

    var activeInstances: [RentInstance] { instances.filter { $0.active } }

    private var baseURL: URL?
    private var decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    var baseURLString: String { baseURL?.absoluteString ?? "" }

    func attach(baseURL: URL) {
        self.baseURL = baseURL
        Task { await self.load() }
    }

    func load() async {
        guard let baseURL = baseURL else { return }
        do {
            var request = URLRequest(url: baseURL.appendingPathComponent("api/snapshot"))
            request.timeoutInterval = 20
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                throw URLError(.badServerResponse)
            }
            let snap = try decoder.decode(Snapshot.self, from: data)
            snapshot = snap
            error = nil
            loading = false
            updateTimestamp()
        } catch {
            self.error = "读取行情失败：\(error.localizedDescription)"
            loading = false
        }
    }

    func refresh() async {
        guard let baseURL = baseURL, !refreshing else { return }
        refreshing = true
        defer { refreshing = false }
        do {
            var request = URLRequest(url: baseURL.appendingPathComponent("api/refresh"))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = Data("{}".utf8)
            request.timeoutInterval = 45
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                throw URLError(.badServerResponse)
            }
            let snap = try decoder.decode(Snapshot.self, from: data)
            snapshot = snap
            error = nil
            loading = false
            updateTimestamp()
        } catch {
            self.error = "刷新失败：\(error.localizedDescription)"
        }
    }

    func refreshIfNeeded() {
        guard snapshot != nil else {
            Task { await load() }
            return
        }
        Task { await refresh() }
    }

    private func updateTimestamp() {
        guard let ts = snapshot?.generatedTs else { lastUpdated = ""; return }
        let seconds = Int(Date().timeIntervalSince1970 - ts)
        if seconds < 45 { lastUpdated = "刚刚更新" }
        else if seconds < 3600 { lastUpdated = "\(max(1, seconds / 60)) 分钟前更新" }
        else if seconds < 86400 { lastUpdated = "\(seconds / 3600) 小时前更新" }
        else { lastUpdated = "\(seconds / 86400) 天前更新" }
    }


    // ------------------------------------------------------------------ 租卡
    private func apiRequest<T: Decodable>(
        _ path: String,
        method: String = "GET",
        body: [String: Any]? = nil,
        timeout: TimeInterval = 30
    ) async throws -> T {
        guard let baseURL = baseURL else { throw URLError(.badURL) }
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.timeoutInterval = timeout
        if let body = body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            if let failure = try? decoder.decode(RentCreateResponse.self, from: data),
               let message = failure.error {
                throw RentFlowError(message)
            }
            throw URLError(.badServerResponse)
        }
        return try decoder.decode(T.self, from: data)
    }

    func loadRentState() async {
        guard baseURL != nil else { return }
        do {
            let cfg: ConfigResponse = try await apiRequest("api/config")
            rentEnabled = cfg.rent?.enabled ?? false
            rentSettings = cfg.rent
        } catch {
            /* 配置读取失败不影响行情 */
        }
        await loadInstances()
    }

    func loadInstances(platform: String? = nil) async {
        guard baseURL != nil else { return }
        var merged: [RentInstance] = []
        if platform == nil || platform == "compshare" {
            if let resp: RentInstancesResponse = try? await apiRequest("api/rent/instances", timeout: 45) {
                merged.append(contentsOf: resp.instances ?? [])
            }
        }
        if platform == nil || platform == "autodl" {
            if let resp: RentInstancesResponse = try? await apiRequest("api/rent/autodl/instances", timeout: 45) {
                merged.append(contentsOf: resp.instances ?? [])
            }
        }
        if platform == nil || platform == "gpushare" {
            if let resp: RentInstancesResponse = try? await apiRequest("api/rent/gpushare/instances", timeout: 45) {
                merged.append(contentsOf: resp.instances ?? [])
            }
        }
        if platform == nil || platform == "matpool" {
            if let resp: RentInstancesResponse = try? await apiRequest("api/rent/matpool/instances", timeout: 45) {
                merged.append(contentsOf: resp.instances ?? [])
            }
        }
        instances = merged
        if let current = rentInstance, let updated = instances.first(where: { $0.uhostId == current.uhostId }) {
            rentInstance = updated
        }
    }

    func openRent(_ offer: Offer) {
        guard let spec = offer.rent else {
            rentError = "该平台暂不支持一键租卡"
            return
        }
        rentTarget = offer
        rentPlatform = spec.platform ?? "compshare"
        rentQuote = nil
        rentInstance = nil
        rentError = nil
        rentNotice = nil
        rentConfirm = false
        panelMode = "rent"
        Task { await quoteRent(spec) }
    }

    func quoteRent(_ spec: RentSpec) async {
        rentBusy = true
        defer { rentBusy = false }
        do {
            let options: RentOptions = try await apiRequest("api/rent/options")
            rentEnabled = options.settings?.enabled ?? rentEnabled
            rentSettings = options.settings
            guard rentEnabled else {
                rentError = "请先在 Dashboard → 设置 → 一键租卡 中启用"
                return
            }
            guard let region = spec.region, let gpuType = spec.gpuType else {
                rentError = "缺少租卡参数，请刷新行情"
                return
            }
            if rentPlatform == "compshare" && spec.zone == nil {
                rentError = "缺少租卡参数，请刷新行情"
                return
            }
            let zone = spec.zone ?? ""
            let endpoint = rentPlatform == "autodl" ? "api/rent/autodl/quote"
                : rentPlatform == "gpushare" ? "api/rent/gpushare/quote"
                : rentPlatform == "matpool" ? "api/rent/matpool/quote" : "api/rent/quote"
            let body: [String: Any] = rentPlatform != "compshare"
                ? ["gpu_type": gpuType, "region": region, "price": spec.price ?? 0]
                : [
                    "gpu_type": gpuType,
                    "region": region,
                    "zone": zone,
                    "cpu": spec.cpu ?? 0,
                    "mem_gb": spec.memGb ?? 0,
                ]
            let resp: RentQuoteResponse = try await apiRequest(endpoint, method: "POST", body: body)
            if resp.ok == false {
                rentError = resp.error ?? "报价失败"
                return
            }
            rentQuote = resp.quote
            if resp.quote?.capacity == false {
                rentError = "当前规格库存不足，请换区域或稍后重试"
            }
        } catch {
            rentError = "报价失败：\(error.localizedDescription)"
        }
    }

    func createRent() async {
        guard rentConfirm, let quote = rentQuote, let spec = rentTarget?.rent else { return }
        guard let region = spec.region, let gpuType = spec.gpuType else { return }
        let zone = spec.zone ?? ""
        rentBusy = true
        rentError = nil
        rentNotice = nil
        defer { rentBusy = false }
        do {
            let endpoint = rentPlatform == "autodl" ? "api/rent/autodl/create"
                : rentPlatform == "gpushare" ? "api/rent/gpushare/create"
                : rentPlatform == "matpool" ? "api/rent/matpool/create" : "api/rent/create"
            let body: [String: Any] = rentPlatform != "compshare"
                ? [
                    "machine_id": quote.machineId ?? "",
                    "image_id": quote.imageId ?? "",
                    "name": "",
                    "confirm": "RENT",
                    "gpu_type": gpuType,
                    "region": region,
                    "price": quote.price ?? 0,
                ]
                : [
                    "gpu_type": gpuType,
                    "region": region,
                    "zone": zone,
                    "cpu": spec.cpu ?? 0,
                    "mem_gb": spec.memGb ?? 0,
                    "image_id": quote.imageId ?? "",
                    "confirm": "RENT",
                ]
            let resp: RentCreateResponse = try await apiRequest(endpoint, method: "POST", body: body, timeout: 180)
            if let instance = resp.instance {
                rentInstance = instance
                rentNotice = instance.warning ?? "实例已创建，正在等待分配 SSH…"
                Task { await pollRent(instance.uhostId) }
            } else {
                rentError = resp.error ?? "创建失败"
            }
        } catch {
            rentError = "创建失败：\(error.localizedDescription)"
        }
    }

    func pollRent(_ id: String) async {
        for _ in 0..<120 {
            try? await Task.sleep(nanoseconds: 5_000_000_000)
            await loadInstances(platform: rentPlatform)
            if let updated = instances.first(where: { $0.uhostId == id }) {
                rentInstance = updated
                if updated.isRunning || updated.released == true {
                    return
                }
            }
        }
    }

    func releaseRent() async {
        guard let id = rentInstance?.uhostId else { return }
        rentBusy = true
        rentError = nil
        defer { rentBusy = false }
        do {
            let endpoint = rentPlatform == "autodl" ? "api/rent/autodl/terminate"
                : rentPlatform == "gpushare" ? "api/rent/gpushare/terminate"
                : rentPlatform == "matpool" ? "api/rent/matpool/terminate" : "api/rent/terminate"
            let resp: RentCreateResponse = try await apiRequest(
                endpoint,
                method: "POST",
                body: ["uhost_id": id],
                timeout: 360
            )
            if let instance = resp.instance { rentInstance = instance }
            rentNotice = "实例已释放"
            await loadInstances()
        } catch {
            rentError = "释放失败：\(error.localizedDescription)"
        }
    }

    func dismissRent() {
        panelMode = "overview"
        rentError = nil
        rentNotice = nil
    }

    func showInstance(_ instance: RentInstance) {
        rentPlatform = instance.platform ?? "compshare"
        rentTarget = nil
        rentQuote = nil
        rentInstance = instance
        rentError = nil
        rentNotice = nil
        panelMode = "rent"
    }

    func openDashboard(settings: Bool = false) {
        guard let base = baseURL else { return }
        let target = settings ? base.absoluteString + "/#settings" : base.absoluteString
        if let url = URL(string: target) { NSWorkspace.shared.open(url) }
    }

    func open(_ offer: Offer) {
        if let url = offer.url.flatMap(URL.init(string:)) {
            NSWorkspace.shared.open(url)
        }
    }
}

// MARK: - 面板视图

struct MenuBarView: View {
    @ObservedObject var store: AppStore
    @ObservedObject var backend: BackendManager

    private var reports: [PlatformReport] { store.snapshot?.platforms ?? [] }
    private var offers: [Offer] { store.snapshot?.offers ?? [] }
    private var family: String { store.selectedFamily }

    /// 面板高度随筛选变化，避免单卡型时留下大片空白
    private var panelHeight: CGFloat {
        if store.panelMode == "rent" { return store.rentInstance == nil ? 480 : 620 }
        return family == "all" ? 676 : 596
    }

    private var subtitle: String {
        guard let snap = store.snapshot else { return "正在连接本地服务…" }
        let available = (snap.offers ?? []).filter { $0.available == true }.count
        let total = snap.offers?.count ?? 0
        let when = store.lastUpdated.isEmpty ? "算力行情" : store.lastUpdated
        return "\(when) · \(total) 条报价 · \(available) 条有货"
    }

    var body: some View {
        Group {
            if store.panelMode == "rent" {
                RentPanelView(store: store)
            } else {
                VStack(spacing: 0) {
                    header
                    Divider().opacity(0.6)
                    ScrollView(showsIndicators: false) {
                        VStack(spacing: 12) {
                            if let error = store.error ?? backend.error {
                                errorBanner(error)
                            }
                            overview
                            if !store.activeInstances.isEmpty {
                                instanceBanner
                            }
                            familyPicker
                            platformList
                        }
                        .padding(16)
                    }
                    Divider().opacity(0.6)
                    footer
                }
            }
        }
        .frame(width: 404, height: panelHeight)
        .background(VisualEffectView().ignoresSafeArea())
    }

    private var instanceBanner: some View {
        Button {
            if let first = store.activeInstances.first { store.showInstance(first) }
        } label: {
            HStack(spacing: 7) {
                Image(systemName: "desktopcomputer")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color.brand)
                Text("\(store.activeInstances.count) 台实例运行中 · 查看 SSH")
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(Color.brand)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(Color.brand.opacity(0.6))
            }
            .padding(.horizontal, 11)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(Color.brand.opacity(0.08))
            )
        }
        .buttonStyle(.plain)
    }

    // ------------------------------------------------------------------ 头部
    private var header: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(LinearGradient(colors: [.brand, .brand2], startPoint: .topLeading, endPoint: .bottomTrailing))
                .frame(width: 30, height: 30)
                .overlay(
                    Image(systemName: "memorychip")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(.white)
                )
                .shadow(color: Color.brand.opacity(0.35), radius: 5, x: 0, y: 2)

            VStack(alignment: .leading, spacing: 1) {
                Text("GPU Finder")
                    .font(.system(size: 14, weight: .semibold))
                Text(subtitle)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if let active = store.activeInstances.first {
                PanelIconButton(systemName: "desktopcomputer", help: "查看运行中的实例", tint: .brand) {
                    store.showInstance(active)
                }
            }
            if store.refreshing {
                ProgressView().controlSize(.small).frame(width: 28, height: 28)
            } else {
                PanelIconButton(systemName: "arrow.clockwise", help: "刷新") {
                    Task { await store.refresh() }
                }
            }
            PanelIconButton(systemName: "gearshape", help: "设置 · 账号凭据 / 租卡参数", tint: .brand) {
                store.openDashboard(settings: true)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    // ------------------------------------------------------------------ 错误
    private func errorBanner(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 11))
                .foregroundStyle(Color.warning)
            Text(message)
                .font(.system(size: 10.5))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 4)
            Button("重试") {
                Task { await store.load() }
            }
            .buttonStyle(.plain)
            .font(.system(size: 10.5, weight: .semibold))
            .foregroundStyle(Color.brand)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 9).fill(Color.warning.opacity(0.1)))
    }

    // ------------------------------------------------------------------ 概览
    private var overview: some View {
        HStack(spacing: 10) {
            overviewCard(family: "rtx4090", title: "RTX 4090", tint: Color.brand)
            overviewCard(family: "rtx5090", title: "RTX 5090", tint: Color(hex: "#7A5CF5"))
        }
    }

    private func overviewCard(family fam: String, title: String, tint: Color) -> some View {
        let pool = offers.filter { $0.family == fam }
        let available = pool.filter { $0.available == true && $0.price != nil }
        let best = (available.isEmpty ? pool.filter { $0.price != nil } : available)
            .min(by: { ($0.price ?? 0) < ($1.price ?? 0) })

        return VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 5) {
                Circle().fill(tint).frame(width: 5, height: 5)
                Text(title).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                Spacer()
                if let best = best, best.available == true {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 9))
                        .foregroundStyle(Color.positive)
                }
            }
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                Text("¥").font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
                Text(best?.price.map { String(format: $0 >= 10 ? "%.1f" : "%.2f", $0) } ?? "—")
                    .font(.system(size: 24, weight: .bold, design: .rounded))
                    .monospacedDigit()
                Text("/时").font(.system(size: 9)).foregroundStyle(.secondary)
            }
            Text(best.map { "\($0.platformName) · \($0.available == true ? "有货" : "库存未知")" } ?? "暂无报价")
                .font(.system(size: 9.5))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(tint.opacity(0.07))
                .overlay(
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(tint.opacity(0.12), lineWidth: 1)
                )
        )
    }

    // ------------------------------------------------------------------ 筛选
    private var familyPicker: some View {
        HStack(spacing: 4) {
            segment("全部", "all")
            segment("4090", "rtx4090")
            segment("5090", "rtx5090")
        }
        .padding(4)
        .background(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .fill(Color.primary.opacity(0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .stroke(Color.primary.opacity(0.10), lineWidth: 1)
        )
    }

    private func segment(_ title: String, _ value: String) -> some View {
        let active = family == value
        return HoverBox { hover in
            Button {
                store.selectedFamily = value
            } label: {
                Text(title)
                    .font(.system(size: 11.5, weight: active ? .bold : .semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(
                                active
                                    ? Color.brand
                                    : (hover ? Color.primary.opacity(0.10) : Color.primary.opacity(0.035))
                            )
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .stroke(
                                active
                                    ? Color.white.opacity(0.22)
                                    : Color.primary.opacity(hover ? 0.20 : 0.09),
                                lineWidth: 1
                            )
                    )
                    .foregroundStyle(active ? Color.white : Color.primary.opacity(0.72))
                    .shadow(
                        color: active ? Color.brand.opacity(0.30) : .clear,
                        radius: active ? 4 : 0, x: 0, y: 2
                    )
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help("只看 \(title)")
        }
    }

    // ------------------------------------------------------------------ 平台列表
    private struct FamilyRow: Identifiable {
        let family: String
        let offer: Offer
        var id: String { family }
    }

    private var platformList: some View {
        VStack(spacing: 8) {
            ForEach(reports) { report in
                platformCard(report)
            }
            if !reports.isEmpty {
                footnote
            }
            if reports.isEmpty && store.loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("正在启动本地服务…").font(.system(size: 11)).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 28)
            }
        }
    }

    private var footnote: some View {
        let live = reports.filter { $0.mode == "live" }.count
        let ref = reports.filter { $0.mode == "reference" }.count
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                Image(systemName: "checkmark.seal")
                    .font(.system(size: 9))
                Text("官网实时 \(live) 家" + (ref > 0 ? " · 第三方参考 \(ref) 家" : ""))
                    .font(.system(size: 9.5))
                Spacer()
                Text("¥/卡·时")
                    .font(.system(size: 9.5))
            }
            .foregroundStyle(.tertiary)
            Text("点开面板即刷新 · 库存为接口快照，热门卡可能秒没")
                .font(.system(size: 9.5))
                .foregroundStyle(.tertiary)
        }
        .padding(.horizontal, 2)
        .padding(.top, 2)
    }

    private func platformCard(_ report: PlatformReport) -> some View {
        let fams = family == "all" ? ["rtx4090", "rtx5090"] : [family]
        let rows: [FamilyRow] = fams.compactMap { fam in
            let pool = offers.filter { $0.platform == report.id && $0.family == fam && $0.price != nil }
            let available = pool.filter { $0.available == true }
            guard let best = (available.isEmpty ? pool : available).min(by: { ($0.price ?? 0) < ($1.price ?? 0) }) else { return nil }
            return FamilyRow(family: fam, offer: best)
        }

        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                Avatar(report: report, size: 24)
                Text(report.name).font(.system(size: 12, weight: .semibold))
                ModeBadge(mode: report.mode ?? "")
                Spacer()
                if report.mode == "reference" || report.mode == "auth" {
                    Button {
                        store.openDashboard(settings: true)
                    } label: {
                        Text(report.mode == "auth" ? "登录" : "配置")
                            .font(.system(size: 9.5, weight: .medium))
                            .foregroundStyle(Color.brand)
                    }
                    .buttonStyle(.plain)
                }
            }

            if rows.isEmpty {
                Text("当前没有 4090 / 5090 报价")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .padding(.leading, 31)
            } else {
                ForEach(rows) { row in
                    let offer = row.offer
                    HoverBox { hover in
                        HStack(spacing: 6) {
                            HStack(spacing: 6) {
                                Text(offer.gpu)
                                    .font(.system(size: 10.5))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.82)
                                    .frame(width: 78, alignment: .leading)
                                Text(offer.region ?? "")
                                    .font(.system(size: 9.5))
                                    .foregroundStyle(.tertiary)
                                    .lineLimit(1)
                            }
                            .contentShape(Rectangle())
                            .onTapGesture { store.open(offer) }
                            .help("在浏览器打开 \(offer.platformName) · \(offer.gpu) \(offer.region ?? "")")
                            Spacer(minLength: 2)
                            if offer.rent != nil && offer.available == true {
                                Button {
                                    store.openRent(offer)
                                } label: {
                                    HStack(spacing: 2) {
                                        Image(systemName: "bolt.fill")
                                            .font(.system(size: 7, weight: .bold))
                                        Text("租")
                                            .font(.system(size: 9.5, weight: .bold))
                                    }
                                    .foregroundStyle(.white)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 3)
                                    .background(
                                        Capsule().fill(hover ? Color.brand.opacity(0.85) : Color.brand)
                                    )
                                    .shadow(color: Color.brand.opacity(0.25), radius: 2, x: 0, y: 1)
                                    .contentShape(Capsule())
                                }
                                .buttonStyle(.plain)
                                .help("一键租用这台实例")
                            }
                            StockPill(offer: offer)
                            PriceText(price: offer.price, size: 12.5)
                                .frame(width: 52, alignment: .trailing)
                            Button {
                                store.open(offer)
                            } label: {
                                Image(systemName: "chevron.right")
                                    .font(.system(size: 7.5, weight: .semibold))
                                    .foregroundStyle(Color.secondary.opacity(hover ? 0.9 : 0.45))
                                    .frame(width: 16, height: 18)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .help("在浏览器打开 \(offer.platformName)")
                        }
                        .padding(.leading, 31)
                        .padding(.trailing, 3)
                        .padding(.vertical, 4)
                        .background(
                            RoundedRectangle(cornerRadius: 7, style: .continuous)
                                .fill(hover ? Color.primary.opacity(0.065) : Color.clear)
                        )
                    }
                }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .fill(Color.primary.opacity(0.045))
        )
    }

    // ------------------------------------------------------------------ 底部
    private var footer: some View {
        HStack(spacing: 10) {
            Button {
                store.openDashboard()
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "safari")
                        .font(.system(size: 11, weight: .medium))
                    Text("打开 Dashboard")
                        .font(.system(size: 11.5, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 7)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(Color.brand)
                )
                .foregroundStyle(.white)
            }
            .buttonStyle(.plain)

            Button {
                NSApp.terminate(nil)
            } label: {
                Text("退出")
                    .font(.system(size: 11.5, weight: .medium))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(Color.primary.opacity(0.06))
                    )
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }
}

// MARK: - 一键租卡面板

struct RentPanelView: View {
    @ObservedObject var store: AppStore

    private var title: String {
        if let target = store.rentTarget { return "租用 \(target.gpu)" }
        if let inst = store.rentInstance { return inst.name ?? "我的实例" }
        return "一键租卡"
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().opacity(0.6)
            ScrollView(showsIndicators: false) {
                VStack(spacing: 12) {
                    if let error = store.rentError { banner(error, color: .warning, icon: "exclamationmark.triangle.fill") }
                    if let notice = store.rentNotice { banner(notice, color: .brand, icon: "info.circle.fill") }
                    if let quote = store.rentQuote { quoteCard(quote) }
                    if store.rentTarget != nil { settingsHint }
                    if let instance = store.rentInstance {
                        instanceCard(instance)
                    } else if store.rentQuote != nil {
                        confirmBox
                    }
                    if store.rentBusy && store.rentQuote == nil {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text("正在获取官方报价与库存…").font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 24)
                    }
                }
                .padding(14)
            }
            Divider().opacity(0.6)
            footer
        }
        .task(id: store.panelMode) {
            if store.panelMode == "rent" { await store.loadInstances() }
        }
    }

    // ------------------------------------------------------------------ 头部
    private var header: some View {
        HStack(spacing: 9) {
            PanelIconButton(systemName: "chevron.left", help: "返回行情", tint: .brand) {
                store.dismissRent()
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.system(size: 13, weight: .semibold)).lineLimit(1)
                Text(store.rentPlatform == "autodl" ? "AutoDL · 官方市场接口"
                     : store.rentPlatform == "gpushare" ? "恒源云 · 官方市场接口"
                     : store.rentPlatform == "matpool" ? "矩池云 · 官方市场接口" : "优云智算 · 官方 API")
                    .font(.system(size: 9.5)).foregroundStyle(.secondary)
            }
            Spacer()
            PanelIconButton(systemName: "gearshape", help: "在 Dashboard 中修改镜像 / 磁盘 / 自动关机", tint: .brand) {
                store.openDashboard(settings: true)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    // ------------------------------------------------------------------ 报价
    private func quoteCard(_ q: RentQuote) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(store.rentTarget?.gpu ?? "GPU 实例")
                        .font(.system(size: 13, weight: .semibold))
                    Text(q.zoneName ?? q.zone ?? "")
                        .font(.system(size: 10)).foregroundStyle(.secondary)
                }
                Spacer()
                HStack(alignment: .firstTextBaseline, spacing: 2) {
                    Text("¥").font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
                    Text(String(format: "%.2f", q.price ?? 0))
                        .font(.system(size: 24, weight: .bold, design: .rounded))
                        .monospacedDigit()
                    Text("/时").font(.system(size: 9)).foregroundStyle(.secondary)
                }
            }
            Divider().opacity(0.7)
            infoRow("配置", "\(q.cpu ?? 0)C · \(q.memGb ?? 0)G 内存")
            infoRow("镜像", q.imageName ?? "自动选择")
            infoRow("系统盘", (q.diskGb ?? 0) > 0 ? "\(q.diskGb ?? 0)GB SSD" : "平台默认")
            infoRow("自动关机", (q.autoStopMinutes ?? 0) > 0 ? "\(q.autoStopMinutes ?? 0) 分钟后" : "不自动关机")
            HStack(spacing: 5) {
                Circle()
                    .fill(q.capacity == false ? Color.negative : (q.capacity == true ? Color.positive : Color.secondary))
                    .frame(width: 5, height: 5)
                Text(q.capacity == false ? "库存不足" : (q.capacity == true ? (store.rentPlatform == "compshare" ? "官方容量检查：有资源" : "官方接口：有可用主机") : "库存未知"))
                    .font(.system(size: 10))
                    .foregroundStyle(q.capacity == false ? Color.negative : .secondary)
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.primary.opacity(0.045))
        )
    }

    private func infoRow(_ key: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(key).font(.system(size: 10.5)).foregroundStyle(.secondary).frame(width: 52, alignment: .leading)
            Text(value).font(.system(size: 10.5, weight: .medium)).lineLimit(1).minimumScaleFactor(0.85)
            Spacer(minLength: 0)
        }
    }

    private var settingsHint: some View {
        HStack(alignment: .top, spacing: 7) {
            Image(systemName: "slider.horizontal.3")
                .font(.system(size: 9.5))
                .foregroundStyle(.secondary)
                .padding(.top, 1)
            VStack(alignment: .leading, spacing: 2) {
                Text("镜像 / 磁盘 / 自动关机 / 价格上限使用 Dashboard 中的设置")
                    .font(.system(size: 9.5))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HoverBox { hover in
                    Button {
                        store.openDashboard(settings: true)
                    } label: {
                        HStack(spacing: 3) {
                            Image(systemName: "slider.horizontal.3")
                                .font(.system(size: 8.5, weight: .semibold))
                            Text("修改设置")
                                .font(.system(size: 9.5, weight: .semibold))
                            Image(systemName: "arrow.up.right")
                                .font(.system(size: 7.5, weight: .bold))
                        }
                        .foregroundStyle(Color.brand)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 4)
                        .background(
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .fill(Color.brand.opacity(hover ? 0.16 : 0.10))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .stroke(Color.brand.opacity(0.28), lineWidth: 1)
                        )
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(9)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Color.primary.opacity(0.035))
        )
    }

    private var confirmBox: some View {
        VStack(alignment: .leading, spacing: 9) {
            Toggle(isOn: Binding(get: { store.rentConfirm }, set: { store.rentConfirm = $0 })) {
                Text("我确认创建按量计费实例，费用由我的\(store.rentPlatform == "autodl" ? "AutoDL" : (store.rentPlatform == "gpushare" ? "恒源云" : (store.rentPlatform == "matpool" ? "矩池云" : "优云智算")))账户承担")
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .toggleStyle(.switch)
            .controlSize(.mini)

            Button {
                Task { await store.createRent() }
            } label: {
                HStack(spacing: 6) {
                    if store.rentBusy { ProgressView().controlSize(.small) }
                    Text(store.rentBusy ? "创建中…" : "确认租用 ¥\(String(format: "%.2f", store.rentQuote?.price ?? 0))/时")
                        .font(.system(size: 11.5, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 7)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(canCreate ? Color.brand : Color.primary.opacity(0.08))
                )
                .foregroundStyle(canCreate ? Color.white : Color.secondary)
            }
            .buttonStyle(.plain)
            .disabled(!canCreate)
        }
        .padding(11)
        .background(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .fill(Color.primary.opacity(0.04))
        )
    }

    private var canCreate: Bool {
        store.rentConfirm && !store.rentBusy && store.rentQuote?.capacity != false
    }

    // ------------------------------------------------------------------ 实例
    private func instanceCard(_ inst: RentInstance) -> some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 7) {
                Circle()
                    .fill(inst.isRunning ? Color.positive : (inst.released == true ? Color.secondary : Color.warning))
                    .frame(width: 6, height: 6)
                Text(inst.stateLabel)
                    .font(.system(size: 11, weight: .semibold))
                Spacer()
                Text("¥\(String(format: "%.2f", inst.price ?? 0))/时")
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            infoRow("实例", inst.name ?? inst.uhostId)
            infoRow("区域", inst.zoneName ?? inst.zone ?? "—")
            infoRow("配置", "\(inst.gpuType ?? "GPU") · \(inst.cpu ?? 0)C · \(inst.memGb ?? 0)G")
            if let stop = inst.autoStopAt, stop > 0 {
                infoRow("定时关机", Date(timeIntervalSince1970: TimeInterval(stop)).formatted(date: .omitted, time: .shortened))
            }
            if inst.released == true {
                Text("实例已释放，费用已停止。")
                    .font(.system(size: 10.5)).foregroundStyle(.secondary)
            } else if inst.isRunning, let ssh = inst.ssh, let command = ssh.command, !command.isEmpty {
                Divider().opacity(0.7)
                sshBox(ssh, command: command)
                HoverBox { hover in
                    Button {
                        confirmRelease()
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "trash")
                                .font(.system(size: 8.5, weight: .semibold))
                            Text("释放实例")
                                .font(.system(size: 10.5, weight: .semibold))
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                        .background(
                            RoundedRectangle(cornerRadius: 7)
                                .fill(Color.negative.opacity(hover ? 0.18 : 0.10))
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 7)
                                .stroke(Color.negative.opacity(0.28), lineWidth: 1)
                        )
                        .foregroundStyle(Color.negative)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(store.rentBusy)
                }
            } else {
                HStack(spacing: 7) {
                    ProgressView().controlSize(.small)
                    Text(inst.released == true ? "已释放" : "实例初始化中，SSH 信息稍后出现…")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.primary.opacity(0.045))
        )
    }

    private func sshBox(_ ssh: SSHInfo, command: String) -> some View {
        VStack(spacing: 6) {
            sshLine("SSH", command)
            sshLine("IP", ssh.ip ?? "—")
            sshLine("用户", ssh.user ?? "root")
            sshLine("密码", ssh.password ?? "等待分配…")
        }
        .padding(9)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.black.opacity(0.06))
        )
    }

    private func sshLine(_ key: String, _ value: String) -> some View {
        HStack(spacing: 7) {
            Text(key)
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
                .frame(width: 30, alignment: .leading)
            Text(value)
                .font(.system(size: 9.5, design: .monospaced))
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
            Spacer(minLength: 2)
            HoverBox { hover in
                Button {
                    let pb = NSPasteboard.general
                    pb.clearContents()
                    pb.setString(value, forType: .string)
                    store.rentNotice = "\(key) 已复制"
                } label: {
                    HStack(spacing: 3) {
                        Image(systemName: "doc.on.doc")
                            .font(.system(size: 8, weight: .semibold))
                        Text("复制")
                            .font(.system(size: 8.5, weight: .medium))
                    }
                    .foregroundStyle(hover ? Color.brand : Color.secondary)
                    .padding(.horizontal, 5)
                    .padding(.vertical, 2.5)
                    .background(
                        RoundedRectangle(cornerRadius: 5, style: .continuous)
                            .fill(Color.primary.opacity(hover ? 0.10 : 0.06))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 5, style: .continuous)
                            .stroke(Color.primary.opacity(0.12), lineWidth: 1)
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("复制\(key)")
            }
        }
    }

    private func confirmRelease() {
        let alert = NSAlert()
        alert.messageText = "释放这台实例？"
        alert.informativeText = "系统盘数据会被清除，费用停止累计。"
        alert.addButton(withTitle: "释放")
        alert.addButton(withTitle: "取消")
        if alert.runModal() == .alertFirstButtonReturn {
            Task { await store.releaseRent() }
        }
    }

    private func banner(_ text: String, color: Color, icon: String) -> some View {
        HStack(alignment: .top, spacing: 7) {
            Image(systemName: icon).font(.system(size: 10)).foregroundStyle(color)
            Text(text)
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(9)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(color.opacity(0.09))
        )
    }

    // ------------------------------------------------------------------ 底部
    private var footer: some View {
        HStack(spacing: 9) {
            HoverBox { hover in
                Button {
                    store.dismissRent()
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "chevron.left")
                            .font(.system(size: 8.5, weight: .semibold))
                        Text("返回行情")
                            .font(.system(size: 11, weight: .medium))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 7)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(Color.primary.opacity(hover ? 0.10 : 0.06))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.primary.opacity(0.10), lineWidth: 1)
                    )
                    .foregroundStyle(.secondary)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
            if store.rentInstance == nil {
                Text("价格与库存以平台下单页为准")
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }
}
