import QtQuick
import Showrunner

// One token in the Tokens panel with its value on the selected file. Drag it onto the rail, or click it (Enter) to
// add it at the end of the template. Its button opens it in the editor: a custom token whole, a built-in one for
// its value map.
Item {
    id: entry

    required property var token

    implicitHeight: Theme.row_lg

    Rectangle {
        id: chip

        objectName: "tokenChip_" + entry.token.name
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: label.implicitWidth + Theme.icon_sm + 3 * Theme.space_md
        height: Theme.row_md
        radius: Theme.radius_md
        color: hover.hovered ? Theme.panel_3 : Theme.panel_2
        border.width: Theme.stroke
        border.color: chip.activeFocus ? Theme.control : Theme.line_strong
        activeFocusOnTab: true
        Accessible.role: Accessible.Button
        Accessible.name: Strings.f("tokens.insert", {"token": entry.token.label})
        Accessible.onPressAction: app.rail_append(entry.token.name)
        Keys.onReturnPressed: app.rail_append(entry.token.name)
        Keys.onEnterPressed: app.rail_append(entry.token.name)
        Keys.onSpacePressed: app.rail_append(entry.token.name)

        HoverHandler {
            id: hover
        }

        // A tap beside the drag: a button under a DragHandler would lose its click.
        TapHandler {
            onTapped: app.rail_append(entry.token.name)
        }

        Row {
            anchors.centerIn: parent
            spacing: Theme.space_sm

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                name: "grip"
                size: Theme.icon_sm
                color: Theme.faint
            }

            UiText {
                id: label

                anchors.verticalCenter: parent.verticalCenter
                text: entry.token.label
                font.weight: Font.DemiBold
            }
        }

        TokenDrag {
            name: entry.token.name
            label: entry.token.label
        }
    }

    IconButton {
        id: edit

        anchors.left: chip.right
        anchors.leftMargin: Theme.space_sm
        anchors.verticalCenter: parent.verticalCenter
        implicitWidth: Theme.row_sm
        implicitHeight: Theme.row_sm
        iconName: "sliders"
        label: Strings.f("tokens.edit", {"token": entry.token.label})
        // A built-in token opens for its value map only.
        onClicked: entry.token.index >= 0 ? app.edit_token(entry.token.index) : app.edit_builtin(entry.token.name)
    }

    UiText {
        anchors.right: parent.right
        anchors.left: edit.right
        anchors.leftMargin: Theme.space_md
        anchors.verticalCenter: parent.verticalCenter
        horizontalAlignment: Text.AlignRight
        mono: true
        text: entry.token.value
        color: Theme.muted
    }
}
