import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// A choice of a few values as one row of segments; each entry of `model` has a `key` and a `label`. Left and Right
// move the choice while a segment has focus. `name` names the group for screen readers.
Rectangle {
    id: group

    property var model: []
    property string current
    property string name: ""

    signal picked(string key)

    // Segments share the width evenly, so every one gets room for the longest label; without this a group that
    // does not fill its row has no width and its segments draw over one another.
    implicitWidth: {
        let widest = 0
        for (let i = 0; i < row.children.length; i++)
            widest = Math.max(widest, row.children[i].implicitContentWidth ?? 0)
        const count = model.length
        return count * (widest + 2 * Theme.space_md) + (count - 1) * row.spacing + 2 * row.anchors.margins
    }
    implicitHeight: Theme.row_lg
    radius: Theme.radius_md
    color: Theme.well
    border.width: Theme.stroke
    border.color: Theme.line
    Accessible.role: Accessible.Grouping
    Accessible.name: name

    function step(by) {
        const at = model.findIndex(entry => entry.key === current)
        const next = Math.max(0, Math.min(model.length - 1, at + by))
        if (next !== at) {
            picked(model[next].key)
            row.children[next].forceActiveFocus()
        }
    }

    RowLayout {
        id: row

        anchors.fill: parent
        anchors.margins: Theme.space_xs + Theme.stroke
        spacing: Theme.space_xs

        Repeater {
            model: group.model

            delegate: AbstractButton {
                id: segment

                required property var modelData
                readonly property bool chosen: modelData.key === group.current

                Layout.fillWidth: true
                Layout.fillHeight: true
                // Equal preferred widths split the row evenly, whatever each label's length.
                Layout.preferredWidth: 1
                text: modelData.label
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                checkable: true
                checked: chosen
                Accessible.role: Accessible.RadioButton
                Accessible.name: text
                Accessible.checked: chosen
                onClicked: group.picked(modelData.key)
                Keys.onLeftPressed: group.step(-1)
                Keys.onRightPressed: group.step(1)

                background: Rectangle {
                    radius: Theme.radius_md - Theme.space_xs
                    color: segment.chosen ? Theme.panel_3 : segment.hovered ? Theme.panel_2 : "transparent"
                    border.width: segment.visualFocus ? Theme.stroke : 0
                    border.color: Theme.control
                }

                contentItem: UiText {
                    text: segment.text
                    horizontalAlignment: Text.AlignHCenter
                    color: segment.chosen ? Theme.ink : Theme.muted
                    font.weight: segment.chosen ? Font.DemiBold : Font.Normal
                }
            }
        }
    }
}
