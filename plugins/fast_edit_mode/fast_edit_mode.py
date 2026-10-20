from rv import rvtypes, commands, extra_commands


class FastEditMode(rvtypes.MinorMode):
    "Toggle between sequence view and single source view with Ctrl+Enter"

    def __init__(self):
        rvtypes.MinorMode.__init__(self)
        self.clipMode = False
        self.init(
            "fast_edit_mode",
            [("key-down--control--enter", self.toggleClipMode, "Toggle clip/sequence view")],
            None,
        )

    def toggleClipMode(self, event):
        if self.clipMode:
            commands.setViewNode("defaultSequence")
            self.clipMode = False
            extra_commands.displayFeedback("Sequence View", 2.0)
        else:
            source = commands.sourcesAtFrame(commands.frame())[0]
            commands.setViewNode(source)
            self.clipMode = True
            extra_commands.displayFeedback("Clip View: %s" % source, 2.0)


def createMode():
    return FastEditMode()
