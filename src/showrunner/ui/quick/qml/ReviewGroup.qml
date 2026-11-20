import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One kind of planned change in Review: a tick box with its name and the files it changes, its lines with their
// counts, what is in the way, and for Tracks where the originals go. An unticked kind is dashed and its lines struck:
// they say what it would do.
Item {
    id: group

    required property var card
    property bool locked: false

    implicitHeight: column.implicitHeight + 2 * Theme.space_lg

    Rectangle {
        anchors.fill: parent
        visible: group.card.in_run
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: Theme.line
    }

    DashedFrame {
        anchors.fill: parent
        visible: !group.card.in_run
    }

    ColumnLayout {
        id: column

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            Tick {
                objectName: "inRun_" + group.card.key
                ticked: group.card.in_run
                enabled: !group.locked
                label: group.card.label
                tip: Strings.t("review.tick_kind")
                onFlipped: on => app.set_in_run(group.card.key, on)
            }

            Rectangle {
                Layout.preferredWidth: Theme.row_md
                Layout.preferredHeight: Theme.row_md
                radius: Theme.radius_md
                color: group.card.in_run ? Theme.change_soft : Theme.panel_3

                Icon {
                    anchors.centerIn: parent
                    name: group.card.icon
                    color: group.card.in_run ? Theme.change : Theme.faint
                }
            }

            UiText {
                Layout.fillWidth: true
                text: group.card.label
                color: group.card.in_run ? Theme.ink : Theme.muted
                font.weight: Font.DemiBold
            }
        }

        PlaceMark {
            objectName: "heldInsideMark"
            Layout.fillWidth: true
            choice: group.card.mark
        }

        Repeater {
            model: group.card.lines

            delegate: RowLayout {
                required property var modelData

                Layout.fillWidth: true
                Layout.leftMargin: Theme.row_sm + Theme.row_md + 2 * Theme.space_md

                UiText {
                    Layout.fillWidth: true
                    text: modelData.label
                    color: group.card.in_run ? Theme.ink : Theme.faint
                    font.strikeout: !group.card.in_run
                }

                UiText {
                    text: modelData.count
                    color: group.card.in_run ? Theme.change : Theme.faint
                    font.weight: Font.DemiBold
                }
            }
        }

        UiText {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.row_sm + Theme.row_md + 2 * Theme.space_md
            visible: group.card.note !== ""
            text: group.card.note
            color: Theme.muted
            font.pixelSize: Theme.text_sm
            wrapMode: Text.WordWrap
        }

        Repeater {
            model: group.card.problems

            delegate: RowLayout {
                required property var modelData

                Layout.fillWidth: true
                Layout.leftMargin: Theme.row_sm + Theme.row_md + 2 * Theme.space_md
                spacing: Theme.space_sm

                Icon {
                    Layout.alignment: Qt.AlignTop
                    name: "alert"
                    size: Theme.icon_sm
                    color: Theme.change
                }

                UiText {
                    Layout.fillWidth: true
                    text: modelData
                    color: Theme.muted
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }
            }
        }

        RowLayout {
            Layout.leftMargin: Theme.row_sm + Theme.row_md + 2 * Theme.space_md
            spacing: Theme.space_md

            ActionButton {
                visible: group.card.program
                kind: "outline"
                size: Theme.row_sm
                iconName: "upload"
                text: Strings.t("review.get_mkvtoolnix")
                onClicked: app.get_program("mkvtoolnix")
            }

            ActionButton {
                id: originals

                objectName: "originals"
                visible: group.card.key === "tracks" && group.card.in_run
                kind: "outline"
                size: Theme.row_sm
                enabled: !group.locked
                iconName: "recycle"
                text: group.card.original_text || ""
                Accessible.role: Accessible.ButtonMenu
                onClicked: menu.open()

                Tip {
                    visible: originals.hovered && !menu.visible
                    text: Strings.t("review.originals_tip")
                }

                Menu {
                    id: menu

                    y: originals.height + Theme.space_xs
                    padding: Theme.space_sm

                    background: Rectangle {
                        implicitWidth: Theme.menu_width
                        radius: Theme.radius_md
                        color: Theme.panel_2
                        border.width: Theme.stroke
                        border.color: Theme.line_strong
                    }

                    MenuRow {
                        checkable: true
                        checked: group.card.original === "recycle"
                        text: group.card.originals ? group.card.originals[0].label : ""
                        onTriggered: app.set_original("recycle")
                    }

                    MenuRow {
                        checkable: true
                        checked: group.card.original === "keep"
                        text: group.card.originals ? group.card.originals[1].label : ""
                        onTriggered: app.set_original("keep")
                    }
                }
            }

            PlaceMark {
                objectName: "originalMark"
                visible: originals.visible && text !== ""
                choice: app.field_marks["mux.original"] || ({})
            }
        }
    }
}
