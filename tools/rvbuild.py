#!/usr/bin/env python3
"""
rvbuild.py - trigger, watch and download the custom OpenRV build on GitHub Actions.

The codecs, the color-timeline patch and the workflow are all committed in
this repo (see CLAUDE.md), so there is nothing to patch here any more. This
script only drives GitHub:

    python tools/rvbuild.py build                 # trigger, wait (~2.5 h), download zip
    python tools/rvbuild.py build --extract C:\\RV-new   # ...and unpack _install/ there
    python tools/rvbuild.py trigger               # just start a build, don't wait
    python tools/rvbuild.py download              # fetch the newest successful build

Needs:  pip install requests   and a GitHub token (fine-grained PAT, this repo only:
Actions=read/write, Contents=read), found in this order: --token, $GITHUB_TOKEN, or an
empty folder named github_pat_<token> next to this script (tools/github_pat_*, git-ignored).
Artifacts expire on GitHub after 7 days; download promptly.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("ERROR: 'requests' library not found. Run: pip install requests")


# --- Configuration ----------------------------------------------------------

DEFAULT_OWNER     = "adrianloh"
UPSTREAM_REPO     = "OpenRV"          # repo name on the fork (name kept from old script)
NEW_WORKFLOW_NAME = "build-aac.yml"   # workflow file we dispatch
BRANCH_NAME       = "main"            # ref we dispatch on (default branch)

POLL_INTERVAL_SEC = 60
POLL_TIMEOUT_HRS  = 5


# --- Helpers ----------------------------------------------------------------

def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def api_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def verify_token_and_fork(token: str, username: str) -> None:
    log("Checking that your fork exists and the token works...")
    r = requests.get(
        f"https://api.github.com/repos/{username}/{UPSTREAM_REPO}",
        headers=api_headers(token),
        timeout=30,
    )
    if r.status_code == 404:
        sys.exit(
            f"ERROR: Can't find https://github.com/{username}/{UPSTREAM_REPO}\n"
            f"       Wrong --username, or the token can't see that repo."
        )
    if r.status_code == 401:
        sys.exit("ERROR: Token is invalid or expired. Generate a new one.")
    r.raise_for_status()
    log("  Fork looks good.")


def trigger_workflow(token: str, username: str) -> float:
    """Dispatch the workflow and return the unix timestamp we captured
    just before the API call. wait_for_run uses this to filter out stale
    runs from previous dispatches."""
    log(f"Triggering '{NEW_WORKFLOW_NAME}' on branch '{BRANCH_NAME}'...")
    url = (f"https://api.github.com/repos/{username}/{UPSTREAM_REPO}"
           f"/actions/workflows/{NEW_WORKFLOW_NAME}/dispatches")
    trigger_time = time.time()  # capture BEFORE the request
    r = requests.post(
        url,
        headers=api_headers(token),
        json={"ref": BRANCH_NAME},
        timeout=30,
    )
    if r.status_code == 204:
        log("  Workflow dispatched.")
        return trigger_time
    if r.status_code == 404:
        sys.exit(
            f"ERROR: Workflow '{NEW_WORKFLOW_NAME}' not found on branch "
            f"'{BRANCH_NAME}'.\n"
            f"       GitHub sometimes takes a few seconds to register a new\n"
            f"       workflow file. Wait 30 seconds and re-run the script\n"
            f"       (it'll skip the edits and just trigger the build).\n"
            f"       Or check: https://github.com/{username}/{UPSTREAM_REPO}/actions"
        )
    if r.status_code == 422:
        sys.exit(
            f"ERROR: Workflow dispatch rejected (422).\n"
            f"       Response: {r.text}"
        )
    r.raise_for_status()
    return trigger_time


def _scan_inner_step_headers(log_text: str, seen_step_states: dict, elapsed_seconds: float) -> None:
    """
    Scan the live log from a GitHub Actions job and print step-transition
    lines for composite-action inner steps. These are the lines of the form:

        2026-04-21T01:23:45.0000000Z ##[group]Run NAME
        ...
        2026-04-21T01:45:02.0000000Z ##[endgroup]

    GitHub's /jobs API doesn't expose inner steps of a composite action, so
    this is the only way to get build progress while that one big outer step
    churns for 2+ hours.

    We also track completion by pairing ##[group] with ##[endgroup], using
    the log timestamps to compute durations.
    """
    import re
    # Match a line starting with an ISO timestamp, then ##[group]Run <title>
    # Capture groups: (1) timestamp, (2) step title
    GROUP_RE = re.compile(r"^(\S+)\s+##\[group\]Run\s+(.+?)\s*$", re.MULTILINE)
    ENDGROUP_RE = re.compile(r"^(\S+)\s+##\[endgroup\]\s*$", re.MULTILINE)

    # Find all group markers with their byte offsets so we can pair them in order.
    groups = [(m.start(), "start", m.group(1), m.group(2)) for m in GROUP_RE.finditer(log_text)]
    endgroups = [(m.start(), "end", m.group(1), None) for m in ENDGROUP_RE.finditer(log_text)]
    markers = sorted(groups + endgroups, key=lambda x: x[0])

    # Walk in order, pairing starts with the next end.
    stack = []  # stack of (name, start_ts)
    for _offset, kind, ts, name in markers:
        if kind == "start":
            stack.append((name, ts))
        elif kind == "end" and stack:
            name, start_ts = stack.pop()
            key = ("__inner__", name)
            if seen_step_states.get(key) == "completed":
                continue  # already reported
            # Compute duration from log timestamps
            dur_str = ""
            try:
                from datetime import datetime
                # Trim fractional part and Z
                def _p(s):
                    s = s.rstrip("Z")
                    # Keep only first 19 chars (YYYY-MM-DDTHH:MM:SS)
                    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
                d = (_p(ts) - _p(start_ts)).total_seconds()
                if d >= 60:
                    dur_str = f" ({int(d)//60}m{int(d)%60:02d}s)"
                elif d > 0:
                    dur_str = f" ({int(d)}s)"
            except Exception:
                pass
            # Filter noise
            lname = name.lower()
            if any(lname.startswith(p) for p in ("echo ", "printf ", "cat ", "set ")):
                continue
            # Skip trivially-named group blocks (e.g. just a shell variable echo)
            if len(name) > 200:
                name = name[:200] + "…"
            mins = int(elapsed_seconds / 60)
            log(f"  [{mins:>3}m]   └─ ✓ {name}{dur_str}")
            seen_step_states[key] = "completed"

    # Any unfinished group on the stack is currently in progress — announce once.
    for name, start_ts in stack:
        key = ("__inner__", name)
        if seen_step_states.get(key) is not None:
            continue
        lname = name.lower()
        if any(lname.startswith(p) for p in ("echo ", "printf ", "cat ", "set ")):
            continue
        if len(name) > 200:
            name = name[:200] + "…"
        mins = int(elapsed_seconds / 60)
        log(f"  [{mins:>3}m]   └─ ▶ {name}")
        seen_step_states[key] = "in_progress"


def wait_for_run(token: str, username: str, trigger_time: float) -> dict:
    """
    Wait for a workflow run that was created strictly AFTER trigger_time
    (a unix timestamp captured just before we called the dispatch endpoint).
    GitHub returns runs in descending creation order; we walk the first
    page and take the oldest one that's still newer than our cutoff. This
    avoids grabbing a stale run from a previous dispatch.
    """
    log("Waiting for the new workflow run to appear...")

    runs_url = (f"https://api.github.com/repos/{username}/{UPSTREAM_REPO}"
                f"/actions/workflows/{NEW_WORKFLOW_NAME}/runs")

    run_id: Optional[int] = None
    for attempt in range(60):  # up to ~2 minutes to appear
        r = requests.get(
            runs_url,
            headers=api_headers(token),
            params={"branch": BRANCH_NAME, "event": "workflow_dispatch", "per_page": 5},
            timeout=30,
        )
        r.raise_for_status()
        runs = r.json().get("workflow_runs", [])
        # Find the oldest run whose created_at > trigger_time (this run is our fresh one).
        # Runs are returned newest-first, so walking in reverse finds the earliest fresh run.
        fresh = []
        for run in runs:
            # GitHub API timestamps are ISO 8601 UTC, e.g. "2026-04-21T00:00:00Z"
            created_at = run.get("created_at", "")
            try:
                from datetime import datetime, timezone
                ts = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except Exception:
                continue
            if ts > trigger_time:
                fresh.append((ts, run))
        if fresh:
            fresh.sort(key=lambda x: x[0])  # oldest fresh first (that's our trigger)
            run = fresh[0][1]
            run_id = run["id"]
            log(f"  Found run #{run['run_number']} (id {run_id})")
            log(f"  Live URL: {run['html_url']}")
            break
        if attempt == 0:
            log("  No fresh run yet; waiting for GitHub to register the dispatch...")
        time.sleep(2)
    if run_id is None:
        sys.exit("ERROR: Fresh workflow run did not appear within 120 seconds.")

    run_url = f"https://api.github.com/repos/{username}/{UPSTREAM_REPO}/actions/runs/{run_id}"
    jobs_url = f"{run_url}/jobs"
    started = time.time()
    last_status = None
    # Fail-fast tracking: did we observe the FFmpeg codec-enable lines in the log?
    saw_prores_enable_line = False
    saw_prores_disable_line = False
    codec_check_done = False
    # Step-progress tracking: print a line whenever a step starts or finishes.
    # Keyed by (job_name, step_name) -> last seen status string.
    seen_step_states: dict = {}

    def _parse_iso(ts: Optional[str]) -> Optional[float]:
        if not ts:
            return None
        try:
            from datetime import datetime, timezone
            return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            return None

    while True:
        elapsed = time.time() - started
        if elapsed > POLL_TIMEOUT_HRS * 3600:
            sys.exit(f"ERROR: Build still not finished after {POLL_TIMEOUT_HRS}h. Bailing out.")
        r = requests.get(run_url, headers=api_headers(token), timeout=30)
        r.raise_for_status()
        info = r.json()
        status, conclusion = info["status"], info.get("conclusion")
        if status != last_status:
            mins = int(elapsed / 60)
            log(f"  [{mins}m elapsed] Run status: {status}" + (f" ({conclusion})" if conclusion else ""))
            last_status = status

        # ----- Step-progress reporting ---------------------------------------
        # Every poll, fetch the jobs list and report any step that has changed
        # state since we last saw it. Skip noisy housekeeping steps.
        try:
            jobs_r = requests.get(jobs_url, headers=api_headers(token), timeout=30)
            jobs_r.raise_for_status()
            jobs = jobs_r.json().get("jobs", [])
        except requests.RequestException:
            jobs = []

        SKIP_STEP_PREFIXES = ("set up job", "post ", "complete job", "checkout")
        for job in jobs:
            jname = job.get("name", "?")
            for step in job.get("steps", []) or []:
                sname = step.get("name") or ""
                # Filter noisy GHA-internal steps
                if any(sname.lower().startswith(p) for p in SKIP_STEP_PREFIXES):
                    continue
                sstatus = step.get("status", "?")
                key = (jname, sname)
                prev = seen_step_states.get(key)
                if prev == sstatus:
                    continue
                # State transition!
                mins = int(elapsed / 60)
                if sstatus == "in_progress":
                    log(f"  [{mins:>3}m] ▶  {sname}")
                elif sstatus == "completed":
                    sconclusion = step.get("conclusion") or "?"
                    started_ts = _parse_iso(step.get("started_at"))
                    completed_ts = _parse_iso(step.get("completed_at"))
                    if started_ts and completed_ts:
                        dur = int(completed_ts - started_ts)
                        dur_str = f"{dur // 60}m{dur % 60:02d}s" if dur >= 60 else f"{dur}s"
                        marker = "✓" if sconclusion == "success" else "✗"
                        log(f"  [{mins:>3}m] {marker}  {sname} ({dur_str})")
                    else:
                        marker = "✓" if sconclusion == "success" else "✗"
                        log(f"  [{mins:>3}m] {marker}  {sname}")
                seen_step_states[key] = sstatus

        # ----- Live log scan: surface inner composite-action step headers --------
        # The Windows build is one giant composite-action step, so the /jobs API
        # only shows "Run ./.github/actions/build-windows" — useless as progress.
        # But the log text itself contains "##[group]Run NAME" lines when each
        # inner step starts. We scan for those so the user sees real activity.
        for job in jobs:
            if "windows" not in job.get("name", "").lower():
                continue
            job_id = job["id"]
            try:
                log_r = requests.get(
                    f"https://api.github.com/repos/{username}/{UPSTREAM_REPO}/actions/jobs/{job_id}/logs",
                    headers=api_headers(token),
                    timeout=60,
                    allow_redirects=True,
                )
                if log_r.status_code != 200:
                    continue
                _scan_inner_step_headers(log_r.text, seen_step_states, elapsed)
            except requests.RequestException:
                pass
            break  # one windows job is enough

        # ----- Live log inspection: check codec enable line early ------------
        # The "FFmpeg decoder prores enabled" line is printed at cmake-configure
        # time, early in the build (~5-10 min in). If it's missing by the time
        # the FFmpeg deps have built (or any later step has started), we know
        # the flags didn't take effect and can abort instead of waiting 2 more hrs.
        if not codec_check_done and status in ("in_progress", "completed"):
            try:
                for job in jobs:  # reuse the jobs list fetched above
                    # Only inspect Windows build jobs (they have the codec flags).
                    if "windows" not in job.get("name", "").lower():
                        continue
                    job_id = job["id"]
                    log_r = requests.get(
                        f"https://api.github.com/repos/{username}/{UPSTREAM_REPO}/actions/jobs/{job_id}/logs",
                        headers=api_headers(token),
                        timeout=60,
                        allow_redirects=True,
                    )
                    if log_r.status_code != 200:
                        continue
                    log_text = log_r.text
                    if "FFmpeg decoder prores enabled" in log_text:
                        saw_prores_enable_line = True
                    if "--disable-decoder=prores" in log_text:
                        saw_prores_disable_line = True

                    # If we've gotten past "Build OpenRV dependencies" step or
                    # the job finished, the codec-enable line should have been
                    # printed by now. Decide verdict.
                    steps = job.get("steps", []) or []
                    configure_done = any(
                        "configure openrv" in (s.get("name") or "").lower()
                        and s.get("status") == "completed"
                        for s in steps
                    )
                    if configure_done or status == "completed":
                        if saw_prores_enable_line:
                            log("  ✓ Codec flags took effect (saw 'FFmpeg decoder prores enabled')")
                        elif saw_prores_disable_line:
                            log("")
                            log("  ✗ ABORT: FFmpeg is being built with ProRes DISABLED.")
                            log("    Your codec flags did NOT reach the FFmpeg configure step.")
                            log(f"    Live URL: {info['html_url']}")
                            log("    Cancelling this run to save you 2 hours...")
                            # Cancel the GHA run
                            cancel_url = f"{run_url}/cancel"
                            requests.post(cancel_url, headers=api_headers(token), timeout=30)
                            sys.exit(1)
                        # else: configure step completed but we saw neither line —
                        # log fetch may have been partial; give it one more loop.
                        else:
                            # Don't mark done yet; try again next poll.
                            continue
                        codec_check_done = True
                        break
            except requests.RequestException as e:
                # Non-fatal — just skip this poll's log check
                log(f"  (log fetch failed: {e}; will retry)")

        if status == "completed":
            if conclusion != "success":
                log(f"Build did not succeed. Conclusion: {conclusion}")
                log(f"Check the logs at: {info['html_url']}")
                sys.exit(1)
            log("  Build succeeded!")
            return info
        time.sleep(POLL_INTERVAL_SEC)


def download_artifact(token: str, username: str, run_info: dict, dest_dir: Path,
                       num_workers: int = 8, chunk_mb: int = 64) -> Path:
    log("Fetching artifact list...")
    r = requests.get(run_info["artifacts_url"], headers=api_headers(token), timeout=30)
    r.raise_for_status()
    artifacts = r.json().get("artifacts", [])
    if not artifacts:
        sys.exit(
            "ERROR: Build succeeded but produced no artifacts.\n"
            "       Check the workflow log to see if the upload step ran."
        )

    artifact = next(
        (a for a in artifacts if "all-codecs" in a["name"]),
        artifacts[0],
    )
    expected_size = artifact.get("size_in_bytes", 0)
    size_mb = expected_size / (1024 * 1024)
    log(f"  Artifact: {artifact['name']} — {size_mb:.1f} MB")

    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / f"{artifact['name']}.zip"
    return resumable_download(
        token,
        artifact["archive_download_url"],
        out_path,
        expected_size,
        num_workers=num_workers,
        chunk_mb=chunk_mb,
    )


def resumable_download(token: str, url: str, out_path: Path, expected_size: int,
                       num_workers: int = 8, chunk_mb: int = 64) -> Path:
    """
    Parallel, chunked, resumable download.

    Strategy:
      1. Resolve the artifact URL once (it's a 302 to an Azure Blob pre-signed URL).
      2. Divide the file into `chunk_mb`-sized ranges. Each chunk becomes a file
         in `<out_path>.parts/chunk_NNNN`.
      3. `num_workers` threads pull chunks off a queue and download each via
         `Range: bytes=start-end`. Completed chunks stay on disk so the whole
         thing is resumable — re-running skips any chunk already at full size.
      4. A reporter thread prints aggregate MB/s and percent every 5 seconds.
      5. When all chunks are present, concatenate them into the final file and
         delete the `.parts/` directory.

    The Azure pre-signed URL typically expires ~60 minutes after issuance;
    if a worker hits a 403 it re-resolves via `url` (going through the token
    to get a fresh redirect).
    """
    import concurrent.futures
    import threading

    MAX_ATTEMPTS_PER_CHUNK = 5
    STREAM_CHUNK = 1024 * 1024       # 1 MB read size from the wire
    CHUNK_SIZE = chunk_mb * 1024 * 1024

    # -- Fast path: already have the full file? ----------------------------
    if out_path.exists() and expected_size and out_path.stat().st_size == expected_size:
        log(f"  Already downloaded in full: {out_path}")
        return out_path

    # -- Resolve the final URL once -----------------------------------------
    # requests.head follows 302s by default; the final response's url is the
    # pre-signed blob URL. We don't actually consume the body.
    def resolve_url() -> str:
        h = requests.head(url, headers=api_headers(token), allow_redirects=True, timeout=30)
        h.raise_for_status()
        return h.url

    resolved_url = resolve_url()
    resolved_lock = threading.Lock()

    # -- Plan chunks --------------------------------------------------------
    if not expected_size:
        sys.exit("ERROR: expected_size is 0; can't plan parallel chunks. Falling back isn't implemented.")

    parts_dir = out_path.with_suffix(out_path.suffix + ".parts")
    parts_dir.mkdir(parents=True, exist_ok=True)

    chunks = []
    start = 0
    idx = 0
    while start < expected_size:
        end = min(start + CHUNK_SIZE - 1, expected_size - 1)
        chunks.append({
            "idx": idx,
            "start": start,
            "end": end,
            "size": end - start + 1,
            "path": parts_dir / f"chunk_{idx:04d}",
        })
        start = end + 1
        idx += 1

    total_chunks = len(chunks)

    # -- Figure out which chunks are already complete -----------------------
    completed_chunks = set()
    already_bytes = 0
    for c in chunks:
        if c["path"].exists() and c["path"].stat().st_size == c["size"]:
            completed_chunks.add(c["idx"])
            already_bytes += c["size"]
        elif c["path"].exists():
            # Partial chunk from a previous interrupt; delete and redownload.
            c["path"].unlink()

    if already_bytes > 0:
        log(f"  Resuming: {len(completed_chunks)}/{total_chunks} chunks already complete "
            f"({already_bytes / (1024*1024):.0f} / {expected_size / (1024*1024):.0f} MB)")
    else:
        log(f"  Downloading {expected_size / (1024*1024):.0f} MB in {total_chunks} chunks "
            f"of {chunk_mb} MB using {num_workers} parallel workers")

    pending = [c for c in chunks if c["idx"] not in completed_chunks]
    if not pending:
        # All chunks were already on disk; just assemble.
        log("  All chunks already present — skipping to assembly")
    else:
        # -- Worker function ------------------------------------------------
        def download_chunk(c: dict) -> None:
            nonlocal resolved_url
            attempt = 0
            while True:
                attempt += 1
                try:
                    # Snapshot the current URL outside the lock to avoid holding it across IO
                    with resolved_lock:
                        current_url = resolved_url
                    headers = {"Range": f"bytes={c['start']}-{c['end']}"}
                    r = requests.get(
                        current_url,
                        headers=headers,
                        stream=True,
                        timeout=(30, 120),
                        allow_redirects=True,
                    )
                    # 403/410 → pre-signed URL expired; refresh via token and retry
                    if r.status_code in (403, 410):
                        r.close()
                        with resolved_lock:
                            try:
                                resolved_url = resolve_url()
                                current_url = resolved_url
                            except Exception:
                                pass
                        if attempt < MAX_ATTEMPTS_PER_CHUNK:
                            time.sleep(1)
                            continue
                    if r.status_code not in (200, 206):
                        r.raise_for_status()
                    # Write to a .tmp file, rename on full success, so a half-written
                    # chunk never looks "complete" to the resume logic.
                    tmp_path = c["path"].with_suffix(".tmp")
                    written = 0
                    with open(tmp_path, "wb") as f:
                        for block in r.iter_content(chunk_size=STREAM_CHUNK):
                            if block:
                                f.write(block)
                                written += len(block)
                    r.close()
                    if written != c["size"]:
                        tmp_path.unlink(missing_ok=True)
                        raise IOError(f"chunk {c['idx']} wrote {written} bytes, expected {c['size']}")
                    tmp_path.replace(c["path"])
                    return  # success

                except (requests.exceptions.RequestException, IOError) as e:
                    if attempt >= MAX_ATTEMPTS_PER_CHUNK:
                        raise
                    backoff = min(15, 2 ** attempt)
                    time.sleep(backoff)

        # -- Reporter thread: aggregate progress every 5s -------------------
        stop_reporter = threading.Event()

        def reporter():
            last_bytes = already_bytes
            last_time = time.time()
            while not stop_reporter.wait(5.0):
                cur_bytes = sum(
                    (c["path"].stat().st_size if c["path"].exists() else 0) +
                    (c["path"].with_suffix(".tmp").stat().st_size if c["path"].with_suffix(".tmp").exists() else 0)
                    for c in chunks
                )
                now = time.time()
                dt = now - last_time
                mbps = ((cur_bytes - last_bytes) / dt) / (1024 * 1024) if dt > 0 else 0
                pct = (cur_bytes / expected_size) * 100
                completed = sum(1 for c in chunks
                                if c["path"].exists() and c["path"].stat().st_size == c["size"])
                log(f"    ...{cur_bytes / (1024*1024):.0f} / {expected_size / (1024*1024):.0f} MB "
                    f"({pct:.1f}%)  [{completed}/{total_chunks} chunks, {mbps:.1f} MB/s]")
                last_bytes = cur_bytes
                last_time = now

        reporter_thread = threading.Thread(target=reporter, daemon=True)
        reporter_thread.start()

        # -- Download all pending chunks in parallel ------------------------
        start_time = time.time()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
                futures = {pool.submit(download_chunk, c): c for c in pending}
                for fut in concurrent.futures.as_completed(futures):
                    c = futures[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        # Cancel everything and bail.
                        for f in futures:
                            f.cancel()
                        stop_reporter.set()
                        sys.exit(
                            f"ERROR: chunk {c['idx']} ({c['start']}-{c['end']}) failed: {e}\n"
                            f"       Partial chunks are preserved in {parts_dir}\n"
                            f"       Re-run with --download to resume from where we left off."
                        )
        finally:
            stop_reporter.set()
            reporter_thread.join(timeout=1)

        elapsed = time.time() - start_time
        new_bytes = expected_size - already_bytes
        avg_mbps = (new_bytes / elapsed) / (1024 * 1024) if elapsed > 0 else 0
        log(f"  All chunks downloaded in {int(elapsed)}s (avg {avg_mbps:.1f} MB/s)")

    # -- Assemble ----------------------------------------------------------
    log(f"  Assembling {total_chunks} chunks into {out_path}...")
    with open(out_path, "wb") as out_f:
        for c in chunks:
            with open(c["path"], "rb") as in_f:
                while True:
                    block = in_f.read(8 * 1024 * 1024)
                    if not block:
                        break
                    out_f.write(block)

    actual = out_path.stat().st_size
    if actual != expected_size:
        sys.exit(f"ERROR: assembled file size {actual:,} != expected {expected_size:,}\n"
                 f"       Chunks preserved at {parts_dir} for inspection.")

    # Clean up chunk files
    for c in chunks:
        c["path"].unlink(missing_ok=True)
    try:
        parts_dir.rmdir()
    except OSError:
        pass  # not empty somehow; leave it

    log(f"  Done. Saved to {out_path} ({actual / (1024*1024):.0f} MB)")
    return out_path


def find_latest_successful_run(token: str, username: str) -> dict:
    """Find the most recent successful workflow run on BRANCH_NAME for the
    build-aac.yml workflow. Used by --download mode to locate the artifact."""
    runs_url = (f"https://api.github.com/repos/{username}/{UPSTREAM_REPO}"
                f"/actions/workflows/{NEW_WORKFLOW_NAME}/runs")
    r = requests.get(
        runs_url,
        headers=api_headers(token),
        params={"branch": BRANCH_NAME, "status": "success", "per_page": 10},
        timeout=30,
    )
    r.raise_for_status()
    runs = r.json().get("workflow_runs", [])
    if not runs:
        sys.exit(
            "ERROR: No successful build runs found for this fork.\n"
            "       Run the script without --download to trigger a build first."
        )
    # Check that the most recent one still has its artifact (they expire after retention-days).
    run = runs[0]
    log(f"Latest successful run: #{run['run_number']} (id {run['id']})")
    log(f"  Completed: {run.get('updated_at', '?')}")
    log(f"  URL: {run['html_url']}")
    return run


# ─── Main ─────────────────────────────────────────────────────────────────────

def default_downloads_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("USERPROFILE", Path.home())) / "Downloads"
    return Path.home() / "Downloads"


def find_token_in_script_dir() -> Optional[str]:
    """Return the name of a 'github_pat_*' folder next to this script (token stashed as a folder name)."""
    script_dir = Path(__file__).resolve().parent
    matches = [p.name for p in script_dir.iterdir() if p.is_dir() and p.name.startswith("github_pat_")]
    if len(matches) > 1:
        log(f"WARNING: multiple github_pat_* folders next to script; using {matches[0]}")
    return matches[0] if matches else None


def extract_install(zip_path: Path, dest: Path) -> None:
    """Unpack the _install/ tree from the artifact zip into dest (without the prefix)."""
    log(f"Extracting _install/ from {zip_path.name} to {dest} ...")
    n = 0
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if not info.filename.startswith("_install/") or info.is_dir():
                continue
            rel = info.filename[len("_install/"):]
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src_f, open(target, "wb") as out_f:
                while chunk := src_f.read(1024 * 1024):
                    out_f.write(chunk)
            n += 1
    log(f"  Extracted {n} files. Run {dest / 'bin' / 'rv.exe'}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["build", "trigger", "download"])
    p.add_argument("--username", default=DEFAULT_OWNER,
                   help=f"GitHub owner of the fork (default: {DEFAULT_OWNER})")
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"),
                   help="GitHub token. Defaults to $GITHUB_TOKEN.")
    p.add_argument("--download-dir", type=Path, default=default_downloads_dir(),
                   help="Where to save the artifact zip (default: Downloads).")
    p.add_argument("--extract", type=Path, default=None, metavar="DIR",
                   help="After downloading, unpack _install/ into DIR.")
    p.add_argument("--workers", type=int, default=8,
                   help="Parallel download workers (default: 8).")
    p.add_argument("--chunk-mb", type=int, default=64,
                   help="Parallel download chunk size in MB (default: 64).")
    args = p.parse_args()

    if not args.token:
        args.token = find_token_in_script_dir()
        if args.token:
            log("Using token from the github_pat_* folder next to this script.")
    if not args.token:
        sys.exit("ERROR: No token. Pass --token, set $GITHUB_TOKEN, or create an empty folder "
                 "named github_pat_<token> in tools/.")

    verify_token_and_fork(args.token, args.username)

    if args.command == "trigger":
        trigger_workflow(args.token, args.username)
        print(f"Started. Watch: https://github.com/{args.username}/{UPSTREAM_REPO}/actions")
        return

    if args.command == "build":
        trigger_time = trigger_workflow(args.token, args.username)
        run_info = wait_for_run(args.token, args.username, trigger_time)
    else:  # download
        run_info = find_latest_successful_run(args.token, args.username)

    out_path = download_artifact(args.token, args.username, run_info, args.download_dir,
                                 num_workers=args.workers, chunk_mb=args.chunk_mb)
    if args.extract:
        extract_install(out_path, args.extract)

    print("\n" + "=" * 60)
    print(f"  Done: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Aborted by user.")
        sys.exit(130)
