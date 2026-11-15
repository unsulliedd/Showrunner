import QtQuick
import Showrunner

// Typed text in the builder rail, or an empty place between chips to type some. What is typed is written when the
// field is left or Enter is pressed; the template escapes braces and brackets, so text is always taken as text.
TextInput {
    id: input

    required property var piece
    readonly property bool slot: piece.kind === "slot"

    objectName: slot ? "railSlot" : "railText"
    text: slot ? "" : piece.text
    width: Math.max(contentWidth + Theme.space_xs, slot && !activeFocus ? Theme.space_lg : Theme.space_md)
    height: Theme.row_md
    verticalAlignment: TextInput.AlignVCenter
    color: Theme.ink
    selectionColor: Theme.select
    selectedTextColor: Theme.ink
    selectByMouse: true
    activeFocusOnTab: true
    font.family: Theme.mono
    font.pixelSize: Theme.text_md
    Accessible.role: Accessible.EditableText
    Accessible.name: slot ? Strings.t("names.slot") : Strings.f("names.text", {"text": piece.text})

    onEditingFinished: {
        const at = piece.at
        const typed = text
        if (slot && typed !== "")
            Qt.callLater(() => app.rail_add_text(at, typed))
        else if (!slot && typed !== piece.text)
            Qt.callLater(() => app.rail_set_text(at, typed))
    }

    HoverHandler {
        id: hover

        cursorShape: Qt.IBeamCursor
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Theme.stroke
        visible: input.activeFocus || hover.hovered
        color: input.activeFocus ? Theme.control : Theme.line_strong
    }
}
