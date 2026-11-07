// 用 WKWebView 加载页面，导出渲染文本与 API 请求，用于核对平台真实字段。
// 用法: probe_web <url> [--cookie name=value] [--storage key=value] [--wait 6]
import Cocoa
import WebKit

let args = CommandLine.arguments
guard args.count >= 2 else {
    fputs("usage: probe_web <url> [--cookie k=v] [--storage k=v] [--wait n]\n", stderr)
    exit(2)
}
let urlString = args[1]
var cookies: [(String, String)] = []
var storage: [(String, String)] = []
var waitSeconds: Double = 6
var clickSelector = ""

var i = 2
while i < args.count {
    let flag = args[i]
    if (flag == "--cookie" || flag == "--storage"), i + 1 < args.count {
        let pair = args[i + 1].split(separator: "=", maxSplits: 1).map(String.init)
        if pair.count == 2 {
            if flag == "--cookie" { cookies.append((pair[0], pair[1])) }
            else { storage.append((pair[0], pair[1])) }
        }
        i += 2
    } else if flag == "--click", i + 1 < args.count {
        clickSelector = args[i + 1]
        i += 2
    } else if flag == "--wait", i + 1 < args.count {
        waitSeconds = Double(args[i + 1]) ?? 6
        i += 2
    } else {
        i += 1
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)

final class Probe: NSObject, WKNavigationDelegate {
    let webView: WKWebView
    let window: NSWindow

    init(url: URL) {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        if !storage.isEmpty {
            let js = storage.map { "localStorage.setItem(\(jsString($0.0)), \(jsString($0.1)));" }.joined()
            let script = WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true)
            config.userContentController.addUserScript(script)
        }
        webView = WKWebView(frame: NSRect(x: 0, y: 0, width: 1280, height: 900), configuration: config)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 900),
                          styleMask: [.borderless], backing: .buffered, defer: false)
        super.init()
        window.contentView = webView
        window.setFrameOrigin(NSPoint(x: -20000, y: -20000))
        window.orderFrontRegardless()
        webView.navigationDelegate = self
        webView.customUserAgent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        let store = config.websiteDataStore.httpCookieStore
        let group = DispatchGroup()
        for (name, value) in cookies {
            group.enter()
            let cookie = HTTPCookie(properties: [
                .name: name,
                .value: value,
                .domain: ".gpushare.com",
                .path: "/",
                .secure: "TRUE",
                .expires: Date().addingTimeInterval(86400),
            ])!
            store.setCookie(cookie) { group.leave() }
        }
        group.notify(queue: .main) {
            self.webView.load(URLRequest(url: url))
        }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if !clickSelector.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                let js = "document.querySelector(\(jsString(clickSelector)))?.click();"
                webView.evaluateJavaScript(js, completionHandler: nil)
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + waitSeconds) {
            let js = """
            (function() {
              var all = performance.getEntriesByType('resource').map(function(e){return e.name});
              var res = all.filter(function(n){return n.indexOf('/api/') >= 0});
              return JSON.stringify({
                url: location.href,
                title: document.title,
                text: (document.body ? document.body.innerText : '').slice(0, 7000),
                api: Array.from(new Set(res)).slice(0, 60),
                resources: Array.from(new Set(all)).slice(0, 200)
              });
            })();
            """
            webView.evaluateJavaScript(js) { result, error in
                if let error = error {
                    fputs("eval error: \(error)\n", stderr)
                    exit(1)
                }
                print(result as? String ?? "{}")
                exit(0)
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        fputs("load failed: \(error)\n", stderr)
        exit(1)
    }
}

func jsString(_ s: String) -> String {
    let data = try! JSONSerialization.data(withJSONObject: [s], options: [])
    let json = String(data: data, encoding: .utf8)!
    return String(json.dropFirst().dropLast())
}

guard let url = URL(string: urlString) else { exit(2) }
let probe = Probe(url: url)
withExtendedLifetime(probe) { app.run() }
