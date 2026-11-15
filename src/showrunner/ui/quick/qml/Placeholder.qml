import QtQuick
import Showrunner

// What a place shows until the step that fills it: an icon, a title and a line under it, centred.
Item {
    id: holder

    property string iconName: ""
    property string title: ""
    property string lead: ""

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * Theme.space_xl, Theme.home_text_width)
        spacing: Theme.space_md

        Icon {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: holder.iconName !== ""
            name: holder.iconName
            size: Theme.icon_lg
            color: Theme.line_strong
        }

        UiText {
            width: parent.width
            visible: holder.title !== ""
            horizontalAlignment: Text.AlignHCenter
            text: holder.title
            color: Theme.muted
            font.weight: Font.Medium
        }

        UiText {
            width: parent.width
            visible: holder.lead !== ""
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: holder.lead
            color: Theme.faint
            font.pixelSize: Theme.text_sm
        }
    }
}
