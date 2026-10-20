# plugins/ — custom RV packages built into our releases

Each sub-folder is one RV package: `PACKAGE` (manifest), `<name>.py` and a `CMakeLists.txt`
containing the `RV_STAGE(TYPE "RVPKG" ...)` boilerplate (copy any sibling's).
`plugins/CMakeLists.txt` picks up every folder that has a `CMakeLists.txt`, so adding a plugin
means adding a folder — nothing else to register.

At build time each one becomes `<name>-<version>.rvpkg` in `PlugIns/Packages/` (version comes from
`PACKAGE`; **bump it when you change a plugin**) and the build's `rvinstall` step installs *and
enables* every package in that folder, same as the stock ones.

| Plugin | What it does |
|---|---|
| `fast_edit_mode` | Ctrl+Enter toggles sequence view / single-clip view (this is the early v1.0; see CLAUDE.md) |
| `frame_capture` | `s` saves the current frame as PNG to `C:/Users/TTWP/Downloads` (path is hardcoded) |
| `py_console` | Modeless Python console window (needs PySide6, which RV bundles) |
| `watch_directory` | Tools > Watch Directory...: auto-loads new .mp4 files from a folder |

Test a change without rebuilding: edit the `.py`, zip `PACKAGE` + the `.py` into `<name>-<ver>.rvpkg`,
and install it with RV's Package Manager (or `rvpkg -install`).

**Avoid duplicates:** if the same package is also installed in your user folder
(`%APPDATA%\RV\Packages`), its keybindings/menus load twice. Remove the user-level copy once the
bundled one is in your build.
