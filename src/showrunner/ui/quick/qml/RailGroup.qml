import QtQuick
import Showrunner

// An optional part of a template: its text and tokens in a dashed frame, all left out when a token directly inside
// is empty.
Item {
    id: frame

    property var group: ({"parts": []})

    // At least as wide as the note on its top edge, so a group of one short token does not leave the note hanging
    // past the frame's corners.
    implicitWidth: Math.max(parts.implicitWidth + 2 * Theme.space_sm, label.width + 2 * Theme.space_md)
    implicitHeight: parts.implicitHeight + 2 * Theme.space_sm
    Accessible.role: Accessible.Grouping
    Accessible.name: Strings.t("names.optional")

    DashedFrame {
        anchors.fill: parent
        radius: Theme.radius_md
    }

    Rectangle {
        id: label

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

        x: (frame.width - width) / 2
        y: Theme.space_sm

        Repeater {
            model: frame.group.parts

            delegate: RailPart {}
        }
    }
}
