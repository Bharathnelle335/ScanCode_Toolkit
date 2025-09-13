import io
import re
import uuid
import requests
import streamlit as st
from datetime import datetime

# ===================== CONFIG ===================== #
OWNER = "Bharathnelle335"              # repo owner that hosts the workflow
REPO = "scanOSS"                        # repo that holds the SCANOSS workflow
WORKFLOW_FILE = "ScanOSS.yml"           # exact filename under .github/workflows/
DEFAULT_REF = "main"                    # default branch/tag where workflow exists
TOKEN = st.secrets.get("GITHUB_TOKEN", "")  # PAT with repo + workflow scopes

BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
HEADERS = {
    "Accept": "application/vnd.github+json",
    **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
    "X-GitHub-Api-Version": "2022-11-28",
}

# ===================== PAGE ===================== #
st.set_page_config(page_title="SCANOSS Workflow Trigger", page_icon="🧩", layout="wide")
st.title("🧩 SCANOSS Workflow Trigger")
st.caption("© EY Internal Use Only")

if not TOKEN:
    st.warning("No GitHub token found. Add `GITHUB_TOKEN` to Streamlit secrets for private repos and higher rate limits.")

# ===================== HELPERS (GitHub) ===================== #
def _next_link(headers: dict):
    link = headers.get("Link")
    if not link:
        return None
    for part in link.split(","):
        seg = part.strip()
        if 'rel="next"' in seg:
            s = seg.find("<"); e = seg.find(">", s + 1)
            if s != -1 and e != -1:
                return seg[s + 1:e]
    return None


def gh_get(url: str, **kw):
    return requests.get(url, headers=HEADERS, timeout=30, **kw)


def gh_post(url: str, payload: dict):
    return requests.post(url, headers=HEADERS, json=payload, timeout=60)


def fetch_all_branches(owner: str, repo: str):
    out, url = [], f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
    while url:
        r = gh_get(url)
        if not r.ok:
            break
        if isinstance(r.json(), list):
            out += [b.get("name") for b in r.json() if isinstance(b, dict) and b.get("name")]
        url = _next_link(r.headers)
    # Put main first if present
    if "main" in out:
        out = ["main"] + [b for b in out if b != "main"]
    return out


def fetch_all_tags(owner: str, repo: str):
    out, url = [], f"https://api.github.com/repos/{owner}/{repo}/tags?per_page=100"
    while url:
        r = gh_get(url)
        if not r.ok:
            break
        if isinstance(r.json(), list):
            out += [t.get("name") for t in r.json() if isinstance(t, dict) and t.get("name")]
        url = _next_link(r.headers)
    return out


def list_workflow_runs(workflow_file: str, ref: str, per_page: int = 30):
    url = f"{BASE}/actions/workflows/{workflow_file}/runs"
    return gh_get(url, params={"per_page": per_page, "event": "workflow_dispatch", "branch": ref})


def find_run_by_tag(runs: list, tag: str):
    for r in runs:
        title = r.get("display_title") or r.get("name") or ""
        if tag and tag in title:
            return r
    return runs[0] if runs else None


def get_run_artifacts(run_id: int):
    return gh_get(f"{BASE}/actions/runs/{run_id}/artifacts", params={"per_page": 100})


def download_artifact_zip(artifact_id: int) -> bytes:
    r = gh_get(f"{BASE}/actions/artifacts/{artifact_id}/zip", stream=True)
    if not r.ok:
        return b""
    return r.content


def new_client_tag() -> str:
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]

# ===================== SESSION STATE ===================== #
for key, default in [
    ("git_ref_input", ""),
    ("_branches", []),
    ("_tags", []),
    ("branch_choice", ""),
    ("tag_choice", ""),
    ("last_client_run_id", ""),
    ("selected_ref", DEFAULT_REF),
]:
    st.session_state.setdefault(key, default)

# ===================== UI: DISPATCH INPUTS ===================== #
st.subheader("Dispatch inputs")

c1, c2 = st.columns(2)
with c1:
    scan_type = st.selectbox("scan_type", ["docker", "git", "upload-zip", "upload-tar"], index=0)
    image_scan_mode = st.selectbox("image_scan_mode (for images)", ["manual", "syft"], index=0)
    enable_scanoss_bool = st.checkbox("enable_scanoss", value=True)
    enable_scanoss = "true" if enable_scanoss_bool else "false"
with c2:
    client_run_id = st.text_input("client_run_id (optional tag)",
                                  value=st.session_state.get("last_client_run_id") or new_client_tag())
    st.session_state["last_client_run_id"] = client_run_id

# Conditional inputs
docker_image = ""; git_url = ""; git_ref = ""; archive_url = ""
if scan_type == "docker":
    docker_image = st.text_input("docker_image (e.g., nginx:latest)")
elif scan_type == "git":
    git_url = st.text_input("git_url (https://github.com/org/repo[/tree/<ref>|/commit/<sha>|/releases/tag/<tag>])")
    git_ref = st.text_input("git_ref (optional if included in git_url)", value="")
elif scan_type in ("upload-zip", "upload-tar"):
    st.caption("Provide a direct-download URL for the archive.")
    samples = {
        "ZIP sample": "https://github.com/actions/checkout/archive/refs/heads/main.zip",
        "TAR.GZ sample": "https://github.com/actions/checkout/archive/refs/heads/main.tar.gz",
    }
    pick = st.selectbox("Use a sample URL?", ["(none)"] + list(samples.keys()), index=0)
    if pick != "(none)":
        archive_url = samples[pick]
    archive_url = st.text_input("archive_url", value=archive_url)

