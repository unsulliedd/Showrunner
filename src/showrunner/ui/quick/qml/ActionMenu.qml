import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// A right-click menu over a list of actions given by Python, each {key, text, enabled} and an optional tip. It only draws and says which
// action was picked; what the actions are and what they do is decided where the list comes from.
Menu {
    id: menu

    property var actions: []

    signal picked(string key)

    padding: Theme.space_sm

    background: Rectangle {
        implicitWidth: Theme.menu_width
        radius: Theme.radius_md
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    Instantiator {
        model: menu.actions

        delegate: MenuRow {
            required property var modelData

            text: modelData.text
            tip: modelData.tip || ""
            enabled: modelData.enabled
            onTriggered: menu.picked(modelData.key)
        }

        onObjectAdded: (index, object) => menu.insertItem(index, object)
        onObjectRemoved: (index, object) => menu.removeItem(object)
    }
}
