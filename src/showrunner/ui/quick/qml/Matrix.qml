import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The Tracks place: each track of the batch is a row, audio then subtitles, beside a strip of the batch's files, one
// cell per file under the numbers across the top. A cell is quiet where its file follows the track and drawn only where
// it differs; Python says which and why. The rows stand in the order of the tracks in the new files: a row's grip drags
// it up or down, or moves it with Ctrl+Up and Ctrl+Down, among the rows of its kind. A click on a cell is that file's
// own choice; a click on a number opens the file. "Only files that differ" folds each run of files that follow every
// track into one cell.
Item {
    id: matrix

    objectName: "matrix"

    // Read once: each read of the property converts the whole batch view for QML.
    readonly property var view: app.matrix
    readonly property var headers: view.headers
    // Which files the strip shows, as the user last chose; until then every file where they fit, else the folded runs.
    property string chosen: app.matrix_files()
    readonly property bool brief: width < Theme.strip_label_short_below
    readonly property real labelWidth: brief ? Theme.track_strip_label_narrow : Theme.track_strip_label
    // The width the rows share: the view less the room its vertical scrollbar takes while it shows.
    readonly property real room: scroll.width - scroll.rightMargin
    // What the strip shows of itself beside the labels, which stand still while it scrolls.
    readonly property real shown: Math.max(0, room - labelWidth - Theme.space_md)
    readonly property bool fitsAll: view.strip.all.files.length * Theme.strip_pitch <= shown
    readonly property bool folded: chosen === "differ" || chosen === "" && !fitsAll
    readonly property var strip: folded ? view.strip.differ : view.strip.all
    readonly property var files: strip.files
    // Where each file's cell starts along the strip, and last where the strip ends: a folded run is wider than a file.
    readonly property var offsets: {
        const result = [0]
        for (const file of files) {
            const least = file.run ? Theme.strip_run : Theme.strip_pitch
            result.push(result[result.length - 1]
                        + Math.max(least, Math.ceil(metrics.advanceWidth(file.label)) + 2 * Theme.space_xs))
        }
        return result
    }
    readonly property real stripWidth: offsets[offsets.length - 1]
    readonly property real scrolled: scroll.contentX
    // The cells each row builds: the same count wherever the strip is scrolled, so a scroll rebinds them to other files
    // instead of making new ones, and a whole show builds only what is in view.
    readonly property int built: Math.min(files.length, Math.ceil(shown / Theme.strip_pitch) + 2)
    readonly property int first: Math.max(0, Math.min(files.length - built, at(scrolled)))
    // The cell of the file the Inspector shows, marked down the strip.
    readonly property int selected: files.findIndex(file => file.paths.indexOf(app.focus_path) >= 0)
    // The row whose names are open (one at a time), -1 for none. Another batch closes it.
    property int openColumn: -1
    readonly property var openNames: {
        matrix.view
        return openColumn < 0 ? [] : app.track_name_rows(openColumn)
    }
    readonly property string openMissing: {
        matrix.view
        return openColumn < 0 ? "" : app.track_missing(openColumn)
    }
    readonly property string openHeld: {
        matrix.view
        return openColumn < 0 ? "" : app.track_held(openColumn)
    }
    // The row a grip drags and how many places it has gone, for the line that shows where it lands.
    property int dragFrom: -1
    property int dragPlaces: 0
    readonly property string batchKey: app.selected

    onBatchKeyChanged: openColumn = -1

    // Where file `at`'s cell starts along the strip; past the last file, where the strip ends. A binding can ask for a
    // file the strip no longer has while a new batch's strip arrives.
    function edge(at) {
        return offsets[Math.max(0, Math.min(at, offsets.length - 1))]
    }

    // The file whose cell starts at or before `x` along the strip.
    function at(x) {
        let low = 0
        let high = files.length - 1
        while (low < high) {
            const middle = Math.ceil((low + high) / 2)
            if (offsets[middle] <= x)
                low = middle
            else
                high = middle - 1
        }
        return Math.max(0, low)
    }

    // Scrolls sideways just enough to show file `at`, so a file reached by keyboard stays in view.
    function showFile(at) {
        if (edge(at) < scroll.contentX)
            scroll.contentX = edge(at)
        else if (edge(at + 1) > scroll.contentX + shown)
            scroll.contentX = Math.min(edge(at + 1) - shown, scroll.contentWidth + scroll.rightMargin - scroll.width)
    }

    function openFile(at) {
        if (at >= 0 && at < files.length)
            app.focus_file(files[at].paths[0])
    }

    FontMetrics {
        id: metrics

        font.family: Theme.mono
        font.pixelSize: Theme.text_xs
    }

    // The part of a row that holds its strip. It stands still beside the labels while its content scrolls sideways
    // under it, so a cell is cut at the labels, not drawn over them.
    component Strip: Item {
        default property alias content: inner.data

        x: matrix.scrolled + matrix.labelWidth
        width: matrix.room - matrix.labelWidth
        height: parent.height
        clip: true

        Item {
            id: inner

            x: -matrix.scrolled
            width: matrix.stripWidth
            height: parent.height
        }
    }

    // One file's cell under one track: quiet where the file follows its track, drawn where it differs.
    component Cell: Item {
        id: cell

        objectName: "stripCell"
        required property int at
        required property string mark
        property bool added: false
        property bool pointed: false

        x: matrix.edge(at)
        width: matrix.edge(at + 1) - matrix.edge(at)
        height: parent.height

        Rectangle {
            anchors.fill: parent
            visible: cell.at >= 0 && cell.at === matrix.selected
            color: Theme.select
        }

        // The file's own choice, the one a click takes back, is the only framed mark.
        Rectangle {
            anchors.centerIn: parent
            width: Theme.strip_cell
            height: Theme.strip_cell
            visible: cell.mark === "own_drop" || cell.mark === "own_keep" || cell.pointed
            radius: Theme.radius_sm
            color: cell.mark === "own_drop" || cell.mark === "own_keep" ? Theme.control_soft : "transparent"
            border.width: Theme.stroke
            border.color: cell.mark === "own_drop" || cell.mark === "own_keep" ? Theme.control : Theme.line_strong
        }

        Rectangle {
            anchors.centerIn: parent
            visible: cell.mark === "follows" || cell.mark === "held"
            width: cell.mark === "held" ? Theme.dot : Theme.dot - Theme.space_xs
            height: width
            radius: width / 2
            color: cell.mark === "held" ? Theme.change : cell.added ? Theme.add : Theme.line_strong
        }

        Icon {
            anchors.centerIn: parent
            visible: cell.mark === "own_drop" || cell.mark === "drop" || cell.mark === "own_keep" || cell.mark === "keep"
            name: cell.mark === "own_drop" || cell.mark === "drop" ? "x" : "check"
            size: Theme.icon_sm
            color: cell.mark === "own_drop" || cell.mark === "drop" ? Theme.drop : Theme.add
        }

        UiText {
            anchors.centerIn: parent
            visible: cell.mark === "missing"
            text: Strings.t("matrix.missing_mark")
            color: Theme.change
            font.weight: Font.Bold
        }

        FlagMark {
            anchors.centerIn: parent
            visible: cell.mark === "fallback" || cell.mark === "set_default" || cell.mark === "set_forced"
                     || cell.mark === "file_default" || cell.mark === "file_forced"
            flag: cell.mark.endsWith("forced") ? "forced" : "default"
            on: !cell.mark.startsWith("file_")
            held: cell.mark.startsWith("file_")
            tone: Theme.change
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        // The switch of files, then the order's mark and the flag switch: on one line, or two where the place is narrow.
        GridLayout {
            Layout.fillWidth: true
            columns: matrix.brief ? 1 : 2
            columnSpacing: Theme.space_lg
            rowSpacing: Theme.space_md

            Segmented {
                objectName: "stripFiles"
                Layout.preferredWidth: Theme.track_strip_label
                Layout.minimumWidth: 0
                Layout.fillWidth: true
                Layout.maximumWidth: Theme.track_strip_label
                name: Strings.t("matrix.show.name")
                current: matrix.folded ? "differ" : "all"
                model: [
                    {"key": "all", "label": Strings.n("matrix.show.all", matrix.view.strip.all.files.length)},
                    {"key": "differ", "label": Strings.f("matrix.show.differ", {"count": matrix.view.strip.differing})}
                ]
                onPicked: key => {
                    matrix.chosen = key
                    app.save_matrix_files(key)
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.space_lg

                Item {
                    Layout.fillWidth: true
                }

                PlaceMark {
                    objectName: "orderMark"
                    Layout.maximumWidth: implicitWidth
                    choice: app.field_marks["tracks.order"] || ({})
                }

                // A name such as Forced or SDH already counts as the flag when rules match; this writes the flag itself.
                ActionButton {
                    objectName: "writeImpliedFlags"
                    kind: "outline"
                    size: Theme.row_sm
                    checkable: true
                    checked: app.write_implied_flags
                    iconName: checked ? "check" : ""
                    text: Strings.t("matrix.write_implied_flags")
                    Accessible.description: Strings.t("matrix.write_implied_flags_help")
                    onToggled: app.set_write_implied_flags(checked)

                    Tip {
                        objectName: "impliedTip"
                        visible: parent.hovered
                        text: Strings.t("matrix.write_implied_flags_help")
                    }
                }

                PlaceMark {
                    objectName: "impliedFlagsMark"
                    Layout.maximumWidth: implicitWidth
                    choice: app.field_marks["metadata.write_implied_flags"] || ({})
                }

                HelpTip {
                    objectName: "firstKeptTip"
                    topic: "first_kept"
                }
            }
        }

        UiText {
            objectName: "impliedNothing"
            Layout.fillWidth: true
            visible: app.implied_nothing
            text: Strings.t("matrix.implied_nothing")
            color: Theme.muted
            font.pixelSize: Theme.text_sm
            horizontalAlignment: Text.AlignRight
            wrapMode: Text.WordWrap
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // A ListView creates a track's row only as it scrolls into view, and each row builds only the cells in view
            // (`built`), so a whole show with many tracks does not build every row and cell. The numbers across the top
            // are one Tab stop, `numberKeys`: Left, Right, Home and End move along the files, Return opens one.
            ListView {
                id: scroll

                objectName: "trackRows"
                anchors.fill: parent
                clip: true
                // The rows stay put while one is dragged, so the drag moves the row, not the view.
                interactive: matrix.dragFrom < 0
                contentWidth: matrix.labelWidth + matrix.stripWidth + Theme.space_md
                // Room for the vertical scrollbar beside the strip, which then scrolls clear of it.
                rightMargin: vbar.visible ? vbar.width : 0
                flickableDirection: Flickable.AutoFlickIfNeeded
                boundsBehavior: Flickable.StopAtBounds
                spacing: Theme.space_xs
                headerPositioning: ListView.OverlayHeader
                // A count, not the headers: a choice or a move then updates the rows in place, so the view keeps its
                // place and the focus can follow a moved row.
                model: matrix.headers.length
                // Another batch starts at the top and at its first file, even with as many rows as the last one.
                readonly property string firstPath: matrix.files.length > 0 ? matrix.files[0].paths[0] : ""
                onFirstPathChanged: {
                    contentX = 0
                    positionViewAtBeginning()
                    numberKeys.current = 0
                }
                ScrollBar.vertical: Scroller {
                    id: vbar
                }
                ScrollBar.horizontal: Scroller {}

                header: Rectangle {
                    readonly property bool seasons: matrix.strip.seasons.length > 0

                    z: 3
                    width: scroll.contentWidth
                    height: (seasons ? Theme.row_sm : 0) + Theme.row_sm + Theme.space_xs
                    color: Theme.panel

                    Strip {
                        objectName: "stripNumbers"

                        Repeater {
                            model: matrix.strip.seasons

                            delegate: UiText {
                                required property var modelData

                                x: matrix.edge(modelData.first) + Theme.space_xs
                                width: matrix.edge(modelData.first + modelData.count) - x
                                height: Theme.row_sm
                                text: modelData.label
                                color: Theme.faint
                                font.pixelSize: Theme.text_xs
                                font.weight: Font.DemiBold
                            }
                        }

                        Repeater {
                            model: matrix.built

                            delegate: Item {
                                id: number

                                required property int index
                                readonly property int at: matrix.first + index
                                readonly property var file: matrix.files[at] ?? {"label": "", "tip": ""}
                                readonly property bool current: numberKeys.activeFocus && at === numberKeys.current

                                objectName: "stripNumber"
                                x: matrix.edge(at)
                                y: parent.height - Theme.row_sm - Theme.space_xs
                                width: matrix.edge(at + 1) - matrix.edge(at)
                                height: Theme.row_sm

                                Rectangle {
                                    anchors.fill: parent
                                    visible: number.at === matrix.selected || number.current || pointer.hovered
                                    radius: Theme.radius_sm
                                    color: number.at === matrix.selected ? Theme.select : Theme.panel_3
                                    border.width: number.current ? Theme.stroke : 0
                                    border.color: Theme.control
                                }

                                UiText {
                                    anchors.centerIn: parent
                                    mono: true
                                    text: number.file.label
                                    color: number.at === matrix.selected ? Theme.ink : Theme.faint
                                    font.pixelSize: Theme.text_xs
                                    font.weight: number.at === matrix.selected ? Font.Bold : Font.Normal
                                }

                                HoverHandler {
                                    id: pointer

                                    cursorShape: Qt.PointingHandCursor
                                }

                                TapHandler {
                                    onTapped: {
                                        numberKeys.forceActiveFocus()
                                        numberKeys.current = number.at
                                        matrix.openFile(number.at)
                                    }
                                }

                                Tip {
                                    visible: pointer.hovered
                                    text: number.file.tip
                                }
                            }
                        }
                    }
                }

                delegate: Item {
                    id: line

                    objectName: "trackLine"
                    required property int index
                    readonly property var column: matrix.headers[index]
                    readonly property var cells: matrix.strip.lines[index] ?? []
                    // The first row of its kind carries the kind's label above it.
                    readonly property bool leads: index === 0 || matrix.headers[index - 1].kind !== column.kind
                    readonly property real rowTop: leads ? Theme.row_sm + (index > 0 ? Theme.space_md : 0) : 0
                    readonly property alias grip: label.grip

                    width: scroll.contentWidth
                    height: rowTop + label.height
                    z: label.grip.active ? 1 : 0

                    Row {
                        x: matrix.scrolled + Theme.space_xs
                        y: line.rowTop - Theme.row_sm
                        height: Theme.row_sm
                        visible: line.leads
                        spacing: Theme.space_sm

                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: line.column.kind === "audio" ? "audio" : "subs"
                            size: Theme.icon_sm
                            color: Theme.faint
                        }

                        UiText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: Strings.t("matrix.group." + line.column.kind)
                            color: Theme.faint
                            font.pixelSize: Theme.text_xs
                            font.weight: Font.DemiBold
                            font.letterSpacing: Theme.stroke
                        }
                    }

                    Item {
                        y: line.rowTop
                        width: parent.width
                        height: label.height
                        transform: Translate {
                            y: label.grip.offset
                        }

                        // The row held by its grip, framed as it moves.
                        Rectangle {
                            x: matrix.scrolled - Theme.space_xs
                            y: -Theme.space_xs
                            z: 1
                            width: matrix.room + 2 * Theme.space_xs
                            height: label.height + 2 * Theme.space_xs
                            visible: label.grip.active
                            radius: Theme.radius_md
                            color: "transparent"
                            border.width: Theme.stroke
                            border.color: Theme.control
                        }

                        TrackChip {
                            id: label

                            x: matrix.scrolled
                            width: matrix.labelWidth
                            form: "label"
                            brief: matrix.brief
                            gripStep: Theme.row_lg + scroll.spacing
                            chip: line.column
                            namesOpen: matrix.openColumn === line.column.id
                            rows: namesOpen ? matrix.openNames : []
                            missing: namesOpen ? matrix.openMissing : ""
                            held: namesOpen ? matrix.openHeld : ""
                            onNamesToggled: matrix.openColumn = namesOpen ? -1 : line.column.id
                        }

                        Connections {
                            target: label.grip

                            function onActiveChanged() {
                                matrix.dragFrom = label.grip.active ? line.column.id : -1
                                matrix.dragPlaces = 0
                                // An open list would make the rows' steps uneven under the drag.
                                if (label.grip.active)
                                    matrix.openColumn = -1
                            }

                            function onPlacesChanged() {
                                if (label.grip.active)
                                    matrix.dragPlaces = label.grip.places
                            }

                            function onMoved(places) {
                                const focused = label.grip.activeFocus
                                const at = app.move_track(line.index, line.index + places)
                                if (focused) {
                                    // Only a row that exists can take the focus: bring it into view first.
                                    scroll.positionViewAtIndex(at, ListView.Contain)
                                    scroll.itemAtIndex(at).grip.forceActiveFocus()
                                }
                            }
                        }

                        Strip {
                            id: cells

                            objectName: "trackStrip"
                            height: Theme.row_lg
                            // The cell under the pointer, -1 for none: one handler for the strip, not one per cell. The
                            // handlers lie on the strip's content, so a point on them is a place along the strip.
                            readonly property int pointed: hover.hovered ? matrix.at(hover.point.position.x) : -1
                            readonly property var pointedCell: pointed >= 0 ? line.cells[pointed] ?? null : null

                            Rectangle {
                                width: matrix.stripWidth
                                height: parent.height
                                visible: line.column.state === "dropped"
                                radius: Theme.radius_md
                                color: Theme.drop_soft
                            }

                            Repeater {
                                model: matrix.built

                                delegate: Cell {
                                    required property int index

                                    at: matrix.first + index
                                    mark: line.cells[at]?.mark ?? "none"
                                    added: line.column.state === "added"
                                    pointed: at === cells.pointed && (line.cells[at]?.click ?? false)
                                }
                            }

                            // Under the cell the pointer is over, for its tooltip.
                            Item {
                                id: tipAnchor

                                x: cells.pointed >= 0 ? matrix.edge(cells.pointed) : 0
                                width: cells.pointed >= 0 ? matrix.edge(cells.pointed + 1) - x : 0
                                height: parent.height
                            }

                            HoverHandler {
                                id: hover

                                cursorShape: cells.pointedCell?.click ? Qt.PointingHandCursor : Qt.ArrowCursor
                            }

                            TapHandler {
                                id: tap

                                onTapped: {
                                    const at = matrix.at(tap.point.position.x)
                                    if (line.cells[at]?.click)
                                        app.toggle_file_track(line.column.id, matrix.files[at].paths[0])
                                }
                            }
                        }

                        Tip {
                            objectName: "cellTip"
                            parent: tipAnchor
                            visible: cells.pointed >= 0 && text !== ""
                            text: cells.pointed < 0 ? ""
                                  : matrix.files[cells.pointed].run ? matrix.files[cells.pointed].tip
                                  : app.cell_tip(line.column.id, matrix.files[cells.pointed].paths[0])
                        }
                    }
                }
            }

            // Where the dragged row lands: the edge of the row whose place it takes.
            Rectangle {
                readonly property var dragged: matrix.dragFrom >= 0 ? matrix.headers[matrix.dragFrom] : null
                readonly property int firstOfKind: dragged ? matrix.headers.findIndex(h => h.kind === dragged.kind) : 0
                readonly property int lastOfKind: dragged
                    ? firstOfKind + matrix.headers.filter(h => h.kind === dragged.kind).length - 1 : 0
                readonly property int to: dragged
                    ? Math.max(firstOfKind, Math.min(lastOfKind, matrix.dragFrom + matrix.dragPlaces)) : -1
                readonly property var target: dragged && to !== matrix.dragFrom ? scroll.itemAtIndex(to) : null

                objectName: "orderLine"
                visible: target !== null
                x: 0
                y: target ? target.mapToItem(parent, 0, to > matrix.dragFrom ? target.height : target.rowTop).y
                            - height / 2 : 0
                z: 2
                width: matrix.room
                height: 3 * Theme.stroke
                radius: height / 2
                color: Theme.control
            }

            Item {
                id: numberKeys

                property int current: 0

                objectName: "numberKeys"
                width: matrix.room
                height: Theme.row_sm
                activeFocusOnTab: true
                Accessible.role: Accessible.List
                Accessible.name: Strings.t("matrix.numbers")
                onActiveFocusChanged: {
                    if (activeFocus)
                        current = matrix.selected >= 0 ? matrix.selected : Math.min(current, matrix.files.length - 1)
                }
                Keys.onPressed: event => {
                    const last = matrix.files.length - 1
                    const to = {
                        [Qt.Key_Left]: current - 1,
                        [Qt.Key_Right]: current + 1,
                        [Qt.Key_Home]: 0,
                        [Qt.Key_End]: last
                    }[event.key]
                    if (to !== undefined) {
                        current = Math.max(0, Math.min(last, to))
                        matrix.showFile(current)
                        event.accepted = true
                    } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && last >= 0) {
                        matrix.openFile(current)
                        event.accepted = true
                    }
                }
            }
        }

        // What the loud marks mean; a file that follows its track draws nothing that needs a key.
        Flow {
            objectName: "stripKey"
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                height: Theme.row_sm
                text: Strings.t("matrix.key")
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }

            Repeater {
                model: [
                    {"mark": "own_drop", "key": "own"},
                    {"mark": "missing", "key": "missing"},
                    {"mark": "fallback", "key": "fallback"}
                ]

                delegate: Row {
                    required property var modelData

                    height: Theme.row_sm
                    spacing: Theme.space_xs

                    // A cell of no file.
                    Cell {
                        at: -1
                        x: 0
                        width: Theme.strip_pitch
                        mark: modelData.mark
                    }

                    UiText {
                        height: Theme.row_sm
                        text: Strings.t("matrix.key." + modelData.key)
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                    }
                }
            }

            UiText {
                height: Theme.row_sm
                leftPadding: Theme.space_lg
                visible: matrix.headers.some(h => h.movable)
                text: Strings.t("matrix.drag_hint")
                color: Theme.faint
                font.pixelSize: Theme.text_sm
            }
        }
    }
}
