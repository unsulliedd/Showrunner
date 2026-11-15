import QtQuick
import Showrunner

// An optional part of a template: its text and tokens in a dashed frame, all left out when a token directly inside
// is empty.
Item {
    id: frame

    property var group: ({"parts": []})

    implicitWidth: parts.implicitWidth + 2 * Theme.space_sm
    implicitHeight: parts.implicitHeight + 2 * Theme.space_sm
    Accessible.role: Accessible.Grouping
    Accessible.name: Strings.t("names.optional")

    DashedFrame {
        anchors.fill: parent
        radius: Theme.radius_md
    }

    Rectangle {
        anchors.right: parent.right
        anchors.rightMargin: Theme.space_md
        anchors.verticalCenter: parent.top
        width: note.implicitWidth + 2 * Theme.space_sm
        height: note.implicitHeight
        color: Theme.panel

        UiText {
            id: note

            anchors.centerIn: parent
            text: Strings.t("names.optional")
            color: Theme.faint
            font.pixelSize: Theme.text_xs
        }
    }

    Row {
        id: parts

        x: Theme.space_sm
        y: Theme.space_sm

        Repeater {
            model: frame.group.parts

            delegate: RailPart {}
        }
    }
}
