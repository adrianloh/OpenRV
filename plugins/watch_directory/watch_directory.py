from rv import rvtypes, commands, extra_commands
import os
import glob
import time


class WatchDirectoryMode(rvtypes.MinorMode):
    """Watch a directory for new .mp4 files and load them into RV."""

    def __init__(self):
        rvtypes.MinorMode.__init__(self)
        self.init(
            "watch_directory_mode",
            None,
            None,
            [
                (
                    "Tools",
                    [
                        ("Watch Directory...", self.showDialog, None, None),
                    ],
                )
            ],
        )
        self._watchDir = None
        self._mode = "replace"  # "replace" or "append"
        self._knownFiles = set()
        self._pendingFile = None
        self._pendingTime = 0
        self._pendingSize = -1
        self._stabilityWait = 2.0  # seconds to wait for file to be stable
        self._pollInterval = 3.0  # seconds between polls

    # ------------------------------------------------------------------ dialog

    def showDialog(self, event):
        # Pick a directory
        dirPath = commands.openFileDialog(
            True,   # directory mode
            False,  # not multiple
            False,  # not saving
            "",     # filter
            None,   # start dir
        )

        if not dirPath:
            return

        # dirPath comes back as a string or list depending on RV version
        if isinstance(dirPath, (list, tuple)):
            dirPath = dirPath[0]

        dirPath = dirPath.replace("\\", "/")

        if not os.path.isdir(dirPath):
            extra_commands.displayFeedback("Not a valid directory", 2.0)
            return

        # Ask for mode via alert panel
        result = commands.alertPanel(
            True,       # modal
            "info",     # type (ErrorAlert/InfoAlert/WarningAlert - using string)
            "Watch Directory",
            "Mode: Replace (always show newest) or Append (build sequence)?",
            "Replace",
            "Append",
            "Cancel",
        )

        # alertPanel returns 0, 1, 2 for the three buttons
        if result == 2:
            return
        elif result == 1:
            self._mode = "append"
        else:
            self._mode = "replace"

        self._watchDir = dirPath
        self._knownFiles = set()
        self._pendingFile = None

        # Scan existing files
        existing = self._scanMp4s()
        if existing:
            # Track all existing files
            self._knownFiles = set(existing)
            # Load the most recent one
            newest = existing[-1]
            self._loadFresh(newest)
            extra_commands.displayFeedback(
                "Watching: %s [%s]" % (dirPath, self._mode), 3.0
            )
        else:
            extra_commands.displayFeedback(
                "Watching (empty): %s [%s]" % (dirPath, self._mode), 3.0
            )

        # Start polling timer
        if commands.isTimerRunning():
            commands.stopTimer()
        commands.startTimer()

    # ------------------------------------------------------------------ polling

    def _scanMp4s(self):
        """Return list of .mp4 files in watch dir, sorted by mtime (oldest first)."""
        if not self._watchDir:
            return []
        pattern = os.path.join(self._watchDir, "*.mp4")
        files = glob.glob(pattern)
        files.sort(key=lambda f: os.path.getmtime(f))
        return files

    def _getNewFiles(self):
        """Return list of new .mp4 files not in _knownFiles, sorted by mtime."""
        current = self._scanMp4s()
        newFiles = [f for f in current if f.replace("\\", "/") not in self._knownFiles]
        return newFiles

    def _isFileStable(self, filepath):
        """Check if file size hasn't changed (i.e. done writing)."""
        try:
            currentSize = os.path.getsize(filepath)
        except OSError:
            return False

        if self._pendingFile != filepath:
            # First time seeing this file as pending
            self._pendingFile = filepath
            self._pendingTime = time.time()
            self._pendingSize = currentSize
            return False

        if currentSize != self._pendingSize:
            # Still changing
            self._pendingSize = currentSize
            self._pendingTime = time.time()
            return False

        # Size stable - check if enough time has passed
        if time.time() - self._pendingTime >= self._stabilityWait:
            return True

        return False

    # ------------------------------------------------------------------ loading

    def _loadFresh(self, filepath):
        """Clear session and load a single file."""
        filepath = filepath.replace("\\", "/")
        commands.clearSession()
        commands.addSources([filepath])

    def _appendToSequence(self, filepaths):
        """Append files to the current session."""
        normalized = [f.replace("\\", "/") for f in filepaths]
        commands.addSources(normalized)

    # ------------------------------------------------------------------ timer event

    def timerEvent(self, event):
        """Called by RV's timer system."""
        event.reject()

        if not self._watchDir:
            return

        newFiles = self._getNewFiles()
        if not newFiles:
            self._pendingFile = None
            return

        if self._mode == "replace":
            # Only care about the newest
            newest = newFiles[-1]
            if self._isFileStable(newest):
                self._knownFiles.add(newest.replace("\\", "/"))
                # Also add any other new files to known so we skip them
                for f in newFiles:
                    self._knownFiles.add(f.replace("\\", "/"))
                self._loadFresh(newest)
                self._pendingFile = None
                extra_commands.displayFeedback(
                    "Loaded: %s" % os.path.basename(newest), 2.0
                )

        elif self._mode == "append":
            # Check each new file for stability, load stable ones
            stableFiles = []
            for f in newFiles:
                # Quick stability check - file must exist and not be zero
                try:
                    size = os.path.getsize(f)
                    if size == 0:
                        continue
                except OSError:
                    continue

                # For append mode, use a simpler stability check:
                # file mtime must be at least stabilityWait seconds ago
                try:
                    mtime = os.path.getmtime(f)
                    if time.time() - mtime >= self._stabilityWait:
                        stableFiles.append(f)
                except OSError:
                    continue

            if stableFiles:
                for f in stableFiles:
                    self._knownFiles.add(f.replace("\\", "/"))
                self._appendToSequence(stableFiles)
                names = ", ".join(os.path.basename(f) for f in stableFiles)
                extra_commands.displayFeedback("Appended: %s" % names, 2.0)


def createMode():
    return WatchDirectoryMode()
