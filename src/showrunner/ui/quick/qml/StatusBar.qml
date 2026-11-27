import QtQuick
import Showrunner

// A dot per program the plans use, found or not, and what the jobs are doing. A click on the programs, or Refresh in
// their menu, checks them all again.
Item {
    implicitHeight: Theme.status_bar

    MouseArea {
        objectName: "programsArea"
        anchors.fill: programs
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        cursorShape: Qt.PointingHandCursor
        Accessible.role: Accessible.Button
        Accessible.name: Strings.t("programs.tip")
        onClicked: mouse => {
            if (mouse.button === Qt.RightButton)
                programsMenu.popup()
            else
                app.refresh_programs()
        }
    }

    ActionMenu {
        id: programsMenu

        objectName: "programsMenu"
        actions: [{ key: "refresh", text: Strings.t("programs.refresh"), enabled: true }]
        onPicked: app.refresh_programs()
    }

    Row {
        id: programs

        anchors.left: parent.left
        anchors.leftMargin: Theme.space_lg + Theme.space_xs
        anchors.verticalCenter: parent.verticalCenter
        // In a narrow window the jobs' side keeps its room; each program's tip still says it in full.
        width: Math.min(implicitWidth, jobs.x - x - Theme.space_lg)
        clip: true
        spacing: Theme.space_lg

        Repeater {
            model: app.status_programs

            delegate: Row {
                required property var modelData

                spacing: Theme.space_sm + Theme.space_xs

                HoverHandler {
                    id: hover
                }

                // Opens after a pause: a tip that opened as the pointer passed would take the press that closes
                // another popup, such as an open help card.
                Tip {
                    visible: hover.hovered
                    delay: 600
                    y: -height - Theme.space_xs
                    text: modelData.tip
                }

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

    // While folders are read: what is read of how many, a bar and Cancel. Otherwise what the jobs are doing.
    Row {
        id: jobs

        anchors.right: parent.right
        anchors.rightMargin: Theme.space_lg + Theme.space_xs
        anchors.verticalCenter: parent.verticalCenter
        spacing: Theme.space_md

        UiText {
            objectName: "jobText"
            anchors.verticalCenter: parent.verticalCenter
            text: app.busy ? app.job_text : app.jobs.status || app.job_text
            color: Theme.ink
            font.pixelSize: Theme.text_sm
        }

        ProgressLine {
            objectName: "readProgress"
            anchors.verticalCenter: parent.verticalCenter
            visible: app.busy
            width: Theme.progress_width
            value: app.read_fraction
        }

        ActionButton {
            objectName: "cancelReading"
            anchors.verticalCenter: parent.verticalCenter
            visible: app.busy
            kind: "ghost"
            size: Theme.row_sm
            text: Strings.t("common.cancel")
            onClicked: app.cancel_reading()
        }
    }
}
