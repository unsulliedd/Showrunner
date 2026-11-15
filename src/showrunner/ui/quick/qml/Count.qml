import QtQuick
import Showrunner

// A count in a small pill: amber for the changes a place plans, neutral for a plain number of things.
Rectangle {
    id: pill

    property int value: 0
    property bool change: true

    implicitWidth: Math.max(label.implicitWidth + 2 * Theme.space_sm + Theme.space_xs, height)
    implicitHeight: Theme.text_md + Theme.space_sm + Theme.space_xs
    radius: Theme.radius_sm
    color: change ? Theme.change_soft : Theme.panel_3

    UiText {
        id: label

        anchors.centerIn: parent
        text: pill.value
        color: pill.change ? Theme.change : Theme.muted
        font.pixelSize: Theme.text_xs
        font.weight: Font.DemiBold
    }
}
