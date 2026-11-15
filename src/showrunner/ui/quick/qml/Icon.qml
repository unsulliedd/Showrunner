import QtQuick
import Showrunner

// A line icon from the icon provider, drawn in a theme color. An Item around the image, so layouts size it by
// `size` rather than by the provider's larger image.
Item {
    id: icon

    property string name
    property color color: Theme.faint
    property int size: Theme.icon_md

    implicitWidth: size
    implicitHeight: size

    Image {
        anchors.fill: parent
        sourceSize: Qt.size(icon.size, icon.size)
        source: icon.name ? "image://icon/" + icon.name + "/" + icon.color.toString().substring(1, 7) : ""
        fillMode: Image.PreserveAspectFit
        smooth: true
    }
}
