import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The Names place: a card per template of the profile, the builder rail of the picked one with its result on the
// selected file, and the template on the whole batch, now and after. The rail is drawn from the template the
// controller parsed; every edit goes back to it as template text.
Item {
    id: place

    readonly property var names: app.names
    readonly property bool empty: names.empty === true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_lg

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            Repeater {
                model: place.names.cards || []

                delegate: TemplateCard {
                    required property var modelData

                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    Layout.alignment: Qt.AlignTop
                    entry: modelData
                    picked: modelData.key === place.names.template
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_sm
            spacing: Theme.space_md

            UiText {
                text: place.names.title || ""
                font.pixelSize: Theme.text_lg
                font.weight: Font.DemiBold
            }

            UiText {
                Layout.fillWidth: true
                text: Strings.f("names.profile", {"name": app.profile})
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }

            ActionButton {
                visible: !place.empty
                kind: "ghost"
                size: Theme.row_sm
                iconName: "x"
                text: Strings.t("names.clear")
                onClicked: app.clear_template()
            }
        }

        UiText {
            Layout.fillWidth: true
            Layout.topMargin: -Theme.space_md
            text: Strings.t("names.lead")
            color: Theme.muted
            font.pixelSize: Theme.text_sm
            wrapMode: Text.WordWrap
        }

        Rectangle {
            id: frame

            objectName: "railFrame"
            Layout.fillWidth: true
            implicitHeight: Math.max(Theme.row_lg * 2, railBody.implicitHeight + 2 * Theme.space_lg)
            radius: Theme.radius_lg
            color: Theme.panel
            border.width: Theme.stroke
            border.color: endDrop.containsDrag ? Theme.control : Theme.line_strong

            // A drop on the frame's free space adds the token at the end.
            DropArea {
                id: endDrop

                anchors.fill: parent
                keys: ["token"]
                onDropped: event => {
                    const name = event.source.tokenName
                    const from = event.source.from
                    const at = place.names.end
                    event.accept()
                    Qt.callLater(() => from >= 0 ? app.rail_move(from, at) : app.rail_insert(at, name))
                }
            }

            ColumnLayout {
                id: railBody

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Theme.space_lg
                spacing: Theme.space_md

                Flow {
                    id: rail

                    objectName: "rail"
                    Layout.fillWidth: true
                    visible: place.names.editable === true && !place.empty
                    spacing: Theme.space_sm

                    Repeater {
                        model: place.names.rail || []

                        delegate: RailPart {
                            lineHeight: Theme.row_lg + 2 * Theme.space_sm
                        }
                    }
                }

                UiText {
                    Layout.fillWidth: true
                    visible: place.empty
                    text: Strings.t("names.empty")
                    color: Theme.faint
                    font.italic: true
                    wrapMode: Text.WordWrap
                }

                UiText {
                    Layout.fillWidth: true
                    visible: place.names.editable === false
                    mono: true
                    text: place.names.text || ""
                    wrapMode: Text.WrapAnywhere
                }

                UiText {
                    Layout.fillWidth: true
                    visible: place.names.editable === false
                    text: Strings.t("names.raw")
                    color: Theme.drop
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }
            }
        }

        Repeater {
            model: place.names.problems || []

            delegate: RowLayout {
                required property var modelData

                Layout.fillWidth: true
                spacing: Theme.space_md

                Icon {
                    name: "alert"
                    size: Theme.icon_sm
                    color: Theme.drop
                }

                UiText {
                    Layout.fillWidth: true
                    text: modelData
                    color: Theme.drop
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            visible: (place.names.blocked || []).length > 0
            implicitHeight: blockedList.implicitHeight + 2 * Theme.space_md
            radius: Theme.radius_md
            color: Theme.drop_soft
            border.width: Theme.stroke
            border.color: Theme.drop

            ColumnLayout {
                id: blockedList

                anchors.fill: parent
                anchors.margins: Theme.space_md
                spacing: Theme.space_xs

                UiText {
                    Layout.fillWidth: true
                    text: Strings.t("names.blocked.title")
                    color: Theme.drop
                    font.weight: Font.DemiBold
                    font.pixelSize: Theme.text_sm
                }

                Repeater {
                    model: place.names.blocked || []

                    delegate: UiText {
                        required property var modelData

                        Layout.fillWidth: true
                        text: modelData
                        color: Theme.ink
                        font.pixelSize: Theme.text_sm
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: place.empty && (place.names.suggestion || "") !== ""
            spacing: Theme.space_md

            UiText {
                Layout.fillWidth: true
                text: Strings.f("names.suggest.lead", {"result": place.names.suggestion || ""})
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }

            ActionButton {
                kind: "outline"
                size: Theme.row_sm
                iconName: "plus"
                text: Strings.t("names.suggest")
                onClicked: app.start_template(place.names.template)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: !place.empty && place.names.result !== undefined && place.names.result.label !== ""
            spacing: Theme.space_md

            UiText {
                text: place.names.result ? place.names.result.label : ""
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }

            Row {
                Layout.fillWidth: true
                clip: true
                // Room for the underline below the text, which the clip would cut off.
                bottomPadding: Theme.underline

                Repeater {
                    model: place.names.result ? place.names.result.segments : []

                    delegate: UiText {
                        required property var modelData

                        mono: true
                        text: modelData.text
                        font.pixelSize: Theme.text_md
                        font.weight: Font.Medium

                        Rectangle {
                            visible: modelData.token
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.bottom
                            height: Theme.underline
                            color: Theme.control
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: Theme.space_sm
            visible: !place.empty
            spacing: Theme.space_lg

            component Heading: UiText {
                color: Theme.faint
                font.pixelSize: Theme.text_xs
                font.weight: Font.DemiBold
                font.letterSpacing: Theme.stroke
                font.capitalization: Font.AllUppercase
            }

            Heading {
                Layout.fillWidth: true
                text: place.names.rows_title || ""
            }

            UiText {
                text: place.names.rows_count || ""
                color: Theme.faint
                font.pixelSize: Theme.text_sm
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: !place.empty
            spacing: Theme.space_lg

            Heading {
                Layout.leftMargin: Theme.space_lg
                Layout.preferredWidth: Theme.row_md
                text: Strings.t("names.column.number")
            }

            Heading {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: Strings.t("names.column.now")
            }

            Heading {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: Strings.t("names.column.after")
            }
        }

        ListView {
            id: rows

            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !place.empty
            clip: true
            model: place.names.rows || []
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            delegate: AbstractButton {
                id: row

                required property var modelData

                width: rows.width
                height: Theme.list_row
                hoverEnabled: true
                focusPolicy: Qt.StrongFocus
                Accessible.role: Accessible.Button
                Accessible.name: modelData.now + " " + modelData.after + " " + modelData.note
                onClicked: app.focus_file(modelData.path)

                background: Rectangle {
                    radius: Theme.radius_md
                    color: row.modelData.focused ? Theme.select : row.hovered ? Theme.panel_2 : "transparent"
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

                    // Half of what the number column leaves, as the NOW and AFTER headings split it.
                    UiText {
                        Layout.preferredWidth: (row.availableWidth - Theme.row_md - 3 * Theme.space_lg) / 2
                        mono: true
                        text: row.modelData.now
                        color: row.modelData.now_empty ? Theme.faint : Theme.muted
                        font.italic: row.modelData.now_empty
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.rightMargin: Theme.space_lg
                        spacing: Theme.space_xs

                        UiText {
                            Layout.fillWidth: true
                            mono: true
                            text: row.modelData.after
                            color: row.modelData.changed ? Theme.ink : Theme.faint
                            font.weight: row.modelData.changed ? Font.Medium : Font.Normal
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            visible: row.modelData.note !== ""
                            spacing: Theme.space_sm

                            Icon {
                                name: "alert"
                                size: Theme.icon_sm
                                color: Theme.change
                            }

                            UiText {
                                Layout.fillWidth: true
                                text: row.modelData.note
                                color: Theme.change
                                font.pixelSize: Theme.text_xs
                            }
                        }
                    }
                }
            }
        }

        Item {
            Layout.fillHeight: true
            visible: place.empty
        }
    }
}
