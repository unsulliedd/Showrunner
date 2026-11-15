import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Overview of a season, a show or a selection: the batch's tracks as chips by kind, then one row per file with
// what its plans leave of its tracks and a warning where it does not follow the batch.
Item {
    id: overview

    signal matrixAsked

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_lg

        Rectangle {
            Layout.fillWidth: true
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
                    text: Strings.t("overview.lead")
                    color: Theme.muted
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }

                Repeater {
                    model: app.overview.groups

                    delegate: RowLayout {
                        required property var modelData

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

                        Flow {
                            Layout.fillWidth: true
                            spacing: Theme.space_md

                            Repeater {
                                model: modelData.chips

                                delegate: TrackChip {
                                    required property var modelData

                                    chip: modelData
                                }
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
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
                text: Strings.t("overview.column.file")
            }

            Heading {
                Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
                text: Strings.t("overview.column.audio")
            }

            Heading {
                Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
                text: Strings.t("overview.column.subtitles")
            }

            Heading {
                Layout.preferredWidth: Theme.matrix_column
                text: Strings.t("overview.column.changes")
            }
        }

        ListView {
            id: rows

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: app.overview.rows
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            delegate: AbstractButton {
                id: row

                required property var modelData
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

                    ColumnLayout {
                        Layout.fillWidth: true
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
                        Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
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
                        Layout.preferredWidth: Theme.matrix_header + Theme.space_2xl
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
