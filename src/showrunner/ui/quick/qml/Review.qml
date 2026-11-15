import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Review: the run's changes grouped by kind, each group in or out of the run, what stays as it is, and
// the one Apply button; beside them one card per file, filtered, with Leave out and Put back.
Item {
    id: place

    readonly property var review: app.review
    // The files opened by hand, by path, so a card stays open when the plan is rebuilt around it.
    property var opened: ({})

    objectName: "reviewPlace"

    RowLayout {
        anchors.fill: parent
        spacing: 0

        ScrollView {
            Layout.preferredWidth: Theme.inspector_width + Theme.space_xl
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: parent.width
                spacing: Theme.space_lg

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.space_lg
                    Layout.bottomMargin: 0
                    spacing: Theme.space_xs

                    UiText {
                        Layout.fillWidth: true
                        text: place.review.title || ""
                        font.pixelSize: Theme.text_xl
                        font.weight: Font.Bold
                    }

                    UiText {
                        Layout.fillWidth: true
                        text: Strings.t("review.lead")
                        color: Theme.muted
                        font.pixelSize: Theme.text_sm
                        wrapMode: Text.WordWrap
                    }
                }

                Repeater {
                    model: place.review.groups || []

                    delegate: ReviewGroup {
                        required property var modelData

                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.space_lg
                        Layout.rightMargin: Theme.space_lg
                        card: modelData
                        locked: app.locked
                    }
                }

                UiText {
                    Layout.leftMargin: Theme.space_lg
                    text: Strings.t("review.stays")
                    color: Theme.faint
                    font.pixelSize: Theme.text_xs
                    font.weight: Font.DemiBold
                    font.letterSpacing: Theme.stroke
                }

                Flow {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.space_lg
                    Layout.rightMargin: Theme.space_lg
                    spacing: Theme.space_sm

                    Repeater {
                        model: place.review.stays || []

                        delegate: Rectangle {
                            required property var modelData

                            implicitWidth: stay.implicitWidth + 2 * Theme.space_md
                            implicitHeight: Theme.pill + Theme.space_xs
                            radius: Theme.radius_sm
                            color: "transparent"
                            border.width: Theme.stroke
                            border.color: Theme.line_strong

                            UiText {
                                id: stay

                                anchors.centerIn: parent
                                text: modelData
                                color: Theme.muted
                                font.pixelSize: Theme.text_sm
                            }
                        }
                    }
                }

                UiText {
                    Layout.fillWidth: true
                    Layout.leftMargin: Theme.space_lg
                    Layout.rightMargin: Theme.space_lg
                    visible: app.apply_message !== ""
                    text: app.apply_message
                    color: Theme.change
                    font.pixelSize: Theme.text_sm
                    wrapMode: Text.WordWrap
                }

                ActionButton {
                    objectName: "applyButton"
                    Layout.fillWidth: true
                    Layout.margins: Theme.space_lg
                    Layout.topMargin: 0
                    size: Theme.row_lg
                    kind: "primary"
                    iconName: "check"
                    enabled: app.can_apply
                    text: app.applying ? Strings.t("review.applying") : (place.review.apply_text || "")
                    onClicked: app.apply()
                }
            }
        }

        Rectangle {
            Layout.preferredWidth: Theme.stroke
            Layout.fillHeight: true
            color: Theme.line
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space_md

            RowLayout {
                Layout.fillWidth: true
                Layout.margins: Theme.space_lg
                Layout.bottomMargin: 0
                spacing: Theme.space_sm

                Repeater {
                    model: place.review.filters || []

                    delegate: ActionButton {
                        required property var modelData

                        objectName: "filter_" + modelData.key
                        kind: app.review_filter === modelData.key ? "outline" : "ghost"
                        size: Theme.row_sm
                        checkable: true
                        checked: app.review_filter === modelData.key
                        text: modelData.label + " " + modelData.count
                        onClicked: app.review_filter = modelData.key
                    }
                }

                Item {
                    Layout.fillWidth: true
                }

                ActionButton {
                    id: expandAll

                    property bool open: false

                    kind: "ghost"
                    size: Theme.row_sm
                    text: open ? Strings.t("review.fold_all") : Strings.t("review.expand_all")
                    onClicked: open = !open
                }
            }

            ListView {
                id: files

                objectName: "reviewFiles"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.leftMargin: Theme.space_lg
                Layout.rightMargin: Theme.space_lg
                clip: true
                spacing: Theme.space_sm
                boundsBehavior: Flickable.StopAtBounds
                model: place.review.rows || []

                delegate: ReviewFile {
                    required property var modelData

                    width: files.width
                    file: modelData
                    expanded: expandAll.open || place.opened[modelData.path] === true
                    locked: app.locked
                    onToggled: {
                        const next = Object.assign({}, place.opened)
                        next[modelData.path] = !expanded
                        place.opened = next
                    }
                }

                ScrollBar.vertical: ScrollBar {}
            }

            Placeholder {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: files.count === 0
                title: Strings.t("review.no_files")
            }
        }
    }
}
