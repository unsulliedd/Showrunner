import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One file in Review: a tick box (unticked, the file is skipped this time and stays planned), what changes in it
// and a mark per kind. An excluded file has no box: it is dashed, greyed, marked with the no-entry sign and has
// Include. Opened, the card shows its tracks, defaults, file, title, track names, flags and languages before and
// after; a row of an unticked kind says so and is muted.
Item {
    id: card

    required property var file
    property bool expanded: false
    property bool locked: false
    readonly property bool excluded: file.state === "excluded"
    readonly property bool out: file.state === "out" || excluded
    readonly property bool unticked: file.state === "out"

    signal toggled()

    implicitHeight: column.implicitHeight + 2 * Theme.space_md

    Rectangle {
        anchors.fill: parent
        visible: !card.excluded
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: card.expanded ? Theme.line_strong : Theme.line
    }

    DashedFrame {
        anchors.fill: parent
        visible: card.excluded
    }

    ColumnLayout {
        id: column

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: Theme.space_md
        anchors.leftMargin: Theme.space_md
        anchors.rightMargin: Theme.space_lg
        spacing: Theme.space_sm

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            Tick {
                objectName: "tickFile"
                visible: !card.excluded
                ticked: !card.unticked
                enabled: !card.locked
                label: card.file.title
                tip: Strings.t("review.tick_file")
                onFlipped: on => app.set_file_in_run(card.file.path, on)
            }

            Item {
                visible: card.excluded
                implicitWidth: Theme.row_sm
                implicitHeight: Theme.row_sm
            }

            IconButton {
                objectName: "expand"
                implicitWidth: Theme.row_sm
                implicitHeight: Theme.row_sm
                iconName: card.expanded ? "down" : "right"
                label: card.expanded ? Strings.t("review.fold") : Strings.t("review.open")
                tip: card.expanded ? Strings.t("tip.review_fold") : Strings.t("tip.review_open")
                onClicked: card.toggled()
            }

            UiText {
                visible: card.file.number !== ""
                mono: true
                text: card.file.number
                color: Theme.faint
                font.pixelSize: Theme.text_xs
            }

            UiText {
                text: card.file.title
                color: card.excluded ? Theme.faint : card.unticked ? Theme.muted : Theme.ink
                font.weight: Font.DemiBold
            }

            Icon {
                objectName: "excludedMark"
                visible: card.excluded
                name: "no_entry"
                size: Theme.icon_sm
            }

            Icon {
                visible: card.file.state === "look"
                name: "alert"
                size: Theme.icon_sm
                color: Theme.change
            }

            UiText {
                Layout.fillWidth: true
                text: card.excluded ? Strings.t("review.file.excluded") : card.file.summary
                color: card.excluded ? Theme.faint : Theme.muted
                font.pixelSize: Theme.text_sm
            }

            Row {
                spacing: Theme.space_xs
                Accessible.ignored: true

                Repeater {
                    model: card.file.marks

                    delegate: Rectangle {
                        required property var modelData

                        width: Theme.space_md + Theme.space_xs
                        height: Theme.space_xs
                        radius: Theme.space_xs / 2
                        color: modelData.on ? Theme.change : modelData.out ? Theme.line_strong : Theme.panel_3
                    }
                }
            }

            ActionButton {
                objectName: "includeFile"
                visible: card.excluded
                kind: "outline"
                size: Theme.row_sm
                enabled: !card.locked
                text: Strings.t("workspace.include")
                Accessible.description: card.file.title
                onClicked: app.exclude_file(card.file.path, false)

                Tip {
                    visible: parent.hovered
                    text: Strings.t("workspace.include_tip")
                }
            }
        }

        UiText {
            Layout.fillWidth: true
            Layout.leftMargin: 2 * Theme.row_sm + 2 * Theme.space_md
            visible: card.file.warning !== "" && !card.out
            text: card.file.warning
            color: Theme.change
            font.pixelSize: Theme.text_sm
            wrapMode: Text.WordWrap
        }

        Repeater {
            model: card.expanded ? card.file.detail : []

            delegate: RowLayout {
                required property var modelData

                Layout.fillWidth: true
                Layout.leftMargin: 2 * Theme.row_sm + 2 * Theme.space_md
                spacing: Theme.space_lg

                Row {
                    Layout.preferredWidth: Theme.matrix_label
                    Layout.alignment: Qt.AlignTop
                    spacing: Theme.space_sm

                    UiText {
                        text: modelData.label
                        color: modelData.out ? Theme.faint : Theme.muted
                        font.pixelSize: Theme.text_sm
                    }

                    Rectangle {
                        visible: modelData.out
                        anchors.verticalCenter: parent.verticalCenter
                        implicitWidth: tag.implicitWidth + 2 * Theme.space_sm
                        implicitHeight: tag.implicitHeight + Theme.space_xs
                        radius: Theme.radius_sm
                        color: "transparent"
                        border.width: Theme.stroke
                        border.color: Theme.line_strong

                        UiText {
                            id: tag

                            anchors.centerIn: parent
                            text: Strings.t("review.left_out_tag")
                            color: Theme.faint
                            font.pixelSize: Theme.text_xs
                        }
                    }
                }

                UiText {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    visible: modelData.text !== ""
                    text: modelData.text
                    color: modelData.out ? Theme.faint : modelData.muted ? Theme.muted : Theme.change
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }

                Loader {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    visible: modelData.text === ""
                    sourceComponent: modelData.pills ? pillsBefore : textBefore

                    Component {
                        id: pillsBefore

                        Flow {
                            spacing: Theme.space_xs

                            Repeater {
                                model: modelData.before

                                delegate: TrackPill {
                                    required property var modelData

                                    track: modelData
                                }
                            }
                        }
                    }

                    Component {
                        id: textBefore

                        UiText {
                            mono: modelData.mono
                            text: modelData.before
                            color: Theme.muted
                            font.pixelSize: Theme.text_sm
                            // At words; inside one only where a file name is longer than the line.
                            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                            maximumLineCount: 2
                        }
                    }
                }

                UiText {
                    Layout.alignment: Qt.AlignTop
                    visible: modelData.text === ""
                    text: Strings.t("inspector.becomes")
                    color: Theme.faint
                }

                Loader {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    visible: modelData.text === ""
                    sourceComponent: modelData.pills ? pillsAfter : textAfter

                    Component {
                        id: pillsAfter

                        Flow {
                            spacing: Theme.space_xs

                            Repeater {
                                model: modelData.after

                                delegate: TrackPill {
                                    required property var modelData

                                    track: modelData
                                }
                            }
                        }
                    }

                    Component {
                        id: textAfter

                        UiText {
                            mono: modelData.mono
                            text: modelData.after
                            color: modelData.out ? Theme.faint : Theme.change
                            font.pixelSize: Theme.text_sm
                            wrapMode: modelData.mono ? Text.WrapAtWordBoundaryOrAnywhere : Text.WordWrap
                            maximumLineCount: 2
                        }
                    }
                }
            }
        }
    }
}
