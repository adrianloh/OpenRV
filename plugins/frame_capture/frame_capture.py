from rv import rvtypes, commands, extra_commands
import os


class FrameCaptureMode(rvtypes.MinorMode):
    "Press s to save the current frame as PNG to Downloads"

    def saveFrame(self, event):
        f = commands.frame()
        sources = commands.sourcesAtFrame(f)
        media = commands.getStringProperty("%s.media.movie" % sources[0])
        filePath = media[0]
        baseName = os.path.basename(filePath)
        name, _ = os.path.splitext(baseName)
        outPath = "C:/Users/TTWP/Downloads/%s_frame%04d.png" % (name, f)

        extra_commands.exportCurrentFrame(outPath)
        extra_commands.displayFeedback("Saved: %s" % outPath, 2.0)

    def __init__(self):
        rvtypes.MinorMode.__init__(self)
        self.init(
            "frame_capture_mode",
            [("key-down--s", self.saveFrame, "Save current frame as PNG")],
            None,
        )


def createMode():
    return FrameCaptureMode()
