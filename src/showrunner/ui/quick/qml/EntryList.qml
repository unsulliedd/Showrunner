import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// A filter field over a scrolling list of (code, name, detail) rows from a Python model. It is a `ListView`, so only
// the rows on screen exist, however long the list. `selected` is the code drawn as chosen; `picked(code)` says a row
// was clicked, or reached with Up and Down and chosen with Space or Return; `filtered(text)` says the field changed.
// Down from the field moves into the list.
ColumnLayout {
    id: control

    property alias model: list.model
    property alias listName: list.objectName
    property alias fieldName: field.objectName
    property alias listHeight: frame.implicitHeight
    property string selected: ""
    property string placeholder: ""
    property string label: ""

    signal picked(string code)
    signal filtered(string text)

    // Brings the chosen row into view, for a list that opens on a pick or follows a tag that was typed.
    function showSelected() {
        const row = list.model ? list.model.row_of(selected) : -1
        if (row >= 0)
            list.positionViewAtIndex(row, ListView.Contain)
    }

    onSelectedChanged: showSelected()
    // A list that was hidden (the dialog closed, the script list folded) shows its pick when it is shown again.
    onVisibleChanged: if (visible) showSelected()

    function focusField() {
        field.forceActiveFocus()
    }

    spacing: Theme.space_sm

    InputField {
        id: field

        Layout.fillWidth: true
        label: control.label
        placeholderText: control.placeholder
        onTextEdited: control.filtered(text)
        Keys.onDownPressed: {
            list.forceActiveFocus()
            if (list.currentIndex < 0 && list.count > 0)
                list.currentIndex = 0
        }
    }

    Rectangle {
        id: frame

        Layout.fillWidth: true
        radius: Theme.radius_md
        color: Theme.well
        border.width: Theme.stroke
        border.color: list.activeFocus ? Theme.control : Theme.line

        ListView {
            id: list

            anchors.fill: parent
            anchors.margins: Theme.space_xs
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            activeFocusOnTab: true
            keyNavigationEnabled: true
            currentIndex: -1
            ScrollBar.vertical: Scroller {}
            Accessible.role: Accessible.List
            Accessible.name: control.label
            Keys.onSpacePressed: chooseCurrent()
            Keys.onReturnPressed: chooseCurrent()
            Keys.onEnterPressed: chooseCurrent()

            function chooseCurrent() {
                const item = currentItem
                if (item)
                    control.picked(item.code)
            }

            delegate: Item {
                id: line

                required property int index
                required property string code
                required property string name
                required property string detail
                readonly property bool chosen: line.code === control.selected

                objectName: "entryRow"
                width: list.width - Theme.scroll_thumb - Theme.space_sm
                height: Theme.row_sm
                Accessible.role: Accessible.ListItem
                Accessible.name: line.name + " " + line.detail
                Accessible.selected: line.chosen

                Rectangle {
                    anchors.fill: parent
                    radius: Theme.radius_sm
                    color: line.chosen ? Theme.control_soft : hover.hovered ? Theme.panel_3 : "transparent"
                    border.width: line.ListView.isCurrentItem && list.activeFocus ? Theme.stroke : 0
                    border.color: Theme.control
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space_sm
                    anchors.rightMargin: Theme.space_sm
                    spacing: Theme.space_md

                    UiText {
                        Layout.fillWidth: true
                        text: line.name
                        font.weight: line.chosen ? Font.DemiBold : Font.Normal
                    }

                    UiText {
                        text: line.detail
                        mono: true
                        color: Theme.muted
                        font.pixelSize: Theme.text_xs
                    }
                }

                HoverHandler {
                    id: hover

                    cursorShape: Qt.PointingHandCursor
                }

                TapHandler {
                    onTapped: {
                        list.currentIndex = line.index
                        control.picked(line.code)
                    }
                }
            }
        }
    }
}
