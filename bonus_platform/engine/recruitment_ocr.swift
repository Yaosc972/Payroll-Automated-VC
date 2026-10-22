import Foundation
import Vision
import ImageIO

func recognize(_ image: CGImage) throws -> [String] {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.minimumTextHeight = 0.001
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image).perform([request])
    return (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
}
var results: [[String: Any]] = []
for path in CommandLine.arguments.dropFirst() {
    do {
        guard let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else { throw NSError(domain: "Image", code: 1) }
        var lines = try recognize(image)
        // Shorter regions recover small body text and comments missed in full-page layout detection.
        let width = image.width, height = image.height
        for y in stride(from: 0, to: height, by: max(1, height / 3)) {
            let rect = CGRect(x: 0, y: max(0, y - 24), width: width, height: min(height - max(0, y - 24), height / 3 + 48))
            if let crop = image.cropping(to: rect) { lines += try recognize(crop) }
        }
        var seen = Set<String>()
        lines = lines.filter { seen.insert($0).inserted }
        results.append(["image": path, "text": lines.joined(separator: "\n")])
    } catch { results.append(["image": path, "error": error.localizedDescription]) }
}
let data = try JSONSerialization.data(withJSONObject: results, options: [.sortedKeys, .withoutEscapingSlashes])
FileHandle.standardOutput.write(data)
