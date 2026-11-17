import QtQuick
import Showrunner

// Over the workspace while files of the open place are being read: the place dims, takes every click and wheel turn
// that lands on it, and shows how far the reading is with Cancel. The library, the top bar and Settings stay outside it.
// Keys are kept out by the parent disabling what lies beneath; Cancel takes the focus, and Escape presses it.
FocusScope {
    id: overlay

    Accessible.role: Accessible.ProgressBar
    Accessible.name: Strings.t("loading.title")
    Accessible.description: app.job_text

    onVisibleChanged: if (visible) cancel.forceActiveFocus()
    Component.onCompleted: if (visible) cancel.forceActiveFocus()
    Keys.onEscapePressed: app.cancel_reading()

    Rectangle {
        anchors.fill: parent
        color: Theme.ground
        opacity: Theme.dim_percent / 100
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        hoverEnabled: true
        onWheel: wheel => wheel.accepted = true
    }

    Rectangle {
        anchors.centerIn: parent
        width: Theme.progress_width * 2
        height: card.implicitHeight + 2 * Theme.space_xl
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong

        Column {
            id: card

            anchors.fill: parent
            anchors.margins: Theme.space_xl
            spacing: Theme.space_md

            UiText {
                width: parent.width
                text: Strings.t("loading.title")
                font.pixelSize: Theme.text_lg
                font.weight: Font.Bold
                Accessible.role: Accessible.Heading
            }

            UiText {
                objectName: "overlayText"
                width: parent.width
                text: app.job_text
                color: Theme.muted
            }

            ProgressLine {
                objectName: "overlayProgress"
                width: parent.width
                value: app.read_fraction
            }

            ActionButton {
                id: cancel

                objectName: "overlayCancel"
                anchors.right: parent.right
                kind: "outline"
                text: Strings.t("common.cancel")
                onClicked: app.cancel_reading()
            }
        }
    }
}
