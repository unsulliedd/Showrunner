import QtQuick
import Showrunner

// The D (default) or F (forced) badge of a track. Filled when the choice sets the flag (`on`), filled and muted when the
// file has it without a choice making it so (`held`), an outline when it is neither (a toggle that is off). `tone`
// colours a filled badge that is not the ink.
Rectangle {
    id: mark

    property string flag: "default"
    property bool on: true
    property bool held: false
    property color tone: Theme.ink

    implicitWidth: Theme.icon_md
    implicitHeight: Theme.icon_md
    radius: Theme.radius_sm
    color: on ? tone : held ? Theme.muted : "transparent"
    border.width: on ? 0 : Theme.stroke
    border.color: Theme.faint

    UiText {
        anchors.centerIn: parent
        text: mark.flag === "default" ? Strings.t("tracks.default_mark") : Strings.t("tracks.forced_mark")
        color: mark.on || mark.held ? Theme.ground : Theme.faint
        font.pixelSize: Theme.text_xs
        font.weight: Font.Bold
    }
}
