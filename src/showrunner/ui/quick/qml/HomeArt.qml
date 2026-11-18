import QtQuick
import Showrunner

// The drawing beside the home screen's title: a folder with an arrow going down into it, a line drawing in the icon
// set's style that takes the control color while something is held over the window.
Item {
    id: art

    property bool active: false

    implicitWidth: Theme.home_art_width
    implicitHeight: Theme.home_art_width

    Icon {
        anchors.fill: parent
        name: "drop"
        size: Math.round(art.width)
        color: art.active ? Theme.control : Theme.muted
    }
}
