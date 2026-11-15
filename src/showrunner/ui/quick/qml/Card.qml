import QtQuick
import Showrunner

// A titled card on the home screen; rows go into `content`.
Panel {
    id: card

    property string title
    default property alias content: rows.data

    UiText {
        id: heading

        x: Theme.space_lg + Theme.space_sm
        y: Theme.space_lg + Theme.space_sm
        text: card.title
        font.weight: Font.DemiBold
    }

    Column {
        id: rows

        anchors.top: heading.bottom
        anchors.topMargin: Theme.space_lg
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: Theme.space_lg + Theme.space_sm
        anchors.rightMargin: Theme.space_lg + Theme.space_sm
        spacing: Theme.space_md
    }
}
