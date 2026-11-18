import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// One separator in the Tokens panel. Drag it onto the rail, or click it (Enter) to add it at the end of the template.
// It goes in as typed text, so the template holds no new kind of part.
Rectangle {
    id: chip

    required property var separator

    objectName: "separatorChip_" + separator.name
    width: Math.max(label.implicitWidth + 2 * Theme.space_lg, Theme.row_md)
    height: Theme.row_md
    radius: Theme.radius_md
    color: hover.hovered ? Theme.panel_3 : Theme.panel_2
    border.width: Theme.stroke
    border.color: chip.activeFocus ? Theme.control : Theme.line_strong
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: Strings.f("tokens.insert", {"token": separator.tip})
    Accessible.onPressAction: app.rail_append_text(separator.text)
    Keys.onReturnPressed: app.rail_append_text(separator.text)
    Keys.onEnterPressed: app.rail_append_text(separator.text)
    Keys.onSpacePressed: app.rail_append_text(separator.text)
    ToolTip.visible: hover.hovered
    ToolTip.text: Accessible.name

    HoverHandler {
        id: hover
    }

    // A tap beside the drag: a button under a DragHandler would lose its click.
    TapHandler {
        onTapped: app.rail_append_text(chip.separator.text)
    }

    UiText {
        id: label

        anchors.centerIn: parent
        mono: true
        text: chip.separator.label
        font.weight: Font.DemiBold
    }

    TokenDrag {
        name: chip.separator.name
        label: chip.separator.label
        text: chip.separator.text
    }
}
