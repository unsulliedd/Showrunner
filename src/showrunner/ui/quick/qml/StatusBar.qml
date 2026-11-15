import QtQuick
import Showrunner

// A dot per program, found or not, and what the jobs are doing.
Item {
    implicitHeight: Theme.status_bar

    Row {
        anchors.left: parent.left
        anchors.leftMargin: Theme.space_lg + Theme.space_xs
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.space_lg

        Repeater {
            model: app.programs

            delegate: Row {
                required property var modelData

                spacing: Theme.space_sm + Theme.space_xs

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Theme.dot
                    height: Theme.dot
                    radius: Theme.dot / 2
                    color: modelData.found ? Theme.add : "transparent"
                    border.width: modelData.found ? 0 : Theme.stroke
                    border.color: Theme.faint
                }

                UiText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.status
                    color: modelData.found ? Theme.ink : Theme.faint
                    font.pixelSize: Theme.text_sm
                }
            }
        }
    }

    UiText {
        anchors.right: parent.right
        anchors.rightMargin: Theme.space_lg + Theme.space_xs
        anchors.verticalCenter: parent.verticalCenter
        text: app.job_text
        color: Theme.ink
        font.pixelSize: Theme.text_sm
    }
}
