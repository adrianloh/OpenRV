# CLAUDE.md — adrianloh/OpenRV (custom fork)

Personal fork of [AcademySoftwareFoundation/OpenRV](https://github.com/AcademySoftwareFoundation/OpenRV),
built **only on GitHub Actions** (Windows, CY2024, Release). Nothing is compiled locally.
Owner uses the result as his daily RV at `C:\Program Files\RV` (plain folder, no suffix).

## What is customized (everything else is stock upstream)

1. **Extra FFmpeg codecs** — `.github/actions/build-windows/action.yml`: both `cmake -B _build` lines carry
   `-DRV_FFMPEG_NON_FREE_DECODERS_TO_ENABLE="aac;aac_fixed;aac_latm;ac3;hevc;mpeg2video;prores;dnxhd;dvvideo;qtrle;vp9"`
   and `-DRV_FFMPEG_NON_FREE_ENCODERS_TO_ENABLE="aac;prores;dnxhd"`. A final step uploads the build as an artifact
   (`_install/**` only, retention **7 days**).
2. **One-click build workflow** — `.github/workflows/build-aac.yml` (`workflow_dispatch`, wraps `ci-windows.yml`,
   CY2024 only, no Debug). Upstream's own `ci.yml` is gated to the ASWF org and never runs on the fork.
3. **Per-clip colors in the sequence timeline** — `src/lib/app/mu_rvui/timeline.mu`: each clip gets a color from a
   32-color palette (`initClipPalettes`), chosen by hashing the clip's source name mod 31 (prime, on purpose:
   mod 32 collapses to 2 buckets). Palettes are precomputed at widget init; the draw loop is just an array lookup.
4. **Custom RV packages** — `plugins/<name>/`: `fast_edit_mode` (v1.1), `frame_capture`, `py_console`,
   `watch_directory`. Hooked into the build by one `ADD_SUBDIRECTORY` line at the end of `src/plugins/CMakeLists.txt`;
   every folder with a `CMakeLists.txt` becomes `<name>-<version>.rvpkg` in `PlugIns/Packages` and is installed *and
   enabled* by the build's `rvinstall` step. All four are the owner's live files, confirmed by him against his
   running RV on 2026-10-21. See `plugins/README.md`. **This hook has not been exercised by a CI build yet.**
   - Changing a plugin: edit the `.py`, **bump `version:` in its `PACKAGE`**. New plugin: copy a sibling folder.
   - `frame_capture` saves to a hardcoded `C:/Users/TTWP/Downloads`. `watch_directory` was installed-but-disabled in
     the owner's old setup; the bundled install will enable it (disable in the Package Manager if unwanted).
   - After installing a build that bundles these, remove the same packages from his user-level package folder,
     otherwise each loads twice (double keybindings/menus).
   - An installed `.rvpkg` can be stale vs the extracted `.py` RV really loads (this nearly cost us the newer
     `fast_edit_mode`); trust the owner's live file, not the package.
5. **`tools/rvbuild.py`** — trigger / watch / download the Actions build (see below).

## Building

```powershell
pip install requests
$env:GITHUB_TOKEN = "github_pat_..."          # or: empty folder tools\github_pat_<token> (git-ignored); fine-grained PAT, this repo only: Actions r/w, Contents read
python tools/rvbuild.py build --extract C:\RV-new   # trigger, wait ~2.5 h, download, unpack _install\ to C:\RV-new
python tools/rvbuild.py trigger                      # just start it (watch on GitHub -> Actions)
python tools/rvbuild.py download                     # newest successful run; resumable
```

- Artifacts **expire after 7 days**, ~1 GB (the old `_build/stage/app` duplicate was dropped from the upload).
- To install: close RV, then replace the contents of `C:\Program Files\RV` with the extracted `_install` tree
  (needs admin). Keep the previous install around until the new one opens a real project.
- **Hot-patch without rebuilding:** `timeline.mu` ships as plain text at `<RV>\PlugIns\Mu\timeline.mu`. Edit it in
  this repo, copy it over the installed one to test, then commit. Mu is not compile-checked locally.

## Git workflow

- Remotes: `origin` = `adrianloh/OpenRV`, `upstream` = ASWF OpenRV. Default branch `main` **is** the custom branch
  (our commits sit on top of upstream); do not force-push it.
- Syncing upstream: `git fetch upstream && git merge upstream/main` (or the GitHub "Sync fork" button), then run a build.
  Expect possible conflicts in `action.yml` (the cmake lines) and `timeline.mu`.
- Line endings: this clone has `core.autocrlf=false` and the repo is LF. If Windows git shows hundreds of "modified"
  files, that's CRLF noise from a different autocrlf setting — check `git config core.autocrlf`, don't commit it.
- Never commit a token. The token may live as an empty folder name in `tools/` (`tools/github_pat_*` is git-ignored).

## State / history (as of 2026-10-21)

- Fork is based on upstream `d1ca02c` (Apr 2026) + our codec commit `fd128e1`; upstream was 115 commits ahead.
  No upstream sync since the Apr 22 build — deliberately left out so the next build changes only our own things.
- Commits made on top that **may still be unpushed** (the PC's Claude can't push; check `git status -sb`): timeline
  colors, `tools/rvbuild.py` + CLAUDE.md, `plugins/`, rvbuild token lookup, fast_edit_mode 1.1.
- The only successful Actions run so far is the Apr 22 build (it has neither the timeline patch nor `plugins/`;
  the timeline was hot-patched into the installs by hand).
- **Next steps:** (1) `git push`; (2) `python tools/rvbuild.py build --extract C:\RV-new`; (3) in the result check the
  colored timeline, that the four packages are present and enabled, and no duplicates with user-level copies;
  (4) swap into `C:\Program Files\RV`; (5) later, merge upstream and rebuild.
- RV's own log: `%APPDATA%\ASWF\OpenRV\OpenRV.log` (session start/end, plugin loading). The owner's user-level
  package folder was not located.
- Old materials were salvaged to `Z:\dev\openrv-builds\_salvage\` (old Python builder scripts, old action.yml,
  the hand-edited timeline.mu). Previous build zips live in `Z:\dev\openrv-builds\` (kept on purpose).
- Superseded, candidates for deletion once the owner confirms: `Z:\dev\openrv-full` (stale shallow clone),
  `Z:\dev\openrv-builder` (old scripts; the token folder now lives in `tools/`), `C:\Program Files\RV_042225`
  (older install).

## Working with Claude on this machine

- Claude's shell on this PC is a Linux VM that sees the folders under `Z:\dev\...` — it can read/edit/commit but
  **cannot push** and cannot run Windows tools (Python/git for Windows, RV itself). The owner pushes and runs builds.
- Commits Claude makes carry a `Co-Authored-By: Claude` trailer.
