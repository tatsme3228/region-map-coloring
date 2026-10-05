//
//  rasterize_svg.swift
//  region-map coloring engine tool
//
//  SVG-only onboarding: rasterizes an ORIGINAL traced SVG with WebKit (the
//  same engine the renderer-fidelity gate uses as its reference) so the
//  region-ID map is derived from the SVG itself — no external raster
//  dependency. Output: a 1x PNG at the SVG's viewBox size, white background.
//
//  Usage:
//    rasterize_svg <svgDir> <outDir> <stem> [<stem> ...]
//
//  Builds:  swiftc -O scripts/rasterize_svg.swift -o bin/rasterize_svg
//

import AppKit
import Foundation
import WebKit

final class NavDelegate: NSObject, WKNavigationDelegate {
    let onDone: (NSImage?) -> Void
    init(_ onDone: @escaping (NSImage?) -> Void) { self.onDone = onDone }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        FileHandle.standardError.write(Data("nav: didFinish\n".utf8))
        // Give the <img> a beat to decode, then snapshot at view size.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            webView.takeSnapshot(with: nil) { image, error in
                if let error {
                    FileHandle.standardError.write(Data(
                        "nav: snapshot error \(error)\n".utf8))
                }
                self.onDone(image)
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!,
                 withError error: Error) {
        FileHandle.standardError.write(Data("nav: didFail \(error)\n".utf8))
        onDone(nil)
    }
    func webView(_ webView: WKWebView,
                 didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        FileHandle.standardError.write(Data(
            "nav: didFailProvisional \(error)\n".utf8))
        onDone(nil)
    }
}

/// Parses `viewBox="0 0 W H"`; falls back to the house size 1024x1536.
func viewBoxSize(of svgURL: URL) -> (w: Int, h: Int) {
    if let text = try? String(contentsOf: svgURL, encoding: .utf8),
       let range = text.range(of: #"viewBox\s*=\s*"[^"]+""#, options: .regularExpression) {
        let nums = text[range]
            .split(whereSeparator: { !($0.isNumber || $0 == ".") })
            .compactMap { Double($0) }
        if nums.count == 4, nums[2] > 0, nums[3] > 0 {
            return (Int(nums[2].rounded()), Int(nums[3].rounded()))
        }
    }
    return (1024, 1536)
}

func rasterize(stem: String, svgDir: URL, outDir: URL) -> Bool {
    let svgURL = svgDir.appendingPathComponent(stem + ".svg")
    guard FileManager.default.fileExists(atPath: svgURL.path) else {
        FileHandle.standardError.write(Data("error: missing \(svgURL.path)\n".utf8))
        return false
    }
    let size = viewBoxSize(of: svgURL)

    // Traced SVGs are typically self-contained, so inline the document text
    // directly:
    // macOS WebKit sandboxes file:// loads for plain CLI processes, but a
    // data-only HTML string needs no file access at all. CSS pins the root
    // <svg> to the exact viewBox pixel size (gate-reference style).
    guard var svgText = try? String(contentsOf: svgURL, encoding: .utf8) else {
        FileHandle.standardError.write(Data("error: unreadable \(svgURL.path)\n".utf8))
        return false
    }
    // Strip any XML prolog / doctype so it embeds cleanly in HTML.
    if let idx = svgText.range(of: "<svg")?.lowerBound {
        svgText = String(svgText[idx...])
    }
    let html = """
    <html><head><style>html,body{margin:0;padding:0;background:#fff}
    svg{display:block;width:\(size.w)px;height:\(size.h)px}</style></head>
    <body>\(svgText)</body></html>
    """

    let webView = WKWebView(frame: NSRect(x: 0, y: 0,
                                          width: CGFloat(size.w),
                                          height: CGFloat(size.h)))
    var result: NSImage?
    let delegate = NavDelegate { result = $0 }
    webView.navigationDelegate = delegate
    webView.loadHTMLString(html, baseURL: nil)

    // Pump the main run loop until the snapshot lands (30 s cap).
    let deadline = Date(timeIntervalSinceNow: 30)
    while result == nil && Date() < deadline {
        RunLoop.current.run(mode: .default, before: Date(timeIntervalSinceNow: 0.05))
    }
    guard let image = result,
          let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff) else {
        FileHandle.standardError.write(Data("error: snapshot failed for \(stem)\n".utf8))
        return false
    }

    // Headless snapshots may carry a 2x backing scale; resample into an
    // exact-pixel rep (1 unit = 1 px) before thresholding downstream.
    var finalRep = rep
    if rep.pixelsWide != size.w || rep.pixelsHigh != size.h {
        if let target = NSBitmapImageRep(bitmapDataPlanes: nil,
                                         pixelsWide: size.w,
                                         pixelsHigh: size.h,
                                         bitsPerSample: 8,
                                         samplesPerPixel: 4,
                                         hasAlpha: true,
                                         isPlanar: false,
                                         colorSpaceName: .deviceRGB,
                                         bytesPerRow: 0,
                                         bitsPerPixel: 0) {
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: target)
            image.draw(in: NSRect(x: 0, y: 0,
                                  width: size.w, height: size.h))
            NSGraphicsContext.restoreGraphicsState()
            finalRep = target
        }
    }
    guard let png = finalRep.representation(using: .png, properties: [:]) else {
        FileHandle.standardError.write(Data("error: png encode failed for \(stem)\n".utf8))
        return false
    }
    let outURL = outDir.appendingPathComponent(stem + "-raster.png")
    do {
        try png.write(to: outURL)
    } catch {
        FileHandle.standardError.write(Data("error: \(error)\n".utf8))
        return false
    }
    print("\(stem): \(finalRep.pixelsWide)x\(finalRep.pixelsHigh) -> \(outURL.path)")
    return true
}

// MARK: - Entry

let args = CommandLine.arguments
guard args.count >= 4 else {
    FileHandle.standardError.write(Data(
        "usage: rasterize_svg <svgDir> <outDir> <stem> [...]\n".utf8))
    exit(1)
}
let svgDir = URL(fileURLWithPath: args[1])
let outDir = URL(fileURLWithPath: args[2])
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

NSApplication.shared.setActivationPolicy(.accessory)

var failed = false
for stem in args[3...] {
    if !rasterize(stem: stem, svgDir: svgDir, outDir: outDir) { failed = true }
}
exit(failed ? 2 : 0)
