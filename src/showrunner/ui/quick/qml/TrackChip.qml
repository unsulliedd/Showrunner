import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One track signature of a batch on Overview: a click keeps or drops it in every file (adds a paired file), the
// star and F set the flags. `chip` is a header from the controller.
AbstractButton {
    id: control

    required property var chip
    readonly property bool dropped: chip.state === "dropped"
    readonly property bool paired: chip.paired

    objectName: "chip" + chip.id
    implicitHeight: Theme.row_lg
    implicitWidth: row.implicitWidth + 2 * Theme.space_md
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: chip.code + " " + chip.title + " " + chip.name + " " + chip.button
    onClicked: app.toggle_keep(chip.id)

    background: Item {
        Rectangle {
            anchors.fill: parent
            visible: !control.paired
            radius: Theme.radius_md
            color: control.dropped ? Theme.drop_soft : control.hovered ? Theme.panel_3 : Theme.panel
            border.width: Theme.stroke
            border.color: control.visualFocus ? Theme.control : control.dropped ? Theme.drop : Theme.line_strong
        }

        DashedFrame {
            anchors.fill: parent
            visible: control.paired
            radius: Theme.radius_md
            stroke: control.visualFocus ? Theme.control : control.chip.state === "added" ? Theme.add : Theme.line_strong
        }
    }

    contentItem: Item {
        implicitWidth: row.implicitWidth
        implicitHeight: row.implicitHeight

        RowLayout {
            id: row

            anchors.centerIn: parent
            spacing: Theme.space_md

            Icon {
                visible: control.paired
                name: "plus"
                size: Theme.icon_sm
                color: control.chip.state === "added" ? Theme.add : Theme.faint
            }

            CodeBadge {
                code: control.chip.code
                look: control.chip.state
            }

            UiText {
                text: control.chip.title
                color: control.dropped ? Theme.drop : Theme.ink
                font.strikeout: control.dropped
                font.weight: Font.Medium
            }

            UiText {
                visible: control.chip.name !== ""
                text: control.chip.name
                color: control.dropped ? Theme.drop : Theme.muted
                font.strikeout: control.dropped
                font.pixelSize: Theme.text_sm
            }

            FlagButton {
                objectName: "defaultFlag"
                visible: !control.dropped && control.chip.flags
                flag: "default"
                on: control.chip.default
                onClicked: app.toggle_flag(control.chip.id, "default")
            }

            FlagButton {
                visible: !control.dropped && control.chip.flags && control.chip.kind === "subtitle"
                flag: "forced"
                on: control.chip.forced
                onClicked: app.toggle_flag(control.chip.id, "forced")
            }

            UiText {
                visible: control.chip.count !== ""
                text: control.chip.count
                color: Theme.change
                font.pixelSize: Theme.text_sm
            }
        }
    }
}
