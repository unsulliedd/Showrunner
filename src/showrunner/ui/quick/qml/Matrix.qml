import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The track matrix of the Tracks place: files down, track signatures across, audio then subtitles. A column's
// header keeps or drops it in every file and sets its flags; a cell shows what the plans leave in that file.
Item {
    id: matrix

    readonly property var headers: app.matrix.headers
    readonly property var rows: app.matrix.rows

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

        width: Theme.matrix_column
        height: Theme.matrix_header

        Rectangle {
            anchors.fill: parent
            anchors.margins: Theme.space_xs
            radius: Theme.radius_md
            color: head.column.state === "dropped" ? Theme.drop_soft : "transparent"
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.space_sm
            spacing: Theme.space_xs

            CodeBadge {
                Layout.alignment: Qt.AlignHCenter
                code: head.column.code
                look: head.column.state
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

            UiText {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                text: head.column.name
                color: Theme.muted
                font.pixelSize: Theme.text_xs
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
                Accessible.name: head.column.code + " " + head.column.title + " " + head.column.button
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

        ScrollView {
            id: scroll

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: grid.implicitWidth
            contentHeight: grid.implicitHeight

            Column {
                id: grid

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
                        model: matrix.headers

                        delegate: Header {
                            required property var modelData

                            column: modelData
                        }
                    }
                }

                Repeater {
                    model: matrix.rows

                    delegate: AbstractButton {
                        id: line

                        required property var modelData
                        readonly property bool focused: modelData.path === app.focus_path

                        width: Theme.matrix_label + matrix.headers.length * Theme.matrix_column
                        height: Theme.list_row
                        hoverEnabled: true
                        focusPolicy: Qt.StrongFocus
                        Accessible.role: Accessible.Button
                        Accessible.name: modelData.title
                        onClicked: app.focus_file(modelData.path)

                        background: Rectangle {
                            color: line.focused ? Theme.select : line.hovered ? Theme.panel_2 : "transparent"
                            border.width: line.visualFocus ? Theme.stroke : 0
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
