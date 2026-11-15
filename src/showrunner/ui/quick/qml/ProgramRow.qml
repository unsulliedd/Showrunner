import QtQuick
import Showrunner

// A program on the home screen: found with its version, or a way to get it.
Item {
    id: entry

    required property var modelData
    readonly property bool found: modelData.found
    readonly property bool checking: modelData.state === "checking"

    width: parent ? parent.width : 0
    height: Theme.row_lg + Theme.space_xs

    Rectangle {
        id: mark

        anchors.verticalCenter: parent.verticalCenter
        width: Theme.icon_lg + Theme.space_xs
        height: width
        radius: width / 2
        color: entry.found ? Theme.add_soft : "transparent"
        border.width: entry.found ? 0 : Theme.stroke
        border.color: Theme.line_strong

        Icon {
            anchors.centerIn: parent
            visible: entry.found
            name: "check"
            size: Theme.icon_sm
            color: Theme.add
        }
    }

    Column {
        anchors.left: mark.right
        anchors.leftMargin: Theme.space_lg
        anchors.right: side.left
        anchors.rightMargin: Theme.space_md
        anchors.verticalCenter: parent.verticalCenter

        UiText {
            width: parent.width
            text: entry.modelData.name
            color: entry.found ? Theme.ink : Theme.muted
            font.weight: Font.Medium
        }

        UiText {
            width: parent.width
            text: entry.modelData.about
            color: Theme.faint
            font.pixelSize: Theme.text_sm
        }
    }

    Item {
        id: side

        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: get.visible ? get.implicitWidth : version.implicitWidth
        height: get.implicitHeight

        UiText {
            id: version

            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            visible: !get.visible
            text: entry.checking ? Strings.t("program.checking") : entry.modelData.version
            color: Theme.muted
            font.pixelSize: Theme.text_sm
        }

        ActionButton {
            id: get

            anchors.right: parent.right
            visible: !entry.found && !entry.checking
            kind: "outline"
            text: Strings.t("home.get")
            Accessible.name: Strings.f("home.get_named", { name: entry.modelData.name })
            onClicked: app.get_program(entry.modelData.id)
        }
    }
}
