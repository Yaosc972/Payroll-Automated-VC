# Σ海外报账核对助手

`Σ海外报账核对助手` is the standalone desktop Worker for overseas labor reconciliation. It is intentionally separate from the Sigma Workbench desktop shell and does not package the platform pages.

## Scope

- Receives an activation link from the overseas labor page.
- Stores the Worker token with Electron `safeStorage`.
- Claims only jobs owned by the activated user.
- Runs long reconciliation jobs locally and writes status for the desktop shell.
- Checks for an available update after a task completes.

The app uses the dedicated assets in `assets/overseas-labor-worker.*`. Do not replace them with the Sigma Workbench platform logo.

## Local development

From this directory:

```bash
npm install
npm run check
npm test
npm run dev
```

Development mode requires the repository Python environment and accepts an activation URL in this form:

```text
sigma-overseas-labor-worker://activate?apiUrl=https%3A%2F%2Fexample.com&code=sigma_labor_a1_REDACTED
```

Only HTTPS service URLs and one-time activation codes are accepted. Worker tokens must not enter URLs, logs, or the repository.

## Build

Every installer build first runs the approved legacy-invoice release gate. The gate verifies source-file hashes and replays the real files through the formal engine in isolated local storage with external AI disabled. A missing case, changed file, employee-count drift, amount drift, or forbidden footer row blocks packaging.

The local approved case manifests live under the ignored `outputs/labor_golden/approved_cases/` directory. They may point to controlled local materials; invoice files themselves must never be committed. Run the gate directly with:

```bash
npm run release:gate
```

After the gate passes, build the embedded Python Worker and macOS installer:

```bash
python3 -m pip install -r ../requirements.txt -r requirements-worker.txt pyinstaller pillow
npm run dist:mac
```

`requirements-worker.txt` is Worker-only. It packages the local RapidOCR/ONNX runtime used for image-only invoices and must not be merged into the Vercel application requirements.

The output is written to `release/`. The current macOS build is ad-hoc signed for local testing; public distribution still requires Apple Developer ID signing and notarization.

The Windows NSIS target must be built and tested on Windows 10/11 x64 before distribution. The Windows computer does not need Codex. Install Python 3.11 x64 and Node.js 20 LTS x64, copy the repository, and place the approved private materials under `labor-worker-desktop/release-gate-materials/` while preserving their relative paths. Then double-click `build-windows.cmd`.

The materials path can also be supplied explicitly from Command Prompt:

```bash
build-windows.cmd -MaterialsRoot "D:\private\Sovitrat groupe"
```

The script creates an isolated Python build environment, installs pinned dependencies, runs the same approved legacy-invoice gate, embeds the Windows Python Worker, and produces the unsigned NSIS installer at `release/Σ海外报账核对助手-<version>-windows-x64.exe`. The installer can be tested on the approved unsigned-software test machine. Do not copy private invoice materials into the repository or release package.

## Runtime data

Electron stores activation settings, encrypted credentials, status, logs, and the Worker PID under its per-user application-data directory. The Worker PID lock prevents duplicate local Worker processes and stale locks are reclaimed on the next start.

The packaged Python bundle includes only an empty `bonus_platform/static` placeholder required by the current backend import path. It does not include the Sigma Workbench HTML, JavaScript, CSS, or seed data.
