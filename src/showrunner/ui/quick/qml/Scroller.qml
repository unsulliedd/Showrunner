import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A scrollbar shown whenever its view holds more than fits. The style's own shows only while the view scrolls, so a
// long list looked as if it held nothing more.
ScrollBar {
    id: bar

    visible: bar.size < 1.0
    padding: Theme.space_xs

    contentItem: Rectangle {
        implicitWidth: Theme.scroll_thumb
        implicitHeight: Theme.scroll_thumb
        radius: width / 2
        color: bar.pressed || bar.hovered ? Theme.muted : Theme.line_strong
    }
}
