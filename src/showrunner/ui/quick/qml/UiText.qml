import QtQuick
import Showrunner

// Text in the theme's face and default size; set `mono` for file names, codes and templates.
Text {
    property bool mono: false

    color: Theme.ink
    font.family: mono ? Theme.mono : Theme.font
    font.pixelSize: mono ? Theme.text_sm : Theme.text_md
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
    renderType: Text.NativeRendering
}
