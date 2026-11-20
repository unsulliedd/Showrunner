import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Overview of a season, a show or a selection: the batch's tracks as rows by kind, then one row per file with
// what its plans leave of its tracks and a warning where it does not follow the batch.
Item {
    id: overview

    // Read once: each read of the property converts the whole batch view for QML.
    readonly property var view: app.overview

    // The height the user gave the tracks box with the separator, 0 until then: the box then fits its chips.
    property int chosenHeight: app.overview_tracks_height()
    // The chip whose names are open (one at a time), -1 for none. Another batch closes it.
    property int openColumn: -1
    readonly property string batchKey: app.selected
    // Read again with each new view: the controller builds them when asked.
    readonly property var openNames: {
        overview.view
        return openColumn < 0 ? [] : app.track_name_rows(openColumn)
    }
    readonly property string openMissing: {
        overview.view
        return openColumn < 0 ? "" : app.track_missing(openColumn)
    }
    readonly property string openHeld: {
        overview.view
        return openColumn < 0 ? "" : app.track_held(openColumn)
    }
    // The most the box may take: what the rest of the place needs stays, so the file list never shrinks to nothing.
    readonly property int maxBox: Math.max(
        Theme.tracks_min_height,
        column.height - headings.height - split.height - 3 * column.spacing - Theme.rows_min_height)
    readonly property int boxHeight: clampBox(chosenHeight > 0 ? chosenHeight : fitHeight)
    // Half the place is a proportion of the window, not a size: a show with hundreds of chips scrolls inside the box.
    readonly property int fitHeight: Math.min(box.implicitHeight, overview.height * 0.5)

    signal matrixAsked

    function clampBox(height) {
        return Math.max(Theme.tracks_min_height, Math.min(height, maxBox))
    }

    onBatchKeyChanged: openColumn = -1

    ColumnLayout {
        id: column

        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_lg

        Rectangle {
            id: box

            objectName: "tracksBox"
            Layout.fillWidth: true
            Layout.preferredHeight: overview.boxHeight
            Layout.minimumHeight: Theme.tracks_min_height
            implicitHeight: chips.implicitHeight + 2 * Theme.space_lg
            radius: Theme.radius_lg
            color: Theme.panel
            border.width: Theme.stroke
            border.color: Theme.line

            ColumnLayout {
                id: chips

                anchors.fill: parent
                anchors.margins: Theme.space_lg
                spacing: Theme.space_md

                RowLayout {
                    Layout.fillWidth: true

                    UiText {
                        Layout.fillWidth: true
                        text: app.has_batch ? Strings.t("overview.title." + app.batch_kind) : ""
                        font.weight: Font.DemiBold
                    }

                    ActionButton {
                        kind: "ghost"
                        size: Theme.row_sm
                        text: Strings.t("overview.open_matrix")
                        onClicked: overview.matrixAsked()
                    }
                }

                UiText {
                    Layout.fillWidth: true
                    text: overview.view.lead ?? ""
                    color: Theme.muted
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }

                // A show whose tracks differ from file to file can have hundreds of chips: past the box's height
                // they scroll, so the file list below keeps its room.
                ScrollPane {
                    id: groupScroll

                    objectName: "chipGroups"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredHeight: groups.implicitHeight
                    Layout.minimumHeight: 0
                    contentWidth: availableWidth
                    clip: true

                    ColumnLayout {
                        id: groups

                        width: groupScroll.availableWidth
                        spacing: Theme.space_md

                        // Counts, not the groups and chips: a new plan then updates the delegates in place. Made
                        // again, the chips (and the box's scroll with them) would move under the pointer between a
                        // press and the next click, which then lands on another chip.
                        Repeater {
                            model: overview.view.groups.length

                            delegate: RowLayout {
                                required property int index
                                readonly property var modelData: overview.view.groups[index]

                                Layout.fillWidth: true
                                Layout.topMargin: Theme.space_sm
                                spacing: Theme.space_md

                                Row {
                                    Layout.preferredWidth: Theme.matrix_label - Theme.space_2xl
                                    Layout.alignment: Qt.AlignTop
                                    Layout.topMargin: (Theme.row_lg - Theme.text_md) / 2
                                    spacing: Theme.space_md

                                    Icon {
                                        anchors.verticalCenter: parent.verticalCenter
                                        name: modelData.icon
                                        size: Theme.icon_sm
                                    }

                                    UiText {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.label
                                        color: Theme.muted
                                    }
                                }

                                // One row per track, one under the other, so the codecs, marks and flags form columns.
                                Column {
                                    id: chipRow

                                    Layout.fillWidth: true
                                    spacing: Theme.space_xs

                                    Repeater {
                                        model: modelData.chips.length

                                        delegate: TrackChip {
                                            required property int index
                                            readonly property var entry: modelData.chips[index]

                                            width: chipRow.width
                                            form: chipRow.width < Theme.track_row_two_lines_below ? "lines" : "row"
                                            chip: entry
                                            namesOpen: overview.openColumn === entry.id
                                            rows: namesOpen ? overview.openNames : []
                                            missing: namesOpen ? overview.openMissing : ""
                                            held: namesOpen ? overview.openHeld : ""
                                            onNamesToggled: overview.openColumn = namesOpen ? -1 : entry.id
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        HeightSplit {
            id: split

            objectName: "tracksSeparator"
            Layout.fillWidth: true
            value: overview.boxHeight
            onAdjusted: height => overview.chosenHeight = overview.clampBox(height)
            onCommitted: app.save_overview_tracks_height(overview.chosenHeight)
        }

        RowLayout {
            id: headings

            Layout.fillWidth: true
            Layout.leftMargin: Theme.space_lg
            Layout.rightMargin: Theme.space_lg
            spacing: Theme.space_lg

            component Heading: UiText {
                color: Theme.faint
                font.pixelSize: Theme.text_xs
                font.weight: Font.DemiBold
                font.letterSpacing: Theme.stroke
            }

            Heading {
                Layout.preferredWidth: Theme.row_md
                text: Strings.t("overview.column.number")
            }

            Heading {
                Layout.fillWidth: true
                Layout.minimumWidth: Theme.matrix_column
                text: Strings.t("overview.column.file")
            }

            // Mostly one track: narrower than the other kinds, and the first to give way in a narrow window.
            Heading {
                Layout.fillWidth: true
                Layout.preferredWidth: Theme.matrix_column
                Layout.maximumWidth: Theme.matrix_column
                Layout.minimumWidth: Theme.pill
                text: Strings.t("overview.column.video")
            }

            Heading {
                Layout.fillWidth: true
                Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
                Layout.maximumWidth: Theme.matrix_header + Theme.space_2xl
                Layout.minimumWidth: Theme.matrix_column
                text: Strings.t("overview.column.audio")
            }

            Heading {
                Layout.fillWidth: true
                Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
                Layout.maximumWidth: Theme.matrix_header + Theme.space_2xl
                Layout.minimumWidth: Theme.matrix_column
                text: Strings.t("overview.column.subtitles")
            }

            Heading {
                Layout.preferredWidth: Theme.matrix_column
                text: Strings.t("overview.column.changes")
            }
        }

        ListView {
            id: rows

            objectName: "overviewRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: Theme.rows_min_height
            clip: true
            // A count, not the rows: new rows of the same batch then update the delegates in place, so the view
            // keeps its scroll position after a choice.
            model: overview.view.rows.length
            // Another batch starts at the top, even with as many rows as the last one.
            readonly property string firstPath: overview.view.rows.length > 0 ? overview.view.rows[0].path : ""
            onFirstPathChanged: positionViewAtBeginning()
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: Scroller {}

            delegate: AbstractButton {
                id: row

                required property int index
                readonly property var modelData: overview.view.rows[index]
                readonly property bool focused: modelData.path === app.focus_path

                width: rows.width
                height: Theme.list_row
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: modelData.title + " " + modelData.changes_text
                onClicked: app.focus_file(modelData.path)

                background: Rectangle {
                    radius: Theme.radius_md
                    color: row.focused ? Theme.select : row.hovered ? Theme.panel_2 : "transparent"
                    border.width: row.visualFocus ? Theme.stroke : 0
                    border.color: Theme.control

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: Theme.stroke
                        color: Theme.line
                    }
                }

                contentItem: RowLayout {
                    spacing: Theme.space_lg

                    UiText {
                        Layout.leftMargin: Theme.space_lg
                        Layout.preferredWidth: Theme.row_md
                        mono: true
                        text: row.modelData.number
                        color: Theme.faint
                    }

                    // A narrow window shrinks the track columns, which clip their pills, and the file names, which elide.
                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.minimumWidth: Theme.matrix_column
                        spacing: Theme.space_xs

                        UiText {
                            Layout.fillWidth: true
                            text: row.modelData.title
                            font.weight: Font.Medium
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space_sm

                            Icon {
                                visible: row.modelData.warning !== ""
                                name: "alert"
                                size: Theme.icon_sm
                                color: Theme.change
                            }

                            UiText {
                                Layout.fillWidth: true
                                mono: row.modelData.warning === ""
                                text: row.modelData.warning !== "" ? row.modelData.warning : row.modelData.file
                                color: row.modelData.warning !== "" ? Theme.change : Theme.faint
                                font.pixelSize: Theme.text_xs
                            }
                        }
                    }

                    Row {
                        Layout.fillWidth: true
                        Layout.preferredWidth: Theme.matrix_column
                        Layout.maximumWidth: Theme.matrix_column
                        Layout.minimumWidth: Theme.pill
                        spacing: Theme.space_sm
                        clip: true

                        Repeater {
                            model: row.modelData.video

                            delegate: TrackPill {
                                required property var modelData

                                track: modelData
                            }
                        }
                    }

                    Row {
                        Layout.fillWidth: true
                        Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
                        Layout.maximumWidth: Theme.matrix_header + Theme.space_2xl
                        Layout.minimumWidth: Theme.matrix_column
                        spacing: Theme.space_sm
                        clip: true

                        Repeater {
                            model: row.modelData.audio

                            delegate: TrackPill {
                                required property var modelData

                                track: modelData
                            }
                        }
                    }

                    Row {
                        Layout.fillWidth: true
                        Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
                        Layout.maximumWidth: Theme.matrix_header + Theme.space_2xl
                        Layout.minimumWidth: Theme.matrix_column
                        spacing: Theme.space_sm
                        clip: true

                        Repeater {
                            model: row.modelData.subtitles

                            delegate: TrackPill {
                                required property var modelData

                                track: modelData
                            }
                        }
                    }

                    UiText {
                        Layout.preferredWidth: Theme.matrix_column
                        Layout.rightMargin: Theme.space_lg
                        text: row.modelData.changes_text
                        color: row.modelData.changes > 0 ? Theme.change : Theme.faint
                        font.pixelSize: Theme.text_sm
                    }
                }
            }
        }
    }
}
