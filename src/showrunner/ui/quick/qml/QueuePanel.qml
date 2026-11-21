import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import Showrunner

// The drawer's Queue tab: Start or Pause for the queue, what the last add did, then each queued place with its state,
// the running one with its progress, and Retry, Cancel or Remove where they apply. The running item's files and
// steps are on the Jobs tab.
Item {
    id: panel

    readonly property var queue: app.queue

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space_lg
        spacing: Theme.space_md

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            UiText {
                text: Strings.t("queue.title")
                font.weight: Font.Bold
                Accessible.role: Accessible.Heading
            }

            HelpTip {
                objectName: "queueTip"
                topic: "queue"
            }

            UiText {
                Layout.fillWidth: true
                text: panel.queue.status
                color: Theme.muted
                font.pixelSize: Theme.text_sm
            }

            ActionButton {
                objectName: "queueClear"
                visible: panel.queue.can_clear
                kind: "ghost"
                text: Strings.t("queue.clear")
                Accessible.description: Strings.t("queue.clear_tip")
                ToolTip.visible: hovered
                ToolTip.text: Accessible.description
                onClicked: panel.queue.clear()
            }

            ActionButton {
                objectName: "queueStart"
                visible: !panel.queue.going
                enabled: panel.queue.can_start
                kind: "primary"
                iconName: "play"
                text: Strings.t("queue.start")
                onClicked: panel.queue.start()
            }

            ActionButton {
                objectName: "queuePause"
                visible: panel.queue.going
                kind: "outline"
                iconName: "pause"
                text: Strings.t("queue.pause")
                onClicked: panel.queue.pause()
            }
        }

        UiText {
            objectName: "queueNote"
            Layout.fillWidth: true
            visible: panel.queue.note !== ""
            text: panel.queue.note
            wrapMode: Text.WordWrap
            elide: Text.ElideNone
        }

        ListView {
            id: rows

            objectName: "queueRows"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: Theme.space_xs
            boundsBehavior: Flickable.StopAtBounds
            // A count, as on the Jobs tab: the rows are rebuilt on every clock tick of the running item.
            model: panel.queue.rows.length
            readonly property int active: panel.queue.active
            onActiveChanged: if (active >= 0) positionViewAtIndex(active, ListView.Contain)

            delegate: Rectangle {
                id: row

                required property int index
                readonly property var modelData: panel.queue.rows[index]
                readonly property string itemState: modelData.state
                readonly property bool problem: itemState === "failed" || itemState === "changed" || itemState === "unreadable"

                width: rows.width
                implicitHeight: content.implicitHeight + 2 * Theme.space_md
                radius: Theme.radius_md
                color: itemState === "running" ? Theme.panel_2 : "transparent"
                border.width: itemState === "running" ? Theme.stroke : 0
                border.color: Theme.line_strong
                Accessible.role: Accessible.ListItem
                Accessible.name: modelData.name + " " + modelData.state_text

                // A rule between items, so a long queue stays easy to follow.
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: -rows.spacing / 2
                    height: Theme.stroke
                    visible: row.index < rows.count - 1 && row.itemState !== "running"
                    color: Theme.line
                }

                ColumnLayout {
                    id: content

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: Theme.space_md
                    spacing: Theme.space_sm

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space_lg

                        Icon {
                            name: row.itemState === "done" ? "check"
                                : row.itemState === "running" ? "resume"
                                : row.itemState === "waiting" ? "list"
                                : row.itemState === "interrupted" ? "pause"
                                : row.itemState === "cancelled" ? "x" : "alert"
                            size: Theme.icon_sm
                            color: row.itemState === "done" ? Theme.add
                                 : row.itemState === "running" ? Theme.control
                                 : row.problem ? Theme.drop
                                 : row.itemState === "waiting" ? Theme.faint : Theme.change
                        }

                        // Cut in the middle: items of one season differ only at the end of their names.
                        UiText {
                            objectName: "queueName"
                            Layout.fillWidth: true
                            text: row.modelData.name
                            font.weight: Font.Medium
                            elide: Text.ElideMiddle
                        }

                        UiText {
                            Layout.preferredWidth: Theme.row_lg * 2
                            text: row.modelData.files
                            color: Theme.muted
                            font.pixelSize: Theme.text_sm
                        }

                        ProgressLine {
                            Layout.preferredWidth: Theme.row_lg * 3
                            value: row.modelData.fraction
                            fill: row.itemState === "done" ? Theme.add : row.problem ? Theme.drop : Theme.control
                            Accessible.name: row.modelData.state_text
                        }

                        UiText {
                            Layout.preferredWidth: Theme.row_lg * 3
                            horizontalAlignment: Text.AlignRight
                            text: row.modelData.state_text
                            color: row.problem ? Theme.drop : Theme.muted
                            font.pixelSize: Theme.text_sm
                            font.weight: Font.DemiBold
                        }

                        Row {
                            Layout.preferredWidth: Theme.matrix_label
                            layoutDirection: Qt.RightToLeft
                            spacing: Theme.space_sm

                            ActionButton {
                                objectName: "queueRemove"
                                visible: row.modelData.can_remove
                                kind: "ghost"
                                text: Strings.t("queue.remove")
                                onClicked: panel.queue.remove(row.modelData.id)
                            }

                            ActionButton {
                                objectName: "queueRetry"
                                visible: row.modelData.can_retry
                                kind: "outline"
                                iconName: "resume"
                                text: Strings.t("queue.retry")
                                onClicked: panel.queue.retry(row.modelData.id)
                            }

                            ActionButton {
                                objectName: "queueCancel"
                                visible: row.modelData.can_cancel
                                kind: "outline"
                                iconName: "x"
                                text: Strings.t("queue.cancel")
                                onClicked: panel.queue.cancel(row.modelData.id)
                            }
                        }
                    }

                    UiText {
                        Layout.fillWidth: true
                        Layout.leftMargin: Theme.icon_sm + Theme.space_lg
                        visible: row.modelData.detail !== ""
                        text: row.modelData.detail
                        color: row.problem ? Theme.drop : Theme.muted
                        font.pixelSize: Theme.text_sm
                        wrapMode: Text.WordWrap
                        elide: Text.ElideNone
                    }
                }
            }

            ScrollBar.vertical: Scroller {}
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space_md

            Icon {
                name: "lock"
                size: Theme.icon_sm
                color: Theme.faint
            }

            UiText {
                Layout.fillWidth: true
                text: Strings.t("queue.kept")
                color: Theme.muted
                font.pixelSize: Theme.text_sm
                wrapMode: Text.WordWrap
            }
        }
    }
}
