import QtQuick
import Showrunner

// A language code in a small box. `state` colours it: dropped is coral and struck through, added is mint.
Rectangle {
    id: badge

    property string code
    property string look: "kept"

    implicitWidth: label.implicitWidth + 2 * Theme.space_sm
    implicitHeight: Theme.pill
    radius: Theme.radius_sm
    color: badge.look === "kept" ? Theme.panel_3 : "transparent"
    border.width: Theme.stroke
    border.color: badge.look === "dropped" ? Theme.drop : badge.look === "added" || badge.look === "paired"
                  ? Theme.add : Theme.panel_3

    UiText {
        id: label

        anchors.centerIn: parent
        mono: true
        text: badge.code
        color: badge.look === "dropped" ? Theme.drop : badge.look === "added" || badge.look === "paired"
               ? Theme.add : Theme.ink
        font.pixelSize: Theme.text_xs
        font.weight: Font.DemiBold
        font.strikeout: badge.look === "dropped"
    }
}
