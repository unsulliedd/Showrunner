import QtQuick
import QtQuick.Shapes
import Showrunner

// A rounded dashed outline: the mark of a place to drop files.
Shape {
    id: frame

    property color stroke: Theme.line_strong
    property real radius: Theme.radius_lg

    preferredRendererType: Shape.CurveRenderer

    ShapePath {
        strokeColor: frame.stroke
        strokeWidth: Theme.stroke
        strokeStyle: ShapePath.DashLine
        dashPattern: [Theme.dash, Theme.dash]
        fillColor: "transparent"

        PathRectangle {
            x: Theme.stroke / 2
            y: Theme.stroke / 2
            width: frame.width - Theme.stroke
            height: frame.height - Theme.stroke
            radius: frame.radius
        }
    }
}
