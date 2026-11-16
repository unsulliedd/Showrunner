import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// The name each file gives the tracks of one chip or matrix column, one line per file, read from the controller
// when it opens. One per place: a chip's or a header's ▾ opens it under itself with `toggle`.
Popup {
    id: popup

    property int column: -1
    property var rows: []

    function toggle(anchor, id) {
        if (opened && column === id) {
            close()
            return
        }
        parent = anchor
        column = id
        rows = app.track_names(id)
        open()
    }

    objectName: "trackNames"
    y: parent ? parent.height : 0
    // Kept inside the window, so a list opened at the right edge moves left instead of being cut off.
    margins: Theme.space_md
    padding: Theme.space_sm
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

    background: Rectangle {
        radius: Theme.radius_md
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line_strong
    }

    contentItem: ListView {
        id: list

        objectName: "trackNameRows"
        implicitWidth: Theme.names_width
        implicitHeight: Math.min(contentHeight, Theme.names_height)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: popup.rows.length
        ScrollBar.vertical: Scroller {}

        delegate: UiText {
            required property int index

            width: ListView.view.width
            height: Theme.row_sm
            leftPadding: Theme.space_sm
            rightPadding: Theme.space_sm
            text: popup.rows[index]
            mono: true
        }
    }
}
