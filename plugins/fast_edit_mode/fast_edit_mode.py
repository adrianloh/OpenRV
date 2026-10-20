from bisect import bisect_right

from rv import rvtypes, commands, extra_commands


class FastEditMode(rvtypes.MinorMode):
    "Toggle between sequence view and single source view with Ctrl+Enter. JKL shuttle."

    SPEEDS = [1.0, 2.0, 4.0, 8.0]
    MIN_INT = -2**31 + 1
    MAX_INT = 2**31 - 1

    def __init__(self):
        rvtypes.MinorMode.__init__(self)
        self.clipMode = False
        self.speedIndex = 0
        self.direction = 0
        self.baseFPS = 0.0
        self.lastPrevShotTime = 0.0
        self.init(
            "fast_edit_mode",
            [
                ("key-down--i", self.setInPoint, "Set in point"),
                ("key-down--o", self.setOutPoint, "Set out point"),
                ("key-down--alt--i", self.clearInPoint, "Clear in point"),
                ("key-down--alt--o", self.clearOutPoint, "Clear out point"),
                ("key-down--alt--/", self.clearInOutPoints, "Clear and set in/out points"),
                ("key-down--shift--up", self.moveClipUp, "Move clip up"),
                ("key-down--shift--down", self.moveClipDown, "Move clip down"),
                ("key-down--/", self.clearSequenceInOutPoints, "Clear sequence in/out points"),
                ("key-down--enter", self.toggleClipMode, "Toggle clip/sequence view"),
                ("key-down--shift-- ", self.preroll, "Preroll 50 frames"),
                ("key-down--up", self.shuttleReverse, "Reverse / faster reverse"),
                ("key-down--k", self.shuttleStop, "Stop"),
                ("key-down--down", self.shuttleForward, "Play / faster forward"),
                ("key-down--control--right", self.nextShot, "Next shot"),
                ("key-down--control--left", self.prevShot, "Previous shot"),
            ],
            None,
        )

    def _getBaseFPS(self):
        if self.baseFPS == 0.0:
            self.baseFPS = commands.fps()
        return self.baseFPS

    def _applyShuttle(self, newDir):
        if newDir == self.direction and self.speedIndex < len(self.SPEEDS) - 1:
            self.speedIndex += 1
        elif newDir != self.direction:
            self.direction = newDir
            self.speedIndex = 0

        speed = self.SPEEDS[self.speedIndex]
        commands.setInc(self.direction)
        commands.setFPS(self._getBaseFPS() * speed)
        commands.play()

        label = "%dx" % int(speed) if self.direction == 1 else "-%dx" % int(speed)
        extra_commands.displayFeedback(label, 1.0)

    def shuttleForward(self, event):
        self._applyShuttle(1)

    def shuttleReverse(self, event):
        self._applyShuttle(-1)

    def shuttleStop(self, event):
        commands.stop()
        commands.setFPS(self._getBaseFPS())
        commands.setInc(1)
        self.direction = 0
        self.speedIndex = 0
        extra_commands.displayFeedback("Stop", 1.0)

    def _currentClipRange(self):
        """Return (start, end) global frames for the clip under the playhead, inclusive."""
        boundaries = self._shotBoundaries()
        if boundaries is None:
            return commands.frameStart(), commands.frameEnd()
        f = commands.frame()
        i = bisect_right(boundaries, f) - 1
        start = boundaries[i] if i >= 0 else boundaries[0]
        end = boundaries[i + 1] - 1 if (i + 1) < len(boundaries) else commands.frameEnd()
        return start, end

    def setInPoint(self, event):
        globalCutFrame, _ = self._currentClipRange()
        f = commands.frame()
        source = commands.sourcesAtFrame(f)[0]
        localFrame = extra_commands.sourceFrame(f)
        # Set cut in at current position
        commands.setIntProperty("%s.cut.in" % source, [localFrame])
        commands.setFrame(globalCutFrame-50)

    def setOutPoint(self, event):
        f = commands.frame()
        source = commands.sourcesAtFrame(f)[0]
        localFrame = extra_commands.sourceFrame(f)
        # Set cut out at current position
        commands.setIntProperty("%s.cut.out" % source, [localFrame])
        commands.setFrame(f - 50)

    def clearInPoint(self, event):
        f = commands.frame()
        source = commands.sourcesAtFrame(f)[0]
        commands.setIntProperty("%s.cut.in" % source, [self.MIN_INT])

    def clearOutPoint(self, event):
        f = commands.frame()
        source = commands.sourcesAtFrame(f)[0]
        commands.setIntProperty("%s.cut.out" % source, [self.MAX_INT])

    def clearInOutPoints(self, event):
        f = commands.frame()
        source = commands.sourcesAtFrame(f)[0]
        commands.setIntProperty("%s.cut.in" % source, [self.MIN_INT])
        commands.setIntProperty("%s.cut.out" % source, [self.MAX_INT])

    def clearSequenceInOutPoints(self, event):
        commands.setInPoint(commands.frameStart())
        commands.setOutPoint(commands.frameEnd())

    def moveClipUp(self, event):
        source = commands.sourcesAtFrame(commands.frame())[0]
        group = commands.nodeGroup(source)
        inputs = commands.nodeConnections("defaultSequence", False)[0]
        idx = inputs.index(group)
        if idx > 0:
            inputs[idx], inputs[idx - 1] = inputs[idx - 1], inputs[idx]
            commands.setNodeInputs("defaultSequence", inputs)
            self._gotoClipStart(idx - 1)
            extra_commands.displayFeedback("Moved up", 1.0)

    def moveClipDown(self, event):
        source = commands.sourcesAtFrame(commands.frame())[0]
        group = commands.nodeGroup(source)
        inputs = commands.nodeConnections("defaultSequence", False)[0]
        idx = inputs.index(group)
        if idx < len(inputs) - 1:
            inputs[idx], inputs[idx + 1] = inputs[idx + 1], inputs[idx]
            commands.setNodeInputs("defaultSequence", inputs)
            self._gotoClipStart(idx + 1)
            extra_commands.displayFeedback("Moved down", 1.0)

    def _gotoClipStart(self, clipIndex):
        # Jump playhead to the first frame of the clip at the given sequence index.
        boundaries = self._shotBoundaries()
        if boundaries is None or clipIndex >= len(boundaries):
            return
        commands.setFrame(boundaries[clipIndex])

    def preroll(self, event):
        commands.setFrame(commands.frame() - 50)
        commands.play()

    def toggleClipMode(self, event):
        if self.clipMode:
            commands.setViewNode("defaultSequence")
            self.clipMode = False
            extra_commands.displayFeedback("Sequence View", 2.0)
        else:
            source = commands.sourcesAtFrame(commands.frame())[0]
            group = commands.nodeGroup(source)
            commands.setViewNode(group)
            self.clipMode = True
            extra_commands.displayFeedback("Clip View: %s" % group, 2.0)

    def _shotBoundaries(self):
        # First frame of each shot; last frame of shot N is boundaries[N+1] - 1.
        b = extra_commands.sequenceBoundaries()
        if not b or len(b) < 2:
            return None
        return sorted(b)

    def nextShot(self, event):
        boundaries = self._shotBoundaries()
        if boundaries is None:
            return
        f = commands.frame()
        i = bisect_right(boundaries, f)
        target = boundaries[i] if i < len(boundaries) else boundaries[0]
        commands.setFrame(target)

    DOUBLE_TAP_SECONDS = 0.5

    def prevShot(self, event):
        import time
        boundaries = self._shotBoundaries()
        if boundaries is None:
            return

        now = time.monotonic()
        doubleTap = (now - self.lastPrevShotTime) < self.DOUBLE_TAP_SECONDS
        self.lastPrevShotTime = now

        f = commands.frame()
        # Greatest boundary <= f = start of the current shot.
        i = bisect_right(boundaries, f) - 1

        if i < 0:
            target = boundaries[-1]
        elif doubleTap or boundaries[i] == f:
            # Double-tap, or already on a shot start — step back one (wrap at front).
            target = boundaries[i - 1] if i > 0 else boundaries[-1]
        else:
            # Mid-shot, single tap — snap to start of current shot.
            target = boundaries[i]

        commands.setFrame(target)


def createMode():
    return FastEditMode()
