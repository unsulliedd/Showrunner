import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A separator in the builder rail: one character that knows on which sides of it the template's join goes. Drag it
// to move it; Delete or a middle click takes it out, Ctrl with Left or Right moves it one place.
Rectangle {
    id: chip

    required property var separator

    objectName: "railSeparator"
    implicitWidth: Math.max(label.implicitWidth + 2 * Theme.space_md, Theme.row_md)
    implicitHeight: Theme.row_md + Theme.space_sm
    radius: Theme.radius_md
    color: Theme.panel_3
    opacity: drag.active ? 0.4 : 1
    border.width: Theme.stroke
    border.color: chip.activeFocus ? Theme.control : Theme.line_strong
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: Strings.f("names.separator.drag", {"separator": separator.text})
    ToolTip.visible: hover.hovered
    ToolTip.text: Accessible.name
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Delete || event.key === Qt.Key_Backspace)
            app.rail_remove(separator.at)
        else if (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_Left && separator.at > 0)
            app.rail_move(separator.at, separator.at - 1)
        else if (event.modifiers & Qt.ControlModifier && event.key === Qt.Key_Right)
            app.rail_move(separator.at, separator.at + 2)
        else
            return
        event.accepted = true
    }

    HoverHandler {
        id: hover
    }

    TapHandler {
        onTapped: chip.forceActiveFocus()
    }

    TapHandler {
        acceptedButtons: Qt.MiddleButton
        onTapped: app.rail_remove(chip.separator.at)
    }

    TokenDrag {
        id: drag

        name: chip.separator.text
        label: chip.separator.text
        from: chip.separator.at
    }

    UiText {
        id: label

        anchors.centerIn: parent
        mono: true
        text: chip.separator.text
        font.weight: Font.DemiBold
    }
}
