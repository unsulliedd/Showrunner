import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// A small "?" that opens a card with a title, a plain explanation and a worked example for `topic` (a key of the help
// topics in Python). It opens on a click, Return or Space and never on hover alone; Escape or a press outside it
// closes the card, and the button itself toggles it.
AbstractButton {
    id: control

    required property string topic
    readonly property var help: Strings.topic(topic)
    readonly property bool shown: card.visible

    implicitWidth: Theme.help_chip
    implicitHeight: Theme.help_chip
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.role: Accessible.Button
    Accessible.name: help.name
    onClicked: shown ? card.close() : card.open()
    Keys.onReturnPressed: control.clicked()
    Keys.onEnterPressed: control.clicked()

    background: Rectangle {
        radius: width / 2
        color: control.shown ? Theme.control_soft : control.hovered ? Theme.panel_3 : "transparent"
        border.width: Theme.stroke
        border.color: control.visualFocus || control.shown ? Theme.control : Theme.line_strong
    }

    contentItem: UiText {
        horizontalAlignment: Text.AlignHCenter
        text: Strings.t("help.mark")
        color: control.shown ? Theme.control : Theme.muted
        font.pixelSize: Theme.text_xs
        font.weight: Font.Bold
    }

    Popup {
        id: card

        y: control.height + Theme.space_sm
        width: Theme.help_width
        margins: Theme.space_lg
        padding: Theme.space_xl
        focus: true
        // Outside the button only: a press on the button is its own toggle, not a close followed by a reopen.
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            radius: Theme.radius_lg
            color: Theme.panel_2
            border.width: Theme.stroke
            border.color: Theme.line_strong
        }

        contentItem: ColumnLayout {
            spacing: Theme.space_lg
            Accessible.role: Accessible.Pane
            Accessible.name: control.help.title

            UiText {
                Layout.fillWidth: true
                text: control.help.title
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
                Accessible.role: Accessible.Heading
            }

            UiText {
                objectName: "helpExplanation"
                Layout.fillWidth: true
                text: control.help.explanation
                wrapMode: Text.WordWrap
                elide: Text.ElideNone
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: example.implicitHeight + 2 * Theme.space_lg
                radius: Theme.radius_md
                color: Theme.well
                border.width: Theme.stroke
                border.color: Theme.line

                ColumnLayout {
                    id: example

                    anchors.fill: parent
                    anchors.margins: Theme.space_lg
                    spacing: Theme.space_sm

                    UiText {
                        Layout.fillWidth: true
                        text: control.help.example_label
                        color: Theme.muted
                        font.pixelSize: Theme.text_xs
                        font.weight: Font.Bold
                    }

                    UiText {
                        objectName: "helpExample"
                        Layout.fillWidth: true
                        text: control.help.example
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                    }
                }
            }
        }
    }
}
