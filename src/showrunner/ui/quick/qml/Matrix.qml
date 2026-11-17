import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The track matrix of the Tracks place: files down, track signatures across, audio then subtitles. A column's
// header keeps or drops it in every file and sets its flags; a cell shows what the plans leave in that file. The
// columns stand in the order of the tracks in the new files: a column's grip drags it, or moves it with Ctrl+Left and
// Ctrl+Right, among the columns of its kind.
Item {
    id: matrix

    // Read once: each read of the property converts the whole batch view for QML.
    readonly property var view: app.matrix
    readonly property var headers: view.headers
    readonly property var rows: view.rows
    // The column a grip drags and how many places it has gone, for the line that shows where it lands.
    property int dragFrom: -1
    property int dragPlaces: 0

    TrackNames {
        id: trackNames
    }

    component Cell: Item {
        id: cell

        required property var value

        width: Theme.matrix_column
        height: Theme.list_row

        Row {
            anchors.centerIn: parent
            spacing: Theme.space_xs
            visible: !cell.value.fallback

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                visible: cell.value.state === "kept" && !cell.value.default && !cell.value.forced
                width: Theme.dot
                height: Theme.dot
                radius: Theme.dot / 2
                color: Theme.ink
            }

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                visible: cell.value.state === "dropped"
                name: "x"
                size: Theme.icon_sm
                color: Theme.drop
            }

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                visible: cell.value.state === "added"
                name: "plus"
                size: Theme.icon_sm
                color: Theme.add
            }

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                visible: cell.value.default
                name: "star_on"
                size: Theme.icon_sm
                color: Theme.change
            }

            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                visible: cell.value.forced
                width: Theme.icon_md
                height: Theme.icon_md
                radius: Theme.radius_sm
                color: Theme.ink

                UiText {
                    anchors.centerIn: parent
                    text: Strings.t("tracks.forced_mark")
                    color: Theme.ground
                    font.pixelSize: Theme.text_xs
                    font.weight: Font.Bold
                }
            }

            UiText {
                anchors.verticalCenter: parent.verticalCenter
                visible: cell.value.state === "missing" || cell.value.state === "paired"
                text: Strings.t("matrix.missing_mark")
                color: Theme.line_strong
            }
        }

        Rectangle {
            anchors.centerIn: parent
            visible: cell.value.fallback
            width: fallback.implicitWidth + 2 * Theme.space_sm
            height: Theme.pill
            radius: Theme.radius_sm
            color: Theme.change_soft
            border.width: Theme.stroke
            border.color: Theme.change

            Row {
                id: fallback

                anchors.centerIn: parent
                spacing: Theme.space_xs

                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    name: "star_on"
                    size: Theme.icon_sm - Theme.space_xs
                    color: Theme.change
                }

                UiText {
                    anchors.verticalCenter: parent.verticalCenter
                    text: Strings.t("matrix.fallback")
                    color: Theme.change
                    font.pixelSize: Theme.text_xs
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    component Header: Item {
        id: head

        required property var column
        property TrackNames names: null
        readonly property alias grip: grip

        signal moveBy(int places)

        width: Theme.matrix_column
        height: Theme.matrix_header
        z: grip.active ? 1 : 0
        transform: Translate {
            x: grip.offset
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: Theme.space_xs
            radius: Theme.radius_md
            color: head.column.state === "dropped" ? Theme.drop_soft : grip.active ? Theme.panel_2 : "transparent"
            border.width: grip.active ? Theme.stroke : 0
            border.color: Theme.control
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.space_sm
            spacing: Theme.space_xs

            Row {
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.space_xs

                Grip {
                    id: grip

                    objectName: "columnGrip"
                    anchors.verticalCenter: parent.verticalCenter
                    visible: head.column.movable
                    step: Theme.matrix_column
                    label: Strings.f("tracks.order.column", {"track": head.column.code + " " + head.column.title})
                    onActiveChanged: {
                        matrix.dragFrom = active ? head.column.id : -1
                        matrix.dragPlaces = 0
                    }
                    onPlacesChanged: if (active) matrix.dragPlaces = places
                    onMoved: places => head.moveBy(places)
                }

                CodeBadge {
                    anchors.verticalCenter: parent.verticalCenter
                    code: head.column.code
                    look: head.column.state
                }
            }

            UiText {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: head.column.title
                color: head.column.state === "dropped" ? Theme.drop : Theme.ink
                font.pixelSize: Theme.text_sm
                font.strikeout: head.column.state === "dropped"
                wrapMode: Text.WordWrap
                maximumLineCount: 2
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 0

                UiText {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: head.column.name
                    color: Theme.muted
                    font.pixelSize: Theme.text_xs
                }

                IconButton {
                    id: headNames

                    objectName: "namesButton"
                    visible: head.column.names && head.names !== null
                    implicitWidth: Theme.pill
                    implicitHeight: Theme.pill
                    iconName: "down"
                    label: Strings.t("tracks.names.open")
                    active: head.names !== null && head.names.opened && head.names.column === head.column.id
                    onClicked: head.names.toggle(headNames, head.column.id)
                }
            }

            PlaceMark {
                objectName: "placeMark"
                Layout.fillWidth: true
                // Kept in the layout while empty, so the toggles below stand at the same height in every column.
                visible: true
                horizontalAlignment: Text.AlignHCenter
                choice: head.column
                brief: true
            }

            Row {
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.space_xs
                opacity: head.column.state === "dropped" || !head.column.flags ? 0 : 1

                FlagButton {
                    side: Theme.pill
                    flag: "default"
                    on: head.column.default
                    enabled: parent.opacity > 0
                    onClicked: app.toggle_flag(head.column.id, "default")
                }

                FlagButton {
                    visible: head.column.kind === "subtitle"
                    side: Theme.pill
                    flag: "forced"
                    on: head.column.forced
                    enabled: parent.opacity > 0
                    onClicked: app.toggle_flag(head.column.id, "forced")
                }
            }

            AbstractButton {
                id: keep

                Layout.fillWidth: true
                Layout.preferredHeight: Theme.row_sm
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: [head.column.code, head.column.title, head.column.button,
                                  head.column.from || head.column.over || ""].join(" ")
                onClicked: app.toggle_keep(head.column.id)

                readonly property color tone: head.column.state === "dropped" ? Theme.drop
                                            : head.column.state === "added" ? Theme.add
                                            : head.column.state === "paired" ? Theme.faint : Theme.ink

                background: Rectangle {
                    radius: Theme.radius_sm
                    color: head.column.state === "dropped" ? Theme.drop_soft
                         : head.column.state === "added" ? Theme.add_soft
                         : keep.hovered ? Theme.panel_3 : Theme.panel_2
                    border.width: Theme.stroke
                    border.color: keep.visualFocus ? Theme.control
                                : head.column.state === "kept" || head.column.state === "paired" ? Theme.line_strong
                                : keep.tone
                }

                contentItem: UiText {
                    horizontalAlignment: Text.AlignHCenter
                    text: head.column.button
                    color: keep.tone
                    font.pixelSize: Theme.text_sm
                    font.weight: Font.Medium
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        // A ListView creates a row only as it scrolls into view, so a whole show does not build every row and cell.
        // The rows are one Tab stop, `rowKeys` (drawn over the list, after the header's buttons in the focus order),
        // since Tab can only reach rows that exist. Up, Down, Home and End move `currentIndex`; Enter focuses the file.
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ListView {
                id: scroll

                anchors.fill: parent
                objectName: "matrixRows"
                clip: true
                // The matrix stays put while a column is dragged, so the drag moves the column, not the view.
                interactive: matrix.dragFrom < 0
                contentWidth: Theme.matrix_label + matrix.headers.length * Theme.matrix_column
                flickableDirection: Flickable.AutoFlickIfNeeded
                boundsBehavior: Flickable.StopAtBounds
                // A count, not the rows: new rows of the same batch then update the delegates in place, so the view
                // keeps its scroll position after a choice.
                model: matrix.rows.length
                // Another batch starts at the top, even with as many rows as the last one.
                readonly property string firstPath: matrix.rows.length > 0 ? matrix.rows[0].path : ""
                onFirstPathChanged: {
                    positionViewAtBeginning()
                    currentIndex = 0
                }
                ScrollBar.vertical: Scroller {}
                ScrollBar.horizontal: Scroller {}

                // Scrolls sideways just enough to show column `at`, so a column moved by keyboard stays in view.
                function showColumn(at) {
                    const left = Theme.matrix_label + at * Theme.matrix_column
                    if (left < contentX)
                        contentX = left
                    else if (left + Theme.matrix_column > contentX + width)
                        contentX = Math.min(left + Theme.matrix_column - width, contentWidth - width)
                }

                header: Column {
                    Row {
                        Item {
                            width: Theme.matrix_label
                            height: Theme.row_sm
                        }

                        Repeater {
                            model: [
                                {"kind": "audio", "icon": "audio"},
                                {"kind": "subtitle", "icon": "subs"}
                            ]

                            delegate: Item {
                                id: group

                                required property var modelData
                                readonly property int span: matrix.headers.filter(h => h.kind === modelData.kind).length

                                visible: span > 0
                                width: span * Theme.matrix_column
                                height: Theme.row_sm

                                Row {
                                    x: Theme.space_md
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: Theme.space_sm

                                    Icon {
                                        anchors.verticalCenter: parent.verticalCenter
                                        name: group.modelData.icon
                                        size: Theme.icon_sm
                                    }

                                    UiText {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: Strings.t("matrix.group." + group.modelData.kind)
                                        color: Theme.faint
                                        font.pixelSize: Theme.text_xs
                                        font.weight: Font.DemiBold
                                        font.letterSpacing: Theme.stroke
                                    }
                                }

                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.leftMargin: Theme.space_md
                                    anchors.bottom: parent.bottom
                                    height: Theme.stroke
                                    color: Theme.line
                                }
                            }
                        }
                    }

                    Row {
                        Item {
                            width: Theme.matrix_label
                            height: Theme.matrix_header

                            Column {
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: Theme.space_md
                                spacing: Theme.space_xs

                                UiText {
                                    text: Strings.n("matrix.files", matrix.rows.length)
                                    font.weight: Font.Medium
                                }

                                UiText {
                                    text: Strings.t("matrix.video_kept")
                                    color: Theme.faint
                                    font.pixelSize: Theme.text_xs
                                }
                            }
                        }

                        Repeater {
                            id: heads

                            // A count, not the headers: a move then updates the headers in place, and the focus can
                            // follow the moved column to its new place.
                            model: matrix.headers.length

                            delegate: Header {
                                required property int index

                                column: matrix.headers[index]
                                names: trackNames
                                onMoveBy: places => {
                                    const focused = grip.activeFocus
                                    const at = app.move_track(index, index + places)
                                    if (focused) {
                                        heads.itemAt(at).grip.forceActiveFocus()
                                        scroll.showColumn(at)
                                    }
                                }
                            }
                        }
                    }
                }

                delegate: AbstractButton {
                    id: line

                    objectName: "matrixRow"
                    required property int index
                    readonly property var modelData: matrix.rows[index]
                    readonly property bool focused: modelData.path === app.focus_path
                    // The row the arrow keys are on, marked like the focus of the other lists while the rows have it.
                    readonly property bool marked: rowKeys.activeFocus && ListView.isCurrentItem

                    width: Theme.matrix_label + matrix.headers.length * Theme.matrix_column
                    height: Theme.list_row
                    hoverEnabled: true
                    focusPolicy: Qt.NoFocus
                    Accessible.role: Accessible.Button
                    Accessible.name: modelData.title
                    onClicked: {
                        rowKeys.forceActiveFocus()  // first: gaining the focus moves the current row to the focused file
                        scroll.currentIndex = index
                        app.focus_file(modelData.path)
                    }

                    background: Rectangle {
                        color: line.focused ? Theme.select : line.hovered ? Theme.panel_2 : "transparent"
                        border.width: line.marked ? Theme.stroke : 0
                        border.color: Theme.control

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: Theme.stroke
                            color: Theme.line
                        }
                    }

                    contentItem: Row {
                        Row {
                            width: Theme.matrix_label
                            height: Theme.list_row
                            spacing: Theme.space_md

                            UiText {
                                anchors.verticalCenter: parent.verticalCenter
                                mono: true
                                text: line.modelData.number
                                color: Theme.faint
                            }

                            UiText {
                                anchors.verticalCenter: parent.verticalCenter
                                width: Theme.matrix_label - Theme.row_md
                                text: line.modelData.title
                            }
                        }

                        Repeater {
                            model: line.modelData.cells

                            delegate: Cell {
                                required property var modelData

                                value: modelData
                            }
                        }
                    }
                }
            }

            // Where the dragged column lands: the edge of the column whose place it takes.
            Rectangle {
                readonly property var dragged: matrix.dragFrom >= 0 ? matrix.headers[matrix.dragFrom] : null
                readonly property int first: dragged ? matrix.headers.findIndex(h => h.kind === dragged.kind) : 0
                readonly property int last: dragged
                                            ? first + matrix.headers.filter(h => h.kind === dragged.kind).length - 1 : 0
                readonly property int to: dragged
                                          ? Math.max(first, Math.min(last, matrix.dragFrom + matrix.dragPlaces)) : -1
                readonly property int edge: to > matrix.dragFrom ? to + 1 : to

                objectName: "orderLine"
                visible: dragged !== null && to !== matrix.dragFrom
                x: Theme.matrix_label + edge * Theme.matrix_column - scroll.contentX - width / 2
                y: Theme.row_sm
                z: 2
                width: 3 * Theme.stroke
                height: parent.height - y
                radius: width / 2
                color: Theme.control
            }

            Item {
                id: rowKeys

                objectName: "matrixRowKeys"
                anchors.fill: parent
                activeFocusOnTab: true
                Accessible.role: Accessible.List
                Accessible.name: Strings.n("matrix.files", matrix.rows.length)
                onActiveFocusChanged: {
                    if (activeFocus) {
                        const at = matrix.rows.findIndex(r => r.path === app.focus_path)
                        scroll.currentIndex = at >= 0 ? at : Math.min(scroll.currentIndex, matrix.rows.length - 1)
                    }
                }
                Keys.onPressed: event => {
                    const last = matrix.rows.length - 1
                    const to = {
                        [Qt.Key_Up]: scroll.currentIndex - 1,
                        [Qt.Key_Down]: scroll.currentIndex + 1,
                        [Qt.Key_Home]: 0,
                        [Qt.Key_End]: last
                    }[event.key]
                    if (to !== undefined) {
                        scroll.currentIndex = Math.max(0, Math.min(last, to))
                        if (scroll.currentIndex === 0) {
                            scroll.positionViewAtBeginning()  // keeps the header in view
                        } else {
                            scroll.positionViewAtIndex(scroll.currentIndex, ListView.Contain)
                        }
                        event.accepted = true
                    } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && last >= 0) {
                        app.focus_file(matrix.rows[scroll.currentIndex].path)
                        event.accepted = true
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_xl

            Flow {
                Layout.fillWidth: true
                spacing: Theme.space_xl

                Repeater {
                    model: ["kept", "dropped", "added", "default", "forced", "missing", "fallback"]

                    delegate: Row {
                        required property string modelData

                        spacing: Theme.space_sm

                        Cell {
                            anchors.verticalCenter: parent.verticalCenter
                            width: Theme.icon_md + Theme.space_md
                            height: Theme.pill
                            visible: modelData !== "fallback"
                            value: ({
                                "state": modelData === "kept" || modelData === "dropped" || modelData === "added"
                                         || modelData === "missing" ? modelData : "kept",
                                "default": modelData === "default",
                                "forced": modelData === "forced",
                                "fallback": false
                            })
                        }

                        UiText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: Strings.t("matrix.legend." + modelData)
                            color: Theme.muted
                            font.pixelSize: Theme.text_sm
                        }
                    }
                }
            }

            HelpTip {
                objectName: "firstKeptTip"
                Layout.alignment: Qt.AlignTop
                topic: "first_kept"
            }

            UiText {
                Layout.alignment: Qt.AlignTop
                Layout.preferredHeight: Theme.row_sm
                verticalAlignment: Text.AlignVCenter
                visible: matrix.headers.some(h => h.movable)
                text: Strings.t("matrix.drag_hint")
                color: Theme.control
                font.pixelSize: Theme.text_sm
            }

            // A name such as Forced or SDH already counts as the flag when rules match; this writes the flag itself.
            ActionButton {
                objectName: "writeImpliedFlags"
                Layout.alignment: Qt.AlignTop
                kind: "outline"
                size: Theme.row_sm
                checkable: true
                checked: app.write_implied_flags
                iconName: checked ? "check" : ""
                text: Strings.t("matrix.write_implied_flags")
                Accessible.description: Strings.t("matrix.write_implied_flags_help")
                onToggled: app.set_write_implied_flags(checked)
            }
        }
    }
}
