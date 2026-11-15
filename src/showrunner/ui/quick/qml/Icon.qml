import QtQuick
import Showrunner

// A line icon from the icon provider, drawn in a theme color.
Image {
    id: icon

    property string name
    property color color: Theme.faint
    property int size: Theme.icon_md

    width: size
    height: size
    sourceSize: Qt.size(size, size)
    source: name ? "image://icon/" + name + "/" + color.toString().substring(1, 7) : ""
    fillMode: Image.PreserveAspectFit
    smooth: true
}
