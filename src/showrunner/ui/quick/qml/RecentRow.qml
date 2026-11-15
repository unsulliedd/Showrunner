import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A folder opened before: its name and how long ago; a click reads it again.
AbstractButton {
    id: entry

    required property var modelData

    width: parent ? parent.width : 0
    height: Theme.row_lg + Theme.space_xs
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: modelData.name
    onClicked: app.open_recent(modelData.path)

    background: Rectangle {
        x: -Theme.space_sm
        width: parent.width + 2 * Theme.space_sm
        radius: Theme.radius_md
        color: entry.hovered ? Theme.panel_2 : "transparent"
        border.width: entry.visualFocus ? Theme.stroke : 0
        border.color: Theme.control
    }

    contentItem: Item {
        Icon {
            id: folder

            anchors.verticalCenter: parent.verticalCenter
            name: "folder"
        }

        UiText {
            anchors.left: folder.right
            anchors.leftMargin: Theme.space_lg
            anchors.right: when.left
            anchors.rightMargin: Theme.space_md
            anchors.verticalCenter: parent.verticalCenter
            text: entry.modelData.name
            font.weight: Font.Medium
        }

        UiText {
            id: when

            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: entry.modelData.when
            color: Theme.muted
            font.pixelSize: Theme.text_sm
        }
    }
}
