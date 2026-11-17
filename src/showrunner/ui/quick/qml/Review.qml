import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// Review: the run's changes grouped by kind, each group in or out of the run, what stays as it is, and
// the one Apply button; beside them one card per file, filtered, with Not this time and Put back.
Item {
    id: place

    readonly property var review: app.review
    // The files opened by hand, by path, so a card stays open when the plan is rebuilt around it.
    property var opened: ({})

    objectName: "reviewPlace"

    RowLayout {
        anchors.fill: parent
        spacing: 0

        ScrollPane {
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

                    objectName: "expandAll"

                    kind: "ghost"
                    size: Theme.row_sm
                    text: open ? Strings.t("review.fold_all") : Strings.t("review.expand_all")
                    // Every card follows again; a card opened or folded by hand after this keeps its own state.
                    onClicked: {
                        open = !open
                        place.opened = ({})
                    }
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
                // A count, not the rows: new rows of the same batch then update the cards in place, so the list
                // keeps its scroll position after a choice.
                model: (place.review.rows || []).length
                // Another batch starts at the top, even with as many rows as the last one.
                readonly property string firstPath: (place.review.rows || []).length > 0 ? (place.review.rows || [])[0].path : ""
                onFirstPathChanged: positionViewAtBeginning()

                delegate: ReviewFile {
                    required property int index
                    readonly property var modelData: place.review.rows[index]

                    width: files.width
                    file: modelData
                    expanded: place.opened[modelData.path] ?? expandAll.open
                    locked: app.locked
                    onToggled: {
                        const next = Object.assign({}, place.opened)
                        next[modelData.path] = !expanded
                        place.opened = next
                    }
                }

                ScrollBar.vertical: Scroller {}
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
