import QtQuick
import QtQuick.Controls.Basic
import Showrunner

// One row of a themed menu; a checkable row shows a check mark when chosen.
MenuItem {
    id: row

    implicitHeight: Theme.row_md
    implicitWidth: Theme.menu_width

    indicator: Icon {
        x: Theme.space_md
        anchors.verticalCenter: parent.verticalCenter
        visible: row.checked
        name: "check"
        size: Theme.icon_sm
        color: Theme.control
    }

    contentItem: UiText {
        leftPadding: row.checkable ? Theme.icon_sm + Theme.space_md : 0
        text: row.text
        color: row.enabled ? Theme.ink : Theme.faint
    }

    background: Rectangle {
        radius: Theme.radius_sm
        color: row.highlighted && row.enabled ? Theme.select : "transparent"
    }
}