# ===================== UI: WORKFLOW REF (BRANCH/TAG) ===================== #
st.markdown("---")
st.subheader("Workflow ref")
rc1, rc2, rc3 = st.columns([1, 1, 2])
with rc1:
    if st.button("🔄 Load branches/tags", use_container_width=True):
        st.session_state["_branches"] = fetch_all_branches(OWNER, REPO)
        st.session_state["_tags"] = fetch_all_tags(OWNER, REPO)
        if not (st.session_state["_branches"] or st.session_state["_tags"]):
            st.warning("No branches or tags found, or token lacks access.")

with rc2:
    # empty spacer
    st.write("")

ref_cols = st.columns(2)
with ref_cols[0]:
    st.session_state["branch_choice"] = st.selectbox(
        "Branch", [""] + st.session_state.get("_branches", []), index=0
    )
with ref_cols[1]:
    st.session_state["tag_choice"] = st.selectbox(
        "Tag", [""] + st.session_state.get("_tags", []), index=0
    )

# Final workflow ref: prefer branch, else tag, else default
st.session_state["selected_ref"] = (
    st.session_state.get("branch_choice")
    or st.session_state.get("tag_choice")
    or DEFAULT_REF
)

# ===================== DISPATCH ===================== #
run = st.button("🚀 Start Scan", use_container_width=True, type="primary")
if run:
    # Validate requireds per scan_type
    err = None
    if scan_type == "docker" and not docker_image:
        err = "docker_image is required for scan_type=docker"
    if scan_type == "git" and not git_url:
        err = "git_url is required for scan_type=git"
    if scan_type in ("upload-zip", "upload-tar") and not archive_url:
        err = f"archive_url is required for scan_type={scan_type}"

    if err:
        st.error(f"❌ {err}")
    else:
        inputs = {
            "scan_type": scan_type,
            "image_scan_mode": image_scan_mode,
            "docker_image": docker_image,
            "git_url": git_url,
            "git_ref": git_ref,
            "enable_scanoss": enable_scanoss,
            "archive_url": archive_url,
            "client_run_id": client_run_id,
        }
        # GitHub workflow_dispatch
        payload = {"ref": st.session_state["selected_ref"], "inputs": inputs}
        resp = gh_post(f"{BASE}/actions/workflows/{WORKFLOW_FILE}/dispatches", payload)
        if resp.status_code == 204:
            st.success("✅ Scan started!")
            with st.expander("Submitted Inputs", expanded=False):
                st.json(inputs)
        else:
            st.error(f"❌ Failed: {resp.status_code} {resp.text}")

# ===================== RESULTS ===================== #
st.markdown("---")
st.header("📦 Results")

res_c1, res_c2, res_c3 = st.columns([3, 2, 1])
with res_c1:
    result_tag = st.text_input("Run tag to check", value=st.session_state.get("last_client_run_id", ""))
with res_c2:
    result_ref = st.selectbox(
        "Branch/Tag to filter",
        options=[st.session_state.get("selected_ref", DEFAULT_REF)] + [r for r in st.session_state.get("_branches", []) + st.session_state.get("_tags", []) if r != st.session_state.get("selected_ref")],
        index=0,
    )
with res_c3:
    check = st.button("🔎 Check & fetch", use_container_width=True)

if check:
    if not result_tag:
        st.error("Provide a run tag (client_run_id).")
    else:
        runs_resp = list_workflow_runs(WORKFLOW_FILE, ref=result_ref, per_page=50)
        if not runs_resp.ok:
            st.error(f"Failed to list runs: {runs_resp.status_code} {runs_resp.text}")
        else:
            runs = runs_resp.json().get("workflow_runs", [])
            run = find_run_by_tag(runs, result_tag)
            if not run:
                st.warning("No run found yet for this tag on the selected ref. Try again later or change the filter.")
            else:
                run_id = run["id"]
                status = run.get("status")
                conclusion = run.get("conclusion")
                started = run.get("run_started_at")
                html_url = run.get("html_url")
                st.write(f"**Run:** [{run_id}]({html_url})")
                st.write(f"**Status:** {status}  |  **Conclusion:** {conclusion or '—'}  |  **Started:** {started or '—'}")

                arts_resp = get_run_artifacts(run_id)
                if not arts_resp.ok:
                    st.error(f"Failed to list artifacts: {arts_resp.status_code} {arts_resp.text}")
                else:
                    artifacts = arts_resp.json().get("artifacts", [])
                    if not artifacts:
                        st.warning("No artifacts found for this run.")
                    else:
                        # Prefer artifact with tag in name; else the first
                        art = None
                        for a in artifacts:
                            if result_tag in a.get("name", ""):
                                art = a; break
                        if not art:
                            art = artifacts[0]
                        st.write(f"**Artifact:** `{art.get('name')}`  •  size ~ {art.get('size_in_bytes', 0)} bytes")
                        if not art.get("expired", False):
                            data = download_artifact_zip(art["id"])
                            if data:
                                fname = f"{art.get('name','scanoss-results')}.zip"
                                st.download_button("⬇️ Download ZIP", data=data, file_name=fname, mime="application/zip")
                            else:
                                st.error("Failed to download artifact zip (empty response).")
                        else:
                            st.error("Artifact expired (per repo retention). Re-run the scan.")
