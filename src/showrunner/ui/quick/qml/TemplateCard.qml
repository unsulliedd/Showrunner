import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One template of the batch's profile: what it makes of the selected file and how many names it changes. A click
// opens it in the builder; an empty one keeps the names as they are and offers the suggested template.
AbstractButton {
    id: control

    required property var entry
    property bool picked: false

    objectName: "templateCard_" + entry.key
    implicitHeight: body.implicitHeight + 2 * Theme.space_lg
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: entry.label + " " + (entry.empty ? entry.stays : entry.sample + " " + entry.count_text)
    onClicked: app.pick_template(entry.key)

    background: Rectangle {
        radius: Theme.radius_lg
        color: control.picked || control.hovered ? Theme.panel_2 : Theme.panel
        border.width: Theme.stroke
        border.color: control.picked || control.visualFocus ? Theme.control : Theme.line
    }

    contentItem: Item {
        implicitHeight: body.implicitHeight

        ColumnLayout {
            id: body

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: Theme.space_lg
            anchors.rightMargin: Theme.space_lg
            anchors.verticalCenter: parent.verticalCenter
            spacing: Theme.space_sm

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space_md

                Icon {
                    name: control.entry.icon
                    size: Theme.icon_sm
                }

                UiText {
                    Layout.fillWidth: true
                    text: control.entry.label
                    font.weight: Font.DemiBold
                }

                Icon {
                    visible: control.entry.problem
                    name: "alert"
                    size: Theme.icon_sm
                    color: Theme.drop
                }
            }

            UiText {
                Layout.fillWidth: true
                mono: !control.entry.empty
                text: control.entry.empty ? control.entry.stays : control.entry.sample
                color: control.entry.empty ? Theme.faint : Theme.ink
                font.italic: control.entry.empty
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.row_sm
                visible: !control.entry.empty
                spacing: Theme.space_md

                Rectangle {
                    width: Theme.dot
                    height: Theme.dot
                    radius: width / 2
                    color: control.entry.count > 0 ? Theme.change : Theme.faint
                }

                UiText {
                    Layout.fillWidth: true
                    text: control.entry.problem ? Strings.t("names.card.problem") : control.entry.count_text
                    color: control.entry.problem ? Theme.drop : control.entry.count > 0 ? Theme.change : Theme.faint
                    font.pixelSize: Theme.text_sm
                }
            }

            ActionButton {
                objectName: "startTemplate"
                visible: control.entry.empty
                Layout.fillWidth: true
                Layout.maximumWidth: implicitWidth
                Layout.preferredHeight: Theme.row_sm
                Layout.leftMargin: -Theme.space_md
                kind: "ghost"
                size: Theme.row_sm
                iconName: "plus"
                text: Strings.t("names.suggest")
                onClicked: app.start_template(control.entry.key)
            }
        }
    }
}
