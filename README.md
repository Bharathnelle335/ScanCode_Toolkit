# ScanCode Toolkit — Workflow Docs

## 1) Why this exists (what it’s for)

This workflow runs **ScanCode Toolkit** in CI to discover:

* OSS **licenses** (with optional license text),
* **copyrights, authors, emails, URLs**,
* **packages & dependencies** (from manifests),
* and (optionally) emits **SBOMs** (CycloneDX & SPDX).

It supports **five input modes** so you can scan what you actually have:

* **repo** – a Git repo at a branch / tag / commit,
* **folder** – a *subdirectory* inside a Git repo,
* **zip / tar** – a remote or workspace archive (`.zip`, `.tar`, `.tar.gz/.tgz`, `.tar.xz/.txz`),
* **docker** – a container image (rootfs is exported and scanned as files).

Outputs are uploaded as a single **artifact bundle** you can download from the run.

---

## 2) How the workflow works (under the hood)

**Inputs (from “Run workflow”):**

* `scan_mode`: `repo | folder | zip | tar | docker`
* `source`:

  * repo/folder → **repo URL** (GitHub URLs with `/tree/…`, `/commit/…`, `/releases/tag/…` are auto-parsed)
  * zip/tar → **URL** (or a workspace path) to an archive
  * docker → **image reference** (e.g., `alpine:latest`)
* `git_ref` *(optional)*: branch/tag/commit (if not included in the URL)
* `folder_path` *(folder mode only)*: subdirectory inside the repo to scan
* `client_run_id` *(optional)*: your tag to make artifact names easy to find
* Feature toggles (all boolean):

  * `enable_license_scan` (licenses + license texts)
  * `enable_copyright_scan`
  * `enable_package` (package & dependency discovery)
  * `enable_sbom_export` (export CycloneDX & SPDX alongside JSON)

**Preparation steps:**

* Installs system deps (git, unzip, tar, xz, Python) and Python libs (pandas/openpyxl).
* **repo / folder**:

  * Normalizes GitHub URLs (auto-detects `/tree/<ref>`, `/commit/<sha>`, `/releases/tag/<tag>`).
  * If the ref is a branch/tag → **shallow clone**; otherwise **full clone + detached checkout** at the commit.
  * For `folder` mode it resolves and validates the subdirectory inside the repo.
* **zip / tar**:

  * Downloads the archive (or reads it from workspace), then extracts it to an input directory.
  * Handles `.zip`, `.tar`, `.tar.gz/.tgz`, `.tar.xz/.txz`.
* **docker**:

  * Pulls the image, **exports** the container filesystem (`docker export`) to `docker-rootfs/`, and scans that directory.

**Scan & reports:**

* **ScanCode run (core JSON)**
  Builds the command from your toggles:

  * `--license --license-text` when license scan is enabled
  * `--copyright --email` when copyright scan is enabled
  * `--package` when package detection is enabled
    Produces: `scancode_<LABEL>.json`
* **SBOM exports (optional)**
  If `enable_sbom_export=true`, ScanCode also writes:

  * `scancode_<LABEL>.cdx.json` (CycloneDX JSON)
  * `scancode_<LABEL>.cdx.xml` (CycloneDX XML)
  * `scancode_<LABEL>.spdx.tv` (SPDX Tag/Value)
  * `scancode_<LABEL>.spdx.rdf` (SPDX RDF)
* **Copyrights CSV**
  If copyright scanning is enabled, it also writes:

  * `scancode_<LABEL>_copyrights.csv`
* **Excel conversion**
  A small Python step converts JSON into an **Excel workbook**:

  * `scancode_<LABEL>.xlsx` with sheets:

    * `Licenses_Detail` (per-file detections & ranges)
    * `Files_Detail` (file metadata + condensed signals)
    * `Copyrights_Detail`
    * `Dependencies`
    * `Summary` (aggregated view when data exists)

**Artifact naming:**

* `LABEL` is derived from the source (repo name/ref, archive name, or image ref) and sanitized for file safety.
* `RUN_TAG` is your `client_run_id` (or falls back to `GITHUB_RUN_ID`).
* Artifact name: **`scancode-reports-<LABEL>-<RUN_TAG>`**
  Contents typically include:

  ```
  scancode_<LABEL>.json
  scancode_<LABEL>.xlsx
  scancode_<LABEL>.spdx.tv
  scancode_<LABEL>.spdx.rdf
  scancode_<LABEL>.cdx.json
  scancode_<LABEL>.cdx.xml
  scancode_<LABEL>_copyrights.csv
  ```

  *(SBOM/CSV files appear only if their respective toggles are enabled.)*

> Notes & limits
>
> * Docker mode scans the **exported filesystem** as files (no runtime execution).
> * Large images/repos can take time; GitHub-hosted runners have \~14 GB free disk by default.
> * SPDX JSON is **not** emitted by ScanCode Toolkit in this flow; the workflow uses SPDX **Tag/Value** and **RDF** formats.

---

## 3) How to use the UI (GitHub Actions → “Run workflow”)

1. **Open the workflow**
   In GitHub, go to **Actions** → select **“ScanCode Toolkit Scan (downloadable in ui)”**.
2. **Click “Run workflow”** and fill inputs:

   * **Common**

     * `client_run_id` *(optional)*: e.g., `release_2025-09-14`.
   * **Repo mode** (`scan_mode=repo`)

     * `source` = repo URL. You can paste links like
       `https://github.com/org/repo/tree/v1.2.3` or `…/releases/tag/v1.2.3` — the ref is auto-detected.
     * `git_ref` *(optional)* if your URL doesn’t include a ref (defaults to `main`).
   * **Folder mode** (`scan_mode=folder`)

     * `source` = repo URL (same rules as repo mode).
     * `folder_path` = the subdirectory to scan (e.g., `src/main/java`).
   * **ZIP / TAR mode** (`scan_mode=zip` or `tar`)

     * `source` = public URL to the archive (or workspace path).
     * Supports `.zip`, `.tar`, `.tar.gz/.tgz`, `.tar.xz/.txz`.
   * **Docker mode** (`scan_mode=docker`)

     * `source` = image reference (e.g., `eclipse-temurin:17-jre-alpine`).
     * The workflow pulls the image, exports the rootfs, and scans the files.
   * **Toggles**

     * Turn on/off: license scan, copyright scan, package detection, SBOM export.
3. **Run**

   * Watch logs for normalization details, clone/extract steps, and ScanCode progress.
4. **Download results**

   * On the run page, under **Artifacts**, download
     **`scancode-reports-<LABEL>-<RUN_TAG>`** and open the Excel + SBOMs locally.

**Troubleshooting quickies**

* “No files found / empty JSON”: verify the repo ref, folder path, or archive URL.
* Docker errors: ensure the image name is valid and public, or that the runner can pull it.
* Very large scans: consider narrowing `folder_path` or scanning from a release source archive instead of the full repo.
