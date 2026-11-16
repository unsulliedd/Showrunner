import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// Text in the theme's face and default size; set `mono` for file names, codes and templates. Text cut short by its
// width shows whole in a tooltip under the pointer.
Text {
    id: label

    property bool mono: false

    color: Theme.ink
    font.family: mono ? Theme.mono : Theme.font
    font.pixelSize: mono ? Theme.text_sm : Theme.text_md
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
    renderType: Text.NativeRendering
    ToolTip.visible: pointer.hovered
    ToolTip.text: label.text

    HoverHandler {
        id: pointer

        enabled: label.truncated
    }
}
