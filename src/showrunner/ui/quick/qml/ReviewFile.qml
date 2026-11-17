import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// One file in Review: what changes in it, a mark per group, and Not this time or Put back, or Include for an
// excluded file. Opened, it shows its tracks, defaults, file, title and track names before and after; a row of a
// left-out group says so and is muted.
Item {
    id: card

    required property var file
    property bool expanded: false
    property bool locked: false
    readonly property bool excluded: file.state === "excluded"
    readonly property bool out: file.state === "out" || excluded

    signal toggled()

    implicitHeight: column.implicitHeight + 2 * Theme.space_md

    Rectangle {
        anchors.fill: parent
        visible: !card.out
        radius: Theme.radius_lg
        color: Theme.panel_2
        border.width: Theme.stroke
        border.color: card.expanded ? Theme.line_strong : Theme.line
    }

    DashedFrame {
        anchors.fill: parent
        visible: card.out
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

            IconButton {
                objectName: "expand"
                implicitWidth: Theme.row_sm
                implicitHeight: Theme.row_sm
                iconName: card.expanded ? "down" : "right"
                label: card.expanded ? Strings.t("review.fold") : Strings.t("review.open")
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
                color: card.out ? Theme.muted : Theme.ink
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
                text: card.excluded ? Strings.t("review.file.excluded") : card.out ? Strings.t("review.file.left_out") : card.file.summary
                color: Theme.muted
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
                objectName: card.excluded ? "includeFile" : "notThisTime"
                kind: card.out ? "outline" : "ghost"
                size: Theme.row_sm
                enabled: !card.locked
                text: card.excluded ? Strings.t("workspace.include") : card.out ? Strings.t("review.put_back") : Strings.t("review.not_this_time")
                Accessible.description: card.file.title
                onClicked: card.excluded ? app.exclude_file(card.file.path, false) : app.set_file_in_run(card.file.path, card.out)
            }
        }

        UiText {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.row_sm + Theme.space_md
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
                Layout.leftMargin: Theme.row_sm + Theme.space_md
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

                Loader {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
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
                            wrapMode: Text.WrapAnywhere
                            maximumLineCount: 2
                        }
                    }
                }

                UiText {
                    Layout.alignment: Qt.AlignTop
                    text: Strings.t("inspector.becomes")
                    color: Theme.faint
                }

                Loader {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
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
                            wrapMode: modelData.mono ? Text.WrapAnywhere : Text.WordWrap
                            maximumLineCount: 2
                        }
                    }
                }
            }
        }
    }
}
