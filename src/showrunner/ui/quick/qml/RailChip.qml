import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A token in the builder rail: its name, and for a number its format as the value it gives (a click steps through
// 1, 01, 001). Once focused (a click or Tab) it offers to leave it out when empty and to take it out; on focus
// rather than hover, so the rail does not reflow under the pointer. Drag it to move it; Delete takes it out, Ctrl
// with Left or Right moves it one place.
Rectangle {
    id: chip

    required property var token
    readonly property bool shown: chip.activeFocus || optional.activeFocus || remove.activeFocus

    objectName: "railChip_" + token.name
    implicitWidth: row.implicitWidth + 2 * Theme.space_md
    implicitHeight: Theme.row_md + Theme.space_sm
    radius: Theme.radius_md
    color: Theme.panel_3
    opacity: drag.active ? 0.4 : 1
    border.width: Theme.stroke
    border.color: chip.activeFocus ? Theme.control : token.known ? Theme.line_strong : Theme.drop
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: token.known ? Strings.f("names.chip.drag", {"token": token.label})
                                 : Strings.f("names.chip.unknown", {"token": token.label})
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace)
            app.rail_remove(token.at)
        else if (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_Left && token.at > 0)
            app.rail_move(token.at, token.at - 1)
        else if (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_Right)
            app.rail_move(token.at, token.at + 2)
        else
            return
        event.accepted = true
    }

    TapHandler {
        onTapped: chip.forceActiveFocus()
    }

    TokenDrag {
        id: drag

        name: chip.token.name
        label: chip.token.label
        from: chip.token.at
    }

    Row {
        id: row

        anchors.centerIn: parent
        spacing: Theme.space_sm

        Icon {
            anchors.verticalCenter: parent.verticalCenter
            name: "grip"
            size: Theme.icon_sm
            color: Theme.faint
        }

        UiText {
            anchors.verticalCenter: parent.verticalCenter
            text: chip.token.label
            color: chip.token.known ? Theme.ink : Theme.drop
            font.weight: Font.DemiBold
        }

        AbstractButton {
            id: format

            objectName: "chipFormat"
            anchors.verticalCenter: parent.verticalCenter
            visible: chip.token.numeric
            implicitWidth: formatText.implicitWidth + 2 * Theme.space_sm
            implicitHeight: Theme.pill
            focusPolicy: Qt.StrongFocus
            Accessible.role: Accessible.Button
            Accessible.name: Strings.f("names.chip.format", {"token": chip.token.label, "format": chip.token.format})
            onClicked: app.rail_padding(chip.token.at)

            background: Rectangle {
                radius: Theme.radius_sm
                color: Theme.control_soft
                border.width: format.visualFocus ? Theme.stroke : 0
                border.color: Theme.control
            }

            contentItem: UiText {
                id: formatText

                horizontalAlignment: Text.AlignHCenter
                mono: true
                text: chip.token.format
                color: Theme.control
                font.pixelSize: Theme.text_xs
            }
        }

        AbstractButton {
            id: optional

            objectName: "chipOptional"
            anchors.verticalCenter: parent.verticalCenter
            visible: chip.shown
            implicitWidth: Theme.row_sm
            implicitHeight: Theme.row_sm
            hoverEnabled: true
            focusPolicy: Qt.StrongFocus
            Accessible.role: Accessible.Button
            Accessible.name: Strings.t(chip.token.grouped ? "names.chip.required" : "names.chip.optional")
            ToolTip.visible: hovered
            ToolTip.text: Accessible.name
            onClicked: app.rail_optional(chip.token.at)

            background: Rectangle {
                radius: Theme.radius_sm
                color: optional.hovered ? Theme.panel_2 : "transparent"
                border.width: optional.visualFocus ? Theme.stroke : 0
                border.color: Theme.control
            }

            contentItem: Item {
                DashedFrame {
                    anchors.centerIn: parent
                    width: Theme.icon_md
                    height: Theme.icon_sm
                    radius: Theme.radius_sm
                    stroke: chip.token.grouped ? Theme.control : Theme.muted
                }
            }
        }

        IconButton {
            id: remove

            objectName: "chipRemove"
            anchors.verticalCenter: parent.verticalCenter
            visible: chip.shown
            implicitWidth: Theme.row_sm
            implicitHeight: Theme.row_sm
            iconName: "x"
            label: Strings.f("names.chip.remove", {"token": chip.token.label})
            onClicked: app.rail_remove(chip.token.at)
        }
    }
}
