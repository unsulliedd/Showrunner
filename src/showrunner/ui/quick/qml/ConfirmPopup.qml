import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// A question with a yes and a no, over a dimmed window. Escape answers no; `danger` colours the yes for a delete.
Popup {
    id: popup

    property string heading: ""
    property string text: ""
    property string yes: ""
    property string no: Strings.t("common.cancel")
    property bool danger: false
    property bool answered: false

    signal accepted()
    signal rejected()

    anchors.centerIn: Overlay.overlay
    width: Theme.dialog_width / 2 + Theme.space_2xl * 2
    padding: Theme.space_xl
    modal: true
    focus: true
    closePolicy: Popup.CloseOnEscape
    onAboutToShow: answered = false
    onOpened: yesButton.forceActiveFocus()
    // Escape closes the popup without a button; that is a no.
    onClosed: if (!answered) rejected()

    function answer(go) {
        answered = true
        close()
        if (go)
            accepted()
        else
            rejected()
    }

    Overlay.modal: Rectangle {
        color: Theme.ground
        opacity: Theme.dim_percent / 100  // the window stays readable behind the question
    }

    background: Rectangle {
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    contentItem: ColumnLayout {
        spacing: Theme.space_lg

        UiText {
            Layout.fillWidth: true
            text: popup.heading
            font.pixelSize: Theme.text_lg
            font.weight: Font.Bold
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
            Accessible.role: Accessible.Heading
        }

        UiText {
            Layout.fillWidth: true
            text: popup.text
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }

        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: Theme.space_md

            ActionButton {
                kind: "ghost"
                text: popup.no
                onClicked: popup.answer(false)
            }

            ActionButton {
                id: yesButton

                objectName: "confirmYes"
                kind: popup.danger ? "outline" : "primary"
                text: popup.yes
                onClicked: popup.answer(true)
            }
        }
    }
}
