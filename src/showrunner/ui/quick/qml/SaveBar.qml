import QtQuick
import QtQuick.Layouts
import Showrunner

// A bar saying the batch's choices are its own, with Save to profile; the built-in profile asks for a new name.
Rectangle {
    id: bar

    property string title
    property string lead
    property string action: Strings.t("profile.save_to")

    implicitHeight: content.implicitHeight + 2 * Theme.space_lg
    radius: Theme.radius_lg
    color: Theme.panel_2
    border.width: Theme.stroke
    border.color: Theme.line_strong

    RowLayout {
        id: content

        anchors.fill: parent
        anchors.leftMargin: Theme.space_xl
        anchors.rightMargin: Theme.space_lg
        spacing: Theme.space_lg

        Rectangle {
            Layout.alignment: Qt.AlignVCenter
            width: Theme.dot
            height: Theme.dot
            radius: Theme.dot / 2
            color: Theme.change
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.space_xs

            UiText {
                Layout.fillWidth: true
                text: bar.title
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }

            UiText {
                Layout.fillWidth: true
                text: bar.lead
                color: Theme.muted
                font.pixelSize: Theme.text_sm
                wrapMode: Text.WordWrap
            }
        }

        ActionButton {
            text: bar.action
            onClicked: app.profile_read_only ? saveAs.open() : app.save_profile()
        }
    }

    SaveAsPopup {
        id: saveAs
    }
}
