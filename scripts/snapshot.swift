// 用 WKWebView 离屏渲染本地页面并截图，用于验收 Dashboard 外观。
// 用法: snapshot <url> <out.png> [width] [height] [dark|light]
import Cocoa
import WebKit

let args = CommandLine.arguments
guard args.count >= 3 else {
    fputs("usage: snapshot <url> <out.png> [width] [height] [dark|light]\n", stderr)
    exit(2)
}
let urlString = args[1]
let outPath = args[2]
let width = args.count > 3 ? (Double(args[3]) ?? 1400) : 1400
let height = args.count > 4 ? (Double(args[4]) ?? 1080) : 1080
let theme = args.count > 5 ? args[5] : "light"

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

class Snapshotter: NSObject, WKNavigationDelegate {
    let webView: WKWebView
    let window: NSWindow
    let outPath: String
    let size: NSSize

    init(url: URL, size: NSSize, outPath: String, theme: String) {
        self.outPath = outPath
        self.size = size
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        self.webView = WKWebView(frame: NSRect(origin: .zero, size: size), configuration: config)
        self.window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                               styleMask: [.borderless], backing: .buffered, defer: false)
        super.init()
        window.contentView = webView
        window.setFrameOrigin(NSPoint(x: -30000, y: -30000))
        window.orderFrontRegardless()
        if theme == "dark" {
            window.appearance = NSAppearance(named: .darkAqua)
            webView.appearance = NSAppearance(named: .darkAqua)
        } else {
            window.appearance = NSAppearance(named: .aqua)
            webView.appearance = NSAppearance(named: .aqua)
        }
        webView.navigationDelegate = self
        webView.load(URLRequest(url: url))
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // 离屏窗口不会推进 CSS 动画，注入样式让内容直接处于最终态
        let js = """
        (function(){
          var s=document.createElement('style');
          s.textContent='*,*::before,*::after{animation:none !important;transition:none !important}';
          document.head.appendChild(s);
        })();
        """
        webView.evaluateJavaScript(js, completionHandler: nil)
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
            let cfg = WKSnapshotConfiguration()
            cfg.rect = NSRect(origin: .zero, size: self.size)
            cfg.snapshotWidth = NSNumber(value: self.size.width)
            self.webView.takeSnapshot(with: cfg) { image, error in
                guard let image = image,
                      let tiff = image.tiffRepresentation,
                      let rep = NSBitmapImageRep(data: tiff),
                      let png = rep.representation(using: .png, properties: [:]) else {
                    fputs("snapshot failed: \(String(describing: error))\n", stderr)
                    exit(1)
                }
                do {
                    try png.write(to: URL(fileURLWithPath: self.outPath))
                    print("saved \(self.outPath) \(Int(self.size.width))x\(Int(self.size.height))")
                    exit(0)
                } catch {
                    fputs("write failed: \(error)\n", stderr)
                    exit(1)
                }
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        fputs("load failed: \(error)\n", stderr)
        exit(1)
    }
}

guard let url = URL(string: urlString) else { exit(2) }
let snapshotter = Snapshotter(url: url, size: NSSize(width: width, height: height), outPath: outPath, theme: theme)
withExtendedLifetime(snapshotter) {
    app.run()
}
