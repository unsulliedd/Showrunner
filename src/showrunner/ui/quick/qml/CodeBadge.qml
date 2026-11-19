import QtQuick
import Showrunner

// A language code in a small box. `look` colours it: dropped is coral and struck through, added is mint. `changed`
// marks a code the user's choice gives the tracks, not the one they have. A `pickable` badge opens the language picker:
// by a click, or Return or Space once it has the focus (it is a tab stop of its own, apart from the chip's header).
Rectangle {
    id: badge

    property string code
    property string look: "kept"
    property bool changed: false
    property bool pickable: false
    readonly property color tone: badge.look === "dropped" ? Theme.drop
        : badge.look === "added" || badge.look === "paired" ? Theme.add
        : badge.changed ? Theme.change : Theme.ink

    signal picked()

    implicitWidth: label.implicitWidth + 2 * Theme.space_sm
    implicitHeight: Theme.pill
    radius: Theme.radius_sm
    color: badge.look === "kept" ? Theme.panel_3 : "transparent"
    border.width: Theme.stroke
    border.color: badge.activeFocus && badge.pickable ? Theme.control
        : badge.look === "dropped" ? Theme.drop
        : badge.look === "added" || badge.look === "paired" ? Theme.add
        : badge.changed ? Theme.change : Theme.panel_3
    activeFocusOnTab: pickable
    Accessible.role: pickable ? Accessible.Button : Accessible.StaticText
    Accessible.name: pickable ? Strings.f("language.change", {"code": code}) : code
    Keys.onReturnPressed: if (pickable) badge.picked()
    Keys.onEnterPressed: if (pickable) badge.picked()
    Keys.onSpacePressed: if (pickable) badge.picked()

    UiText {
        id: label

        anchors.centerIn: parent
        mono: true
        text: badge.code
        color: badge.tone
        font.pixelSize: Theme.text_xs
        font.weight: Font.DemiBold
        font.strikeout: badge.look === "dropped"
    }

    MouseArea {
        id: area

        anchors.fill: parent
        enabled: badge.pickable
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            badge.forceActiveFocus()
            badge.picked()
        }
    }

    Tip {
        visible: area.containsMouse && badge.pickable
        text: Strings.f("language.change", {"code": badge.code})
    }
}
